from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from services.competitive_service import CompetitiveService
from services.expansion_database import (
    columns_for,
    expansion_connection,
    table_exists,
    utcnow_iso,
)


CASUAL_TABLE_CANDIDATES = (
    "casual_matches",
    "casual_duels",
    "casual_match_sessions",
)

PLAYER_COLUMN_PAIRS = (
    ("player1_id", "player2_id"),
    ("challenger_id", "opponent_id"),
    ("requester_id", "opponent_id"),
    ("creator_id", "accepted_by"),
)

THREAD_COLUMNS = ("thread_id", "match_thread_id", "channel_id")
FORMAT_COLUMNS = ("format", "format_name", "game_format")
RANKED_COLUMNS = ("ranked", "is_ranked", "competitive")


@dataclass(slots=True)
class CasualMatchAdapter:
    table: str
    columns: set[str]
    player1_column: str
    player2_column: str
    thread_column: str | None
    format_column: str | None
    ranked_column: str | None


class CasualResultService:
    def __init__(self) -> None:
        self.competitive = CompetitiveService()

    async def adapter(
        self,
        db: Any,
        required_table: str | None = None,
    ) -> CasualMatchAdapter:
        tables = (required_table,) if required_table else CASUAL_TABLE_CANDIDATES
        for table in tables:
            if table not in CASUAL_TABLE_CANDIDATES:
                continue
            if not await table_exists(db, table):
                continue
            columns = await columns_for(db, table)
            pair = next(
                (
                    (first, second)
                    for first, second in PLAYER_COLUMN_PAIRS
                    if first in columns and second in columns
                ),
                None,
            )
            if pair is None or "id" not in columns:
                continue
            thread_column = next((name for name in THREAD_COLUMNS if name in columns), None)
            format_column = next((name for name in FORMAT_COLUMNS if name in columns), None)
            ranked_column = next((name for name in RANKED_COLUMNS if name in columns), None)
            return CasualMatchAdapter(
                table=table,
                columns=columns,
                player1_column=pair[0],
                player2_column=pair[1],
                thread_column=thread_column,
                format_column=format_column,
                ranked_column=ranked_column,
            )
        raise ValueError(
            "La table du système casual n'a pas été reconnue. "
            "Noms compatibles : casual_matches, casual_duels ou casual_match_sessions."
        )

    async def find_match(
        self,
        *,
        guild_id: str,
        user_id: str,
        match_id: int | None,
        channel_id: str | None,
    ) -> tuple[CasualMatchAdapter, dict[str, Any]]:
        async with expansion_connection() as db:
            adapter = await self.adapter(db)
            filters = [
                f"(? IN ({adapter.player1_column}, {adapter.player2_column}))"
            ]
            parameters: list[Any] = [user_id]
            if "guild_id" in adapter.columns:
                filters.append("guild_id=?")
                parameters.append(guild_id)
            if match_id is not None:
                filters.append("id=?")
                parameters.append(match_id)
            elif channel_id and adapter.thread_column:
                filters.append(f"{adapter.thread_column}=?")
                parameters.append(channel_id)
            else:
                raise ValueError(
                    "Indique l'identifiant du match casual ou utilise la commande dans son fil."
                )
            row = await (
                await db.execute(
                    f"SELECT * FROM {adapter.table} WHERE {' AND '.join(filters)} "
                    "ORDER BY id DESC LIMIT 1",
                    tuple(parameters),
                )
            ).fetchone()
            if row is None:
                raise ValueError("Match casual introuvable ou tu n'en fais pas partie.")
            return adapter, dict(row)

    @staticmethod
    def _participants(adapter: CasualMatchAdapter, match: dict[str, Any]) -> tuple[str, str]:
        return (
            str(match.get(adapter.player1_column) or ""),
            str(match.get(adapter.player2_column) or ""),
        )

    async def report(
        self,
        *,
        guild_id: str,
        reporter_id: str,
        winner_id: str,
        score: str,
        match_id: int | None,
        channel_id: str | None,
    ) -> dict[str, Any]:
        cleaned_score = score.strip().replace(" ", "")
        match_score = re.fullmatch(r"(\d{1,2})-(\d{1,2})", cleaned_score)
        if match_score is None or match_score.group(1) == match_score.group(2):
            raise ValueError("Le score doit ressembler à `2-1` et ne peut pas être nul.")

        adapter, match = await self.find_match(
            guild_id=guild_id,
            user_id=reporter_id,
            match_id=match_id,
            channel_id=channel_id,
        )
        player1_id, player2_id = self._participants(adapter, match)
        if winner_id not in {player1_id, player2_id}:
            raise ValueError("Le gagnant doit être l'un des deux joueurs du match.")
        loser_id = player2_id if winner_id == player1_id else player1_id

        async with expansion_connection() as db:
            existing = await (
                await db.execute(
                    """
                    SELECT id FROM casual_result_requests_plus
                    WHERE casual_table=? AND casual_match_id=? AND status='pending'
                    """,
                    (adapter.table, int(match["id"])),
                )
            ).fetchone()
            if existing:
                raise ValueError(
                    f"Une demande est déjà en attente (`#{existing['id']}`)."
                )
            cursor = await db.execute(
                """
                INSERT INTO casual_result_requests_plus(
                    guild_id, casual_table, casual_match_id, reporter_id,
                    winner_id, loser_id, score, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    guild_id,
                    adapter.table,
                    int(match["id"]),
                    reporter_id,
                    winner_id,
                    loser_id,
                    cleaned_score,
                    utcnow_iso(),
                ),
            )
            await db.commit()
            request_id = int(cursor.lastrowid)
        return {
            "request_id": request_id,
            "match": match,
            "adapter": adapter,
            "winner_id": winner_id,
            "loser_id": loser_id,
            "score": cleaned_score,
        }

    async def pending_request(
        self,
        *,
        guild_id: str,
        request_id: int,
    ) -> dict[str, Any]:
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    """
                    SELECT * FROM casual_result_requests_plus
                    WHERE id=? AND guild_id=?
                    """,
                    (request_id, guild_id),
                )
            ).fetchone()
            if row is None:
                raise ValueError("Demande de résultat introuvable.")
            return dict(row)

    async def confirm(
        self,
        *,
        guild_id: str,
        request_id: int,
        confirmer_id: str,
    ) -> dict[str, Any]:
        async with expansion_connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            request = await (
                await db.execute(
                    """
                    SELECT * FROM casual_result_requests_plus
                    WHERE id=? AND guild_id=?
                    """,
                    (request_id, guild_id),
                )
            ).fetchone()
            if request is None:
                await db.rollback()
                raise ValueError("Demande de résultat introuvable.")
            if str(request["status"]) != "pending":
                await db.rollback()
                raise ValueError("Cette demande a déjà été traitée.")
            if confirmer_id == str(request["reporter_id"]):
                await db.rollback()
                raise ValueError("L'autre joueur doit confirmer le résultat.")
            if confirmer_id not in {str(request["winner_id"]), str(request["loser_id"])}:
                await db.rollback()
                raise ValueError("Tu ne fais pas partie de ce match.")

            table = str(request["casual_table"])
            adapter = await self.adapter(db, table)
            match = await (
                await db.execute(
                    f"SELECT * FROM {adapter.table} WHERE id=?",
                    (int(request["casual_match_id"]),),
                )
            ).fetchone()
            if match is None:
                await db.rollback()
                raise ValueError("Le match casual lié n'existe plus.")

            updates: list[str] = []
            parameters: list[Any] = []
            if "status" in adapter.columns:
                schema_row = await (
                    await db.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                        (adapter.table,),
                    )
                ).fetchone()
                schema_sql = str(schema_row["sql"] or "").casefold() if schema_row else ""
                completion_status = (
                    "completed"
                    if "check" not in schema_sql
                    else next(
                        (value for value in ("completed", "finished", "closed", "validated") if value in schema_sql),
                        None,
                    )
                )
                if completion_status is not None:
                    updates.append("status=?")
                    parameters.append(completion_status)
            if "winner_id" in adapter.columns:
                updates.append("winner_id=?")
                parameters.append(str(request["winner_id"]))
            if "score" in adapter.columns:
                updates.append("score=?")
                parameters.append(str(request["score"]))
            if "finished_at" in adapter.columns:
                updates.append("finished_at=?")
                parameters.append(utcnow_iso())
            if updates:
                parameters.append(int(request["casual_match_id"]))
                await db.execute(
                    f"UPDATE {adapter.table} SET {', '.join(updates)} WHERE id=?",
                    tuple(parameters),
                )

            now = utcnow_iso()
            await db.execute(
                """
                UPDATE casual_result_requests_plus
                SET status='confirmed', confirmed_by=?, resolved_at=?
                WHERE id=?
                """,
                (confirmer_id, now, request_id),
            )
            await db.commit()
            match_data = dict(match)

        player1_id, player2_id = self._participants(adapter, match_data)
        should_rate = False
        if adapter.ranked_column:
            raw = match_data.get(adapter.ranked_column)
            should_rate = str(raw).strip().casefold() in {"1", "true", "yes", "oui"}
        if should_rate:
            format_name = (
                str(match_data.get(adapter.format_column) or "Casual")
                if adapter.format_column
                else "Casual"
            )
            await self.competitive.process_result(
                guild_id=guild_id,
                source_key=f"casual:{adapter.table}:{request['casual_match_id']}",
                tournament_id=None,
                format_name=format_name,
                player1_id=player1_id,
                player2_id=player2_id,
                winner_id=str(request["winner_id"]),
                score=str(request["score"]),
            )

        return {
            "request": dict(request),
            "match": match_data,
            "adapter": adapter,
            "player1_id": player1_id,
            "player2_id": player2_id,
            "rated": should_rate,
        }

    async def contest(
        self,
        *,
        guild_id: str,
        request_id: int,
        contester_id: str,
        reason: str,
    ) -> dict[str, Any]:
        async with expansion_connection() as db:
            request = await (
                await db.execute(
                    """
                    SELECT * FROM casual_result_requests_plus
                    WHERE id=? AND guild_id=?
                    """,
                    (request_id, guild_id),
                )
            ).fetchone()
            if request is None or str(request["status"]) != "pending":
                raise ValueError("Demande introuvable ou déjà traitée.")
            if contester_id == str(request["reporter_id"]):
                raise ValueError("Le déclarant peut annuler, mais pas contester sa propre demande.")
            if contester_id not in {str(request["winner_id"]), str(request["loser_id"])}:
                raise ValueError("Tu ne fais pas partie de ce match.")
            await db.execute(
                """
                UPDATE casual_result_requests_plus
                SET status='contested', contested_by=?, contest_reason=?, resolved_at=?
                WHERE id=?
                """,
                (contester_id, reason.strip()[:1000], utcnow_iso(), request_id),
            )
            await db.commit()
            return dict(request)

    async def cancel(
        self,
        *,
        guild_id: str,
        request_id: int,
        reporter_id: str,
    ) -> None:
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                UPDATE casual_result_requests_plus
                SET status='cancelled', resolved_at=?
                WHERE id=? AND guild_id=? AND reporter_id=? AND status='pending'
                """,
                (utcnow_iso(), request_id, guild_id, reporter_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Demande introuvable, déjà traitée ou créée par un autre joueur.")
            await db.commit()
