from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite

try:
    from config import DATABASE
except ImportError:
    from database import DATABASE

from services.deck_canonicalizer import DeckCanonicalizer


APPROVED_STATUSES = {"approved", "validated", "completed"}
IGNORED_TOURNAMENT_STATUSES = {
    "registration",
    "open",
    "draft",
    "cancelled",
    "canceled",
    "deleted",
}


class ArchetypeStatsService:
    """Source de vérité pour les statistiques de /archetypes.

    - fusionne les alias ;
    - exclut les tournois uniquement en inscription / annulés ;
    - utilise seulement les matchs validés pour les W/L ;
    - compte les joueurs uniques après canonicalisation.
    """

    def __init__(
        self,
        database_path: str = DATABASE,
        canonicalizer: DeckCanonicalizer | None = None,
    ) -> None:
        self.database_path = database_path
        self.canonicalizer = canonicalizer or DeckCanonicalizer()

    @asynccontextmanager
    async def _connect(self):
        db = await aiosqlite.connect(self.database_path)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()

    @staticmethod
    async def _table_exists(db, table: str) -> bool:
        row = await (
            await db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
        ).fetchone()
        return row is not None

    @staticmethod
    async def _columns(db, table: str) -> set[str]:
        rows = await (await db.execute(f"PRAGMA table_info({table})")).fetchall()
        return {str(row[1]) for row in rows}

    async def _relevant_tournaments(
        self,
        db,
        guild_id: str,
        format_filter: str | None,
    ) -> set[int]:
        params: list[Any] = [guild_id]
        format_sql = ""
        if format_filter:
            format_sql = "AND LOWER(TRIM(format))=LOWER(TRIM(?))"
            params.append(format_filter)
        rows = await (
            await db.execute(
                f"""
                SELECT id, LOWER(TRIM(COALESCE(status,''))) AS status
                FROM tournaments
                WHERE guild_id=?
                {format_sql}
                """,
                tuple(params),
            )
        ).fetchall()

        candidates = {
            int(row["id"])
            for row in rows
            if str(row["status"] or "") not in IGNORED_TOURNAMENT_STATUSES
        }

        # Un tournoi avec un vrai résultat validé est pertinent même si son
        # statut historique est inhabituel.
        for table in ("matches", "swiss_matches"):
            if not await self._table_exists(db, table):
                continue
            cols = await self._columns(db, table)
            if "status" not in cols or "tournament_id" not in cols:
                continue
            query = f"""
                SELECT DISTINCT m.tournament_id
                FROM {table} m
                JOIN tournaments t ON t.id=m.tournament_id
                WHERE t.guild_id=?
                  AND LOWER(TRIM(COALESCE(m.status,'')))
                      IN ('approved','validated','completed')
            """
            values: list[Any] = [guild_id]
            if format_filter:
                query += " AND LOWER(TRIM(t.format))=LOWER(TRIM(?))"
                values.append(format_filter)
            for row in await (await db.execute(query, tuple(values))).fetchall():
                candidates.add(int(row["tournament_id"]))
        return candidates

    async def _registration_rows(
        self,
        db,
        guild_id: str,
        tournament_ids: set[int],
    ) -> list[dict[str, Any]]:
        if not tournament_ids:
            return []
        placeholders = ",".join("?" for _ in tournament_ids)
        rows = await (
            await db.execute(
                f"""
                SELECT r.id, r.tournament_id, r.discord_id, r.username,
                       r.deck, r.final_rank, t.winner_id
                FROM registrations r
                JOIN tournaments t ON t.id=r.tournament_id
                WHERE t.guild_id=?
                  AND r.tournament_id IN ({placeholders})
                  AND TRIM(COALESCE(r.deck,'')) <> ''
                """,
                tuple([guild_id, *sorted(tournament_ids)]),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    async def _validated_match_rows(
        self,
        db,
        guild_id: str,
        tournament_ids: set[int],
    ) -> list[dict[str, Any]]:
        if not tournament_ids:
            return []
        out: list[dict[str, Any]] = []
        placeholders = ",".join("?" for _ in tournament_ids)

        for kind, table in (("bracket", "matches"), ("swiss", "swiss_matches")):
            if not await self._table_exists(db, table):
                continue
            cols = await self._columns(db, table)
            required = {"tournament_id", "player1_id", "player2_id", "winner_id"}
            if not required.issubset(cols):
                continue

            status_expr = (
                "LOWER(TRIM(COALESCE(m.status,'')))"
                if "status" in cols else "'completed'"
            )
            is_bye = "COALESCE(m.is_bye,0)" if "is_bye" in cols else "0"
            is_double_loss = (
                "COALESCE(m.is_double_loss,0)"
                if "is_double_loss" in cols else "0"
            )
            rows = await (
                await db.execute(
                    f"""
                    SELECT '{kind}' AS kind,
                           m.id, m.tournament_id,
                           m.player1_id, m.player2_id, m.winner_id,
                           {is_bye} AS is_bye,
                           {is_double_loss} AS is_double_loss
                    FROM {table} m
                    JOIN tournaments t ON t.id=m.tournament_id
                    WHERE t.guild_id=?
                      AND m.tournament_id IN ({placeholders})
                      AND {status_expr}
                          IN ('approved','validated','completed')
                    """,
                    tuple([guild_id, *sorted(tournament_ids)]),
                )
            ).fetchall()
            out.extend(dict(row) for row in rows)
        return out

    async def list_archetypes(
        self,
        guild_id: str,
        *,
        format_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self._connect() as db:
            tournament_ids = await self._relevant_tournaments(
                db, guild_id, format_filter
            )
            registrations = await self._registration_rows(
                db, guild_id, tournament_ids
            )
            matches = await self._validated_match_rows(
                db, guild_id, tournament_ids
            )

        deck_display: dict[str, str] = {}
        player_sets: dict[str, set[str]] = defaultdict(set)
        top4_counts: Counter[str] = Counter()
        tournament_win_counts: Counter[str] = Counter()
        deck_by_tp: dict[tuple[int, str], str] = {}

        for row in registrations:
            deck = self.canonicalizer.canonicalize(row.get("deck"))
            if not deck:
                continue
            key = self.canonicalizer.canonical_key(deck)
            deck_display.setdefault(key, deck)
            tournament_id = int(row["tournament_id"])
            player_id = str(row["discord_id"])
            deck_by_tp[(tournament_id, player_id)] = key
            player_sets[key].add(player_id)

            try:
                rank = int(row.get("final_rank") or 0)
            except (TypeError, ValueError):
                rank = 0
            if 1 <= rank <= 4:
                top4_counts[key] += 1
            if str(row.get("winner_id") or "") == player_id:
                tournament_win_counts[key] += 1

        match_counts: Counter[str] = Counter()
        win_counts: Counter[str] = Counter()
        loss_counts: Counter[str] = Counter()
        double_loss_counts: Counter[str] = Counter()

        for match in matches:
            if int(match.get("is_bye") or 0):
                continue
            tournament_id = int(match["tournament_id"])
            p1 = str(match.get("player1_id") or "")
            p2 = str(match.get("player2_id") or "")
            winner = str(match.get("winner_id") or "")
            double_loss = bool(int(match.get("is_double_loss") or 0))

            for player_id in (p1, p2):
                if not player_id:
                    continue
                key = deck_by_tp.get((tournament_id, player_id))
                if not key:
                    continue
                match_counts[key] += 1
                if double_loss:
                    double_loss_counts[key] += 1
                elif winner == player_id:
                    win_counts[key] += 1
                elif winner:
                    loss_counts[key] += 1

        rows: list[dict[str, Any]] = []
        for key, deck in deck_display.items():
            matches_n = int(match_counts[key])
            wins = int(win_counts[key])
            rows.append(
                {
                    "deck": deck,
                    "players": len(player_sets[key]),
                    "matches": matches_n,
                    "wins": wins,
                    "losses": int(loss_counts[key]),
                    "double_losses": int(double_loss_counts[key]),
                    "win_rate": (
                        wins / matches_n * 100.0 if matches_n else 0.0
                    ),
                    "top4": int(top4_counts[key]),
                    "tournament_wins": int(tournament_win_counts[key]),
                    "sample_label": (
                        "Échantillon très faible"
                        if matches_n <= 2
                        else "Échantillon faible"
                        if matches_n <= 7
                        else ""
                    ),
                }
            )
        return rows

    async def players_for_deck(
        self,
        guild_id: str,
        deck_name: str,
        *,
        format_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        target = self.canonicalizer.canonical_key(deck_name)
        async with self._connect() as db:
            tournament_ids = await self._relevant_tournaments(
                db, guild_id, format_filter
            )
            registrations = await self._registration_rows(
                db, guild_id, tournament_ids
            )
            matching = [
                row for row in registrations
                if self.canonicalizer.canonical_key(row.get("deck")) == target
            ]
            if not matching:
                return []

            ids = sorted({str(row["discord_id"]) for row in matching})
            profiles: dict[str, dict[str, Any]] = {}
            if ids and await self._table_exists(db, "players"):
                placeholders = ",".join("?" for _ in ids)
                rows = await (
                    await db.execute(
                        f"""
                        SELECT discord_id, username, display_name, avatar_url
                        FROM players
                        WHERE guild_id=? AND discord_id IN ({placeholders})
                        """,
                        tuple([guild_id, *ids]),
                    )
                ).fetchall()
                profiles = {
                    str(row["discord_id"]): dict(row)
                    for row in rows
                }

        tournament_sets: dict[str, set[int]] = defaultdict(set)
        names: dict[str, str] = {}
        for row in matching:
            player_id = str(row["discord_id"])
            tournament_sets[player_id].add(int(row["tournament_id"]))
            names.setdefault(player_id, str(row.get("username") or player_id))

        result = []
        for player_id in ids:
            profile = profiles.get(player_id, {})
            result.append(
                {
                    "discord_id": player_id,
                    "display_name": str(
                        profile.get("display_name")
                        or profile.get("username")
                        or names.get(player_id)
                        or player_id
                    ),
                    "avatar_url": profile.get("avatar_url"),
                    # Corrigé : uniquement les tournois joués avec CE deck.
                    "tournaments": len(tournament_sets[player_id]),
                }
            )
        result.sort(key=lambda row: row["display_name"].casefold())
        return result

    async def deck_exists(self, guild_id: str, deck_name: str) -> bool:
        target = self.canonicalizer.canonical_key(deck_name)
        async with self._connect() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT r.deck
                    FROM registrations r
                    JOIN tournaments t ON t.id=r.tournament_id
                    WHERE t.guild_id=?
                      AND TRIM(COALESCE(r.deck,'')) <> ''
                    """,
                    (guild_id,),
                )
            ).fetchall()
        return any(
            self.canonicalizer.canonical_key(row["deck"]) == target
            for row in rows
        )
