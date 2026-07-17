from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.bracket_service import BracketService
from services.match_history_service import MatchHistoryService

from utils.embeds import error_embed, info_embed, success_embed
from utils.permissions import is_staff_member
from utils.tournament_resolver import resolve_tournament


# ==========================================================
# CONSTANTES
# ==========================================================

RESULT_FOOTER_PREFIX = "HAMTARO_RESULT:"

MATCH_KIND_AUTO = "auto"
MATCH_KIND_BRACKET = "bracket"
MATCH_KIND_SWISS = "swiss"
MATCH_KINDS = {MATCH_KIND_BRACKET, MATCH_KIND_SWISS}

RESULT_TYPE_NORMAL = "normal"
RESULT_TYPE_ADMIN = "admin_win"
RESULT_TYPE_DOUBLE_LOSS = "double_loss"
RESULT_TYPE_ABANDON = "abandon"
RESULT_TYPE_DISQUALIFICATION = "disqualification"
RESULT_TYPES = {
    RESULT_TYPE_NORMAL,
    RESULT_TYPE_ADMIN,
    RESULT_TYPE_DOUBLE_LOSS,
    RESULT_TYPE_ABANDON,
    RESULT_TYPE_DISQUALIFICATION,
}

OPEN_REQUEST_STATUSES = {
    "pending",
    "confirmed",
    "contested",
    "processing",
}

RESULT_TYPE_LABELS = {
    RESULT_TYPE_NORMAL: "Victoire normale",
    RESULT_TYPE_ADMIN: "Victoire administrative",
    RESULT_TYPE_DOUBLE_LOSS: "Double Loss",
    RESULT_TYPE_ABANDON: "Abandon",
    RESULT_TYPE_DISQUALIFICATION: "Disqualification",
}

RESULT_STATUS_LABELS = {
    "pending": "⏳ En attente",
    "confirmed": "✅ Confirmé par l’adversaire",
    "contested": "⚠️ Contesté",
    "processing": "🔄 Traitement en cours",
    "approved": "✅ Validé",
    "rejected": "❌ Refusé",
}

MATCH_KIND_LABELS = {
    MATCH_KIND_BRACKET: "Bracket à élimination directe",
    MATCH_KIND_SWISS: "Rondes suisses",
}


# ==========================================================
# HELPERS GÉNÉRAUX
# ==========================================================


def _row_to_dict(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None

    if isinstance(row, dict):
        return dict(row)

    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _object_value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(name, default)

    try:
        return obj[name]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, name, default)


def _status_value(value: Any) -> str:
    if value is None:
        return ""

    raw = getattr(value, "value", value)
    return str(raw).lower().strip()


def _parse_database_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _truncate(text: str, limit: int = 900) -> str:
    clean = text.strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


# ==========================================================
# MODALES
# ==========================================================


