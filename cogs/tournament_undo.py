from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import error_embed, info_embed, success_embed
from utils.permissions import is_staff_member
from utils.tournament_resolver import resolve_tournament


MATCH_KIND_BRACKET = "bracket"
MATCH_KIND_SWISS = "swiss"
REVERSIBLE_ACTIONS = {
    "result_approval",
    "automatic_result_approval",
    "admin_win_immediate",
}
FINAL_MATCH_STATUSES = {
    "completed",
    "validated",
    "approved",
    "finished",
}
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _row_to_dict(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    try:
        return obj[name]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, name, default)


def _status(value: Any) -> str:
    return str(getattr(value, "value", value) or "").lower().strip()


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _load(data: str | None, default: Any) -> Any:
    if not data:
        return default
    try:
        return json.loads(data)
    except (TypeError, json.JSONDecodeError):
        return default


def _safe_identifier(name: str) -> str:
    if not IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Identifiant SQL non autorisé : {name}")
    return name


class UndoConfirmView(discord.ui.View):
    def __init__(
        self,
        cog: "TournamentUndoCog",
        snapshot_id: int,
        reason: str,
    ) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.snapshot_id = snapshot_id
        self.reason = reason
        self.done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await self.cog._ensure_staff(interaction):
            return False
        return True

    def _disable(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    @discord.ui.button(
        label="Confirmer l’annulation",
        emoji="↩️",
        style=discord.ButtonStyle.danger,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.done:
            await interaction.response.send_message(
                "⚠️ Cette action a déjà été traitée.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.cog.undo_snapshot(
                snapshot_id=self.snapshot_id,
                actor=interaction.user,
                reason=self.reason,
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Annulation impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return
        except Exception as error:
            print(f"❌ Annulation Hamtaro #{self.snapshot_id} : {error}")
            await interaction.followup.send(
                embed=error_embed(
                    title="Erreur pendant l’annulation",
                    description=(
                        "Hamtaro n’a pas pu restaurer l’action. "
                        "Aucune nouvelle tentative automatique n’a été lancée."
                    ),
                ),
                ephemeral=True,
            )
            return

        self.done = True
        self._disable()
        try:
            await interaction.message.edit(view=self)
        except (discord.Forbidden, discord.HTTPException):
            pass

        await interaction.followup.send(
            embed=success_embed(
                title="Action annulée",
                description=result,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Conserver l’action",
        emoji="❌",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.done = True
        self._disable()
        await interaction.response.edit_message(
            embed=info_embed(
                title="Annulation abandonnée",
                description="Aucune donnée du tournoi n’a été modifiée.",
            ),
            view=self,
        )


class TournamentUndoCog(commands.Cog):
    """Annulation sûre de la dernière validation d’un tournoi Hamtaro."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db
        self._locks: dict[int, asyncio.Lock] = {}

    async def cog_load(self) -> None:
        await self._init_tables()

    async def _init_tables(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS tournament_action_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                match_kind TEXT NOT NULL,
                match_id INTEGER NOT NULL,
                actor_id TEXT,
                metadata_json TEXT,
                snapshot_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'captured',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                applied_at TEXT,
                undone_at TEXT,
                undone_by TEXT,
                undo_reason TEXT
            )
            """
        )
        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tournament_undo_latest
            ON tournament_action_snapshots(
                guild_id, tournament_id, status, id DESC
            )
            """
        )
        await self.db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tournament_undo_single_applied
            ON tournament_action_snapshots(match_kind, match_id, id)
            """
        )
        await self.db.commit()

    # ==========================================================
    # PERMISSIONS
    # ==========================================================

    async def _ensure_staff(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "❌ Cette action doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return False

        permissions = interaction.user.guild_permissions
        allowed = (
            permissions.administrator
            or permissions.manage_guild
            or is_staff_member(interaction.user)
        )
        if not allowed:
            await interaction.response.send_message(
                "❌ Seul le staff peut annuler une action de tournoi.",
                ephemeral=True,
            )
            return False
        return True

    def _lock(self, tournament_id: int) -> asyncio.Lock:
        if tournament_id not in self._locks:
            self._locks[tournament_id] = asyncio.Lock()
        return self._locks[tournament_id]

    # ==========================================================
    # OUTILS SQL GÉNÉRIQUES
    # ==========================================================

    async def _table_exists(self, table: str) -> bool:
        row = await self.db.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        )
        return row is not None

    async def _columns(self, table: str) -> list[str]:
        table = _safe_identifier(table)
        rows = await self.db.fetchall(f"PRAGMA table_info({table})")
        return [str(row[1]) for row in rows]

    async def _restore_row(
        self,
        table: str,
        row: dict[str, Any] | None,
        key_columns: tuple[str, ...],
    ) -> None:
        if row is None:
            return
        table = _safe_identifier(table)
        columns = await self._columns(table)
        usable = [column for column in columns if column in row]
        if not usable:
            return

        where = " AND ".join(f"{_safe_identifier(column)} = ?" for column in key_columns)
        key_values = tuple(row.get(column) for column in key_columns)
        existing = await self.db.fetchone(
            f"SELECT 1 FROM {table} WHERE {where} LIMIT 1",
            key_values,
        )

        if existing is None:
            placeholders = ", ".join("?" for _ in usable)
            await self.db.execute(
                f"INSERT INTO {table} ({', '.join(usable)}) VALUES ({placeholders})",
                tuple(row.get(column) for column in usable),
            )
            return

        update_columns = [column for column in usable if column not in key_columns]
        if not update_columns:
            return
        assignments = ", ".join(f"{_safe_identifier(column)} = ?" for column in update_columns)
        await self.db.execute(
            f"UPDATE {table} SET {assignments} WHERE {where}",
            tuple(row.get(column) for column in update_columns) + key_values,
        )

    async def _snapshot_auxiliary_history(
        self,
        tournament_id: int,
        match_id: int,
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        tables = await self.db.fetchall(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND LOWER(name) LIKE '%history%'
            """
        )
        for table_row in tables:
            table = str(table_row[0])
            if table in {"result_audit_logs", "tournament_action_snapshots"}:
                continue
            if not IDENTIFIER_RE.fullmatch(table):
                continue
            columns = await self._columns(table)
            if "match_id" not in columns:
                continue

            conditions = ["match_id = ?"]
            parameters: list[Any] = [match_id]
            if "tournament_id" in columns:
                conditions.append("tournament_id = ?")
                parameters.append(tournament_id)

            rows = await self.db.fetchall(
                f"SELECT * FROM {table} WHERE {' AND '.join(conditions)}",
                tuple(parameters),
            )
            result[table] = [dict(row) for row in rows]
        return result

    async def _restore_auxiliary_history(
        self,
        history: dict[str, list[dict[str, Any]]],
        tournament_id: int,
        match_id: int,
    ) -> None:
        for table, rows in history.items():
            if not await self._table_exists(table):
                continue
            columns = await self._columns(table)
            if "match_id" not in columns:
                continue
            conditions = ["match_id = ?"]
            parameters: list[Any] = [match_id]
            if "tournament_id" in columns:
                conditions.append("tournament_id = ?")
                parameters.append(tournament_id)
            await self.db.execute(
                f"DELETE FROM {_safe_identifier(table)} WHERE {' AND '.join(conditions)}",
                tuple(parameters),
            )
            for row in rows:
                usable = [column for column in columns if column in row]
                if not usable:
                    continue
                await self.db.execute(
                    f"INSERT INTO {_safe_identifier(table)} "
                    f"({', '.join(usable)}) VALUES ({', '.join('?' for _ in usable)})",
                    tuple(row.get(column) for column in usable),
                )

    # ==========================================================
    # CAPTURE AVANT VALIDATION
    # ==========================================================

    async def capture_result_action(
        self,
        *,
        request: dict[str, Any],
        actor_id: str,
        action_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        match_kind = str(request["match_kind"])
        match_id = int(request["match_id"])
        tournament_id = int(request["tournament_id"])
        guild_id = str(request["guild_id"])

        match_table = "matches" if match_kind == MATCH_KIND_BRACKET else "swiss_matches"
        match = _row_to_dict(
            await self.db.fetchone(
                f"SELECT * FROM {match_table} WHERE id = ?",
                (match_id,),
            )
        )
        if match is None:
            raise ValueError("Le match à sauvegarder est introuvable.")

        tournament = _row_to_dict(
            await self.db.fetchone("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
        )
        request_row = _row_to_dict(
            await self.db.fetchone(
                "SELECT * FROM result_requests WHERE match_kind = ? AND match_id = ?",
                (match_kind, match_id),
            )
        )
        session = None
        if await self._table_exists("match_center_sessions"):
            session = _row_to_dict(
                await self.db.fetchone(
                    """
                    SELECT * FROM match_center_sessions
                    WHERE match_kind = ? AND match_id = ?
                    """,
                    (match_kind, match_id),
                )
            )

        publication = None
        if await self._table_exists("progression_match_publications"):
            publication = _row_to_dict(
                await self.db.fetchone(
                    """
                    SELECT * FROM progression_match_publications
                    WHERE match_kind = ? AND match_id = ?
                    """,
                    (match_kind, match_id),
                )
            )

        player_ids = {
            str(match.get("player1_id") or ""),
            str(match.get("player2_id") or ""),
        }
        player_ids.discard("")
        players: list[dict[str, Any]] = []
        for player_id in player_ids:
            row = await self.db.fetchone(
                "SELECT * FROM players WHERE discord_id = ? AND guild_id = ?",
                (player_id, guild_id),
            )
            if row is not None:
                players.append(dict(row))

        payload: dict[str, Any] = {
            "match": match,
            "tournament": tournament,
            "request": request_row,
            "session": session,
            "publication": publication,
            "players": players,
            "history": await self._snapshot_auxiliary_history(tournament_id, match_id),
        }

        if match_kind == MATCH_KIND_BRACKET:
            next_match_id = match.get("next_match_id")
            payload["next_match"] = (
                _row_to_dict(
                    await self.db.fetchone(
                        "SELECT * FROM matches WHERE id = ?",
                        (int(next_match_id),),
                    )
                )
                if next_match_id is not None
                else None
            )
        else:
            payload["swiss_settings"] = _row_to_dict(
                await self.db.fetchone(
                    "SELECT * FROM swiss_settings WHERE tournament_id = ?",
                    (tournament_id,),
                )
            )
            if await self._table_exists("progression_swiss_actions"):
                round_number = int(match.get("round_number") or 0)
                payload["swiss_action"] = _row_to_dict(
                    await self.db.fetchone(
                        """
                        SELECT * FROM progression_swiss_actions
                        WHERE tournament_id = ? AND completed_round = ?
                        """,
                        (tournament_id, round_number),
                    )
                )

        cursor = await self.db.execute(
            """
            INSERT INTO tournament_action_snapshots (
                guild_id, tournament_id, action_type,
                match_kind, match_id, actor_id,
                metadata_json, snapshot_json, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'captured')
            """,
            (
                guild_id,
                tournament_id,
                action_type,
                match_kind,
                match_id,
                actor_id,
                _dump(metadata or {}),
                _dump(payload),
            ),
        )
        await self.db.commit()
        return int(cursor.lastrowid)

    async def mark_snapshot_applied(self, snapshot_id: int) -> None:
        await self.db.execute(
            """
            UPDATE tournament_action_snapshots
            SET status = 'applied', applied_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'captured'
            """,
            (snapshot_id,),
        )
        await self.db.commit()

    async def abort_snapshot(self, snapshot_id: int, reason: str) -> None:
        await self.db.execute(
            """
            UPDATE tournament_action_snapshots
            SET status = 'aborted', undo_reason = ?
            WHERE id = ? AND status = 'captured'
            """,
            (reason[:1000], snapshot_id),
        )
        await self.db.commit()

    # ==========================================================
    # SÉLECTION ET DÉPENDANCES
    # ==========================================================

    async def _get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        return _row_to_dict(
            await self.db.fetchone(
                "SELECT * FROM tournament_action_snapshots WHERE id = ?",
                (snapshot_id,),
            )
        )

    async def _latest_snapshot(
        self,
        *,
        guild_id: str,
        tournament_id: int,
        match_kind: str | None = None,
        match_id: int | None = None,
    ) -> dict[str, Any] | None:
        conditions = ["guild_id = ?", "tournament_id = ?", "status = 'applied'"]
        parameters: list[Any] = [guild_id, tournament_id]
        if match_kind is not None:
            conditions.append("match_kind = ?")
            parameters.append(match_kind)
        if match_id is not None:
            conditions.append("match_id = ?")
            parameters.append(match_id)
        row = await self.db.fetchone(
            f"""
            SELECT * FROM tournament_action_snapshots
            WHERE {' AND '.join(conditions)}
            ORDER BY id DESC
            LIMIT 1
            """,
            tuple(parameters),
        )
        return _row_to_dict(row)

    async def _ensure_is_latest_tournament_action(self, snapshot: dict[str, Any]) -> None:
        newer = await self.db.fetchone(
            """
            SELECT id, match_kind, match_id
            FROM tournament_action_snapshots
            WHERE tournament_id = ?
              AND guild_id = ?
              AND status = 'applied'
              AND id > ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                int(snapshot["tournament_id"]),
                str(snapshot["guild_id"]),
                int(snapshot["id"]),
            ),
        )
        if newer is not None:
            raise ValueError(
                "Cette action n’est plus la dernière action validée du tournoi. "
                f"Annule d’abord `{newer['match_kind']}:{newer['match_id']}`."
            )

    async def _check_bracket_dependencies(
        self,
        snapshot: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        match_before = payload["match"]
        match_id = int(snapshot["match_id"])
        current = _row_to_dict(
            await self.db.fetchone("SELECT * FROM matches WHERE id = ?", (match_id,))
        )
        if current is None or _status(current.get("status")) not in FINAL_MATCH_STATUSES:
            raise ValueError("Le match n’est plus dans un état validé pouvant être annulé.")

        next_before = payload.get("next_match")
        if next_before is None:
            return
        next_id = int(next_before["id"])
        next_current = _row_to_dict(
            await self.db.fetchone("SELECT * FROM matches WHERE id = ?", (next_id,))
        )
        if next_current is None:
            raise ValueError("Le match suivant du bracket a disparu.")

        if _status(next_current.get("status")) not in {"waiting"}:
            raise ValueError(
                "Le match suivant a déjà commencé ou reçu un résultat. "
                "L’annulation automatique est bloquée."
            )
        if any(
            next_current.get(field)
            for field in (
                "winner_id", "winner_name", "score", "reported_by",
                "validated_by", "reported_at", "validated_at",
            )
        ):
            raise ValueError("Le match suivant contient déjà un résultat ou une validation.")
        if int(next_current.get("player1_score") or 0) != 0 or int(
            next_current.get("player2_score") or 0
        ) != 0:
            raise ValueError("Le match suivant possède déjà un score.")

        next_request = None
        if await self._table_exists("result_requests"):
            next_request = await self.db.fetchone(
                """
                SELECT status FROM result_requests
                WHERE match_kind = 'bracket' AND match_id = ?
                """,
                (next_id,),
            )
        if next_request is not None and str(next_request["status"]) not in {"rejected"}:
            raise ValueError("Le match suivant possède déjà une demande de résultat.")

        if await self._table_exists("match_center_sessions"):
            next_session = await self.db.fetchone(
                """
                SELECT status FROM match_center_sessions
                WHERE match_kind = 'bracket' AND match_id = ?
                """,
                (next_id,),
            )
            if next_session is not None and str(next_session["status"]) not in {"waiting"}:
                raise ValueError("L’espace Discord du match suivant a déjà été utilisé.")

        propagated_slot = int(match_before.get("next_slot") or 0)
        winner_id = str(current.get("winner_id") or "")
        if propagated_slot == 1:
            if str(next_current.get("player1_id") or "") != winner_id:
                raise ValueError("Le slot propagé du bracket ne correspond plus au vainqueur.")
            if str(next_current.get("player2_id") or "") != str(next_before.get("player2_id") or ""):
                raise ValueError("L’autre participant du match suivant a changé.")
        elif propagated_slot == 2:
            if str(next_current.get("player2_id") or "") != winner_id:
                raise ValueError("Le slot propagé du bracket ne correspond plus au vainqueur.")
            if str(next_current.get("player1_id") or "") != str(next_before.get("player1_id") or ""):
                raise ValueError("L’autre participant du match suivant a changé.")

    async def _check_swiss_dependencies(
        self,
        snapshot: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        match_before = payload["match"]
        tournament_id = int(snapshot["tournament_id"])
        round_number = int(match_before.get("round_number") or 0)
        current = await self.db.fetchone(
            "SELECT status FROM swiss_matches WHERE id = ?",
            (int(snapshot["match_id"]),),
        )
        if current is None or _status(current["status"]) not in FINAL_MATCH_STATUSES:
            raise ValueError("Le match suisse n’est plus dans un état validé.")

        later = await self.db.fetchone(
            """
            SELECT round_number
            FROM swiss_matches
            WHERE tournament_id = ? AND round_number > ?
            ORDER BY round_number ASC
            LIMIT 1
            """,
            (tournament_id, round_number),
        )
        if later is not None:
            raise ValueError(
                f"La ronde suisse {later['round_number']} a déjà été générée. "
                "Il faut d’abord l’annuler ou utiliser une réparation administrative."
            )

    async def check_dependencies(self, snapshot: dict[str, Any]) -> None:
        await self._ensure_is_latest_tournament_action(snapshot)
        payload = _load(snapshot.get("snapshot_json"), {})
        if snapshot["match_kind"] == MATCH_KIND_BRACKET:
            await self._check_bracket_dependencies(snapshot, payload)
        elif snapshot["match_kind"] == MATCH_KIND_SWISS:
            await self._check_swiss_dependencies(snapshot, payload)
        else:
            raise ValueError("Type de match non pris en charge par l’annulation.")

    # ==========================================================
    # RESTAURATION
    # ==========================================================

    async def _restore_players(self, players: list[dict[str, Any]]) -> None:
        for row in players:
            await self._restore_row(
                "players",
                row,
                ("discord_id", "guild_id"),
            )

    async def _restore_common(
        self,
        snapshot: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        await self._restore_row("tournaments", payload.get("tournament"), ("id",))
        await self._restore_players(payload.get("players") or [])

        if await self._table_exists("result_requests"):
            await self._restore_row(
                "result_requests",
                payload.get("request"),
                ("match_kind", "match_id"),
            )
        if await self._table_exists("match_center_sessions"):
            await self._restore_row(
                "match_center_sessions",
                payload.get("session"),
                ("match_kind", "match_id"),
            )
        if await self._table_exists("progression_match_publications"):
            await self._restore_row(
                "progression_match_publications",
                payload.get("publication"),
                ("match_kind", "match_id"),
            )

        await self._restore_auxiliary_history(
            payload.get("history") or {},
            int(snapshot["tournament_id"]),
            int(snapshot["match_id"]),
        )

    async def _revoke_downstream_publication(
        self,
        next_match: dict[str, Any] | None,
    ) -> None:
        if not next_match or not await self._table_exists("progression_match_publications"):
            return
        next_id = int(next_match["id"])
        publication = _row_to_dict(
            await self.db.fetchone(
                """
                SELECT * FROM progression_match_publications
                WHERE match_kind = 'bracket' AND match_id = ?
                """,
                (next_id,),
            )
        )
        if publication is None:
            return

        thread_id = publication.get("thread_id")
        if thread_id:
            channel = self.bot.get_channel(int(thread_id))
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(int(thread_id))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    channel = None
            if isinstance(channel, discord.Thread):
                try:
                    await channel.send(
                        "↩️ Ce match est temporairement annulé après la correction du match précédent."
                    )
                    await channel.edit(archived=True, locked=True, reason="Annulation Hamtaro")
                except (discord.Forbidden, discord.HTTPException):
                    pass

        channel_id = publication.get("channel_id")
        message_id = publication.get("message_id")
        if channel_id and message_id:
            channel = self.bot.get_channel(int(channel_id))
            if channel is not None and hasattr(channel, "fetch_message"):
                try:
                    message = await channel.fetch_message(int(message_id))
                    embed = (
                        discord.Embed.from_dict(message.embeds[0].to_dict())
                        if message.embeds
                        else discord.Embed()
                    )
                    embed.title = "↩️ Match annulé temporairement"
                    embed.colour = discord.Colour.orange()
                    embed.description = (
                        "Le match précédent a été annulé par le staff. "
                        "Cet affrontement sera republié lorsque les participants seront de nouveau connus."
                    )
                    await message.edit(embed=embed, view=None)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        await self.db.execute(
            """
            DELETE FROM progression_match_publications
            WHERE match_kind = 'bracket' AND match_id = ?
            """,
            (next_id,),
        )
        if await self._table_exists("match_center_sessions"):
            await self.db.execute(
                """
                DELETE FROM match_center_sessions
                WHERE match_kind = 'bracket' AND match_id = ?
                """,
                (next_id,),
            )

        # Le résumé de la phase peut également être devenu faux.
        if await self._table_exists("progression_round_publications"):
            round_number = int(next_match.get("round") or 0)
            summary = _row_to_dict(
                await self.db.fetchone(
                    """
                    SELECT * FROM progression_round_publications
                    WHERE tournament_id = ?
                      AND match_kind = 'bracket'
                      AND round_number = ?
                    """,
                    (int(next_match["tournament_id"]), round_number),
                )
            )
            if summary is not None:
                summary_channel = self.bot.get_channel(int(summary["channel_id"])) if summary.get("channel_id") else None
                if summary_channel is not None and hasattr(summary_channel, "fetch_message") and summary.get("message_id"):
                    try:
                        summary_message = await summary_channel.fetch_message(int(summary["message_id"]))
                        summary_embed = (
                            discord.Embed.from_dict(summary_message.embeds[0].to_dict())
                            if summary_message.embeds
                            else discord.Embed()
                        )
                        summary_embed.title = "↩️ Phase en cours de correction"
                        summary_embed.description = (
                            "Un résultat précédent a été annulé. "
                            "La liste correcte des matchs sera republiée automatiquement."
                        )
                        summary_embed.colour = discord.Colour.orange()
                        await summary_message.edit(embed=summary_embed, view=None)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass
                await self.db.execute(
                    """
                    DELETE FROM progression_round_publications
                    WHERE tournament_id = ?
                      AND match_kind = 'bracket'
                      AND round_number = ?
                    """,
                    (int(next_match["tournament_id"]), round_number),
                )

        await self.db.commit()

    async def _close_swiss_generation_prompt(
        self,
        action: dict[str, Any] | None,
    ) -> None:
        if not action:
            return
        channel_id = action.get("channel_id")
        message_id = action.get("message_id")
        if not channel_id or not message_id:
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel is None or not hasattr(channel, "fetch_message"):
            return
        try:
            message = await channel.fetch_message(int(message_id))
            embed = (
                discord.Embed.from_dict(message.embeds[0].to_dict())
                if message.embeds
                else discord.Embed()
            )
            embed.title = "↩️ Ronde de nouveau incomplète"
            embed.description = (
                "Un résultat de cette ronde a été annulé. "
                "Le bouton de génération de la ronde suivante n’est plus valable."
            )
            embed.colour = discord.Colour.orange()
            await message.edit(embed=embed, view=None)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def _reopen_current_match_discord(
        self,
        snapshot: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        session = payload.get("session")
        if not session:
            return
        thread_id = session.get("thread_id")
        if thread_id:
            channel = self.bot.get_channel(int(thread_id))
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(int(thread_id))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    channel = None
            if isinstance(channel, discord.Thread):
                try:
                    await channel.edit(archived=False, locked=False, reason="Résultat annulé")
                    await channel.send(
                        "↩️ Le staff a annulé la dernière validation. "
                        "Le résultat doit être corrigé ou validé de nouveau."
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

        match_center = self.bot.get_cog("MatchCenterCog")
        if match_center is not None:
            try:
                await match_center._refresh_panel(
                    str(snapshot["match_kind"]),
                    int(snapshot["match_id"]),
                    disabled=False,
                )
            except Exception as error:
                print(f"⚠️ Réouverture panneau après undo : {error}")

        results = self.bot.get_cog("ResultsCog")
        if results is not None and payload.get("request") is not None:
            try:
                restored = await results._get_request(
                    str(snapshot["match_kind"]),
                    int(snapshot["match_id"]),
                )
                if restored is not None:
                    await results._refresh_validation_message(restored, disabled=False)
            except Exception as error:
                print(f"⚠️ Réactivation validation après undo : {error}")

    async def undo_snapshot(
        self,
        *,
        snapshot_id: int,
        actor: discord.abc.User,
        reason: str,
    ) -> str:
        snapshot = await self._get_snapshot(snapshot_id)
        if len(reason.strip()) < 3:
            raise ValueError("Le motif de l’annulation doit contenir au moins 3 caractères.")
        if snapshot is None:
            raise ValueError("Sauvegarde d’annulation introuvable.")
        if snapshot["status"] != "applied":
            raise ValueError("Cette action a déjà été annulée ou n’a jamais été appliquée.")

        tournament_id = int(snapshot["tournament_id"])
        async with self._lock(tournament_id):
            snapshot = await self._get_snapshot(snapshot_id)
            if snapshot is None or snapshot["status"] != "applied":
                raise ValueError("Cette action a déjà été traitée.")
            await self.check_dependencies(snapshot)
            payload = _load(snapshot.get("snapshot_json"), {})
            swiss_action_current = None
            if (
                snapshot["match_kind"] == MATCH_KIND_SWISS
                and await self._table_exists("progression_swiss_actions")
            ):
                swiss_action_current = _row_to_dict(
                    await self.db.fetchone(
                        """
                        SELECT * FROM progression_swiss_actions
                        WHERE tournament_id = ? AND completed_round = ?
                        """,
                        (
                            tournament_id,
                            int(payload["match"].get("round_number") or 0),
                        ),
                    )
                )

            await self.db.execute("BEGIN IMMEDIATE")
            try:
                if snapshot["match_kind"] == MATCH_KIND_BRACKET:
                    await self._restore_row("matches", payload.get("match"), ("id",))
                    await self._restore_row("matches", payload.get("next_match"), ("id",))
                else:
                    await self._restore_row("swiss_matches", payload.get("match"), ("id",))
                    await self._restore_row(
                        "swiss_settings",
                        payload.get("swiss_settings"),
                        ("tournament_id",),
                    )
                    if await self._table_exists("progression_swiss_actions"):
                        action_before = payload.get("swiss_action")
                        round_number = int(payload["match"].get("round_number") or 0)
                        await self.db.execute(
                            """
                            DELETE FROM progression_swiss_actions
                            WHERE tournament_id = ? AND completed_round = ?
                            """,
                            (tournament_id, round_number),
                        )
                        await self._restore_row(
                            "progression_swiss_actions",
                            action_before,
                            ("tournament_id", "completed_round"),
                        )

                await self._restore_common(snapshot, payload)
                await self.db.execute(
                    """
                    UPDATE tournament_action_snapshots
                    SET status = 'undone', undone_at = CURRENT_TIMESTAMP,
                        undone_by = ?, undo_reason = ?
                    WHERE id = ? AND status = 'applied'
                    """,
                    (
                        str(actor.id),
                        reason.strip()[:1000],
                        snapshot_id,
                    ),
                )
                await self.db.commit()
            except Exception:
                await self.db.rollback()
                raise

            if snapshot["match_kind"] == MATCH_KIND_BRACKET:
                await self._revoke_downstream_publication(payload.get("next_match"))
            else:
                await self._close_swiss_generation_prompt(swiss_action_current)
            await self._reopen_current_match_discord(snapshot, payload)

            results = self.bot.get_cog("ResultsCog")
            if results is not None:
                try:
                    await results._audit(
                        guild_id=str(snapshot["guild_id"]),
                        match_kind=str(snapshot["match_kind"]),
                        match_id=int(snapshot["match_id"]),
                        action="staff_undo",
                        actor_id=str(actor.id),
                        details={
                            "snapshot_id": snapshot_id,
                            "action_type": snapshot["action_type"],
                            "reason": reason.strip(),
                        },
                    )
                except Exception as error:
                    print(f"⚠️ Log de l’annulation impossible : {error}")

        kind_label = "bracket" if snapshot["match_kind"] == MATCH_KIND_BRACKET else "ronde suisse"
        return (
            f"La dernière validation du match **{kind_label} #{snapshot['match_id']}** "
            "a été restaurée. Le staff peut maintenant corriger ou valider de nouveau le résultat."
        )

    # ==========================================================
    # PRÉSENTATION
    # ==========================================================

    async def _preview_embed(
        self,
        snapshot: dict[str, Any],
        reason: str,
    ) -> discord.Embed:
        payload = _load(snapshot.get("snapshot_json"), {})
        match = payload.get("match") or {}
        metadata = _load(snapshot.get("metadata_json"), {})
        kind_label = (
            "Bracket à élimination directe"
            if snapshot["match_kind"] == MATCH_KIND_BRACKET
            else "Rondes suisses"
        )
        player1 = match.get("player1_name") or "Joueur 1"
        player2 = match.get("player2_name") or "Joueur 2"
        score = metadata.get("score") or (
            f"{match.get('player1_score', 0)}-{match.get('player2_score', 0)}"
        )
        embed = discord.Embed(
            title="⚠️ Annuler la dernière action ?",
            description=(
                "Hamtaro restaurera l’état enregistré juste avant la validation. "
                "Cette opération est refusée si une étape suivante a déjà commencé."
            ),
            colour=discord.Colour.orange(),
        )
        embed.add_field(name="Tournoi", value=f"`#{snapshot['tournament_id']}`", inline=True)
        embed.add_field(name="Système", value=kind_label, inline=True)
        embed.add_field(name="Match", value=f"`{snapshot['match_kind']}:{snapshot['match_id']}`", inline=True)
        embed.add_field(name="Affrontement", value=f"**{player1}** contre **{player2}**", inline=False)
        embed.add_field(name="Résultat annulé", value=f"Score : `{score}`", inline=False)
        embed.add_field(name="Motif staff", value=reason.strip()[:1000], inline=False)
        embed.add_field(
            name="Conséquences",
            value=(
                "• le match redevient à traiter ;\n"
                "• le vainqueur est retiré du match suivant si nécessaire ;\n"
                "• les statistiques et l’historique sont restaurés ;\n"
                "• le fil Discord du match est rouvert."
            ),
            inline=False,
        )
        embed.set_footer(text=f"HAMTARO_UNDO:{snapshot['id']}")
        return embed

    # ==========================================================
    # COMMANDES
    # ==========================================================

    @app_commands.command(
        name="undo_tournament_action",
        description="Annuler la dernière validation d’un tournoi",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi",
        match_id="ID facultatif du match à rechercher",
        type_match="Type du match si un ID est indiqué",
        raison="Motif obligatoire de l’annulation",
    )
    @app_commands.choices(
        type_match=[
            app_commands.Choice(name="Bracket", value=MATCH_KIND_BRACKET),
            app_commands.Choice(name="Rondes suisses", value=MATCH_KIND_SWISS),
        ]
    )
    @app_commands.default_permissions(manage_guild=True)
    async def undo_tournament_action(
        self,
        interaction: discord.Interaction,
        raison: str,
        code: str | None = None,
        match_id: int | None = None,
        type_match: str | None = None,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            if len(raison.strip()) < 3:
                raise ValueError("Le motif de l’annulation est obligatoire.")
            if match_id is not None and type_match is None:
                raise ValueError(
                    "Indique `type_match` lorsque tu recherches un match par son ID."
                )
            tournament = await resolve_tournament(
                interaction,
                self.db,
                code=code,
                require_active=False,
            )
            snapshot = await self._latest_snapshot(
                guild_id=str(interaction.guild_id),
                tournament_id=int(tournament.id),
                match_kind=type_match if match_id is not None else None,
                match_id=match_id,
            )
            if snapshot is None:
                raise ValueError(
                    "Aucune validation réversible n’a été enregistrée pour ce tournoi."
                )
            await self.check_dependencies(snapshot)
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Aucune annulation disponible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=await self._preview_embed(snapshot, raison),
            view=UndoConfirmView(self, int(snapshot["id"]), raison),
            ephemeral=True,
        )

    @app_commands.command(
        name="undo_history",
        description="Voir les dernières actions annulables ou annulées",
    )
    @app_commands.describe(code="Code facultatif du tournoi")
    @app_commands.default_permissions(manage_guild=True)
    async def undo_history(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            tournament = await resolve_tournament(
                interaction,
                self.db,
                code=code,
                require_active=False,
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(title="Tournoi introuvable", description=str(error)),
                ephemeral=True,
            )
            return

        rows = await self.db.fetchall(
            """
            SELECT * FROM tournament_action_snapshots
            WHERE guild_id = ? AND tournament_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (str(interaction.guild_id), int(tournament.id)),
        )
        if not rows:
            await interaction.followup.send(
                embed=info_embed(
                    title="Historique d’annulation vide",
                    description="Aucune action compatible n’a encore été enregistrée.",
                ),
                ephemeral=True,
            )
            return

        labels = {
            "captured": "🟡 Capture en cours",
            "applied": "🟢 Annulable",
            "undone": "↩️ Annulée",
            "aborted": "⚫ Abandonnée",
        }
        lines = []
        for row in rows:
            lines.append(
                f"{labels.get(row['status'], row['status'])} — "
                f"`#{row['id']}` — `{row['match_kind']}:{row['match_id']}` — "
                f"{row['action_type']}"
            )
        await interaction.followup.send(
            embed=info_embed(
                title=f"Historique Undo — {tournament.name}",
                description="\n".join(lines),
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentUndoCog(bot))
