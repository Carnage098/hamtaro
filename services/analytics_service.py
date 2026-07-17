from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Iterable

import aiosqlite

try:
    from config import DATABASE
except ImportError:
    from database import DATABASE


BRACKET_COMPLETED_STATUSES = ("approved", "validated", "completed")
SWISS_COMPLETED_STATUSES = ("completed", "validated", "approved")


@dataclass(slots=True)
class PlayerSummary:
    player_id: str
    username: str
    display_name: str
    avatar_url: str | None
    matches: int
    wins: int
    losses: int
    double_losses: int
    byes: int
    win_rate: float
    tournaments_played: int
    tournaments_won: int
    finals: int
    top4: int
    current_streak: int
    best_streak: int
    current_deck: str | None
    most_used_deck: str | None
    best_deck: str | None
    best_deck_win_rate: float | None


@dataclass(slots=True)
class DeckSummary:
    deck: str
    players: int
    matches: int
    wins: int
    losses: int
    double_losses: int
    win_rate: float
    top4: int
    tournament_wins: int


class AnalyticsService:
    """Statistiques et exports pour Hamtaro.

    Le service lit directement les tables réelles du bot. Les colonnes ajoutées
    par les versions récentes (Double Loss, audit des résultats, undo, etc.)
    sont détectées dynamiquement afin de rester compatible avec les anciennes
    bases SQLite.
    """

    def __init__(self, database_path: str = DATABASE):
        self.database_path = database_path

    @asynccontextmanager
    async def _connect(self):
        db = await aiosqlite.connect(self.database_path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
        finally:
            await db.close()

    @staticmethod
    async def _table_exists(db: aiosqlite.Connection, table: str) -> bool:
        cursor = await db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        )
        return await cursor.fetchone() is not None

    @staticmethod
    async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
        cursor = await db.execute(f"PRAGMA table_info({table})")
        return {str(row[1]) for row in await cursor.fetchall()}

    @staticmethod
    def _row_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalized_deck(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    async def get_tournament_by_code(
        self,
        guild_id: str,
        code: str,
    ) -> dict[str, Any] | None:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM tournaments WHERE guild_id = ? AND UPPER(code) = UPPER(?)",
                (guild_id, code.strip()),
            )
            return self._row_dict(await cursor.fetchone())

    async def get_latest_tournament(
        self,
        guild_id: str,
        *,
        active_first: bool = True,
    ) -> dict[str, Any] | None:
        ordering = (
            "CASE WHEN status IN ('running', 'registration', 'paused') THEN 0 ELSE 1 END, id DESC"
            if active_first
            else "id DESC"
        )
        async with self._connect() as db:
            cursor = await db.execute(
                f"SELECT * FROM tournaments WHERE guild_id = ? ORDER BY {ordering} LIMIT 1",
                (guild_id,),
            )
            return self._row_dict(await cursor.fetchone())

    async def _player_identity(
        self,
        db: aiosqlite.Connection,
        guild_id: str,
        player_id: str,
        fallback_name: str,
    ) -> dict[str, Any]:
        cursor = await db.execute(
            """
            SELECT discord_id, username, display_name, avatar_url
            FROM players
            WHERE guild_id = ? AND discord_id = ?
            """,
            (guild_id, player_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return {
                "discord_id": player_id,
                "username": fallback_name,
                "display_name": fallback_name,
                "avatar_url": None,
            }
        return {
            "discord_id": str(row["discord_id"]),
            "username": str(row["username"] or fallback_name),
            "display_name": str(row["display_name"] or row["username"] or fallback_name),
            "avatar_url": row["avatar_url"],
        }

    async def _fetch_player_matches(
        self,
        db: aiosqlite.Connection,
        guild_id: str,
        player_id: str,
        tournament_id: int | None = None,
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []

        bracket_columns = await self._columns(db, "matches")
        bracket_filter = ""
        parameters: list[Any] = [guild_id, player_id, player_id]
        if tournament_id is not None:
            bracket_filter = "AND m.tournament_id = ?"
            parameters.append(tournament_id)

        validated_at = "m.validated_at" if "validated_at" in bracket_columns else "NULL"
        is_bye = "m.is_bye" if "is_bye" in bracket_columns else "0"
        score_text = "m.score" if "score" in bracket_columns else "NULL"
        cursor = await db.execute(
            f"""
            SELECT
                'bracket' AS match_kind,
                m.id,
                m.tournament_id,
                m.round AS round_number,
                m.match_number AS table_number,
                m.player1_id,
                m.player2_id,
                m.player1_name,
                m.player2_name,
                m.player1_score,
                m.player2_score,
                m.winner_id,
                m.winner_name,
                {is_bye} AS is_bye,
                0 AS is_double_loss,
                m.status,
                COALESCE({validated_at}, m.created_at) AS played_at,
                {score_text} AS score_text,
                t.name AS tournament_name,
                t.code AS tournament_code,
                t.format AS tournament_format,
                r1.deck AS player1_deck,
                r2.deck AS player2_deck
            FROM matches m
            JOIN tournaments t ON t.id = m.tournament_id
            LEFT JOIN registrations r1
                ON r1.tournament_id = m.tournament_id
               AND r1.discord_id = m.player1_id
            LEFT JOIN registrations r2
                ON r2.tournament_id = m.tournament_id
               AND r2.discord_id = m.player2_id
            WHERE t.guild_id = ?
              AND (m.player1_id = ? OR m.player2_id = ?)
              AND m.status IN ('approved', 'validated', 'completed')
              {bracket_filter}
            """,
            tuple(parameters),
        )
        matches.extend(dict(row) for row in await cursor.fetchall())

        if await self._table_exists(db, "swiss_matches"):
            swiss_columns = await self._columns(db, "swiss_matches")
            swiss_filter = ""
            swiss_parameters: list[Any] = [guild_id, player_id, player_id]
            if tournament_id is not None:
                swiss_filter = "AND sm.tournament_id = ?"
                swiss_parameters.append(tournament_id)

            if "is_double_loss" in swiss_columns:
                double_loss_expr = "sm.is_double_loss"
            elif "result" in swiss_columns:
                double_loss_expr = "CASE WHEN LOWER(COALESCE(sm.result, '')) IN ('double_loss', 'draw') THEN 1 ELSE 0 END"
            elif "is_draw" in swiss_columns:
                double_loss_expr = "sm.is_draw"
            else:
                double_loss_expr = "0"

            is_bye_expr = "sm.is_bye" if "is_bye" in swiss_columns else "0"
            played_at = (
                "COALESCE(sm.validated_at, sm.reported_at, sm.created_at)"
                if "validated_at" in swiss_columns
                else "COALESCE(sm.reported_at, sm.created_at)"
                if "reported_at" in swiss_columns
                else "sm.created_at"
            )
            cursor = await db.execute(
                f"""
                SELECT
                    'swiss' AS match_kind,
                    sm.id,
                    sm.tournament_id,
                    sm.round_number,
                    sm.table_number,
                    sm.player1_id,
                    sm.player2_id,
                    sm.player1_name,
                    sm.player2_name,
                    sm.player1_score,
                    sm.player2_score,
                    sm.winner_id,
                    sm.winner_name,
                    {is_bye_expr} AS is_bye,
                    {double_loss_expr} AS is_double_loss,
                    sm.status,
                    {played_at} AS played_at,
                    NULL AS score_text,
                    t.name AS tournament_name,
                    t.code AS tournament_code,
                    t.format AS tournament_format,
                    r1.deck AS player1_deck,
                    r2.deck AS player2_deck
                FROM swiss_matches sm
                JOIN tournaments t ON t.id = sm.tournament_id
                LEFT JOIN registrations r1
                    ON r1.tournament_id = sm.tournament_id
                   AND r1.discord_id = sm.player1_id
                LEFT JOIN registrations r2
                    ON r2.tournament_id = sm.tournament_id
                   AND r2.discord_id = sm.player2_id
                WHERE t.guild_id = ?
                  AND (sm.player1_id = ? OR sm.player2_id = ?)
                  AND sm.status IN ('completed', 'validated', 'approved')
                  {swiss_filter}
                """,
                tuple(swiss_parameters),
            )
            matches.extend(dict(row) for row in await cursor.fetchall())

        matches.sort(key=lambda item: str(item.get("played_at") or ""), reverse=True)
        return matches

    @staticmethod
    def _result_for_player(match: dict[str, Any], player_id: str) -> str:
        if AnalyticsService._safe_int(match.get("is_bye")) == 1:
            return "BYE"
        if AnalyticsService._safe_int(match.get("is_double_loss")) == 1:
            return "DL"
        winner_id = str(match.get("winner_id") or "")
        if winner_id == player_id:
            return "W"
        if winner_id:
            return "L"
        return "N"

    @staticmethod
    def _streaks(results: Iterable[str]) -> tuple[int, int]:
        ordered = list(results)
        current = 0
        for result in ordered:
            if result == "BYE":
                continue
            if result == "W":
                current += 1
            else:
                break

        best = 0
        running = 0
        for result in reversed(ordered):
            if result == "BYE":
                continue
            if result == "W":
                running += 1
                best = max(best, running)
            else:
                running = 0
        return current, best

    async def get_player_profile(
        self,
        guild_id: str,
        player_id: str,
        fallback_name: str,
        tournament_id: int | None = None,
    ) -> tuple[PlayerSummary, list[dict[str, Any]], list[DeckSummary]]:
        async with self._connect() as db:
            identity = await self._player_identity(db, guild_id, player_id, fallback_name)
            matches = await self._fetch_player_matches(db, guild_id, player_id, tournament_id)

            results = [self._result_for_player(match, player_id) for match in matches]
            wins = sum(result == "W" for result in results)
            losses = sum(result == "L" for result in results)
            double_losses = sum(result == "DL" for result in results)
            byes = sum(result == "BYE" for result in results)
            match_count = wins + losses + double_losses
            win_rate = (wins / match_count * 100.0) if match_count else 0.0
            current_streak, best_streak = self._streaks(results)

            registration_filter = ""
            registration_parameters: list[Any] = [guild_id, player_id]
            if tournament_id is not None:
                registration_filter = "AND r.tournament_id = ?"
                registration_parameters.append(tournament_id)
            cursor = await db.execute(
                f"""
                SELECT r.tournament_id, r.deck, r.final_rank, r.registered_at,
                       t.winner_id, t.status
                FROM registrations r
                JOIN tournaments t ON t.id = r.tournament_id
                WHERE t.guild_id = ? AND r.discord_id = ?
                {registration_filter}
                ORDER BY COALESCE(r.registered_at, t.created_at) DESC, r.id DESC
                """,
                tuple(registration_parameters),
            )
            registrations = [dict(row) for row in await cursor.fetchall()]
            tournaments_played = len({int(row["tournament_id"]) for row in registrations})
            tournaments_won = sum(str(row.get("winner_id") or "") == player_id for row in registrations)
            finals = sum(self._safe_int(row.get("final_rank")) == 2 for row in registrations)
            top4 = sum(1 <= self._safe_int(row.get("final_rank")) <= 4 for row in registrations)
            current_deck = next(
                (self._normalized_deck(row.get("deck")) for row in registrations if self._normalized_deck(row.get("deck"))),
                None,
            )

            deck_counts: Counter[str] = Counter()
            deck_results: dict[str, Counter[str]] = defaultdict(Counter)
            deck_display: dict[str, str] = {}
            for match in matches:
                is_player1 = str(match.get("player1_id") or "") == player_id
                raw_deck = match.get("player1_deck") if is_player1 else match.get("player2_deck")
                deck = self._normalized_deck(raw_deck)
                if not deck:
                    continue
                key = deck.casefold()
                deck_display.setdefault(key, deck)
                result = self._result_for_player(match, player_id)
                if result != "BYE":
                    deck_counts[key] += 1
                    deck_results[key][result] += 1

            if not deck_counts:
                for row in registrations:
                    deck = self._normalized_deck(row.get("deck"))
                    if deck:
                        key = deck.casefold()
                        deck_display.setdefault(key, deck)
                        deck_counts[key] += 1

            most_used_key = deck_counts.most_common(1)[0][0] if deck_counts else None
            most_used_deck = deck_display.get(most_used_key) if most_used_key else None

            best_deck_key: str | None = None
            best_deck_rate: float | None = None
            best_deck_matches = -1
            for key, counts in deck_results.items():
                played = counts["W"] + counts["L"] + counts["DL"]
                if played < 1:
                    continue
                rate = counts["W"] / played * 100.0
                if best_deck_rate is None or (rate, played) > (best_deck_rate, best_deck_matches):
                    best_deck_key = key
                    best_deck_rate = rate
                    best_deck_matches = played

            deck_summaries: list[DeckSummary] = []
            for key, count in deck_counts.most_common():
                counts = deck_results[key]
                played = counts["W"] + counts["L"] + counts["DL"]
                deck_summaries.append(
                    DeckSummary(
                        deck=deck_display.get(key, key),
                        players=1,
                        matches=played,
                        wins=counts["W"],
                        losses=counts["L"],
                        double_losses=counts["DL"],
                        win_rate=(counts["W"] / played * 100.0) if played else 0.0,
                        top4=0,
                        tournament_wins=0,
                    )
                )

            summary = PlayerSummary(
                player_id=player_id,
                username=identity["username"],
                display_name=identity["display_name"],
                avatar_url=identity["avatar_url"],
                matches=match_count,
                wins=wins,
                losses=losses,
                double_losses=double_losses,
                byes=byes,
                win_rate=win_rate,
                tournaments_played=tournaments_played,
                tournaments_won=tournaments_won,
                finals=finals,
                top4=top4,
                current_streak=current_streak,
                best_streak=best_streak,
                current_deck=current_deck,
                most_used_deck=most_used_deck,
                best_deck=deck_display.get(best_deck_key) if best_deck_key else None,
                best_deck_win_rate=best_deck_rate,
            )
            return summary, matches, deck_summaries

    async def get_deck_statistics(
        self,
        guild_id: str,
        tournament_id: int | None = None,
    ) -> list[DeckSummary]:
        async with self._connect() as db:
            tournament_filter = ""
            params: list[Any] = [guild_id]
            if tournament_id is not None:
                tournament_filter = "AND r.tournament_id = ?"
                params.append(tournament_id)

            cursor = await db.execute(
                f"""
                SELECT r.tournament_id, r.discord_id, r.deck, r.final_rank,
                       t.winner_id
                FROM registrations r
                JOIN tournaments t ON t.id = r.tournament_id
                WHERE t.guild_id = ?
                  AND TRIM(COALESCE(r.deck, '')) <> ''
                  {tournament_filter}
                """,
                tuple(params),
            )
            registrations = [dict(row) for row in await cursor.fetchall()]

            deck_display: dict[str, str] = {}
            player_sets: dict[str, set[str]] = defaultdict(set)
            top4_counts: Counter[str] = Counter()
            tournament_win_counts: Counter[str] = Counter()
            deck_by_tournament_player: dict[tuple[int, str], str] = {}
            for row in registrations:
                deck = self._normalized_deck(row.get("deck"))
                if not deck:
                    continue
                key = deck.casefold()
                deck_display.setdefault(key, deck)
                tournament = self._safe_int(row.get("tournament_id"))
                player = str(row.get("discord_id") or "")
                deck_by_tournament_player[(tournament, player)] = key
                player_sets[key].add(player)
                rank = self._safe_int(row.get("final_rank"))
                if 1 <= rank <= 4:
                    top4_counts[key] += 1
                if str(row.get("winner_id") or "") == player:
                    tournament_win_counts[key] += 1

            match_counts: Counter[str] = Counter()
            win_counts: Counter[str] = Counter()
            loss_counts: Counter[str] = Counter()
            double_loss_counts: Counter[str] = Counter()

            match_tournament_filter = ""
            match_params: list[Any] = [guild_id]
            if tournament_id is not None:
                match_tournament_filter = "AND m.tournament_id = ?"
                match_params.append(tournament_id)
            cursor = await db.execute(
                f"""
                SELECT m.tournament_id, m.player1_id, m.player2_id,
                       m.winner_id, COALESCE(m.is_bye, 0) AS is_bye
                FROM matches m
                JOIN tournaments t ON t.id = m.tournament_id
                WHERE t.guild_id = ?
                  AND m.status IN ('approved', 'validated', 'completed')
                  {match_tournament_filter}
                """,
                tuple(match_params),
            )
            for row in await cursor.fetchall():
                if self._safe_int(row["is_bye"]) == 1:
                    continue
                tid = self._safe_int(row["tournament_id"])
                winner = str(row["winner_id"] or "")
                for player_value in (row["player1_id"], row["player2_id"]):
                    player = str(player_value or "")
                    key = deck_by_tournament_player.get((tid, player))
                    if not key:
                        continue
                    match_counts[key] += 1
                    if winner == player:
                        win_counts[key] += 1
                    elif winner:
                        loss_counts[key] += 1

            if await self._table_exists(db, "swiss_matches"):
                columns = await self._columns(db, "swiss_matches")
                if "is_double_loss" in columns:
                    double_loss_expr = "sm.is_double_loss"
                elif "result" in columns:
                    double_loss_expr = "CASE WHEN LOWER(COALESCE(sm.result, '')) IN ('double_loss', 'draw') THEN 1 ELSE 0 END"
                elif "is_draw" in columns:
                    double_loss_expr = "sm.is_draw"
                else:
                    double_loss_expr = "0"
                swiss_filter = ""
                swiss_params: list[Any] = [guild_id]
                if tournament_id is not None:
                    swiss_filter = "AND sm.tournament_id = ?"
                    swiss_params.append(tournament_id)
                cursor = await db.execute(
                    f"""
                    SELECT sm.tournament_id, sm.player1_id, sm.player2_id,
                           sm.winner_id, COALESCE(sm.is_bye, 0) AS is_bye,
                           {double_loss_expr} AS is_double_loss
                    FROM swiss_matches sm
                    JOIN tournaments t ON t.id = sm.tournament_id
                    WHERE t.guild_id = ?
                      AND sm.status IN ('completed', 'validated', 'approved')
                      {swiss_filter}
                    """,
                    tuple(swiss_params),
                )
                for row in await cursor.fetchall():
                    if self._safe_int(row["is_bye"]) == 1:
                        continue
                    tid = self._safe_int(row["tournament_id"])
                    winner = str(row["winner_id"] or "")
                    is_double_loss = self._safe_int(row["is_double_loss"]) == 1
                    for player_value in (row["player1_id"], row["player2_id"]):
                        player = str(player_value or "")
                        key = deck_by_tournament_player.get((tid, player))
                        if not key:
                            continue
                        match_counts[key] += 1
                        if is_double_loss:
                            double_loss_counts[key] += 1
                        elif winner == player:
                            win_counts[key] += 1
                        elif winner:
                            loss_counts[key] += 1

            summaries = []
            for key in deck_display:
                matches = match_counts[key]
                wins = win_counts[key]
                summaries.append(
                    DeckSummary(
                        deck=deck_display[key],
                        players=len(player_sets[key]),
                        matches=matches,
                        wins=wins,
                        losses=loss_counts[key],
                        double_losses=double_loss_counts[key],
                        win_rate=(wins / matches * 100.0) if matches else 0.0,
                        top4=top4_counts[key],
                        tournament_wins=tournament_win_counts[key],
                    )
                )
            summaries.sort(
                key=lambda item: (item.matches, item.win_rate, item.players),
                reverse=True,
            )
            return summaries

    async def _table_rows_for_tournament(
        self,
        db: aiosqlite.Connection,
        table: str,
        tournament_id: int,
    ) -> list[dict[str, Any]]:
        if not await self._table_exists(db, table):
            return []
        columns = await self._columns(db, table)
        if "tournament_id" not in columns:
            return []
        cursor = await db.execute(
            f"SELECT * FROM {table} WHERE tournament_id = ? ORDER BY 1 ASC",
            (tournament_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def build_tournament_export(
        self,
        guild_id: str,
        tournament_id: int,
        export_format: str,
    ) -> tuple[bytes, str]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM tournaments WHERE id = ? AND guild_id = ?",
                (tournament_id, guild_id),
            )
            tournament_row = await cursor.fetchone()
            if tournament_row is None:
                raise ValueError("Tournoi introuvable sur ce serveur.")
            tournament = dict(tournament_row)

            datasets: dict[str, list[dict[str, Any]]] = {
                "players": await self._table_rows_for_tournament(db, "registrations", tournament_id),
                "bracket_matches": await self._table_rows_for_tournament(db, "matches", tournament_id),
                "swiss_matches": await self._table_rows_for_tournament(db, "swiss_matches", tournament_id),
                "result_requests": await self._table_rows_for_tournament(db, "result_requests", tournament_id),
                "result_audit_logs": await self._table_rows_for_tournament(db, "result_audit_logs", tournament_id),
                "undo_snapshots": await self._table_rows_for_tournament(db, "tournament_action_snapshots", tournament_id),
                "progression_publications": await self._table_rows_for_tournament(db, "progression_match_publications", tournament_id),
                "progression_rounds": await self._table_rows_for_tournament(db, "progression_round_publications", tournament_id),
                "match_sessions": await self._table_rows_for_tournament(db, "match_center_sessions", tournament_id),
                "staff_requests": await self._table_rows_for_tournament(db, "staff_assistance_requests", tournament_id),
                "runtime_state": await self._table_rows_for_tournament(db, "tournament_runtime_state", tournament_id),
            }

            standings: dict[str, dict[str, Any]] = {}
            for registration in datasets["players"]:
                player_id = str(registration.get("discord_id") or "")
                standings[player_id] = {
                    "discord_id": player_id,
                    "username": registration.get("username"),
                    "deck": registration.get("deck"),
                    "final_rank": registration.get("final_rank"),
                    "matches": 0,
                    "wins": 0,
                    "losses": 0,
                    "double_losses": 0,
                    "byes": 0,
                    "swiss_points": 0,
                }

            for match in datasets["bracket_matches"]:
                if self._safe_int(match.get("is_bye")) == 1:
                    player_id = str(match.get("winner_id") or match.get("player1_id") or "")
                    if player_id in standings:
                        standings[player_id]["byes"] += 1
                    continue
                winner_id = str(match.get("winner_id") or "")
                for slot in ("player1_id", "player2_id"):
                    player_id = str(match.get(slot) or "")
                    if player_id not in standings:
                        continue
                    standings[player_id]["matches"] += 1
                    if player_id == winner_id:
                        standings[player_id]["wins"] += 1
                    elif winner_id:
                        standings[player_id]["losses"] += 1

            swiss_columns = set()
            if await self._table_exists(db, "swiss_matches"):
                swiss_columns = await self._columns(db, "swiss_matches")
            for match in datasets["swiss_matches"]:
                is_bye = self._safe_int(match.get("is_bye")) == 1
                is_double_loss = (
                    self._safe_int(match.get("is_double_loss")) == 1
                    if "is_double_loss" in swiss_columns
                    else str(match.get("result") or "").lower() in {"double_loss", "draw"}
                    if "result" in swiss_columns
                    else self._safe_int(match.get("is_draw")) == 1
                )
                winner_id = str(match.get("winner_id") or "")
                if is_bye:
                    player_id = str(match.get("player1_id") or winner_id)
                    if player_id in standings:
                        standings[player_id]["byes"] += 1
                        standings[player_id]["swiss_points"] += 3
                    continue
                for slot in ("player1_id", "player2_id"):
                    player_id = str(match.get(slot) or "")
                    if player_id not in standings:
                        continue
                    standings[player_id]["matches"] += 1
                    if is_double_loss:
                        standings[player_id]["double_losses"] += 1
                    elif player_id == winner_id:
                        standings[player_id]["wins"] += 1
                        standings[player_id]["swiss_points"] += 3
                    elif winner_id:
                        standings[player_id]["losses"] += 1

            standing_rows = list(standings.values())
            standing_rows.sort(
                key=lambda row: (
                    self._safe_int(row.get("swiss_points")),
                    self._safe_int(row.get("wins")),
                    -self._safe_int(row.get("losses")),
                    str(row.get("username") or "").casefold(),
                ),
                reverse=True,
            )
            for position, row in enumerate(standing_rows, start=1):
                row["calculated_position"] = position
            datasets["standings"] = standing_rows

            deck_stats = await self.get_deck_statistics(guild_id, tournament_id)
            datasets["deck_statistics"] = [
                {
                    "deck": item.deck,
                    "players": item.players,
                    "matches": item.matches,
                    "wins": item.wins,
                    "losses": item.losses,
                    "double_losses": item.double_losses,
                    "win_rate": round(item.win_rate, 2),
                    "top4": item.top4,
                    "tournament_wins": item.tournament_wins,
                }
                for item in deck_stats
            ]

        safe_code = "".join(char if char.isalnum() or char in "-_" else "_" for char in str(tournament["code"]))
        export_format = export_format.lower().strip()
        if export_format == "json":
            payload = {
                "tournament": tournament,
                **datasets,
            }
            data = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
            return data, f"hamtaro_{safe_code}.json"

        if export_format != "csv":
            raise ValueError("Format d’export inconnu. Utilise CSV ou JSON.")

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            all_datasets = {"tournament": [tournament], **datasets}
            for name, rows in all_datasets.items():
                text = io.StringIO(newline="")
                if rows:
                    fieldnames: list[str] = []
                    seen: set[str] = set()
                    for row in rows:
                        for key in row:
                            if key not in seen:
                                seen.add(key)
                                fieldnames.append(key)
                    writer = csv.DictWriter(text, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    for row in rows:
                        writer.writerow({key: row.get(key) for key in fieldnames})
                else:
                    text.write("aucune_donnee\n")
                archive.writestr(f"{name}.csv", text.getvalue().encode("utf-8-sig"))
        return output.getvalue(), f"hamtaro_{safe_code}_csv.zip"