class RejectResultModal(discord.ui.Modal):
    """Le motif est obligatoire pour assurer la traçabilité du refus."""

    def __init__(
        self,
        cog: "ResultsCog",
        match_kind: str,
        match_id: int,
    ) -> None:
        super().__init__(title=f"Refuser le résultat #{match_id}")

        self.cog = cog
        self.match_kind = match_kind
        self.match_id = match_id

        self.reason = discord.ui.TextInput(
            label="Motif obligatoire",
            placeholder="Ex. : les scores déclarés ne correspondent pas.",
            required=True,
            min_length=3,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.cog._ensure_staff(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            request = await self.cog._reject_request(
                match_kind=self.match_kind,
                match_id=self.match_id,
                actor=interaction.user,
                reason=str(self.reason.value).strip(),
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Refus impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return
        except Exception as error:
            print(
                f"❌ Refus du résultat {self.match_kind}:{self.match_id} : {error}"
            )
            await interaction.followup.send(
                embed=error_embed(
                    title="Erreur inattendue",
                    description="Le résultat n’a pas pu être refusé.",
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=info_embed(
                title="Résultat refusé",
                description=(
                    f"Le résultat `{request['match_kind']}:{request['match_id']}` "
                    "a été refusé et les joueurs ont été informés."
                ),
            ),
            ephemeral=True,
        )


class ContestResultModal(discord.ui.Modal):
    """Permet à l’adversaire d’expliquer précisément le litige."""

    def __init__(
        self,
        cog: "ResultsCog",
        match_kind: str,
        match_id: int,
    ) -> None:
        super().__init__(title=f"Contester le résultat #{match_id}")

        self.cog = cog
        self.match_kind = match_kind
        self.match_id = match_id

        self.reason = discord.ui.TextInput(
            label="Que s’est-il passé ?",
            placeholder="Ex. : le véritable score est 2-0 et non 2-1.",
            required=True,
            min_length=3,
            max_length=700,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            await self.cog._contest_request(
                match_kind=self.match_kind,
                match_id=self.match_id,
                actor=interaction.user,
                reason=str(self.reason.value).strip(),
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Contestation impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return
        except Exception as error:
            print(
                "❌ Contestation du résultat "
                f"{self.match_kind}:{self.match_id} : {error}"
            )
            await interaction.followup.send(
                embed=error_embed(
                    title="Erreur inattendue",
                    description="La contestation n’a pas pu être enregistrée.",
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=info_embed(
                title="Contestation transmise",
                description=(
                    "Le résultat est maintenant signalé comme litigieux. "
                    "Le staff a été prévenu."
                ),
            ),
            ephemeral=True,
        )


class EditResultModal(discord.ui.Modal):
    """Corrige un résultat sans obliger le joueur à tout recommencer."""

    def __init__(
        self,
        cog: "ResultsCog",
        request: dict[str, Any],
    ) -> None:
        match_id = int(request["match_id"])
        super().__init__(title=f"Corriger le résultat #{match_id}")

        self.cog = cog
        self.request = request

        self.player1_score = discord.ui.TextInput(
            label="Score joueur 1",
            default=str(request.get("player1_score", 0)),
            required=True,
            max_length=2,
        )
        self.player2_score = discord.ui.TextInput(
            label="Score joueur 2",
            default=str(request.get("player2_score", 0)),
            required=True,
            max_length=2,
        )
        self.result_type = discord.ui.TextInput(
            label="Type de résultat",
            default=str(request.get("result_type", RESULT_TYPE_NORMAL)),
            placeholder=(
                "normal, admin_win, double_loss, abandon, disqualification"
            ),
            required=True,
            max_length=30,
        )
        self.winner_slot = discord.ui.TextInput(
            label="Vainqueur",
            default=str(request.get("winner_slot") or "player1"),
            placeholder="player1, player2 ou none",
            required=True,
            max_length=10,
        )
        self.notes = discord.ui.TextInput(
            label="Note de correction",
            placeholder="Explique brièvement la modification.",
            required=True,
            min_length=3,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )

        self.add_item(self.player1_score)
        self.add_item(self.player2_score)
        self.add_item(self.result_type)
        self.add_item(self.winner_slot)
        self.add_item(self.notes)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.cog._ensure_staff(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            player1_score = int(str(self.player1_score.value).strip())
            player2_score = int(str(self.player2_score.value).strip())
        except ValueError:
            await interaction.followup.send(
                embed=error_embed(
                    title="Scores invalides",
                    description="Les deux scores doivent être des nombres entiers.",
                ),
                ephemeral=True,
            )
            return

        try:
            await self.cog._edit_request(
                match_kind=str(self.request["match_kind"]),
                match_id=int(self.request["match_id"]),
                actor=interaction.user,
                player1_score=player1_score,
                player2_score=player2_score,
                result_type=str(self.result_type.value).lower().strip(),
                winner_slot=str(self.winner_slot.value).lower().strip(),
                notes=str(self.notes.value).strip(),
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Correction impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return
        except Exception as error:
            print(
                "❌ Correction du résultat "
                f"{self.request['match_kind']}:{self.request['match_id']} : {error}"
            )
            await interaction.followup.send(
                embed=error_embed(
                    title="Erreur inattendue",
                    description="La correction n’a pas pu être enregistrée.",
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success_embed(
                title="Résultat corrigé",
                description=(
                    "Le message staff a été actualisé et l’adversaire "
                    "a reçu une nouvelle demande de confirmation."
                ),
            ),
            ephemeral=True,
        )


# ==========================================================
# VUES PERSISTANTES
# ==========================================================


class ResultValidationView(discord.ui.View):
    """Boutons réservés au staff dans le salon de validation."""

    def __init__(
        self,
        cog: "ResultsCog",
        *,
        disabled: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.cog = cog

        if disabled:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.cog._ensure_staff(interaction)

    @discord.ui.button(
        label="Valider",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="hamtaro:result:staff:approve",
    )
    async def approve_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        reference = self.cog._extract_result_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message(
                "❌ Hamtaro ne retrouve pas le match associé.",
                ephemeral=True,
            )
            return

        match_kind, match_id = reference
        await interaction.response.defer(ephemeral=True)

        try:
            request = await self.cog._approve_request(
                match_kind=match_kind,
                match_id=match_id,
                actor=interaction.user,
                notes="Validation effectuée avec le bouton Discord.",
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Validation impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return
        except Exception as error:
            print(f"❌ Validation {match_kind}:{match_id} : {error}")
            await interaction.followup.send(
                embed=error_embed(
                    title="Erreur inattendue",
                    description="Le résultat n’a pas pu être validé.",
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success_embed(
                title="Résultat validé",
                description=(
                    f"Le résultat `{request['match_kind']}:{request['match_id']}` "
                    "a été appliqué au tournoi."
                ),
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Modifier",
        emoji="✏️",
        style=discord.ButtonStyle.primary,
        custom_id="hamtaro:result:staff:edit",
    )
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        reference = self.cog._extract_result_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message(
                "❌ Hamtaro ne retrouve pas le match associé.",
                ephemeral=True,
            )
            return

        match_kind, match_id = reference
        request = await self.cog._get_request(match_kind, match_id)

        if request is None:
            await interaction.response.send_message(
                "❌ La demande de validation est introuvable.",
                ephemeral=True,
            )
            return

        if request["status"] not in {"pending", "confirmed", "contested"}:
            await interaction.response.send_message(
                "⚠️ Ce résultat a déjà été traité.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            EditResultModal(self.cog, request)
        )

    @discord.ui.button(
        label="Refuser",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="hamtaro:result:staff:reject",
    )
    async def reject_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        reference = self.cog._extract_result_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message(
                "❌ Hamtaro ne retrouve pas le match associé.",
                ephemeral=True,
            )
            return

        match_kind, match_id = reference
        await interaction.response.send_modal(
            RejectResultModal(
                cog=self.cog,
                match_kind=match_kind,
                match_id=match_id,
            )
        )


class OpponentConfirmationView(discord.ui.View):
    """Confirmation par l’adversaire avant la décision du staff."""

    def __init__(
        self,
        cog: "ResultsCog",
        *,
        disabled: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.cog = cog

        if disabled:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

    @discord.ui.button(
        label="Confirmer",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="hamtaro:result:opponent:confirm",
    )
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        reference = self.cog._extract_result_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message(
                "❌ Hamtaro ne retrouve pas ce résultat.",
                ephemeral=True,
            )
            return

        match_kind, match_id = reference
        await interaction.response.defer(ephemeral=True)

        try:
            auto_approved = await self.cog._confirm_request(
                match_kind=match_kind,
                match_id=match_id,
                actor=interaction.user,
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Confirmation impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return

        description = "Le staff voit maintenant que les deux joueurs sont d’accord."
        if auto_approved:
            description = "Le résultat confirmé a été automatiquement validé."

        await interaction.followup.send(
            embed=success_embed(
                title="Résultat confirmé",
                description=description,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Contester",
        emoji="⚠️",
        style=discord.ButtonStyle.danger,
        custom_id="hamtaro:result:opponent:contest",
    )
    async def contest_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        reference = self.cog._extract_result_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message(
                "❌ Hamtaro ne retrouve pas ce résultat.",
                ephemeral=True,
            )
            return

        match_kind, match_id = reference
        await interaction.response.send_modal(
            ContestResultModal(
                cog=self.cog,
                match_kind=match_kind,
                match_id=match_id,
            )
        )


class PendingResultSelect(discord.ui.Select):
    def __init__(
        self,
        cog: "ResultsCog",
        requests: list[dict[str, Any]],
    ) -> None:
        self.cog = cog

        options: list[discord.SelectOption] = []
        for request in requests[:25]:
            kind = str(request["match_kind"])
            match_id = int(request["match_id"])
            status = str(request["status"])
            score = f"{request['player1_score']}-{request['player2_score']}"
            options.append(
                discord.SelectOption(
                    label=f"{kind.title()} #{match_id} — {score}",
                    value=f"{kind}:{match_id}",
                    description=RESULT_STATUS_LABELS.get(status, status)[:100],
                    emoji="🇨🇭" if kind == MATCH_KIND_SWISS else "🏆",
                )
            )

        super().__init__(
            placeholder="Choisir un résultat à consulter",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.cog._ensure_staff(interaction):
            return

        kind, raw_match_id = self.values[0].split(":", 1)
        match_id = int(raw_match_id)

        request = await self.cog._get_request(kind, match_id)
        if request is None:
            await interaction.response.send_message(
                "❌ Ce résultat n’existe plus.",
                ephemeral=True,
            )
            return

        embed = await self.cog._build_validation_embed(request)
        jump_url = self.cog._request_jump_url(request)
        if jump_url:
            embed.description = (
                f"{embed.description or ''}\n\n[Ouvrir le message de validation]({jump_url})"
            )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )


class PendingResultsView(discord.ui.View):
    def __init__(
        self,
        cog: "ResultsCog",
        requests: list[dict[str, Any]],
    ) -> None:
        super().__init__(timeout=180)
        self.add_item(PendingResultSelect(cog, requests))


# ==========================================================
# COG PRINCIPAL
# ==========================================================


class ResultsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db
        self.brackets = BracketService(self.db)
        self.history = MatchHistoryService()
        self._match_locks: dict[tuple[str, int], asyncio.Lock] = {}

    async def cog_load(self) -> None:
        await self._init_result_tables()

        self.bot.add_view(ResultValidationView(self))
        self.bot.add_view(OpponentConfirmationView(self))

        if not self.result_reminders.is_running():
            self.result_reminders.start()

    def cog_unload(self) -> None:
        if self.result_reminders.is_running():
            self.result_reminders.cancel()

    # ==========================================================
    # INITIALISATION BASE DE DONNÉES
    # ==========================================================

    async def _init_result_tables(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS result_settings (
                guild_id TEXT PRIMARY KEY,
                validation_channel_id TEXT,
                public_results_channel_id TEXT,
                logs_channel_id TEXT,
                staff_role_id TEXT,
                auto_approve_confirmed INTEGER NOT NULL DEFAULT 0,
                reminder_minutes INTEGER NOT NULL DEFAULT 30,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS result_requests (
                match_kind TEXT NOT NULL,
                match_id INTEGER NOT NULL,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER NOT NULL,
                reporter_id TEXT NOT NULL,
                opponent_id TEXT,
                result_type TEXT NOT NULL DEFAULT 'normal',
                winner_slot TEXT,
                player1_score INTEGER NOT NULL DEFAULT 0,
                player2_score INTEGER NOT NULL DEFAULT 0,
                proof_url TEXT,
                proof_is_image INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                confirmation_channel_id TEXT,
                confirmation_message_id TEXT,
                validation_channel_id TEXT,
                validation_message_id TEXT,
                dispute_thread_id TEXT,
                confirmed_by TEXT,
                confirmed_at TIMESTAMP,
                contested_by TEXT,
                contest_reason TEXT,
                decision_by TEXT,
                decision_notes TEXT,
                last_reminded_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (match_kind, match_id)
            )
            """
        )

        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS result_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                match_kind TEXT NOT NULL,
                match_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                actor_id TEXT,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_result_requests_status
            ON result_requests(guild_id, status, created_at)
            """
        )
        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_result_audit_match
            ON result_audit_logs(match_kind, match_id, created_at)
            """
        )
        await self.db.commit()

    # ==========================================================
    # PERMISSIONS ET CONFIGURATION
    # ==========================================================

    def _guild_id(self, interaction: discord.Interaction) -> str:
        if interaction.guild is None:
            raise ValueError("Cette commande doit être utilisée dans un serveur.")
        return str(interaction.guild.id)

    async def _get_settings(self, guild_id: str) -> dict[str, Any]:
        row = await self.db.fetchone(
            """
            SELECT *
            FROM result_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
        )
        settings = _row_to_dict(row) or {}

        settings.setdefault("guild_id", guild_id)
        settings.setdefault(
            "validation_channel_id",
            os.getenv("VALIDATION_RESULTS_CHANNEL_ID") or None,
        )
        settings.setdefault(
            "public_results_channel_id",
            os.getenv("RESULTS_CHANNEL_ID") or None,
        )
        settings.setdefault(
            "logs_channel_id",
            os.getenv("RESULT_LOGS_CHANNEL_ID") or None,
        )
        settings.setdefault(
            "staff_role_id",
            os.getenv("STAFF_ROLE_ID") or None,
        )
        settings.setdefault("auto_approve_confirmed", 0)
        settings.setdefault("reminder_minutes", 30)
        return settings

    async def _is_authorized_staff(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True

        try:
            if is_staff_member(member):
                return True
        except Exception:
            pass

        settings = await self._get_settings(str(member.guild.id))
        raw_role_id = settings.get("staff_role_id")

        if raw_role_id:
            try:
                role_id = int(raw_role_id)
            except (TypeError, ValueError):
                role_id = 0

            if role_id and any(role.id == role_id for role in member.roles):
                return True

        return member.guild_permissions.manage_guild

    async def _ensure_staff(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Cette action doit être utilisée dans un serveur.",
                    ephemeral=True,
                )
            return False

        if await self._is_authorized_staff(interaction.user):
            return True

        if interaction.response.is_done():
            await interaction.followup.send(
                "❌ Seuls les membres du staff peuvent utiliser cette action.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "❌ Seuls les membres du staff peuvent utiliser cette action.",
                ephemeral=True,
            )
        return False

    async def _get_channel(
        self,
        channel_id: Any,
    ) -> discord.abc.Messageable | None:
        if channel_id in (None, "", 0, "0"):
            return None

        try:
            parsed_id = int(channel_id)
        except (TypeError, ValueError):
            return None

        channel = self.bot.get_channel(parsed_id)
        if channel is not None:
            return channel

        try:
            fetched = await self.bot.fetch_channel(parsed_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

        return fetched if hasattr(fetched, "send") else None

    async def _get_configured_channel(
        self,
        guild_id: str,
        setting_name: str,
    ) -> discord.abc.Messageable | None:
        settings = await self._get_settings(guild_id)
        return await self._get_channel(settings.get(setting_name))

    # ==========================================================
    # ACCÈS AUX MATCHS ET DEMANDES
    # ==========================================================

    def _lock_for(self, match_kind: str, match_id: int) -> asyncio.Lock:
        key = (match_kind, match_id)
        if key not in self._match_locks:
            self._match_locks[key] = asyncio.Lock()
        return self._match_locks[key]

    async def _get_request(
        self,
        match_kind: str,
        match_id: int,
    ) -> dict[str, Any] | None:
        row = await self.db.fetchone(
            """
            SELECT *
            FROM result_requests
            WHERE match_kind = ? AND match_id = ?
            """,
            (match_kind, match_id),
        )
        return _row_to_dict(row)

    async def _list_open_requests(
        self,
        guild_id: str,
    ) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT *
            FROM result_requests
            WHERE guild_id = ?
              AND status IN ('pending', 'confirmed', 'contested', 'processing')
            ORDER BY
                CASE status
                    WHEN 'contested' THEN 0
                    WHEN 'confirmed' THEN 1
                    WHEN 'pending' THEN 2
                    ELSE 3
                END,
                created_at ASC
            """,
            (guild_id,),
        )
        return [dict(row) for row in rows]

    async def _resolve_tournament(
        self,
        interaction: discord.Interaction,
    ) -> Any:
        return await resolve_tournament(interaction, self.db)

    async def _resolve_match(
        self,
        *,
        tournament_id: int,
        user_id: str,
        match_id: int | None,
        requested_kind: str,
        require_player: bool = True,
    ) -> tuple[str, Any]:
        if requested_kind not in {MATCH_KIND_AUTO, *MATCH_KINDS}:
            raise ValueError("Type de match invalide.")

        bracket_match = None
        swiss_match = None

        if match_id is None:
            if requested_kind in {MATCH_KIND_AUTO, MATCH_KIND_BRACKET}:
                bracket_match = await self.db.get_next_match_for_player(
                    tournament_id=tournament_id,
                    discord_id=user_id,
                )

            if requested_kind in {MATCH_KIND_AUTO, MATCH_KIND_SWISS}:
                swiss_row = await self.db.fetchone(
                    """
                    SELECT *
                    FROM swiss_matches
                    WHERE tournament_id = ?
                      AND (player1_id = ? OR player2_id = ?)
                      AND status = 'pending'
                      AND is_bye = 0
                    ORDER BY round_number DESC, table_number ASC, id ASC
                    LIMIT 1
                    """,
                    (tournament_id, user_id, user_id),
                )
                swiss_match = swiss_row
        else:
            if requested_kind in {MATCH_KIND_AUTO, MATCH_KIND_BRACKET}:
                candidate = await self.db.get_match(match_id)
                if candidate is not None and int(candidate.tournament_id) == int(tournament_id):
                    bracket_match = candidate

            if requested_kind in {MATCH_KIND_AUTO, MATCH_KIND_SWISS}:
                candidate = await self.db.get_swiss_match(match_id)
                if candidate is not None and int(candidate["tournament_id"]) == int(tournament_id):
                    swiss_match = candidate

        if requested_kind == MATCH_KIND_BRACKET:
            if bracket_match is None:
                raise ValueError("Match de bracket introuvable.")
            selected_kind, selected_match = MATCH_KIND_BRACKET, bracket_match
        elif requested_kind == MATCH_KIND_SWISS:
            if swiss_match is None:
                raise ValueError("Match suisse introuvable.")
            selected_kind, selected_match = MATCH_KIND_SWISS, swiss_match
        else:
            candidates = [
                (MATCH_KIND_BRACKET, bracket_match),
                (MATCH_KIND_SWISS, swiss_match),
            ]
            candidates = [(kind, match) for kind, match in candidates if match is not None]

            if not candidates:
                raise ValueError(
                    "Aucun match actif trouvé. Utilise `/nextmatch` ou indique le type du match."
                )
            if len(candidates) > 1:
                raise ValueError(
                    "Hamtaro trouve un match de bracket et un match suisse avec cet ID. "
                    "Indique explicitement `type_match`."
                )
            selected_kind, selected_match = candidates[0]

        if require_player:
            player_ids = {
                str(_object_value(selected_match, "player1_id") or ""),
                str(_object_value(selected_match, "player2_id") or ""),
            }
            if user_id not in player_ids:
                raise ValueError("Tu ne participes pas à ce match.")

        return selected_kind, selected_match

    def _match_context(self, match_kind: str, match: Any) -> dict[str, Any]:
        if match_kind == MATCH_KIND_BRACKET:
            return {
                "match_id": int(_object_value(match, "id")),
                "tournament_id": int(_object_value(match, "tournament_id")),
                "round_number": _object_value(match, "round"),
                "table_number": None,
                "player1_id": _object_value(match, "player1_id"),
                "player2_id": _object_value(match, "player2_id"),
                "player1_name": _object_value(match, "player1_name"),
                "player2_name": _object_value(match, "player2_name"),
                "status": _status_value(_object_value(match, "status")),
                "is_bye": bool(_object_value(match, "is_bye", False)),
            }

        row = _row_to_dict(match) or {}
        return {
            "match_id": int(row["id"]),
            "tournament_id": int(row["tournament_id"]),
            "round_number": row.get("round_number"),
            "table_number": row.get("table_number"),
            "player1_id": row.get("player1_id"),
            "player2_id": row.get("player2_id"),
            "player1_name": row.get("player1_name"),
            "player2_name": row.get("player2_name"),
            "status": str(row.get("status") or "").lower(),
            "is_bye": bool(row.get("is_bye")),
        }

    async def _load_match_context(
        self,
        match_kind: str,
        match_id: int,
    ) -> dict[str, Any]:
        if match_kind == MATCH_KIND_BRACKET:
            match = await self.db.get_match(match_id)
        else:
            match = await self.db.get_swiss_match(match_id)

        if match is None:
            raise ValueError("Match introuvable.")

        return self._match_context(match_kind, match)

    def _winner_from_request(
        self,
        request: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        slot = request.get("winner_slot")
        if slot == "player1":
            return (
                str(context["player1_id"]),
                str(context["player1_name"]),
            )
        if slot == "player2":
            return (
                str(context["player2_id"]),
                str(context["player2_name"]),
            )
        return None, None

    async def _create_request(
        self,
        *,
        match_kind: str,
        context: dict[str, Any],
        guild_id: str,
        reporter_id: str,
        result_type: str,
        winner_slot: str | None,
        player1_score: int,
        player2_score: int,
        proof_url: str | None,
        proof_is_image: bool,
    ) -> dict[str, Any]:
        existing = await self._get_request(match_kind, int(context["match_id"]))
        if existing is not None and existing["status"] in OPEN_REQUEST_STATUSES:
            raise ValueError(
                "Un résultat est déjà en attente pour ce match. "
                "Le staff doit le traiter avant une nouvelle déclaration."
            )

        player_ids = [
            str(context.get("player1_id") or ""),
            str(context.get("player2_id") or ""),
        ]
        opponent_id = next(
            (player_id for player_id in player_ids if player_id and player_id != reporter_id),
            None,
        )

        await self.db.execute(
            """
            INSERT INTO result_requests (
                match_kind,
                match_id,
                guild_id,
                tournament_id,
                reporter_id,
                opponent_id,
                result_type,
                winner_slot,
                player1_score,
                player2_score,
                proof_url,
                proof_is_image,
                status,
                confirmation_channel_id,
                confirmation_message_id,
                validation_channel_id,
                validation_message_id,
                dispute_thread_id,
                confirmed_by,
                confirmed_at,
                contested_by,
                contest_reason,
                decision_by,
                decision_notes,
                last_reminded_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending',
                    NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                    NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(match_kind, match_id)
            DO UPDATE SET
                guild_id = excluded.guild_id,
                tournament_id = excluded.tournament_id,
                reporter_id = excluded.reporter_id,
                opponent_id = excluded.opponent_id,
                result_type = excluded.result_type,
                winner_slot = excluded.winner_slot,
                player1_score = excluded.player1_score,
                player2_score = excluded.player2_score,
                proof_url = excluded.proof_url,
                proof_is_image = excluded.proof_is_image,
                status = 'pending',
                confirmation_channel_id = NULL,
                confirmation_message_id = NULL,
                validation_channel_id = NULL,
                validation_message_id = NULL,
                dispute_thread_id = NULL,
                confirmed_by = NULL,
                confirmed_at = NULL,
                contested_by = NULL,
                contest_reason = NULL,
                decision_by = NULL,
                decision_notes = NULL,
                last_reminded_at = NULL,
                created_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                match_kind,
                int(context["match_id"]),
                guild_id,
                int(context["tournament_id"]),
                reporter_id,
                opponent_id,
                result_type,
                winner_slot,
                player1_score,
                player2_score,
                proof_url,
                int(proof_is_image),
            ),
        )
        await self.db.commit()

        request = await self._get_request(match_kind, int(context["match_id"]))
        if request is None:
            raise RuntimeError("La demande a été créée, mais elle est introuvable.")
        return request

    # ==========================================================
    # VALIDATION DES DONNÉES
    # ==========================================================

    def _validate_result_data(
        self,
        *,
        match_kind: str,
        result_type: str,
        player1_score: int,
        player2_score: int,
        winner_slot: str | None,
    ) -> None:
        if result_type not in RESULT_TYPES:
            raise ValueError(
                "Type invalide : normal, admin_win, double_loss, abandon ou disqualification."
            )

        if player1_score < 0 or player2_score < 0:
            raise ValueError("Les scores ne peuvent pas être négatifs.")

        if result_type == RESULT_TYPE_DOUBLE_LOSS:
            if match_kind != MATCH_KIND_SWISS:
                raise ValueError(
                    "Le Double Loss s’applique uniquement aux rondes suisses."
                )
            if winner_slot not in {None, "none"}:
                raise ValueError("Un Double Loss ne possède aucun vainqueur.")
            return

        if winner_slot not in {"player1", "player2"}:
            raise ValueError("Le vainqueur doit être `player1` ou `player2`.")

        if match_kind == MATCH_KIND_SWISS and player1_score == player2_score:
            raise ValueError(
                "Un résultat suisse avec vainqueur ne peut pas avoir deux scores égaux. "
                "Utilise un Double Loss lorsqu’aucun joueur ne gagne."
            )

        if result_type == RESULT_TYPE_NORMAL:
            if player1_score == player2_score:
                raise ValueError(
                    "Les matchs nuls n’existent pas. En ronde suisse, utilise un Double Loss."
                )
            expected_winner = (
                "player1" if player1_score > player2_score else "player2"
            )
            if winner_slot != expected_winner:
                raise ValueError(
                    "Le vainqueur indiqué ne correspond pas aux scores saisis."
                )

    def _proof_data(
        self,
        proof: discord.Attachment | None,
    ) -> tuple[str | None, bool]:
        if proof is None:
            return None, False

        content_type = (proof.content_type or "").lower()
        is_image = content_type.startswith("image/")
        is_pdf = content_type == "application/pdf" or proof.filename.lower().endswith(".pdf")

        if not is_image and not is_pdf:
            raise ValueError("La preuve doit être une image ou un fichier PDF.")

        return proof.url, is_image

    # ==========================================================
    # EMBEDS ET MESSAGES
    # ==========================================================

    def _player_display(
        self,
        guild: discord.Guild | None,
        discord_id: Any,
        fallback_name: Any,
    ) -> str:
        if discord_id and guild is not None:
            try:
                member = guild.get_member(int(discord_id))
            except (TypeError, ValueError):
                member = None
            if member is not None:
                return f"{member.mention}\n`{member.id}`"

        name = str(fallback_name or "Joueur inconnu")
        if discord_id:
            return f"**{name}**\n`{discord_id}`"
        return f"**{name}**"

    async def _build_validation_embed(
        self,
        request: dict[str, Any],
    ) -> discord.Embed:
        context = await self._load_match_context(
            str(request["match_kind"]),
            int(request["match_id"]),
        )
        tournament = await self.db.get_tournament(int(request["tournament_id"]))
        guild = self.bot.get_guild(int(request["guild_id"]))

        player1_deck = await self._get_registration_deck(
            int(request["tournament_id"]),
            context.get("player1_id"),
        )
        player2_deck = await self._get_registration_deck(
            int(request["tournament_id"]),
            context.get("player2_id"),
        )

        status = str(request["status"])
        colour = {
            "pending": discord.Colour.orange(),
            "confirmed": discord.Colour.green(),
            "contested": discord.Colour.red(),
            "processing": discord.Colour.blurple(),
            "approved": discord.Colour.green(),
            "rejected": discord.Colour.dark_red(),
        }.get(status, discord.Colour.orange())

        embed = discord.Embed(
            title=f"{RESULT_STATUS_LABELS.get(status, status)} — Résultat de match",
            description=(
                "Le staff peut valider, corriger ou refuser ce résultat."
                if status in {"pending", "confirmed", "contested"}
                else "Cette demande a été traitée."
            ),
            colour=colour,
            timestamp=discord.utils.utcnow(),
        )

        tournament_name = _object_value(tournament, "name", "Tournoi Hamtaro")
        tournament_format = _object_value(tournament, "format", "Inconnu")
        tournament_code = _object_value(tournament, "code", None)
        tournament_text = f"**{tournament_name}**\nFormat : `{tournament_format}`"
        if tournament_code:
            tournament_text += f" | Code : `{tournament_code}`"

        embed.add_field(name="🏟️ Tournoi", value=tournament_text, inline=False)
        embed.add_field(
            name="🧭 Système",
            value=MATCH_KIND_LABELS.get(str(request["match_kind"]), "Inconnu"),
            inline=True,
        )
        embed.add_field(
            name="🆔 Match",
            value=f"`{request['match_kind']}:{request['match_id']}`",
            inline=True,
        )

        round_text = str(context.get("round_number") or "Inconnue")
        if context.get("table_number") is not None:
            round_text += f" — Table {context['table_number']}"
        embed.add_field(name="🔄 Ronde", value=f"`{round_text}`", inline=True)

        embed.add_field(
            name="👤 Joueur 1",
            value=(
                f"{self._player_display(guild, context.get('player1_id'), context.get('player1_name'))}\n"
                f"🎴 Deck : **{player1_deck or 'Non renseigné'}**\n"
                f"📊 Score : **{request['player1_score']}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="👤 Joueur 2",
            value=(
                f"{self._player_display(guild, context.get('player2_id'), context.get('player2_name'))}\n"
                f"🎴 Deck : **{player2_deck or 'Non renseigné'}**\n"
                f"📊 Score : **{request['player2_score']}**"
            ),
            inline=True,
        )

        winner_id, winner_name = self._winner_from_request(request, context)
        if request["result_type"] == RESULT_TYPE_DOUBLE_LOSS:
            winner_text = "🔴 Aucun — Double Loss"
        else:
            winner_text = self._player_display(guild, winner_id, winner_name)

        embed.add_field(
            name="🏆 Décision déclarée",
            value=(
                f"Type : **{RESULT_TYPE_LABELS.get(request['result_type'], request['result_type'])}**\n"
                f"Vainqueur : {winner_text}"
            ),
            inline=False,
        )

        reporter_id = request.get("reporter_id")
        reporter_mention = f"<@{reporter_id}>" if reporter_id else "Inconnu"
        embed.add_field(name="📨 Déclaré par", value=reporter_mention, inline=True)

        created_at = _parse_database_datetime(request.get("created_at"))
        if created_at:
            embed.add_field(
                name="🕐 Déclaré le",
                value=discord.utils.format_dt(created_at, style="F"),
                inline=True,
            )

        if request.get("confirmed_by"):
            embed.add_field(
                name="✅ Confirmation adverse",
                value=f"Confirmé par <@{request['confirmed_by']}>",
                inline=False,
            )

        if request.get("contest_reason"):
            embed.add_field(
                name="⚠️ Motif du litige",
                value=_truncate(str(request["contest_reason"]), 1000),
                inline=False,
            )

        if request.get("decision_notes"):
            embed.add_field(
                name="📝 Note staff",
                value=_truncate(str(request["decision_notes"]), 1000),
                inline=False,
            )

        proof_url = request.get("proof_url")
        if proof_url:
            embed.add_field(
                name="📎 Preuve",
                value=f"[Ouvrir la preuve]({proof_url})",
                inline=False,
            )
            if int(request.get("proof_is_image") or 0) == 1:
                embed.set_image(url=str(proof_url))

        embed.set_footer(
            text=(
                f"{RESULT_FOOTER_PREFIX}{request['match_kind']}:{request['match_id']} | "
                f"{RESULT_STATUS_LABELS.get(status, status)}"
            )
        )
        return embed

    async def _build_confirmation_embed(
        self,
        request: dict[str, Any],
    ) -> discord.Embed:
        context = await self._load_match_context(
            str(request["match_kind"]),
            int(request["match_id"]),
        )
        tournament = await self.db.get_tournament(int(request["tournament_id"]))

        winner_id, winner_name = self._winner_from_request(request, context)
        if request["result_type"] == RESULT_TYPE_DOUBLE_LOSS:
            winner_text = "Aucun — Double Loss"
        else:
            winner_text = str(winner_name or winner_id or "Inconnu")

        embed = discord.Embed(
            title="🐹 Ton adversaire a déclaré un résultat",
            description=(
                "Confirme le résultat s’il est correct. En cas d’erreur, "
                "utilise **Contester** et explique la différence."
            ),
            colour=discord.Colour.orange(),
        )
        embed.add_field(
            name="🏟️ Tournoi",
            value=f"**{_object_value(tournament, 'name', 'Tournoi Hamtaro')}**",
            inline=False,
        )
        embed.add_field(
            name="⚔️ Match",
            value=(
                f"**{context.get('player1_name')}** "
                f"{request['player1_score']}-{request['player2_score']} "
                f"**{context.get('player2_name')}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏆 Résultat déclaré",
            value=(
                f"Type : **{RESULT_TYPE_LABELS.get(request['result_type'], request['result_type'])}**\n"
                f"Vainqueur : **{winner_text}**"
            ),
            inline=False,
        )
        if request.get("proof_url"):
            embed.add_field(
                name="📎 Preuve",
                value=f"[Ouvrir la preuve]({request['proof_url']})",
                inline=False,
            )
        embed.set_footer(
            text=f"{RESULT_FOOTER_PREFIX}{request['match_kind']}:{request['match_id']}"
        )
        return embed

    def _extract_result_reference(
        self,
        message: discord.Message | None,
    ) -> tuple[str, int] | None:
        if message is None or not message.embeds:
            return None

        footer = message.embeds[0].footer.text or ""
        pattern = rf"{re.escape(RESULT_FOOTER_PREFIX)}(bracket|swiss):(\d+)"
        match = re.search(pattern, footer)
        if match is None:
            return None
        return match.group(1), int(match.group(2))

    def _request_jump_url(self, request: dict[str, Any]) -> str | None:
        channel_id = request.get("validation_channel_id")
        message_id = request.get("validation_message_id")
        guild_id = request.get("guild_id")
        if not channel_id or not message_id or not guild_id:
            return None
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    async def _send_validation_message(
        self,
        request: dict[str, Any],
    ) -> bool:
        channel = await self._get_configured_channel(
            str(request["guild_id"]),
            "validation_channel_id",
        )
        if channel is None:
            return False

        embed = await self._build_validation_embed(request)
        try:
            message = await channel.send(
                embed=embed,
                view=ResultValidationView(self),
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"⚠️ Envoi dans validation-résultats impossible : {error}")
            return False

        await self.db.execute(
            """
            UPDATE result_requests
            SET validation_channel_id = ?,
                validation_message_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE match_kind = ? AND match_id = ?
            """,
            (
                str(message.channel.id),
                str(message.id),
                request["match_kind"],
                request["match_id"],
            ),
        )
        await self.db.commit()
        return True

    async def _send_opponent_confirmation(
        self,
        request: dict[str, Any],
    ) -> bool:
        opponent_id = request.get("opponent_id")
        if not opponent_id:
            return False

        try:
            user = self.bot.get_user(int(opponent_id)) or await self.bot.fetch_user(int(opponent_id))
        except (ValueError, discord.NotFound, discord.HTTPException):
            user = None

        embed = await self._build_confirmation_embed(request)
        message = None

        if user is not None:
            try:
                message = await user.send(
                    embed=embed,
                    view=OpponentConfirmationView(self),
                )
            except (discord.Forbidden, discord.HTTPException):
                message = None

        if message is None:
            public_channel = await self._get_configured_channel(
                str(request["guild_id"]),
                "public_results_channel_id",
            )
            if public_channel is not None:
                try:
                    message = await public_channel.send(
                        content=f"<@{opponent_id}>",
                        embed=embed,
                        view=OpponentConfirmationView(self),
                    )
                except (discord.Forbidden, discord.HTTPException):
                    message = None

        if message is None:
            return False

        await self.db.execute(
            """
            UPDATE result_requests
            SET confirmation_channel_id = ?,
                confirmation_message_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE match_kind = ? AND match_id = ?
            """,
            (
                str(message.channel.id),
                str(message.id),
                request["match_kind"],
                request["match_id"],
            ),
        )
        await self.db.commit()
        return True

    async def _refresh_validation_message(
        self,
        request: dict[str, Any],
        *,
        disabled: bool | None = None,
    ) -> None:
        channel = await self._get_channel(request.get("validation_channel_id"))
        message_id = request.get("validation_message_id")
        if channel is None or not message_id or not hasattr(channel, "fetch_message"):
            return

        try:
            message = await channel.fetch_message(int(message_id))
            embed = await self._build_validation_embed(request)
            final_disabled = (
                request["status"] in {"approved", "rejected"}
                if disabled is None
                else disabled
            )
            await message.edit(
                embed=embed,
                view=ResultValidationView(self, disabled=final_disabled),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    async def _disable_confirmation_message(
        self,
        request: dict[str, Any],
    ) -> None:
        channel = await self._get_channel(request.get("confirmation_channel_id"))
        message_id = request.get("confirmation_message_id")
        if channel is None or not message_id or not hasattr(channel, "fetch_message"):
            return

        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(view=OpponentConfirmationView(self, disabled=True))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    # ==========================================================
    # HISTORIQUE, LOGS ET NOTIFICATIONS
    # ==========================================================

    async def _get_registration_deck(
        self,
        tournament_id: int,
        discord_id: Any,
    ) -> str | None:
        if not discord_id:
            return None

        try:
            registration = await self.db.get_registration_by_user(
                tournament_id=tournament_id,
                discord_id=str(discord_id),
            )
        except (ValueError, AttributeError):
            return None

        return _object_value(registration, "deck") if registration else None

    async def _record_match_history(
        self,
        guild_id: str,
        match: Any,
        status: str = "approved",
    ) -> None:
        try:
            tournament_id = _object_value(match, "tournament_id")
            if tournament_id is None:
                return

            player1_id = _object_value(match, "player1_id")
            player2_id = _object_value(match, "player2_id")
            round_number = _object_value(match, "round_number")
            if round_number is None:
                round_number = _object_value(match, "round")

            await self.history.record_match(
                guild_id=guild_id,
                tournament_id=tournament_id,
                match_id=_object_value(match, "id"),
                round_number=round_number,
                player1_id=player1_id,
                player1_name=_object_value(match, "player1_name"),
                player2_id=player2_id,
                player2_name=_object_value(match, "player2_name"),
                winner_id=_object_value(match, "winner_id"),
                winner_name=_object_value(match, "winner_name"),
                score=_object_value(match, "score"),
                player1_deck=await self._get_registration_deck(tournament_id, player1_id),
                player2_deck=await self._get_registration_deck(tournament_id, player2_id),
                status=status,
            )
        except Exception as error:
            print(f"⚠️ Historique du match non enregistré : {error}")

    async def _audit(
        self,
        *,
        guild_id: str,
        match_kind: str,
        match_id: int,
        action: str,
        actor_id: str | None,
        details: dict[str, Any] | str | None = None,
    ) -> None:
        details_text = (
            json.dumps(details, ensure_ascii=False, default=str)
            if isinstance(details, dict)
            else details
        )

        await self.db.execute(
            """
            INSERT INTO result_audit_logs (
                guild_id, match_kind, match_id, action, actor_id, details
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild_id, match_kind, match_id, action, actor_id, details_text),
        )
        await self.db.commit()

        channel = await self._get_configured_channel(guild_id, "logs_channel_id")
        if channel is None:
            return

        embed = discord.Embed(
            title="📋 Log Hamtaro — Résultat",
            colour=discord.Colour.dark_gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Action", value=f"`{action}`", inline=True)
        embed.add_field(
            name="Match",
            value=f"`{match_kind}:{match_id}`",
            inline=True,
        )
        embed.add_field(
            name="Auteur",
            value=f"<@{actor_id}>" if actor_id else "Automatique",
            inline=True,
        )
        if details_text:
            embed.add_field(
                name="Détails",
                value=f"```json\n{_truncate(details_text, 900)}\n```",
                inline=False,
            )
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _safe_dm(
        self,
        user_id: Any,
        *,
        embed: discord.Embed,
    ) -> None:
        if not user_id:
            return
        try:
            user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
            await user.send(embed=embed)
        except (ValueError, discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    async def _notify_players_rejected(
        self,
        request: dict[str, Any],
        reason: str,
    ) -> None:
        embed = info_embed(
            title="❌ Résultat refusé par le staff",
            description=(
                f"Match `{request['match_kind']}:{request['match_id']}`\n\n"
                f"**Motif :** {reason}\n\n"
                "Le résultat peut être déclaré à nouveau."
            ),
        )
        await asyncio.gather(
            self._safe_dm(request.get("reporter_id"), embed=embed),
            self._safe_dm(request.get("opponent_id"), embed=embed),
        )

    async def _notify_result_approved(
        self,
        request: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        winner_id, winner_name = self._winner_from_request(request, context)
        result_label = RESULT_TYPE_LABELS.get(request["result_type"], request["result_type"])

        if request["result_type"] == RESULT_TYPE_DOUBLE_LOSS:
            summary = (
                f"**{context['player1_name']}** et **{context['player2_name']}** "
                "reçoivent un Double Loss."
            )
        else:
            summary = (
                f"**{winner_name}** remporte le match "
                f"{request['player1_score']}-{request['player2_score']}."
            )

        embed = success_embed(
            title="✅ Résultat validé",
            description=(
                f"{summary}\n\nType : **{result_label}**\n"
                f"Match : `{request['match_kind']}:{request['match_id']}`"
            ),
        )

        public_channel = await self._get_configured_channel(
            str(request["guild_id"]),
            "public_results_channel_id",
        )
        if public_channel is not None:
            try:
                await public_channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

        player_ids = {
            str(context.get("player1_id") or ""),
            str(context.get("player2_id") or ""),
        }
        await asyncio.gather(
            *(self._safe_dm(player_id, embed=embed) for player_id in player_ids if player_id)
        )

        if request["match_kind"] == MATCH_KIND_BRACKET and winner_id:
            next_match = await self.db.get_next_match_for_player(
                tournament_id=int(request["tournament_id"]),
                discord_id=str(winner_id),
            )
            if next_match is not None and int(next_match.id) != int(request["match_id"]):
                opponent_name = (
                    next_match.player2_name
                    if str(next_match.player1_id) == str(winner_id)
                    else next_match.player1_name
                )
                next_embed = info_embed(
                    title="🎯 Prochain match disponible",
                    description=(
                        f"Ton prochain adversaire est **{opponent_name or 'à déterminer'}**.\n"
                        f"Match ID : `{next_match.id}`"
                    ),
                )
                await self._safe_dm(winner_id, embed=next_embed)

    # ==========================================================
    # LITIGES ET FILS DE DISCUSSION
    # ==========================================================

    async def _create_dispute_thread(
        self,
        request: dict[str, Any],
        reason: str,
    ) -> int | None:
        public_channel = await self._get_configured_channel(
            str(request["guild_id"]),
            "public_results_channel_id",
        )
        validation_channel = await self._get_channel(request.get("validation_channel_id"))

        parent = public_channel or validation_channel
        if parent is None or not hasattr(parent, "send"):
            return None

        content = (
            f"⚠️ Litige du match `{request['match_kind']}:{request['match_id']}`\n"
            f"Joueurs : <@{request['reporter_id']}> <@{request['opponent_id']}>\n"
            f"Motif : {reason}"
        )

        try:
            starter = await parent.send(content)
            thread = await starter.create_thread(
                name=f"litige-{request['match_kind']}-{request['match_id']}",
                auto_archive_duration=1440,
            )
        except (AttributeError, discord.Forbidden, discord.HTTPException):
            return None

        for user_id in {request.get("reporter_id"), request.get("opponent_id")}:
            if not user_id:
                continue
            try:
                member = thread.guild.get_member(int(user_id))
                if member is not None:
                    await thread.add_user(member)
            except (ValueError, discord.Forbidden, discord.HTTPException):
                continue

        await thread.send(
            "Le staff examinera les preuves et décidera du résultat. "
            "Merci de rester factuels et respectueux."
        )
        return thread.id

    async def _close_dispute_thread(self, request: dict[str, Any]) -> None:
        thread_id = request.get("dispute_thread_id")
        if not thread_id:
            return
        thread = self.bot.get_channel(int(thread_id))
        if not isinstance(thread, discord.Thread):
            return
        try:
            await thread.edit(archived=True, locked=True)
        except (discord.Forbidden, discord.HTTPException):
            return

    # ==========================================================
    # CONFIRMATION, CONTESTATION ET CORRECTION
    # ==========================================================

    async def _confirm_request(
        self,
        *,
        match_kind: str,
        match_id: int,
        actor: discord.abc.User,
    ) -> bool:
        async with self._lock_for(match_kind, match_id):
            request = await self._get_request(match_kind, match_id)
            if request is None:
                raise ValueError("Résultat introuvable.")

            if str(actor.id) != str(request.get("opponent_id")):
                raise ValueError("Seul l’adversaire concerné peut confirmer ce résultat.")

            if request["status"] != "pending":
                raise ValueError("Ce résultat a déjà été confirmé, contesté ou traité.")

            changed = await self.db.update(
                """
                UPDATE result_requests
                SET status = 'confirmed',
                    confirmed_by = ?,
                    confirmed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE match_kind = ? AND match_id = ? AND status = 'pending'
                """,
                (str(actor.id), match_kind, match_id),
            )
            if changed != 1:
                raise ValueError("Ce résultat vient déjà d’être traité.")

            request = await self._get_request(match_kind, match_id)
            assert request is not None

            await self._disable_confirmation_message(request)
            await self._refresh_validation_message(request)
            await self._audit(
                guild_id=str(request["guild_id"]),
                match_kind=match_kind,
                match_id=match_id,
                action="opponent_confirmed",
                actor_id=str(actor.id),
            )

            settings = await self._get_settings(str(request["guild_id"]))
            auto_approve = int(settings.get("auto_approve_confirmed") or 0) == 1

        if auto_approve:
            await self._approve_request(
                match_kind=match_kind,
                match_id=match_id,
                actor=actor,
                notes="Validation automatique après confirmation des deux joueurs.",
                automatic=True,
            )
            return True

        return False

    async def _contest_request(
        self,
        *,
        match_kind: str,
        match_id: int,
        actor: discord.abc.User,
        reason: str,
    ) -> None:
        async with self._lock_for(match_kind, match_id):
            request = await self._get_request(match_kind, match_id)
            if request is None:
                raise ValueError("Résultat introuvable.")

            if str(actor.id) != str(request.get("opponent_id")):
                raise ValueError("Seul l’adversaire concerné peut contester ce résultat.")

            if request["status"] not in {"pending", "confirmed"}:
                raise ValueError("Ce résultat a déjà été traité ou contesté.")

            await self.db.update(
                """
                UPDATE result_requests
                SET status = 'contested',
                    contested_by = ?,
                    contest_reason = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE match_kind = ? AND match_id = ?
                """,
                (str(actor.id), reason, match_kind, match_id),
            )
            request = await self._get_request(match_kind, match_id)
            assert request is not None

            thread_id = await self._create_dispute_thread(request, reason)
            if thread_id:
                await self.db.update(
                    """
                    UPDATE result_requests
                    SET dispute_thread_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE match_kind = ? AND match_id = ?
                    """,
                    (str(thread_id), match_kind, match_id),
                )
                request = await self._get_request(match_kind, match_id)
                assert request is not None

            await self._disable_confirmation_message(request)
            await self._refresh_validation_message(request)
            await self._audit(
                guild_id=str(request["guild_id"]),
                match_kind=match_kind,
                match_id=match_id,
                action="opponent_contested",
                actor_id=str(actor.id),
                details={"reason": reason, "thread_id": thread_id},
            )

    async def _edit_request(
        self,
        *,
        match_kind: str,
        match_id: int,
        actor: discord.abc.User,
        player1_score: int,
        player2_score: int,
        result_type: str,
        winner_slot: str,
        notes: str,
    ) -> None:
        if winner_slot == "none":
            normalized_winner: str | None = None
        else:
            normalized_winner = winner_slot

        # Pour une décision spéciale suisse, un score laissé à 0-0 est
        # automatiquement converti en 1-0 ou 0-1 selon le vainqueur.
        if (
            match_kind == MATCH_KIND_SWISS
            and result_type != RESULT_TYPE_DOUBLE_LOSS
            and player1_score == player2_score
        ):
            if normalized_winner == "player1":
                player1_score, player2_score = 1, 0
            elif normalized_winner == "player2":
                player1_score, player2_score = 0, 1

        self._validate_result_data(
            match_kind=match_kind,
            result_type=result_type,
            player1_score=player1_score,
            player2_score=player2_score,
            winner_slot=normalized_winner,
        )

        async with self._lock_for(match_kind, match_id):
            request = await self._get_request(match_kind, match_id)
            if request is None:
                raise ValueError("Résultat introuvable.")
            if request["status"] not in {"pending", "confirmed", "contested"}:
                raise ValueError("Ce résultat a déjà été traité.")

            # Les anciens boutons de confirmation et l’ancien fil de litige
            # ne doivent plus pouvoir agir sur une version corrigée du résultat.
            await self._disable_confirmation_message(request)
            await self._close_dispute_thread(request)

            context = await self._load_match_context(match_kind, match_id)
            winner_id = None
            winner_name = None
            if normalized_winner == "player1":
                winner_id = context["player1_id"]
                winner_name = context["player1_name"]
            elif normalized_winner == "player2":
                winner_id = context["player2_id"]
                winner_name = context["player2_name"]

            await self.db.update(
                """
                UPDATE result_requests
                SET result_type = ?,
                    winner_slot = ?,
                    player1_score = ?,
                    player2_score = ?,
                    status = 'pending',
                    confirmed_by = NULL,
                    confirmed_at = NULL,
                    contested_by = NULL,
                    contest_reason = NULL,
                    confirmation_channel_id = NULL,
                    confirmation_message_id = NULL,
                    dispute_thread_id = NULL,
                    decision_by = ?,
                    decision_notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE match_kind = ? AND match_id = ?
                """,
                (
                    result_type,
                    normalized_winner,
                    player1_score,
                    player2_score,
                    str(actor.id),
                    notes,
                    match_kind,
                    match_id,
                ),
            )

            if match_kind == MATCH_KIND_BRACKET:
                score_text = f"{player1_score}-{player2_score}"
                await self.db.update(
                    """
                    UPDATE matches
                    SET player1_score = ?,
                        player2_score = ?,
                        winner_id = ?,
                        winner_name = ?,
                        score = ?,
                        status = 'reported',
                        notes = ?
                    WHERE id = ?
                    """,
                    (
                        player1_score,
                        player2_score,
                        winner_id,
                        winner_name,
                        score_text,
                        notes,
                        match_id,
                    ),
                )

            request = await self._get_request(match_kind, match_id)
            assert request is not None
            await self._refresh_validation_message(request)
            await self._send_opponent_confirmation(request)
            await self._audit(
                guild_id=str(request["guild_id"]),
                match_kind=match_kind,
                match_id=match_id,
                action="staff_edited",
                actor_id=str(actor.id),
                details={
                    "result_type": result_type,
                    "winner_slot": normalized_winner,
                    "score": f"{player1_score}-{player2_score}",
                    "notes": notes,
                },
            )

    # ==========================================================
    # APPROBATION ET REFUS
    # ==========================================================

    async def _apply_bracket_request(
        self,
        request: dict[str, Any],
        context: dict[str, Any],
        *,
        actor_id: str,
        notes: str,
    ) -> Any:
        result_type = str(request["result_type"])
        winner_id, winner_name = self._winner_from_request(request, context)

        if result_type == RESULT_TYPE_DOUBLE_LOSS:
            raise ValueError("Le Double Loss ne peut pas être appliqué à un bracket.")

        if winner_id is None or winner_name is None:
            raise ValueError("Aucun vainqueur valide n’est défini.")

        if result_type == RESULT_TYPE_NORMAL:
            match = await self.brackets.approve_result(
                match_id=int(request["match_id"]),
                validated_by=actor_id,
                guild_id=str(request["guild_id"]),
                notes=notes,
            )
        else:
            match = await self.brackets.admin_win(
                match_id=int(request["match_id"]),
                winner_id=str(winner_id),
                winner_name=str(winner_name),
                validated_by=actor_id,
                guild_id=str(request["guild_id"]),
                notes=(
                    f"{RESULT_TYPE_LABELS.get(result_type, result_type)} — {notes}"
                ),
            )

        await self._record_match_history(
            guild_id=str(request["guild_id"]),
            match=match,
            status="approved",
        )
        await self.brackets.sync_current_round(int(request["tournament_id"]))
        await self.brackets.get_winner(int(request["tournament_id"]))
        return match

    async def _apply_swiss_request(
        self,
        request: dict[str, Any],
        context: dict[str, Any],
        *,
        actor_id: str,
    ) -> Any:
        result_type = str(request["result_type"])

        if result_type == RESULT_TYPE_DOUBLE_LOSS:
            await self.db.report_swiss_double_loss(
                match_id=int(request["match_id"]),
                reported_by=actor_id,
            )
        else:
            winner_id, winner_name = self._winner_from_request(request, context)
            if winner_id is None or winner_name is None:
                raise ValueError("Aucun vainqueur valide n’est défini.")

            await self.db.report_swiss_result(
                match_id=int(request["match_id"]),
                winner_id=str(winner_id),
                winner_name=str(winner_name),
                player1_score=int(request["player1_score"]),
                player2_score=int(request["player2_score"]),
                is_draw=False,
                reported_by=actor_id,
            )

        match = await self.db.get_swiss_match(int(request["match_id"]))
        if match is None:
            raise RuntimeError("Le match suisse validé est introuvable.")
        return match

    async def _approve_request(
        self,
        *,
        match_kind: str,
        match_id: int,
        actor: discord.abc.User,
        notes: str,
        automatic: bool = False,
    ) -> dict[str, Any]:
        async with self._lock_for(match_kind, match_id):
            request = await self._get_request(match_kind, match_id)
            if request is None:
                raise ValueError("Résultat introuvable.")

            if request["status"] not in {"pending", "confirmed", "contested"}:
                raise ValueError("Ce résultat a déjà été traité.")

            changed = await self.db.update(
                """
                UPDATE result_requests
                SET status = 'processing',
                    decision_by = ?,
                    decision_notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE match_kind = ? AND match_id = ?
                  AND status IN ('pending', 'confirmed', 'contested')
                """,
                (str(actor.id), notes, match_kind, match_id),
            )
            if changed != 1:
                raise ValueError("Un autre membre du staff traite déjà ce résultat.")

            request = await self._get_request(match_kind, match_id)
            assert request is not None
            context = await self._load_match_context(match_kind, match_id)

            try:
                if match_kind == MATCH_KIND_BRACKET:
                    await self._apply_bracket_request(
                        request,
                        context,
                        actor_id=str(actor.id),
                        notes=notes,
                    )
                else:
                    await self._apply_swiss_request(
                        request,
                        context,
                        actor_id=str(actor.id),
                    )
            except Exception:
                await self.db.update(
                    """
                    UPDATE result_requests
                    SET status = 'pending', updated_at = CURRENT_TIMESTAMP
                    WHERE match_kind = ? AND match_id = ? AND status = 'processing'
                    """,
                    (match_kind, match_id),
                )
                raise

            await self.db.update(
                """
                UPDATE result_requests
                SET status = 'approved',
                    decision_by = ?,
                    decision_notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE match_kind = ? AND match_id = ?
                """,
                (str(actor.id), notes, match_kind, match_id),
            )
            request = await self._get_request(match_kind, match_id)
            assert request is not None

            await self._refresh_validation_message(request, disabled=True)
            await self._disable_confirmation_message(request)
            await self._close_dispute_thread(request)
            await self._audit(
                guild_id=str(request["guild_id"]),
                match_kind=match_kind,
                match_id=match_id,
                action="auto_approved" if automatic else "staff_approved",
                actor_id=str(actor.id),
                details={
                    "type": request["result_type"],
                    "score": f"{request['player1_score']}-{request['player2_score']}",
                    "notes": notes,
                },
            )

        await self._notify_result_approved(request, context)

        # Progression immédiate : publication du prochain match de bracket
        # ou proposition/génération de la ronde suisse suivante.
        progression = self.bot.get_cog("TournamentProgressionCog")
        if progression is not None:
            try:
                await progression.handle_result_approved(
                    guild_id=str(request["guild_id"]),
                    tournament_id=int(request["tournament_id"]),
                    match_kind=str(request["match_kind"]),
                    match_id=int(request["match_id"]),
                )
            except Exception as error:
                # Le résultat reste validé même si Discord ne peut pas publier
                # immédiatement le prochain affrontement. Le scan automatique
                # du cog de progression réessaiera ensuite.
                print(
                    "⚠️ Progression automatique après validation "
                    f"{request['match_kind']}:{request['match_id']} : {error}"
                )

        return request

    async def _reject_request(
        self,
        *,
        match_kind: str,
        match_id: int,
        actor: discord.abc.User,
        reason: str,
    ) -> dict[str, Any]:
        if len(reason.strip()) < 3:
            raise ValueError("Le motif du refus est obligatoire.")

        async with self._lock_for(match_kind, match_id):
            request = await self._get_request(match_kind, match_id)
            if request is None:
                raise ValueError("Résultat introuvable.")
            if request["status"] not in {"pending", "confirmed", "contested"}:
                raise ValueError("Ce résultat a déjà été traité.")

            if match_kind == MATCH_KIND_BRACKET:
                await self.brackets.reject_result(
                    match_id=match_id,
                    validated_by=str(actor.id),
                    notes=reason,
                )

            await self.db.update(
                """
                UPDATE result_requests
                SET status = 'rejected',
                    decision_by = ?,
                    decision_notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE match_kind = ? AND match_id = ?
                """,
                (str(actor.id), reason, match_kind, match_id),
            )
            request = await self._get_request(match_kind, match_id)
            assert request is not None

            await self._refresh_validation_message(request, disabled=True)
            await self._disable_confirmation_message(request)
            await self._close_dispute_thread(request)
            await self._audit(
                guild_id=str(request["guild_id"]),
                match_kind=match_kind,
                match_id=match_id,
                action="staff_rejected",
                actor_id=str(actor.id),
                details={"reason": reason},
            )

        await self._notify_players_rejected(request, reason)
        return request

    # ==========================================================
    # RAPPELS AUTOMATIQUES
    # ==========================================================

    @tasks.loop(minutes=5)
    async def result_reminders(self) -> None:
        try:
            rows = await self.db.fetchall(
                """
                SELECT *
                FROM result_requests
                WHERE status IN ('pending', 'confirmed', 'contested')
                ORDER BY created_at ASC
                """
            )
        except Exception as error:
            print(f"⚠️ Vérification des rappels de résultats impossible : {error}")
            return

        now = discord.utils.utcnow()

        for raw_row in rows:
            request = dict(raw_row)
            settings = await self._get_settings(str(request["guild_id"]))
            reminder_minutes = max(5, int(settings.get("reminder_minutes") or 30))

            created_at = _parse_database_datetime(request.get("created_at"))
            last_reminded = _parse_database_datetime(request.get("last_reminded_at"))
            if created_at is None:
                continue

            age_minutes = (now - created_at).total_seconds() / 60
            since_last = (
                (now - last_reminded).total_seconds() / 60
                if last_reminded
                else None
            )

            if age_minutes < reminder_minutes:
                continue
            if since_last is not None and since_last < reminder_minutes:
                continue

            channel = await self._get_configured_channel(
                str(request["guild_id"]),
                "validation_channel_id",
            )
            if channel is None:
                continue

            staff_role_id = settings.get("staff_role_id")
            ping = f"<@&{staff_role_id}> " if staff_role_id else ""
            urgency = "🚨" if age_minutes >= reminder_minutes * 2 else "⚠️"
            jump_url = self._request_jump_url(request)
            link_text = f"\n[Ouvrir le résultat]({jump_url})" if jump_url else ""

            try:
                await channel.send(
                    f"{ping}{urgency} Le résultat `{request['match_kind']}:{request['match_id']}` "
                    f"attend depuis environ **{int(age_minutes)} minutes**.{link_text}",
                    allowed_mentions=discord.AllowedMentions(roles=True),
                )
            except (discord.Forbidden, discord.HTTPException):
                continue

            await self.db.update(
                """
                UPDATE result_requests
                SET last_reminded_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE match_kind = ? AND match_id = ?
                """,
                (request["match_kind"], request["match_id"]),
            )

    @result_reminders.before_loop
    async def before_result_reminders(self) -> None:
        await self.bot.wait_until_ready()

    # ==========================================================
    # COMMANDES JOUEURS
    # ==========================================================

    @app_commands.command(
        name="result",
        description="Déclarer le résultat de ton match",
    )
    @app_commands.describe(
        player1_score="Score du joueur 1",
        player2_score="Score du joueur 2",
        match_id="ID facultatif du match",
        type_match="Bracket, rondes suisses ou détection automatique",
        preuve="Capture d’écran ou PDF facultatif",
    )
    @app_commands.choices(
        type_match=[
            app_commands.Choice(name="Détection automatique", value=MATCH_KIND_AUTO),
            app_commands.Choice(name="Bracket", value=MATCH_KIND_BRACKET),
            app_commands.Choice(name="Rondes suisses", value=MATCH_KIND_SWISS),
        ]
    )
    async def result(
        self,
        interaction: discord.Interaction,
        player1_score: app_commands.Range[int, 0, 99],
        player2_score: app_commands.Range[int, 0, 99],
        match_id: int | None = None,
        type_match: str = MATCH_KIND_AUTO,
        preuve: discord.Attachment | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            tournament = await self._resolve_tournament(interaction)
            if tournament is None:
                raise ValueError("Aucun tournoi sélectionné.")

            match_kind, match = await self._resolve_match(
                tournament_id=int(tournament.id),
                user_id=str(interaction.user.id),
                match_id=match_id,
                requested_kind=type_match,
                require_player=True,
            )
            context = self._match_context(match_kind, match)

            if context["is_bye"]:
                raise ValueError("Un BYE ne nécessite aucune déclaration.")
            if not context.get("player1_id") or not context.get("player2_id"):
                raise ValueError("Ce match n’est pas encore jouable.")
            if player1_score == player2_score:
                raise ValueError(
                    "Les matchs nuls n’existent pas. Le Double Loss doit être décidé par le staff."
                )

            winner_slot = "player1" if player1_score > player2_score else "player2"
            proof_url, proof_is_image = self._proof_data(preuve)

            self._validate_result_data(
                match_kind=match_kind,
                result_type=RESULT_TYPE_NORMAL,
                player1_score=player1_score,
                player2_score=player2_score,
                winner_slot=winner_slot,
            )

            async with self._lock_for(match_kind, int(context["match_id"])):
                existing = await self._get_request(match_kind, int(context["match_id"]))
                if existing and existing["status"] in OPEN_REQUEST_STATUSES:
                    raise ValueError("Ce match possède déjà un résultat en attente.")

                if match_kind == MATCH_KIND_BRACKET:
                    reported = await self.brackets.report_result(
                        match_id=int(context["match_id"]),
                        player1_score=int(player1_score),
                        player2_score=int(player2_score),
                        reported_by=str(interaction.user.id),
                    )
                    context = self._match_context(match_kind, reported)

                request = await self._create_request(
                    match_kind=match_kind,
                    context=context,
                    guild_id=self._guild_id(interaction),
                    reporter_id=str(interaction.user.id),
                    result_type=RESULT_TYPE_NORMAL,
                    winner_slot=winner_slot,
                    player1_score=int(player1_score),
                    player2_score=int(player2_score),
                    proof_url=proof_url,
                    proof_is_image=proof_is_image,
                )

            sent_staff = await self._send_validation_message(request)
            request = await self._get_request(match_kind, int(context["match_id"])) or request
            sent_opponent = await self._send_opponent_confirmation(request)

            await self._audit(
                guild_id=str(request["guild_id"]),
                match_kind=match_kind,
                match_id=int(request["match_id"]),
                action="player_reported",
                actor_id=str(interaction.user.id),
                details={
                    "score": f"{player1_score}-{player2_score}",
                    "proof": bool(proof_url),
                    "staff_message_sent": sent_staff,
                    "opponent_message_sent": sent_opponent,
                },
            )

        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Résultat impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return

        delivery_lines = []
        delivery_lines.append(
            "✅ Envoyé dans `validation-résultats`."
            if sent_staff
            else "⚠️ Salon `validation-résultats` non configuré ou inaccessible."
        )
        delivery_lines.append(
            "✅ L’adversaire a reçu une demande de confirmation."
            if sent_opponent
            else "⚠️ Impossible de contacter l’adversaire automatiquement."
        )

        embed = success_embed(
            title="Résultat déclaré",
            description=(
                "Le résultat est enregistré et protégé contre les doubles déclarations.\n\n"
                + "\n".join(delivery_lines)
            ),
        )
        embed.add_field(
            name="Match",
            value=f"`{match_kind}:{request['match_id']}`",
            inline=True,
        )
        embed.add_field(
            name="Score",
            value=f"`{player1_score}-{player2_score}`",
            inline=True,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ==========================================================
    # COMMANDES STAFF
    # ==========================================================

    @app_commands.command(
        name="result_setup",
        description="Configurer les salons et options du système de résultats",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        validation_channel="Salon privé de validation",
        results_channel="Salon public des résultats et litiges",
        logs_channel="Salon des logs Hamtaro",
        staff_role="Rôle autorisé à traiter les résultats",
        auto_approve_confirmed="Valider automatiquement si l’adversaire confirme",
        reminder_minutes="Délai avant les rappels staff",
    )
    async def result_setup(
        self,
        interaction: discord.Interaction,
        validation_channel: discord.TextChannel | None = None,
        results_channel: discord.TextChannel | None = None,
        logs_channel: discord.TextChannel | None = None,
        staff_role: discord.Role | None = None,
        auto_approve_confirmed: bool | None = None,
        reminder_minutes: app_commands.Range[int, 5, 1440] | None = None,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        guild_id = self._guild_id(interaction)
        current = await self._get_settings(guild_id)

        new_values = {
            "validation_channel_id": (
                str(validation_channel.id)
                if validation_channel is not None
                else current.get("validation_channel_id")
            ),
            "public_results_channel_id": (
                str(results_channel.id)
                if results_channel is not None
                else current.get("public_results_channel_id")
            ),
            "logs_channel_id": (
                str(logs_channel.id)
                if logs_channel is not None
                else current.get("logs_channel_id")
            ),
            "staff_role_id": (
                str(staff_role.id)
                if staff_role is not None
                else current.get("staff_role_id")
            ),
            "auto_approve_confirmed": (
                int(auto_approve_confirmed)
                if auto_approve_confirmed is not None
                else int(current.get("auto_approve_confirmed") or 0)
            ),
            "reminder_minutes": (
                int(reminder_minutes)
                if reminder_minutes is not None
                else int(current.get("reminder_minutes") or 30)
            ),
        }

        await self.db.execute(
            """
            INSERT INTO result_settings (
                guild_id,
                validation_channel_id,
                public_results_channel_id,
                logs_channel_id,
                staff_role_id,
                auto_approve_confirmed,
                reminder_minutes,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                validation_channel_id = excluded.validation_channel_id,
                public_results_channel_id = excluded.public_results_channel_id,
                logs_channel_id = excluded.logs_channel_id,
                staff_role_id = excluded.staff_role_id,
                auto_approve_confirmed = excluded.auto_approve_confirmed,
                reminder_minutes = excluded.reminder_minutes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                guild_id,
                new_values["validation_channel_id"],
                new_values["public_results_channel_id"],
                new_values["logs_channel_id"],
                new_values["staff_role_id"],
                new_values["auto_approve_confirmed"],
                new_values["reminder_minutes"],
            ),
        )
        await self.db.commit()

        embed = success_embed(
            title="Configuration des résultats",
            description="La configuration de ce serveur est enregistrée.",
        )
        embed.add_field(
            name="✅ Validation",
            value=(
                f"<#{new_values['validation_channel_id']}>"
                if new_values["validation_channel_id"]
                else "Non configuré"
            ),
            inline=True,
        )
        embed.add_field(
            name="📢 Résultats publics",
            value=(
                f"<#{new_values['public_results_channel_id']}>"
                if new_values["public_results_channel_id"]
                else "Non configuré"
            ),
            inline=True,
        )
        embed.add_field(
            name="📋 Logs",
            value=(
                f"<#{new_values['logs_channel_id']}>"
                if new_values["logs_channel_id"]
                else "Non configuré"
            ),
            inline=True,
        )
        embed.add_field(
            name="👥 Rôle staff",
            value=(
                f"<@&{new_values['staff_role_id']}>"
                if new_values["staff_role_id"]
                else "Permissions Discord / configuration existante"
            ),
            inline=True,
        )
        embed.add_field(
            name="🤝 Confirmation automatique",
            value="Activée" if new_values["auto_approve_confirmed"] else "Désactivée",
            inline=True,
        )
        embed.add_field(
            name="⏰ Rappel",
            value=f"Après {new_values['reminder_minutes']} minutes",
            inline=True,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="special_result",
        description="Préparer une décision spéciale pour validation staff",
    )
    @app_commands.describe(
        match_id="ID du match",
        type_match="Bracket ou rondes suisses",
        type_resultat="Victoire administrative, Double Loss, abandon ou disqualification",
        gagnant="Gagnant, sauf pour un Double Loss",
        player1_score="Score du joueur 1",
        player2_score="Score du joueur 2",
        preuve="Preuve facultative",
    )
    @app_commands.choices(
        type_match=[
            app_commands.Choice(name="Bracket", value=MATCH_KIND_BRACKET),
            app_commands.Choice(name="Rondes suisses", value=MATCH_KIND_SWISS),
        ],
        type_resultat=[
            app_commands.Choice(name="Victoire administrative", value=RESULT_TYPE_ADMIN),
            app_commands.Choice(name="Double Loss", value=RESULT_TYPE_DOUBLE_LOSS),
            app_commands.Choice(name="Abandon", value=RESULT_TYPE_ABANDON),
            app_commands.Choice(name="Disqualification", value=RESULT_TYPE_DISQUALIFICATION),
        ],
    )
    async def special_result(
        self,
        interaction: discord.Interaction,
        match_id: int,
        type_match: str,
        type_resultat: str,
        gagnant: discord.Member | None = None,
        player1_score: app_commands.Range[int, 0, 99] = 0,
        player2_score: app_commands.Range[int, 0, 99] = 0,
        preuve: discord.Attachment | None = None,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        try:
            tournament = await self._resolve_tournament(interaction)
            match_kind, match = await self._resolve_match(
                tournament_id=int(tournament.id),
                user_id=str(interaction.user.id),
                match_id=match_id,
                requested_kind=type_match,
                require_player=False,
            )
            context = self._match_context(match_kind, match)

            if type_resultat == RESULT_TYPE_DOUBLE_LOSS:
                winner_slot = None
            else:
                if gagnant is None:
                    raise ValueError("Un gagnant est obligatoire pour cette décision.")
                if str(gagnant.id) == str(context.get("player1_id")):
                    winner_slot = "player1"
                elif str(gagnant.id) == str(context.get("player2_id")):
                    winner_slot = "player2"
                else:
                    raise ValueError("Le gagnant doit participer à ce match.")

            # Les décisions administratives suisses peuvent être saisies
            # sans score explicite : Hamtaro crée alors un score technique 1-0.
            if (
                match_kind == MATCH_KIND_SWISS
                and type_resultat != RESULT_TYPE_DOUBLE_LOSS
                and player1_score == player2_score
            ):
                if winner_slot == "player1":
                    player1_score, player2_score = 1, 0
                elif winner_slot == "player2":
                    player1_score, player2_score = 0, 1

            self._validate_result_data(
                match_kind=match_kind,
                result_type=type_resultat,
                player1_score=int(player1_score),
                player2_score=int(player2_score),
                winner_slot=winner_slot,
            )
            proof_url, proof_is_image = self._proof_data(preuve)

            async with self._lock_for(match_kind, match_id):
                existing = await self._get_request(match_kind, match_id)
                if existing and existing["status"] in OPEN_REQUEST_STATUSES:
                    raise ValueError("Ce match possède déjà une décision en attente.")

                if match_kind == MATCH_KIND_BRACKET:
                    winner_id = (
                        context["player1_id"] if winner_slot == "player1" else context["player2_id"]
                    )
                    winner_name = (
                        context["player1_name"] if winner_slot == "player1" else context["player2_name"]
                    )
                    await self.db.update(
                        """
                        UPDATE matches
                        SET player1_score = ?, player2_score = ?,
                            winner_id = ?, winner_name = ?, score = ?,
                            reported_by = ?, reported_at = CURRENT_TIMESTAMP,
                            status = 'reported'
                        WHERE id = ?
                        """,
                        (
                            int(player1_score),
                            int(player2_score),
                            winner_id,
                            winner_name,
                            f"{player1_score}-{player2_score}",
                            str(interaction.user.id),
                            match_id,
                        ),
                    )

                request = await self._create_request(
                    match_kind=match_kind,
                    context=context,
                    guild_id=self._guild_id(interaction),
                    reporter_id=str(interaction.user.id),
                    result_type=type_resultat,
                    winner_slot=winner_slot,
                    player1_score=int(player1_score),
                    player2_score=int(player2_score),
                    proof_url=proof_url,
                    proof_is_image=proof_is_image,
                )

            sent = await self._send_validation_message(request)
            await self._audit(
                guild_id=str(request["guild_id"]),
                match_kind=match_kind,
                match_id=match_id,
                action="special_result_created",
                actor_id=str(interaction.user.id),
                details={"type": type_resultat, "validation_message_sent": sent},
            )

        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Décision spéciale impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success_embed(
                title="Décision envoyée au staff",
                description=(
                    f"La décision **{RESULT_TYPE_LABELS[type_resultat]}** "
                    f"pour `{match_kind}:{match_id}` attend sa validation."
                ),
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="approve_result",
        description="Valider un résultat reporté",
    )
    @app_commands.describe(
        match_id="ID du match",
        type_match="Bracket ou rondes suisses",
        notes="Note staff facultative",
    )
    @app_commands.choices(
        type_match=[
            app_commands.Choice(name="Bracket", value=MATCH_KIND_BRACKET),
            app_commands.Choice(name="Rondes suisses", value=MATCH_KIND_SWISS),
        ]
    )
    async def approve_result(
        self,
        interaction: discord.Interaction,
        match_id: int,
        type_match: str = MATCH_KIND_BRACKET,
        notes: str | None = None,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        try:
            request = await self._approve_request(
                match_kind=type_match,
                match_id=match_id,
                actor=interaction.user,
                notes=notes or "Validation avec la commande /approve_result.",
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Validation impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success_embed(
                title="Résultat validé",
                description=f"Le match `{request['match_kind']}:{request['match_id']}` est validé.",
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="reject_result",
        description="Refuser un résultat avec un motif obligatoire",
    )
    @app_commands.describe(
        match_id="ID du match",
        raison="Motif obligatoire du refus",
        type_match="Bracket ou rondes suisses",
    )
    @app_commands.choices(
        type_match=[
            app_commands.Choice(name="Bracket", value=MATCH_KIND_BRACKET),
            app_commands.Choice(name="Rondes suisses", value=MATCH_KIND_SWISS),
        ]
    )
    async def reject_result(
        self,
        interaction: discord.Interaction,
        match_id: int,
        raison: str,
        type_match: str = MATCH_KIND_BRACKET,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        try:
            request = await self._reject_request(
                match_kind=type_match,
                match_id=match_id,
                actor=interaction.user,
                reason=raison,
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Refus impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=info_embed(
                title="Résultat refusé",
                description=f"Le match `{request['match_kind']}:{request['match_id']}` est de nouveau déclarable.",
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="pending_results",
        description="Voir et sélectionner les résultats en attente",
    )
    async def pending_results(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        guild_id = self._guild_id(interaction)
        requests = await self._list_open_requests(guild_id)

        if not requests:
            await interaction.followup.send(
                embed=info_embed(
                    title="Résultats en attente",
                    description="Aucun résultat n’attend une décision.",
                ),
                ephemeral=True,
            )
            return

        lines = []
        for request in requests[:15]:
            created_at = _parse_database_datetime(request.get("created_at"))
            age = (
                discord.utils.format_dt(created_at, style="R")
                if created_at
                else "date inconnue"
            )
            lines.append(
                f"{RESULT_STATUS_LABELS.get(request['status'], request['status'])} — "
                f"`{request['match_kind']}:{request['match_id']}` — "
                f"`{request['player1_score']}-{request['player2_score']}` — {age}"
            )

        embed = info_embed(
            title=f"Résultats en attente — {len(requests)}",
            description="\n".join(lines),
        )
        await interaction.followup.send(
            embed=embed,
            view=PendingResultsView(self, requests),
            ephemeral=True,
        )

    @app_commands.command(
        name="admin_win",
        description="Appliquer immédiatement une victoire administrative",
    )
    @app_commands.describe(
        match_id="ID du match de bracket",
        winner="Joueur gagnant",
        notes="Raison obligatoire de la décision",
    )
    async def admin_win(
        self,
        interaction: discord.Interaction,
        match_id: int,
        winner: discord.Member,
        notes: str,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        try:
            guild_id = self._guild_id(interaction)
            completed = await self.brackets.admin_win(
                match_id=match_id,
                winner_id=str(winner.id),
                winner_name=winner.display_name,
                validated_by=str(interaction.user.id),
                guild_id=guild_id,
                notes=notes,
            )
            await self._record_match_history(guild_id, completed, "approved")
            await self.brackets.sync_current_round(completed.tournament_id)
            await self.brackets.get_winner(completed.tournament_id)
            await self._audit(
                guild_id=guild_id,
                match_kind=MATCH_KIND_BRACKET,
                match_id=match_id,
                action="admin_win_immediate",
                actor_id=str(interaction.user.id),
                details={"winner_id": str(winner.id), "reason": notes},
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Victoire administrative impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success_embed(
                title="Victoire administrative validée",
                description=(
                    f"**{winner.display_name}** remporte le match `{match_id}`.\n\n"
                    f"Motif : {notes}"
                ),
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    service = MatchHistoryService()
    await service.init_table()
    await bot.add_cog(ResultsCog(bot))
