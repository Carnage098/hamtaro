from __future__ import annotations

import datetime as dt
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite

try:
    from config import DATABASE
except ImportError:
    from database import DATABASE

from services.deck_intelligence_service import DeckIntelligenceService


COMPLETED = ("approved", "validated", "completed")


class MetaCenterV2Service:
    """Statistiques avancées du métagame Hamtaro.

    Aucun minimum de matchs n'est appliqué pour apparaître. Les petits
    échantillons reçoivent simplement un badge explicite.
    """

    def __init__(self, database_path: str = DATABASE) -> None:
        self.database_path = database_path
        self.deck_intel = DeckIntelligenceService()

    @asynccontextmanager
    async def _connect(self):
        db = await aiosqlite.connect(self.database_path)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()

    @staticmethod
    def _safe_date(value: Any) -> dt.datetime | None:
        raw = str(value or "").strip().replace("Z", "+00:00")
        if not raw:
            return None
        try:
            parsed = dt.datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        except ValueError:
            return None

    async def _table_exists(self, db, name: str) -> bool:
        row = await (
            await db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            )
        ).fetchone()
        return row is not None

    async def _columns(self, db, name: str) -> set[str]:
        rows = await (await db.execute(f"PRAGMA table_info({name})")).fetchall()
        return {str(row[1]) for row in rows}

    async def _fetch_matches(
        self,
        guild_id: str,
        *,
        format_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self._connect() as db:
            results: list[dict[str, Any]] = []
            fmt_sql = ""
            fmt_params: list[Any] = []
            if format_filter:
                fmt_sql = "AND LOWER(TRIM(t.format)) = LOWER(TRIM(?))"
                fmt_params.append(format_filter)

            if await self._table_exists(db, "matches"):
                cols = await self._columns(db, "matches")
                played_at = (
                    "COALESCE(m.validated_at, m.created_at)"
                    if "validated_at" in cols else "m.created_at"
                )
                rows = await (
                    await db.execute(
                        f"""
                        SELECT 'bracket' kind, m.id, m.tournament_id,
                               m.player1_id, m.player2_id, m.winner_id,
                               m.status, {played_at} played_at,
                               t.format,
                               r1.deck player1_deck, r2.deck player2_deck
                        FROM matches m
                        JOIN tournaments t ON t.id=m.tournament_id
                        LEFT JOIN registrations r1
                          ON r1.tournament_id=m.tournament_id
                         AND r1.discord_id=m.player1_id
                        LEFT JOIN registrations r2
                          ON r2.tournament_id=m.tournament_id
                         AND r2.discord_id=m.player2_id
                        WHERE t.guild_id=?
                          AND m.status IN ('approved','validated','completed')
                          AND COALESCE(m.is_bye,0)=0
                          {fmt_sql}
                        """,
                        tuple([guild_id] + fmt_params),
                    )
                ).fetchall()
                results.extend(dict(row) for row in rows)

            if await self._table_exists(db, "swiss_matches"):
                cols = await self._columns(db, "swiss_matches")
                played_at = (
                    "COALESCE(sm.validated_at, sm.reported_at, sm.created_at)"
                    if "validated_at" in cols and "reported_at" in cols
                    else "COALESCE(sm.reported_at, sm.created_at)"
                    if "reported_at" in cols else "sm.created_at"
                )
                bye_expr = "COALESCE(sm.is_bye,0)" if "is_bye" in cols else "0"
                rows = await (
                    await db.execute(
                        f"""
                        SELECT 'swiss' kind, sm.id, sm.tournament_id,
                               sm.player1_id, sm.player2_id, sm.winner_id,
                               sm.status, {played_at} played_at,
                               t.format,
                               r1.deck player1_deck, r2.deck player2_deck
                        FROM swiss_matches sm
                        JOIN tournaments t ON t.id=sm.tournament_id
                        LEFT JOIN registrations r1
                          ON r1.tournament_id=sm.tournament_id
                         AND r1.discord_id=sm.player1_id
                        LEFT JOIN registrations r2
                          ON r2.tournament_id=sm.tournament_id
                         AND r2.discord_id=sm.player2_id
                        WHERE t.guild_id=?
                          AND sm.status IN ('approved','validated','completed')
                          AND {bye_expr}=0
                          {fmt_sql}
                        """,
                        tuple([guild_id] + fmt_params),
                    )
                ).fetchall()
                results.extend(dict(row) for row in rows)
        return results

    async def _season_start(self, guild_id: str) -> dt.datetime | None:
        async with self._connect() as db:
            for table in ("competitive_seasons", "seasons"):
                if not await self._table_exists(db, table):
                    continue
                cols = await self._columns(db, table)
                if "guild_id" not in cols:
                    continue
                date_col = "starts_at" if "starts_at" in cols else "created_at"
                status_sql = (
                    "AND status IN ('active','running','open')"
                    if "status" in cols else ""
                )
                row = await (
                    await db.execute(
                        f"""
                        SELECT {date_col} value
                        FROM {table}
                        WHERE guild_id=? {status_sql}
                        ORDER BY id DESC LIMIT 1
                        """,
                        (guild_id,),
                    )
                ).fetchone()
                if row:
                    return self._safe_date(row["value"])
        return None

    async def _window_start(self, guild_id: str, period: str) -> dt.datetime | None:
        now = dt.datetime.now(dt.timezone.utc)
        if period == "7d":
            return now - dt.timedelta(days=7)
        if period == "30d":
            return now - dt.timedelta(days=30)
        if period == "season":
            return await self._season_start(guild_id)
        return None

    @staticmethod
    def _sample_label(matches: int) -> str:
        if matches <= 2:
            return "Échantillon très faible"
        if matches <= 7:
            return "Échantillon faible"
        return ""

    async def overview(
        self,
        guild_id: str,
        *,
        period: str = "30d",
        format_filter: str | None = None,
    ) -> dict[str, Any]:
        matches = await self._fetch_matches(guild_id, format_filter=format_filter)
        start = await self._window_start(guild_id, period)
        now = dt.datetime.now(dt.timezone.utc)

        selected = []
        for match in matches:
            date = self._safe_date(match.get("played_at"))
            if start and (date is None or date < start):
                continue
            selected.append(match)

        previous: list[dict[str, Any]] = []
        if start and period in {"7d", "30d"}:
            span = now - start
            previous_start = start - span
            for match in matches:
                date = self._safe_date(match.get("played_at"))
                if date and previous_start <= date < start:
                    previous.append(match)

        async def build(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
            stats: dict[str, dict[str, Any]] = {}
            for match in rows:
                p1 = DeckIntelligenceService.normalize_text(match.get("player1_deck"))
                p2 = DeckIntelligenceService.normalize_text(match.get("player2_deck"))
                if not p1 or not p2:
                    continue
                # La canonicalisation complète dépend du DB service du bot ;
                # la normalisation canonique à l'inscription évite déjà les alias.
                for deck, pid, is_p1 in (
                    (p1, str(match.get("player1_id") or ""), True),
                    (p2, str(match.get("player2_id") or ""), False),
                ):
                    row = stats.setdefault(
                        deck.casefold(),
                        {
                            "deck": deck, "matches": 0, "wins": 0, "losses": 0,
                            "players": set(), "opponents": defaultdict(lambda: [0, 0]),
                        },
                    )
                    row["matches"] += 1
                    if pid:
                        row["players"].add(pid)
                    winner = str(match.get("winner_id") or "")
                    if winner and winner == pid:
                        row["wins"] += 1
                    elif winner:
                        row["losses"] += 1
                    opponent = p2 if is_p1 else p1
                    opp = row["opponents"][opponent]
                    opp[0] += 1
                    if winner and winner == pid:
                        opp[1] += 1
            return stats

        current_stats = await build(selected)
        previous_stats = await build(previous)
        total_appearances = sum(v["matches"] for v in current_stats.values()) or 1
        previous_appearances = sum(v["matches"] for v in previous_stats.values()) or 1

        items = []
        for key, row in current_stats.items():
            matches_n = int(row["matches"])
            wins = int(row["wins"])
            rate = wins / matches_n * 100 if matches_n else 0.0
            share = matches_n / total_appearances * 100
            old = previous_stats.get(key)
            old_share = (old["matches"] / previous_appearances * 100) if old else 0.0
            old_rate = (
                old["wins"] / old["matches"] * 100
                if old and old["matches"] else 0.0
            )
            matchups = []
            for opponent, pair in row["opponents"].items():
                games, matchup_wins = pair
                matchups.append({
                    "opponent": opponent,
                    "matches": games,
                    "wins": matchup_wins,
                    "win_rate": matchup_wins / games * 100 if games else 0.0,
                })
            matchups.sort(key=lambda x: (x["matches"], x["win_rate"]), reverse=True)
            items.append({
                "deck": row["deck"],
                "players": len(row["players"]),
                "matches": matches_n,
                "wins": wins,
                "losses": int(row["losses"]),
                "win_rate": rate,
                "popularity": share,
                "popularity_delta": share - old_share,
                "win_rate_delta": rate - old_rate if previous else 0.0,
                "sample_label": self._sample_label(matches_n),
                "emerging_score": (share - old_share) * 2 + min(matches_n, 12) / 12,
                "common_opponents": matchups[:5],
            })

        items.sort(
            key=lambda x: (x["players"], x["matches"], x["win_rate"]),
            reverse=True,
        )
        emerging = sorted(
            items, key=lambda x: (x["emerging_score"], x["matches"]), reverse=True
        )[:5]
        podium = sorted(
            items, key=lambda x: (x["players"], x["matches"], x["win_rate"]),
            reverse=True,
        )[:3]
        return {
            "period": period,
            "format": format_filter or "",
            "matches": len(selected),
            "decks": len(items),
            "items": items,
            "emerging": emerging,
            "podium": podium,
        }

    async def deck_detail(
        self,
        guild_id: str,
        deck_name: str,
        *,
        period: str = "30d",
        format_filter: str | None = None,
    ) -> dict[str, Any]:
        overview = await self.overview(
            guild_id, period=period, format_filter=format_filter
        )
        key = DeckIntelligenceService.normalize_text(deck_name).casefold()
        item = next(
            (row for row in overview["items"] if row["deck"].casefold() == key),
            None,
        )
        if item is None:
            return {"deck": deck_name, "matchups": [], "pilots": [], "timeline": []}

        matches = await self._fetch_matches(guild_id, format_filter=format_filter)
        start = await self._window_start(guild_id, period)
        pilots: dict[str, dict[str, Any]] = {}
        timeline: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        matchups = defaultdict(lambda: [0, 0])

        for match in matches:
            date = self._safe_date(match.get("played_at"))
            if start and (date is None or date < start):
                continue
            p1 = DeckIntelligenceService.normalize_text(match.get("player1_deck"))
            p2 = DeckIntelligenceService.normalize_text(match.get("player2_deck"))
            for deck, player_id, opponent in (
                (p1, str(match.get("player1_id") or ""), p2),
                (p2, str(match.get("player2_id") or ""), p1),
            ):
                if not deck or deck.casefold() != key:
                    continue
                winner = str(match.get("winner_id") or "")
                pilot = pilots.setdefault(
                    player_id, {"player_id": player_id, "matches": 0, "wins": 0}
                )
                pilot["matches"] += 1
                if winner == player_id:
                    pilot["wins"] += 1
                if opponent:
                    matchups[opponent][0] += 1
                    if winner == player_id:
                        matchups[opponent][1] += 1
                if date:
                    bucket = date.date().isoformat()
                    timeline[bucket][0] += 1
                    if winner == player_id:
                        timeline[bucket][1] += 1

        pilot_rows = list(pilots.values())
        for row in pilot_rows:
            row["win_rate"] = (
                row["wins"] / row["matches"] * 100 if row["matches"] else 0.0
            )
        pilot_rows.sort(
            key=lambda x: (x["wins"], x["win_rate"], x["matches"]), reverse=True
        )
        matchup_rows = [
            {
                "opponent": opp,
                "matches": values[0],
                "wins": values[1],
                "win_rate": values[1] / values[0] * 100 if values[0] else 0.0,
            }
            for opp, values in matchups.items()
        ]
        matchup_rows.sort(key=lambda x: (x["matches"], x["win_rate"]), reverse=True)
        timeline_rows = [
            {
                "date": day, "matches": values[0], "wins": values[1],
                "win_rate": values[1] / values[0] * 100 if values[0] else 0.0,
            }
            for day, values in sorted(timeline.items())
        ]
        return {
            **item,
            "matchups": matchup_rows,
            "pilots": pilot_rows[:10],
            "timeline": timeline_rows,
        }
