from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from services.expansion_database import (
    DEFAULT_RATING,
    columns_for,
    expansion_connection,
    normalize_format,
    utcnow_iso,
)


@dataclass(slots=True)
class RatingChange:
    player_id: str
    old_rating: int
    new_rating: int
    delta: int
    result: str


MIN_OFFICIAL_GAMES = 5


class CompetitiveService:
    """Classement ELO, saisons, historique et synchronisation des matchs existants."""

    async def active_season_id(self, guild_id: str) -> int:
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    """
                    SELECT id
                    FROM competitive_seasons
                    WHERE guild_id = ? AND status = 'active'
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (guild_id,),
                )
            ).fetchone()
            return int(row["id"]) if row else 0

    async def display_season(self, guild_id: str) -> dict[str, Any]:
        """Saison affichée : active, sinon dernière clôturée, sinon classement permanent."""
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    """
                    SELECT * FROM competitive_seasons
                    WHERE guild_id=? AND status IN ('active','closed')
                    ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id DESC
                    LIMIT 1
                    """,
                    (guild_id,),
                )
            ).fetchone()
            if row:
                return dict(row)
            return {
                "id": 0,
                "guild_id": guild_id,
                "name": "Classement permanent",
                "status": "permanent",
                "starts_at": None,
                "ends_at": None,
                "soft_reset_factor": 1.0,
            }

    async def create_season(
        self,
        *,
        guild_id: str,
        name: str,
        created_by: str,
        ends_at: str | None = None,
        soft_reset_factor: float = 0.50,
    ) -> int:
        factor = min(1.0, max(0.0, float(soft_reset_factor)))
        now = utcnow_iso()
        async with expansion_connection() as db:
            existing = await (
                await db.execute(
                    "SELECT id FROM competitive_seasons WHERE guild_id=? AND status='active'",
                    (guild_id,),
                )
            ).fetchone()
            if existing:
                raise ValueError("Une saison compétitive est déjà active sur ce serveur.")
            cursor = await db.execute(
                """
                INSERT INTO competitive_seasons(
                    guild_id, name, starts_at, ends_at, status,
                    soft_reset_factor, created_by, created_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (guild_id, name.strip(), now, ends_at, factor, created_by, now),
            )
            season_id = int(cursor.lastrowid)

            previous_season = await (
                await db.execute(
                    """
                    SELECT id
                    FROM competitive_seasons
                    WHERE guild_id=? AND status='closed' AND id<>?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (guild_id, season_id),
                )
            ).fetchone()
            source_season_id = int(previous_season["id"]) if previous_season else 0
            previous_rows = await (
                await db.execute(
                    """
                    SELECT discord_id, format, rating
                    FROM competitive_ratings
                    WHERE guild_id=? AND season_id=? AND games>0
                    """,
                    (guild_id, source_season_id),
                )
            ).fetchall()
            for row in previous_rows:
                previous = int(row["rating"])
                reset_rating = round(DEFAULT_RATING + (previous - DEFAULT_RATING) * factor)
                await db.execute(
                    """
                    INSERT OR IGNORE INTO competitive_ratings(
                        guild_id, discord_id, format, season_id,
                        rating, peak_rating, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        row["discord_id"],
                        row["format"],
                        season_id,
                        reset_rating,
                        reset_rating,
                        now,
                    ),
                )
            await db.commit()
            return season_id

    async def close_season(self, guild_id: str) -> dict[str, Any]:
        async with expansion_connection() as db:
            season = await (
                await db.execute(
                    """
                    SELECT * FROM competitive_seasons
                    WHERE guild_id=? AND status='active'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (guild_id,),
                )
            ).fetchone()
            if season is None:
                raise ValueError("Aucune saison active.")
            now = utcnow_iso()
            await db.execute(
                """
                UPDATE competitive_seasons
                SET status='closed', closed_at=?, final_summary_sent=0
                WHERE id=?
                """,
                (now, int(season["id"])),
            )
            await db.commit()
            result = dict(season)
            result.update({"status": "closed", "closed_at": now})

        await self.snapshot_season(guild_id, int(result["id"]))
        result["summary"] = await self.season_summary(guild_id, int(result["id"]))
        return result

    async def close_expired_seasons(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        expired: list[tuple[str, int]] = []
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT id, guild_id, ends_at
                    FROM competitive_seasons
                    WHERE status='active' AND ends_at IS NOT NULL
                    """
                )
            ).fetchall()
            for row in rows:
                try:
                    end = datetime.fromisoformat(str(row["ends_at"]).replace("Z", "+00:00"))
                    if end.tzinfo is None:
                        end = end.replace(tzinfo=UTC)
                    end = end.astimezone(UTC)
                except ValueError:
                    continue
                if end <= now:
                    expired.append((str(row["guild_id"]), int(row["id"])))

        closed: list[dict[str, Any]] = []
        for guild_id, season_id in expired:
            try:
                season = await self.close_season(guild_id)
            except ValueError:
                continue
            if int(season["id"]) == season_id:
                closed.append(season)
        return closed

    async def season_status(self, guild_id: str) -> dict[str, Any] | None:
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    """
                    SELECT * FROM competitive_seasons
                    WHERE guild_id=?
                    ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id DESC
                    LIMIT 1
                    """,
                    (guild_id,),
                )
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _expected(rating_a: int, rating_b: int) -> float:
        return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0))

    @staticmethod
    def _k_factor(games: int, rating: int) -> int:
        if games < 20:
            return 40
        if rating >= 1800:
            return 20
        return 32

    async def _rating_row(
        self,
        db: Any,
        *,
        guild_id: str,
        discord_id: str,
        format_name: str,
        season_id: int,
    ) -> dict[str, Any]:
        row = await (
            await db.execute(
                """
                SELECT * FROM competitive_ratings
                WHERE guild_id=? AND discord_id=? AND format=? AND season_id=?
                """,
                (guild_id, discord_id, format_name, season_id),
            )
        ).fetchone()
        if row:
            return dict(row)
        now = utcnow_iso()
        await db.execute(
            """
            INSERT INTO competitive_ratings(
                guild_id, discord_id, format, season_id,
                rating, peak_rating, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, discord_id, format_name, season_id, DEFAULT_RATING, DEFAULT_RATING, now),
        )
        return {
            "guild_id": guild_id,
            "discord_id": discord_id,
            "format": format_name,
            "season_id": season_id,
            "rating": DEFAULT_RATING,
            "peak_rating": DEFAULT_RATING,
            "games": 0,
            "wins": 0,
            "losses": 0,
            "current_streak": 0,
            "best_streak": 0,
        }

    async def process_result(
        self,
        *,
        guild_id: str,
        source_key: str,
        tournament_id: int | None,
        format_name: str,
        player1_id: str,
        player2_id: str,
        winner_id: str,
        score: str | None = None,
    ) -> tuple[RatingChange, RatingChange] | None:
        format_name = normalize_format(format_name)
        if not player1_id or not player2_id or player1_id == player2_id:
            return None
        if winner_id not in {player1_id, player2_id}:
            return None

        async with expansion_connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            duplicate = await (
                await db.execute(
                    """
                    SELECT 1 FROM processed_competitive_matches
                    WHERE guild_id=? AND source_key=?
                    """,
                    (guild_id, source_key),
                )
            ).fetchone()
            if duplicate:
                await db.rollback()
                return None

            season_row = await (
                await db.execute(
                    """
                    SELECT id FROM competitive_seasons
                    WHERE guild_id=? AND status='active'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (guild_id,),
                )
            ).fetchone()
            season_id = int(season_row["id"]) if season_row else 0

            p1 = await self._rating_row(
                db,
                guild_id=guild_id,
                discord_id=player1_id,
                format_name=format_name,
                season_id=season_id,
            )
            p2 = await self._rating_row(
                db,
                guild_id=guild_id,
                discord_id=player2_id,
                format_name=format_name,
                season_id=season_id,
            )

            p1_score = 1.0 if winner_id == player1_id else 0.0
            p2_score = 1.0 - p1_score
            expected1 = self._expected(int(p1["rating"]), int(p2["rating"]))
            expected2 = self._expected(int(p2["rating"]), int(p1["rating"]))
            delta1 = round(self._k_factor(int(p1["games"]), int(p1["rating"])) * (p1_score - expected1))
            delta2 = round(self._k_factor(int(p2["games"]), int(p2["rating"])) * (p2_score - expected2))
            new1 = max(100, int(p1["rating"]) + delta1)
            new2 = max(100, int(p2["rating"]) + delta2)
            now = utcnow_iso()

            async def update_player(
                row: dict[str, Any],
                player_id: str,
                won: bool,
                new_rating: int,
                delta: int,
                opponent_id: str,
            ) -> RatingChange:
                current_streak = int(row["current_streak"])
                next_streak = current_streak + 1 if won else 0
                best_streak = max(int(row["best_streak"]), next_streak)
                await db.execute(
                    """
                    UPDATE competitive_ratings
                    SET rating=?, peak_rating=MAX(peak_rating, ?), games=games+1,
                        wins=wins+?, losses=losses+?, current_streak=?,
                        best_streak=?, updated_at=?
                    WHERE guild_id=? AND discord_id=? AND format=? AND season_id=?
                    """,
                    (
                        new_rating,
                        new_rating,
                        1 if won else 0,
                        0 if won else 1,
                        next_streak,
                        best_streak,
                        now,
                        guild_id,
                        player_id,
                        format_name,
                        season_id,
                    ),
                )
                await db.execute(
                    """
                    INSERT INTO rating_history(
                        guild_id, discord_id, format, season_id, source_key,
                        opponent_id, old_rating, new_rating, delta, result, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        player_id,
                        format_name,
                        season_id,
                        source_key,
                        opponent_id,
                        int(row["rating"]),
                        new_rating,
                        delta,
                        "win" if won else "loss",
                        now,
                    ),
                )
                return RatingChange(
                    player_id=player_id,
                    old_rating=int(row["rating"]),
                    new_rating=new_rating,
                    delta=delta,
                    result="win" if won else "loss",
                )

            change1 = await update_player(
                p1, player1_id, winner_id == player1_id, new1, delta1, player2_id
            )
            change2 = await update_player(
                p2, player2_id, winner_id == player2_id, new2, delta2, player1_id
            )
            await db.execute(
                """
                INSERT INTO processed_competitive_matches(
                    guild_id, source_key, tournament_id, format,
                    player1_id, player2_id, winner_id, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    source_key,
                    tournament_id,
                    format_name,
                    player1_id,
                    player2_id,
                    winner_id,
                    now,
                ),
            )

            higher_before = p1 if int(p1["rating"]) > int(p2["rating"]) else p2
            lower_before = p2 if higher_before is p1 else p1
            lower_id = player2_id if higher_before is p1 else player1_id
            if winner_id == lower_id and int(higher_before["rating"]) - int(lower_before["rating"]) >= 150:
                await self._unlock(db, guild_id, winner_id, "giant_killer", source_key)

            await self._evaluate_achievements(
                db,
                guild_id=guild_id,
                player_ids=(player1_id, player2_id),
                winner_id=winner_id,
                format_name=format_name,
                source_key=source_key,
                score=score,
            )
            await db.commit()
            return change1, change2

    async def _unlock(
        self,
        db: Any,
        guild_id: str,
        discord_id: str,
        code: str,
        source_key: str | None,
    ) -> None:
        await db.execute(
            """
            INSERT OR IGNORE INTO player_achievements(
                guild_id, discord_id, achievement_code,
                progress, unlocked_at, source_key
            ) VALUES (?, ?, ?, 1, ?, ?)
            """,
            (guild_id, discord_id, code, utcnow_iso(), source_key),
        )

    async def _evaluate_achievements(
        self,
        db: Any,
        *,
        guild_id: str,
        player_ids: tuple[str, str],
        winner_id: str,
        format_name: str,
        source_key: str,
        score: str | None,
    ) -> None:
        for player_id in player_ids:
            aggregate = await (
                await db.execute(
                    """
                    SELECT COALESCE(SUM(games),0) AS games,
                           COALESCE(MAX(best_streak),0) AS best_streak,
                           COUNT(DISTINCT format) AS formats
                    FROM competitive_ratings
                    WHERE guild_id=? AND discord_id=?
                    """,
                    (guild_id, player_id),
                )
            ).fetchone()
            games = int(aggregate["games"])
            best_streak = int(aggregate["best_streak"])
            formats = int(aggregate["formats"])
            if games >= 1:
                await self._unlock(db, guild_id, player_id, "first_duel", source_key)
            if games >= 100:
                await self._unlock(db, guild_id, player_id, "hundred_games", source_key)
            if best_streak >= 5:
                await self._unlock(db, guild_id, player_id, "five_streak", source_key)
            if formats >= 5:
                await self._unlock(db, guild_id, player_id, "versatile", source_key)

        if winner_id and score:
            pieces = score.replace("–", "-").split("-")
            try:
                high = max(int(piece.strip()) for piece in pieces)
            except (ValueError, TypeError):
                high = 0
            if high >= 3:
                await self._unlock(db, guild_id, winner_id, "bo5_master", source_key)

    async def sync_completed_matches(self, guild_id: str | None = None) -> int:
        pending: list[dict[str, Any]] = []
        async with expansion_connection() as db:
            if await self._table(db, "matches") and await self._table(db, "tournaments"):
                match_columns = await columns_for(db, "matches")
                status_filter = ""
                if "status" in match_columns:
                    status_filter = "AND m.status IN ('validated','completed')"
                validated_filter = ""
                if "validated_at" in match_columns:
                    validated_filter = "AND (m.validated_at IS NOT NULL OR m.status IN ('validated','completed'))"
                guild_filter = "AND t.guild_id=?" if guild_id else ""
                params: tuple[Any, ...] = (guild_id,) if guild_id else ()
                rows = await (
                    await db.execute(
                        f"""
                        SELECT m.id, m.tournament_id, m.player1_id, m.player2_id,
                               m.winner_id, m.score, t.guild_id, t.format
                        FROM matches m
                        JOIN tournaments t ON t.id=m.tournament_id
                        WHERE COALESCE(m.is_bye,0)=0
                          AND m.player1_id IS NOT NULL
                          AND m.player2_id IS NOT NULL
                          AND m.winner_id IS NOT NULL
                          {status_filter}
                          {validated_filter}
                          {guild_filter}
                        ORDER BY m.id
                        """,
                        params,
                    )
                ).fetchall()
                pending.extend(
                    {
                        "source_key": f"bracket:{row['id']}",
                        "tournament_id": int(row["tournament_id"]),
                        "player1_id": str(row["player1_id"]),
                        "player2_id": str(row["player2_id"]),
                        "winner_id": str(row["winner_id"]),
                        "guild_id": str(row["guild_id"]),
                        "format": str(row["format"]),
                        "score": row["score"],
                    }
                    for row in rows
                )

            if await self._table(db, "swiss_matches") and await self._table(db, "tournaments"):
                guild_filter = "AND t.guild_id=?" if guild_id else ""
                params = (guild_id,) if guild_id else ()
                rows = await (
                    await db.execute(
                        f"""
                        SELECT sm.id, sm.tournament_id, sm.player1_id, sm.player2_id,
                               sm.winner_id, sm.player1_score, sm.player2_score,
                               t.guild_id, t.format
                        FROM swiss_matches sm
                        JOIN tournaments t ON t.id=sm.tournament_id
                        WHERE COALESCE(sm.is_bye,0)=0
                          AND COALESCE(sm.is_double_loss,0)=0
                          AND sm.status='completed'
                          AND sm.player2_id IS NOT NULL
                          AND sm.winner_id IS NOT NULL
                          {guild_filter}
                        ORDER BY sm.id
                        """,
                        params,
                    )
                ).fetchall()
                pending.extend(
                    {
                        "source_key": f"swiss:{row['id']}",
                        "tournament_id": int(row["tournament_id"]),
                        "player1_id": str(row["player1_id"]),
                        "player2_id": str(row["player2_id"]),
                        "winner_id": str(row["winner_id"]),
                        "guild_id": str(row["guild_id"]),
                        "format": str(row["format"]),
                        "score": f"{row['player1_score']}-{row['player2_score']}",
                    }
                    for row in rows
                )

        processed = 0
        for match in pending:
            result = await self.process_result(
                guild_id=match["guild_id"],
                source_key=match["source_key"],
                tournament_id=match["tournament_id"],
                format_name=match["format"],
                player1_id=match["player1_id"],
                player2_id=match["player2_id"],
                winner_id=match["winner_id"],
                score=match["score"],
            )
            processed += 1 if result is not None else 0
        await self.sync_champion_achievements(guild_id)
        await self.sync_tournament_participation_achievements(guild_id)
        return processed

    @staticmethod
    async def _table(db: Any, table_name: str) -> bool:
        row = await (
            await db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
        ).fetchone()
        return row is not None

    async def sync_champion_achievements(self, guild_id: str | None = None) -> None:
        async with expansion_connection() as db:
            if not await self._table(db, "tournaments"):
                return
            where = "WHERE winner_id IS NOT NULL"
            params: tuple[Any, ...] = ()
            if guild_id:
                where += " AND guild_id=?"
                params = (guild_id,)
            rows = await (
                await db.execute(
                    f"SELECT id, guild_id, winner_id FROM tournaments {where}",
                    params,
                )
            ).fetchall()
            for row in rows:
                await self._unlock(
                    db,
                    str(row["guild_id"]),
                    str(row["winner_id"]),
                    "champion",
                    f"tournament:{row['id']}",
                )
            await db.commit()

    async def sync_tournament_participation_achievements(self, guild_id: str | None = None) -> None:
        async with expansion_connection() as db:
            if not await self._table(db, "registrations") or not await self._table(db, "tournaments"):
                return
            where = ""
            params: tuple[Any, ...] = ()
            if guild_id:
                where = "WHERE t.guild_id=?"
                params = (guild_id,)
            rows = await (
                await db.execute(
                    f"""
                    SELECT t.guild_id, r.discord_id, COUNT(DISTINCT r.tournament_id) AS total
                    FROM registrations r
                    JOIN tournaments t ON t.id=r.tournament_id
                    {where}
                    GROUP BY t.guild_id, r.discord_id
                    HAVING COUNT(DISTINCT r.tournament_id) >= 10
                    """,
                    params,
                )
            ).fetchall()
            for row in rows:
                await self._unlock(
                    db,
                    str(row["guild_id"]),
                    str(row["discord_id"]),
                    "ten_tournaments",
                    None,
                )
            await db.commit()

    async def ranking(
        self,
        guild_id: str,
        format_name: str,
        limit: int = 20,
        *,
        season_id: int | None = None,
        official_only: bool = True,
    ) -> list[dict[str, Any]]:
        format_name = normalize_format(format_name)
        if season_id is None:
            season = await self.display_season(guild_id)
            season_id = int(season["id"])
        minimum = MIN_OFFICIAL_GAMES if official_only else 1
        async with expansion_connection() as db:
            if format_name == "Général":
                rows = await (
                    await db.execute(
                        """
                        SELECT
                            r.guild_id,
                            r.discord_id,
                            'Général' AS format,
                            r.season_id,
                            CAST(ROUND(
                                SUM(r.rating * r.games) * 1.0 /
                                NULLIF(SUM(r.games), 0)
                            ) AS INTEGER) AS rating,
                            MAX(r.peak_rating) AS peak_rating,
                            SUM(r.games) AS games,
                            SUM(r.wins) AS wins,
                            SUM(r.losses) AS losses,
                            MAX(r.current_streak) AS current_streak,
                            MAX(r.best_streak) AS best_streak,
                            MAX(r.updated_at) AS updated_at,
                            COALESCE(p.display_name, p.username, r.discord_id) AS player_name
                        FROM competitive_ratings r
                        LEFT JOIN players p
                          ON p.guild_id=r.guild_id AND p.discord_id=r.discord_id
                        WHERE r.guild_id=? AND r.season_id=? AND r.games>0
                        GROUP BY r.guild_id, r.discord_id, r.season_id,
                                 p.display_name, p.username
                        HAVING SUM(r.games)>=?
                        ORDER BY rating DESC, games DESC, wins DESC
                        LIMIT ?
                        """,
                        (guild_id, season_id, minimum, max(1, min(limit, 100))),
                    )
                ).fetchall()
            else:
                rows = await (
                    await db.execute(
                        """
                        SELECT r.*, COALESCE(p.display_name, p.username, r.discord_id) AS player_name
                        FROM competitive_ratings r
                        LEFT JOIN players p
                          ON p.guild_id=r.guild_id AND p.discord_id=r.discord_id
                        WHERE r.guild_id=? AND r.format=? AND r.season_id=? AND r.games>=?
                        ORDER BY r.rating DESC, r.games DESC, r.wins DESC
                        LIMIT ?
                        """,
                        (guild_id, format_name, season_id, minimum, max(1, min(limit, 100))),
                    )
                ).fetchall()
            return [dict(row) for row in rows]

    async def snapshot_season(self, guild_id: str, season_id: int) -> None:
        """Fige le Top 20 général et le Top 20 de chaque format à la clôture."""
        formats: list[str] = []
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT DISTINCT format FROM competitive_ratings
                    WHERE guild_id=? AND season_id=? AND games>0
                    ORDER BY format
                    """,
                    (guild_id, season_id),
                )
            ).fetchall()
            formats = [str(row["format"]) for row in rows]
            await db.execute(
                "DELETE FROM season_ranking_snapshots WHERE guild_id=? AND season_id=?",
                (guild_id, season_id),
            )
            await db.commit()

        created_at = utcnow_iso()
        for format_name in ["Général", *formats]:
            rows = await self.ranking(
                guild_id,
                format_name,
                limit=20,
                season_id=season_id,
                official_only=True,
            )
            async with expansion_connection() as db:
                for rank, row in enumerate(rows, start=1):
                    await db.execute(
                        """
                        INSERT INTO season_ranking_snapshots(
                            season_id, guild_id, format, rank, discord_id,
                            player_name, rating, games, wins, losses, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            season_id,
                            guild_id,
                            format_name,
                            rank,
                            str(row["discord_id"]),
                            str(row["player_name"]),
                            int(row["rating"]),
                            int(row["games"]),
                            int(row["wins"]),
                            int(row["losses"]),
                            created_at,
                        ),
                    )
                await db.commit()

    async def season_ranking(
        self,
        guild_id: str,
        season_id: int,
        format_name: str = "Général",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        format_name = normalize_format(format_name)
        async with expansion_connection() as db:
            season = await (
                await db.execute(
                    "SELECT * FROM competitive_seasons WHERE id=? AND guild_id=?",
                    (season_id, guild_id),
                )
            ).fetchone()
            if season is None:
                raise ValueError("Saison introuvable.")
            if str(season["status"]) == "closed":
                rows = await (
                    await db.execute(
                        """
                        SELECT discord_id, player_name, format, rating, games, wins, losses, rank
                        FROM season_ranking_snapshots
                        WHERE guild_id=? AND season_id=? AND format=?
                        ORDER BY rank LIMIT ?
                        """,
                        (guild_id, season_id, format_name, max(1, min(limit, 100))),
                    )
                ).fetchall()
                if rows:
                    return [dict(row) for row in rows]
        return await self.ranking(
            guild_id, format_name, limit, season_id=season_id, official_only=True
        )

    async def season_summary(self, guild_id: str, season_id: int) -> dict[str, Any]:
        async with expansion_connection() as db:
            season = await (
                await db.execute(
                    "SELECT * FROM competitive_seasons WHERE id=? AND guild_id=?",
                    (season_id, guild_id),
                )
            ).fetchone()
            if season is None:
                raise ValueError("Saison introuvable.")
            snapshots = await (
                await db.execute(
                    """
                    SELECT * FROM season_ranking_snapshots
                    WHERE guild_id=? AND season_id=?
                    ORDER BY CASE format WHEN 'Général' THEN 0 ELSE 1 END, format, rank
                    """,
                    (guild_id, season_id),
                )
            ).fetchall()
            total = await (
                await db.execute(
                    """
                    SELECT COUNT(DISTINCT discord_id) AS players,
                           COALESCE(SUM(games),0)/2 AS matches
                    FROM competitive_ratings
                    WHERE guild_id=? AND season_id=? AND games>0
                    """,
                    (guild_id, season_id),
                )
            ).fetchone()
        rows = [dict(row) for row in snapshots]
        general = [row for row in rows if row["format"] == "Général"]
        format_champions = [
            row for row in rows if row["format"] != "Général" and int(row["rank"]) == 1
        ]
        return {
            "season": dict(season),
            "podium": general[:3],
            "format_champions": format_champions,
            "qualified_players": len({row["discord_id"] for row in general}),
            "players": int(total["players"] or 0),
            "matches": int(total["matches"] or 0),
            "minimum_games": MIN_OFFICIAL_GAMES,
        }

    async def mark_season_summary_sent(self, season_id: int) -> None:
        async with expansion_connection() as db:
            await db.execute(
                "UPDATE competitive_seasons SET final_summary_sent=1 WHERE id=?",
                (season_id,),
            )
            await db.commit()

    async def announcement_channel_id(self, guild_id: str) -> str | None:
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    "SELECT announcements_channel_id FROM expansion_settings WHERE guild_id=?",
                    (guild_id,),
                )
            ).fetchone()
            return str(row["announcements_channel_id"]) if row and row["announcements_channel_id"] else None

    async def player_rating(
        self,
        guild_id: str,
        discord_id: str,
        format_name: str,
    ) -> dict[str, Any]:
        format_name = normalize_format(format_name)
        season = await self.display_season(guild_id)
        season_id = int(season["id"])
        async with expansion_connection() as db:
            if format_name == "Général":
                row = await (
                    await db.execute(
                        """
                        SELECT
                            guild_id, discord_id, 'Général' AS format, season_id,
                            CAST(ROUND(SUM(rating * games) * 1.0 / NULLIF(SUM(games),0)) AS INTEGER) AS rating,
                            MAX(peak_rating) AS peak_rating, SUM(games) AS games,
                            SUM(wins) AS wins, SUM(losses) AS losses,
                            MAX(current_streak) AS current_streak,
                            MAX(best_streak) AS best_streak, MAX(updated_at) AS updated_at
                        FROM competitive_ratings
                        WHERE guild_id=? AND discord_id=? AND season_id=? AND games>0
                        GROUP BY guild_id, discord_id, season_id
                        """,
                        (guild_id, discord_id, season_id),
                    )
                ).fetchone()
            else:
                row = await (
                    await db.execute(
                        """
                        SELECT * FROM competitive_ratings
                        WHERE guild_id=? AND discord_id=? AND format=? AND season_id=?
                        """,
                        (guild_id, discord_id, format_name, season_id),
                    )
                ).fetchone()

            result = dict(row) if row else {
                "guild_id": guild_id, "discord_id": discord_id, "format": format_name,
                "season_id": season_id, "rating": DEFAULT_RATING, "peak_rating": DEFAULT_RATING,
                "games": 0, "wins": 0, "losses": 0, "current_streak": 0, "best_streak": 0,
            }
            games = int(result["games"] or 0)
            result["official"] = games >= MIN_OFFICIAL_GAMES
            result["games_until_ranked"] = max(0, MIN_OFFICIAL_GAMES - games)
            result["season_name"] = season["name"]
            if not result["official"]:
                result["rank"] = None
                return result

            rating = int(result["rating"] or DEFAULT_RATING)
            if format_name == "Général":
                rank = await (
                    await db.execute(
                        """
                        WITH general_ratings AS (
                            SELECT discord_id,
                                   CAST(ROUND(SUM(rating * games) * 1.0 / NULLIF(SUM(games),0)) AS INTEGER) AS value,
                                   SUM(games) AS games
                            FROM competitive_ratings
                            WHERE guild_id=? AND season_id=? AND games>0
                            GROUP BY discord_id
                            HAVING SUM(games)>=?
                        )
                        SELECT 1 + COUNT(*) AS rank FROM general_ratings WHERE value>?
                        """,
                        (guild_id, season_id, MIN_OFFICIAL_GAMES, rating),
                    )
                ).fetchone()
            else:
                rank = await (
                    await db.execute(
                        """
                        SELECT 1 + COUNT(*) AS rank FROM competitive_ratings
                        WHERE guild_id=? AND format=? AND season_id=? AND games>=? AND rating>?
                        """,
                        (guild_id, format_name, season_id, MIN_OFFICIAL_GAMES, rating),
                    )
                ).fetchone()
            result["rank"] = int(rank["rank"])
            return result

    async def history(
        self,
        guild_id: str,
        discord_id: str,
        format_name: str,
        limit: int = 15,
    ) -> list[dict[str, Any]]:
        season_id = int((await self.display_season(guild_id))["id"])
        normalized = normalize_format(format_name)
        async with expansion_connection() as db:
            if normalized == "Général":
                rows = await (
                    await db.execute(
                        """
                        SELECT * FROM rating_history
                        WHERE guild_id=? AND discord_id=? AND season_id=?
                        ORDER BY id DESC LIMIT ?
                        """,
                        (guild_id, discord_id, season_id, max(1, min(limit, 50))),
                    )
                ).fetchall()
            else:
                rows = await (
                    await db.execute(
                        """
                        SELECT * FROM rating_history
                        WHERE guild_id=? AND discord_id=? AND format=? AND season_id=?
                        ORDER BY id DESC LIMIT ?
                        """,
                        (
                            guild_id,
                            discord_id,
                            normalized,
                            season_id,
                            max(1, min(limit, 50)),
                        ),
                    )
                ).fetchall()
            return [dict(row) for row in rows]

    async def head_to_head(
        self,
        guild_id: str,
        player1_id: str,
        player2_id: str,
        format_name: str | None = None,
    ) -> dict[str, Any]:
        filters = ["guild_id=?", "player1_id IN (?,?)", "player2_id IN (?,?)"]
        parameters: list[Any] = [
            guild_id,
            player1_id,
            player2_id,
            player1_id,
            player2_id,
        ]
        if format_name:
            filters.append("format=?")
            parameters.append(normalize_format(format_name))
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    f"""
                    SELECT * FROM processed_competitive_matches
                    WHERE {' AND '.join(filters)}
                    ORDER BY processed_at DESC
                    """,
                    tuple(parameters),
                )
            ).fetchall()
            p1_wins = sum(1 for row in rows if str(row["winner_id"]) == player1_id)
            p2_wins = sum(1 for row in rows if str(row["winner_id"]) == player2_id)
            return {
                "matches": len(rows),
                "player1_wins": p1_wins,
                "player2_wins": p2_wins,
                "last": dict(rows[0]) if rows else None,
            }

    async def reset_and_rebuild(self, guild_id: str) -> int:
        async with expansion_connection() as db:
            await db.execute("DELETE FROM rating_history WHERE guild_id=?", (guild_id,))
            await db.execute("DELETE FROM competitive_ratings WHERE guild_id=?", (guild_id,))
            await db.execute("DELETE FROM processed_competitive_matches WHERE guild_id=?", (guild_id,))
            await db.execute(
                "DELETE FROM player_achievements WHERE guild_id=? AND achievement_code IN ('first_duel','five_streak','bo5_master','versatile','giant_killer','hundred_games')",
                (guild_id,),
            )
            await db.commit()
        return await self.sync_completed_matches(guild_id)
