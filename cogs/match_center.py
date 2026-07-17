from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.embeds import error_embed, info_embed, success_embed
from utils.permissions import is_staff_member
from utils.tournament_resolver import resolve_tournament


MATCH_KIND_BRACKET = "bracket"
MATCH_KIND_SWISS = "swiss"
MATCH_KINDS = {MATCH_KIND_BRACKET, MATCH_KIND_SWISS}

PANEL_FOOTER = "HAMTARO_MATCH_CENTER:"
ASSISTANCE_FOOTER = "HAMTARO_ASSISTANCE:"
TIMER_EXPIRED_FOOTER = "HAMTARO_TIMER_EXPIRED:"

OPEN_RESULT_STATUSES = {"pending", "confirmed", "contested", "processing"}
FINAL_MATCH_STATUSES = {
    "approved",
    "cancelled",
    "completed",
    "finished",
    "refused",
    "rejected",
    "validated",
}

ASSISTANCE_LABELS = {
    "ruling": "Problème de ruling",
    "score": "Désaccord sur le score",
    "absent": "Adversaire absent",
    "connection": "Problème de connexion",
    "behaviour": "Comportement incorrect",
    "other": "Autre problème",
}

SESSION_LABELS = {
    "waiting": "🕓 En attente de démarrage",
    "running": "▶️ Match en cours",
    "paused": "⏸️ Chronomètre suspendu",
    "expired": "⏰ Temps réglementaire terminé",
    "reported": "📨 Résultat déclaré",
    "completed": "✅ Résultat validé",
    "cancelled": "❌ Match annulé",
}


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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mention(discord_id: Any, fallback: str) -> str:
    if discord_id is None:
        return fallback
    return f"<@{discord_id}>"


def _round_name(match_kind: str, match: dict[str, Any]) -> str:
    if match_kind == MATCH_KIND_SWISS:
        return f"Ronde suisse {match.get('round_number', '?')} — Table {match.get('table_number', '?')}"

    round_number = int(match.get("round") or 0)
    names = {
        1: "Finale",
        2: "Demi-finale",
        3: "Quart de finale",
        4: "Huitième de finale",
        5: "Seizième de finale",
    }
    return names.get(round_number, f"Round {round_number}")


# ==========================================================
# MODALES ET MENUS JOUEURS
# ==========================================================


class QuickResultModal(discord.ui.Modal):
    def __init__(self, cog: "MatchCenterCog", match_kind: str, match_id: int) -> None:
        super().__init__(title=f"Résultat du match #{match_id}")
        self.cog = cog
        self.match_kind = match_kind
        self.match_id = match_id

        self.player1_score = discord.ui.TextInput(
            label="Score du joueur 1",
            placeholder="Ex. : 2",
            required=True,
            max_length=2,
        )
        self.player2_score = discord.ui.TextInput(
            label="Score du joueur 2",
            placeholder="Ex. : 1",
            required=True,
            max_length=2,
        )
        self.add_item(self.player1_score)
        self.add_item(self.player2_score)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            score1 = int(str(self.player1_score.value).strip())
            score2 = int(str(self.player2_score.value).strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Les scores doivent être des nombres entiers.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            sent_staff, sent_opponent = await self.cog.submit_quick_result(
                interaction=interaction,
                match_kind=self.match_kind,
                match_id=self.match_id,
                player1_score=score1,
                player2_score=score2,
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(title="Résultat impossible", description=str(error)),
                ephemeral=True,
            )
            return
        except Exception as error:
            print(f"❌ Résultat rapide {self.match_kind}:{self.match_id} : {error}")
            await interaction.followup.send(
                embed=error_embed(
                    title="Erreur inattendue",
                    description="Le résultat n’a pas pu être transmis.",
                ),
                ephemeral=True,
            )
            return

        details = [
            "✅ Résultat envoyé au staff." if sent_staff else "⚠️ Salon de validation inaccessible.",
            "✅ Confirmation envoyée à l’adversaire."
            if sent_opponent
            else "⚠️ L’adversaire n’a pas pu être contacté automatiquement.",
            "Pour joindre une preuve, utilisez aussi `/result` avec le paramètre `preuve`.",
        ]
        await interaction.followup.send(
            embed=success_embed(
                title="Résultat déclaré",
                description="\n".join(details),
            ),
            ephemeral=True,
        )


class AssistanceDetailsModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "MatchCenterCog",
        match_kind: str,
        match_id: int,
        category: str,
    ) -> None:
        super().__init__(title="Appeler le staff")
        self.cog = cog
        self.match_kind = match_kind
        self.match_id = match_id
        self.category = category

        self.details = discord.ui.TextInput(
            label="Explique brièvement le problème",
            placeholder="Donne les faits utiles pour que le staff puisse intervenir.",
            required=True,
            min_length=3,
            max_length=700,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            request_id = await self.cog.create_assistance_request(
                interaction=interaction,
                match_kind=self.match_kind,
                match_id=self.match_id,
                category=self.category,
                details=str(self.details.value).strip(),
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(title="Appel impossible", description=str(error)),
                ephemeral=True,
            )
            return
        except Exception as error:
            print(f"❌ Appel staff {self.match_kind}:{self.match_id} : {error}")
            await interaction.followup.send(
                embed=error_embed(
                    title="Erreur inattendue",
                    description="Le staff n’a pas pu être contacté.",
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success_embed(
                title="Staff prévenu",
                description=f"Ta demande d’assistance `#{request_id}` a été envoyée.",
            ),
            ephemeral=True,
        )


class AssistanceCategorySelect(discord.ui.Select):
    def __init__(self, cog: "MatchCenterCog", match_kind: str, match_id: int) -> None:
        self.cog = cog
        self.match_kind = match_kind
        self.match_id = match_id
        options = [
            discord.SelectOption(label=label, value=value, emoji=emoji)
            for value, label, emoji in (
                ("ruling", ASSISTANCE_LABELS["ruling"], "⚖️"),
                ("score", ASSISTANCE_LABELS["score"], "📊"),
                ("absent", ASSISTANCE_LABELS["absent"], "👻"),
                ("connection", ASSISTANCE_LABELS["connection"], "📡"),
                ("behaviour", ASSISTANCE_LABELS["behaviour"], "🚨"),
                ("other", ASSISTANCE_LABELS["other"], "❓"),
            )
        ]
        super().__init__(
            placeholder="Choisir le motif de l’appel",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            AssistanceDetailsModal(
                self.cog,
                self.match_kind,
                self.match_id,
                self.values[0],
            )
        )


class AssistanceCategoryView(discord.ui.View):
    def __init__(self, cog: "MatchCenterCog", match_kind: str, match_id: int) -> None:
        super().__init__(timeout=120)
        self.add_item(AssistanceCategorySelect(cog, match_kind, match_id))


# ==========================================================
# MODALES ET VUES STAFF
# ==========================================================


class ResolveAssistanceModal(discord.ui.Modal):
    def __init__(self, cog: "MatchCenterCog", request_id: int) -> None:
        super().__init__(title=f"Résoudre la demande #{request_id}")
        self.cog = cog
        self.request_id = request_id
        self.note = discord.ui.TextInput(
            label="Résolution",
            placeholder="Ex. : ruling expliqué aux deux joueurs.",
            required=True,
            min_length=3,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.cog.ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await self.cog.resolve_assistance(
                request_id=self.request_id,
                actor=interaction.user,
                resolution=str(self.note.value).strip(),
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(title="Résolution impossible", description=str(error)),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=success_embed(
                title="Demande résolue",
                description=f"La demande `#{self.request_id}` est maintenant fermée.",
            ),
            ephemeral=True,
        )


class AdministrativeWinModal(discord.ui.Modal):
    def __init__(self, cog: "MatchCenterCog", match_kind: str, match_id: int) -> None:
        super().__init__(title=f"Victoire administrative #{match_id}")
        self.cog = cog
        self.match_kind = match_kind
        self.match_id = match_id

        self.winner_slot = discord.ui.TextInput(
            label="Gagnant",
            placeholder="Écrire player1 ou player2",
            required=True,
            max_length=7,
        )
        self.reason = discord.ui.TextInput(
            label="Motif",
            placeholder="Ex. : adversaire absent après le délai réglementaire.",
            required=True,
            min_length=3,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.winner_slot)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.cog.ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await self.cog.create_special_result_request(
                match_kind=self.match_kind,
                match_id=self.match_id,
                actor=interaction.user,
                result_type="admin_win",
                winner_slot=str(self.winner_slot.value).strip().lower(),
                reason=str(self.reason.value).strip(),
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(title="Décision impossible", description=str(error)),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=success_embed(
                title="Décision préparée",
                description="La victoire administrative attend maintenant la validation staff.",
            ),
            ephemeral=True,
        )


class StaffAssistanceView(discord.ui.View):
    def __init__(self, cog: "MatchCenterCog", *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        if disabled:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

    @discord.ui.button(
        label="Prendre en charge",
        emoji="👀",
        style=discord.ButtonStyle.primary,
        custom_id="hamtaro:match:assistance:claim",
    )
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.ensure_staff(interaction):
            return
        request_id = self.cog.extract_assistance_reference(interaction.message)
        if request_id is None:
            await interaction.response.send_message("❌ Demande introuvable.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await self.cog.claim_assistance(request_id, interaction.user)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Demande `#{request_id}` prise en charge.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Marquer résolu",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="hamtaro:match:assistance:resolve",
    )
    async def resolve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.ensure_staff(interaction):
            return
        request_id = self.cog.extract_assistance_reference(interaction.message)
        if request_id is None:
            await interaction.response.send_message("❌ Demande introuvable.", ephemeral=True)
            return
        await interaction.response.send_modal(ResolveAssistanceModal(self.cog, request_id))


class TimerExpiredView(discord.ui.View):
    def __init__(self, cog: "MatchCenterCog", *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        if disabled:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.cog.ensure_staff(interaction)

    @discord.ui.button(
        label="Ajouter 5 minutes",
        emoji="➕",
        style=discord.ButtonStyle.primary,
        custom_id="hamtaro:match:timer:add5",
    )
    async def add_five(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        reference = self.cog.extract_timer_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message("❌ Match introuvable.", ephemeral=True)
            return
        kind, match_id = reference
        await interaction.response.defer(ephemeral=True)
        await self.cog.add_timer_seconds(kind, match_id, 300, interaction.user)
        await interaction.followup.send("✅ Cinq minutes ajoutées.", ephemeral=True)

    @discord.ui.button(
        label="Victoire administrative",
        emoji="🏆",
        style=discord.ButtonStyle.success,
        custom_id="hamtaro:match:timer:adminwin",
    )
    async def admin_win(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        reference = self.cog.extract_timer_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message("❌ Match introuvable.", ephemeral=True)
            return
        kind, match_id = reference
        await interaction.response.send_modal(AdministrativeWinModal(self.cog, kind, match_id))

    @discord.ui.button(
        label="Double Loss",
        emoji="⚠️",
        style=discord.ButtonStyle.danger,
        custom_id="hamtaro:match:timer:doubleloss",
    )
    async def double_loss(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        reference = self.cog.extract_timer_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message("❌ Match introuvable.", ephemeral=True)
            return
        kind, match_id = reference
        if kind != MATCH_KIND_SWISS:
            await interaction.response.send_message(
                "❌ Le Double Loss est réservé aux rondes suisses.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await self.cog.create_special_result_request(
                match_kind=kind,
                match_id=match_id,
                actor=interaction.user,
                result_type="double_loss",
                winner_slot=None,
                reason="Temps réglementaire dépassé : Double Loss proposé par le staff.",
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        await interaction.followup.send(
            "✅ Le Double Loss a été envoyé dans le salon de validation.",
            ephemeral=True,
        )


# ==========================================================
# PANNEAU PERSISTANT DU MATCH
# ==========================================================


class MatchPanelView(discord.ui.View):
    def __init__(self, cog: "MatchCenterCog", *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        if disabled:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

    @discord.ui.button(
        label="Commencer le match",
        emoji="▶️",
        style=discord.ButtonStyle.success,
        custom_id="hamtaro:match:start",
    )
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        reference = self.cog.extract_panel_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message("❌ Match introuvable.", ephemeral=True)
            return
        kind, match_id = reference
        await interaction.response.defer(ephemeral=True)
        try:
            message = await self.cog.start_match(kind, match_id, interaction.user)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(
        label="Déclarer le résultat",
        emoji="📊",
        style=discord.ButtonStyle.primary,
        custom_id="hamtaro:match:result",
    )
    async def result(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        reference = self.cog.extract_panel_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message("❌ Match introuvable.", ephemeral=True)
            return
        kind, match_id = reference
        if not await self.cog.ensure_participant_or_staff(interaction, kind, match_id):
            return
        await interaction.response.send_modal(QuickResultModal(self.cog, kind, match_id))

    @discord.ui.button(
        label="Appeler le staff",
        emoji="🆘",
        style=discord.ButtonStyle.danger,
        custom_id="hamtaro:match:staff",
    )
    async def staff(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        reference = self.cog.extract_panel_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message("❌ Match introuvable.", ephemeral=True)
            return
        kind, match_id = reference
        if not await self.cog.ensure_participant_or_staff(interaction, kind, match_id):
            return
        await interaction.response.send_message(
            "Choisis la raison de l’appel :",
            view=AssistanceCategoryView(self.cog, kind, match_id),
            ephemeral=True,
        )

    @discord.ui.button(
        label="État du match",
        emoji="ℹ️",
        style=discord.ButtonStyle.secondary,
        custom_id="hamtaro:match:status",
    )
    async def status(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        reference = self.cog.extract_panel_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message("❌ Match introuvable.", ephemeral=True)
            return
        kind, match_id = reference
        embed = await self.cog.build_status_embed(kind, match_id)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ==========================================================
# COG PRINCIPAL
# ==========================================================


class MatchCenterCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db
        self._locks: dict[tuple[str, int], asyncio.Lock] = {}

    async def cog_load(self) -> None:
        await self._init_tables()
        self.bot.add_view(MatchPanelView(self))
        self.bot.add_view(StaffAssistanceView(self))
        self.bot.add_view(TimerExpiredView(self))
        if not self.timer_watch.is_running():
            self.timer_watch.start()

    async def cog_unload(self) -> None:
        if self.timer_watch.is_running():
            self.timer_watch.cancel()

    # ==========================================================
    # TABLES
    # ==========================================================

    async def _init_tables(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS match_center_settings (
                guild_id TEXT PRIMARY KEY,
                staff_channel_id TEXT,
                staff_role_id TEXT,
                swiss_timer_minutes INTEGER NOT NULL DEFAULT 50,
                warning_minutes INTEGER NOT NULL DEFAULT 10,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS match_center_sessions (
                match_kind TEXT NOT NULL,
                match_id INTEGER NOT NULL,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER NOT NULL,
                thread_id TEXT,
                panel_message_id TEXT,
                status TEXT NOT NULL DEFAULT 'waiting',
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                paused_at TEXT,
                accumulated_pause_seconds INTEGER NOT NULL DEFAULT 0,
                warning_sent INTEGER NOT NULL DEFAULT 0,
                expired_sent INTEGER NOT NULL DEFAULT 0,
                started_by TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (match_kind, match_id)
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS tournament_runtime_state (
                tournament_id INTEGER PRIMARY KEY,
                guild_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                pause_started_at TEXT,
                reason TEXT,
                paused_by TEXT,
                resumed_by TEXT,
                total_pause_seconds INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS staff_assistance_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER NOT NULL,
                match_kind TEXT NOT NULL,
                match_id INTEGER NOT NULL,
                thread_id TEXT,
                requester_id TEXT NOT NULL,
                category TEXT NOT NULL,
                details TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                claimed_by TEXT,
                resolved_by TEXT,
                resolution TEXT,
                staff_channel_id TEXT,
                staff_message_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                claimed_at TEXT,
                resolved_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_match_center_sessions_tournament
            ON match_center_sessions(tournament_id, status)
            """
        )
        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assistance_match
            ON staff_assistance_requests(match_kind, match_id, status)
            """
        )
        await self.db.commit()

    # ==========================================================
    # CONFIGURATION ET PERMISSIONS
    # ==========================================================

    def _lock_for(self, match_kind: str, match_id: int) -> asyncio.Lock:
        key = (match_kind, match_id)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def _settings(self, guild_id: str) -> dict[str, Any]:
        own = _row_to_dict(
            await self.db.fetchone(
                "SELECT * FROM match_center_settings WHERE guild_id = ?",
                (guild_id,),
            )
        ) or {}
        progression = _row_to_dict(
            await self.db.fetchone(
                "SELECT * FROM progression_settings WHERE guild_id = ?",
                (guild_id,),
            )
        ) or {}
        if not own.get("staff_channel_id"):
            own["staff_channel_id"] = progression.get("staff_channel_id")
        if not own.get("staff_role_id"):
            own["staff_role_id"] = progression.get("staff_role_id")
        own.setdefault("swiss_timer_minutes", 50)
        own.setdefault("warning_minutes", 10)
        own["matches_channel_id"] = progression.get("matches_channel_id")
        return own

    async def ensure_staff(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Cette action doit être utilisée dans un serveur.",
                    ephemeral=True,
                )
            return False

        settings = await self._settings(str(interaction.guild_id))
        role_id = str(settings.get("staff_role_id") or "")
        has_role = bool(role_id) and any(str(role.id) == role_id for role in member.roles)
        allowed = (
            member.guild_permissions.administrator
            or member.guild_permissions.manage_guild
            or is_staff_member(member)
            or has_role
        )
        if not allowed and not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Seul le staff peut utiliser cette action.",
                ephemeral=True,
            )
        return allowed

    async def _is_staff_user(self, guild_id: str, user: discord.abc.User) -> bool:
        if not isinstance(user, discord.Member):
            return False
        settings = await self._settings(guild_id)
        role_id = str(settings.get("staff_role_id") or "")
        return bool(
            user.guild_permissions.administrator
            or user.guild_permissions.manage_guild
            or is_staff_member(user)
            or (role_id and any(str(role.id) == role_id for role in user.roles))
        )

    async def ensure_participant_or_staff(
        self,
        interaction: discord.Interaction,
        match_kind: str,
        match_id: int,
    ) -> bool:
        match = await self._load_match(match_kind, match_id)
        if match is None:
            await interaction.response.send_message("❌ Match introuvable.", ephemeral=True)
            return False
        user_id = str(interaction.user.id)
        participant = user_id in {
            str(match.get("player1_id") or ""),
            str(match.get("player2_id") or ""),
        }
        staff = await self._is_staff_user(str(interaction.guild_id), interaction.user)
        if not participant and not staff:
            await interaction.response.send_message(
                "❌ Seuls les deux joueurs et le staff peuvent utiliser ce panneau.",
                ephemeral=True,
            )
            return False
        return True

    async def _get_channel(self, channel_id: Any) -> discord.abc.GuildChannel | None:
        if not channel_id:
            return None
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return channel

    # ==========================================================
    # RÉFÉRENCES
    # ==========================================================

    @staticmethod
    def _extract_reference(message: discord.Message | None, prefix: str) -> tuple[str, int] | None:
        if message is None or not message.embeds:
            return None
        footer = message.embeds[0].footer.text or ""
        found = re.search(rf"{re.escape(prefix)}(bracket|swiss):(\d+)", footer)
        if found is None:
            return None
        return found.group(1), int(found.group(2))

    def extract_panel_reference(self, message: discord.Message | None) -> tuple[str, int] | None:
        return self._extract_reference(message, PANEL_FOOTER)

    def extract_timer_reference(self, message: discord.Message | None) -> tuple[str, int] | None:
        return self._extract_reference(message, TIMER_EXPIRED_FOOTER)

    @staticmethod
    def extract_assistance_reference(message: discord.Message | None) -> int | None:
        if message is None or not message.embeds:
            return None
        footer = message.embeds[0].footer.text or ""
        found = re.search(rf"{re.escape(ASSISTANCE_FOOTER)}(\d+)", footer)
        return int(found.group(1)) if found else None

    # ==========================================================
    # MATCHS ET PANNEAUX
    # ==========================================================

    async def _load_match(self, match_kind: str, match_id: int) -> dict[str, Any] | None:
        if match_kind == MATCH_KIND_BRACKET:
            row = await self.db.fetchone("SELECT * FROM matches WHERE id = ?", (match_id,))
        elif match_kind == MATCH_KIND_SWISS:
            row = await self.db.fetchone("SELECT * FROM swiss_matches WHERE id = ?", (match_id,))
        else:
            return None
        return _row_to_dict(row)

    async def _session(self, match_kind: str, match_id: int) -> dict[str, Any] | None:
        return _row_to_dict(
            await self.db.fetchone(
                "SELECT * FROM match_center_sessions WHERE match_kind = ? AND match_id = ?",
                (match_kind, match_id),
            )
        )

    async def create_match_panel(
        self,
        *,
        thread: discord.Thread,
        tournament: Any,
        match_kind: str,
        match: dict[str, Any],
    ) -> discord.Message | None:
        match_id = int(match["id"])
        existing = await self._session(match_kind, match_id)
        if existing and existing.get("panel_message_id"):
            try:
                return await thread.fetch_message(int(existing["panel_message_id"]))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        embed = await self._build_panel_embed(
            tournament=tournament,
            match_kind=match_kind,
            match=match,
            session=existing,
        )
        content = (
            f"{_mention(match.get('player1_id'), str(match.get('player1_name') or 'Joueur 1'))} "
            f"{_mention(match.get('player2_id'), str(match.get('player2_name') or 'Joueur 2'))}"
        )
        try:
            message = await thread.send(
                content=content,
                embed=embed,
                view=MatchPanelView(self),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"⚠️ Panneau match {match_kind}:{match_id} : {error}")
            return None

        await self.db.execute(
            """
            INSERT INTO match_center_sessions (
                match_kind, match_id, guild_id, tournament_id,
                thread_id, panel_message_id, status, duration_seconds,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'waiting', 0, CURRENT_TIMESTAMP)
            ON CONFLICT(match_kind, match_id)
            DO UPDATE SET
                guild_id = excluded.guild_id,
                tournament_id = excluded.tournament_id,
                thread_id = excluded.thread_id,
                panel_message_id = excluded.panel_message_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                match_kind,
                match_id,
                str(_value(tournament, "guild_id")),
                int(_value(tournament, "id")),
                str(thread.id),
                str(message.id),
            ),
        )
        await self.db.commit()
        return message

    async def _build_panel_embed(
        self,
        *,
        tournament: Any,
        match_kind: str,
        match: dict[str, Any],
        session: dict[str, Any] | None,
    ) -> discord.Embed:
        session = session or {"status": "waiting"}
        status = str(session.get("status") or "waiting")
        description = (
            f"{_mention(match.get('player1_id'), str(match.get('player1_name') or 'Joueur 1'))} "
            f"**contre** {_mention(match.get('player2_id'), str(match.get('player2_name') or 'Joueur 2'))}"
        )
        embed = discord.Embed(
            title=f"⚔️ Espace du match #{match.get('id')}",
            description=description,
            colour=discord.Colour.gold(),
        )
        embed.add_field(
            name="🏟️ Tournoi",
            value=f"**{_value(tournament, 'name', 'Tournoi Hamtaro')}**",
            inline=False,
        )
        embed.add_field(name="🔄 Phase", value=_round_name(match_kind, match), inline=False)
        embed.add_field(name="📍 État", value=SESSION_LABELS.get(status, status), inline=True)
        if match_kind == MATCH_KIND_SWISS:
            settings = await self._settings(str(_value(tournament, "guild_id")))
            embed.add_field(
                name="⏱️ Chronomètre",
                value=f"{int(settings.get('swiss_timer_minutes') or 50)} minutes",
                inline=True,
            )
        else:
            embed.add_field(
                name="⏱️ Chronomètre",
                value="Non utilisé en élimination directe",
                inline=True,
            )
        embed.add_field(
            name="📊 Résultat",
            value=(
                "Le bouton permet une déclaration rapide. Pour joindre une preuve, "
                "utilisez `/result`."
            ),
            inline=False,
        )
        embed.set_footer(text=f"{PANEL_FOOTER}{match_kind}:{match.get('id')}")
        return embed

    async def _refresh_panel(self, match_kind: str, match_id: int, *, disabled: bool = False) -> None:
        session = await self._session(match_kind, match_id)
        match = await self._load_match(match_kind, match_id)
        if not session or not match:
            return
        tournament = await self.db.get_tournament(int(session["tournament_id"]))
        thread = await self._get_channel(session.get("thread_id"))
        if tournament is None or not isinstance(thread, discord.Thread):
            return
        try:
            message = await thread.fetch_message(int(session["panel_message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        embed = await self._build_panel_embed(
            tournament=tournament,
            match_kind=match_kind,
            match=match,
            session=session,
        )
        try:
            await message.edit(embed=embed, view=MatchPanelView(self, disabled=disabled))
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def start_match(
        self,
        match_kind: str,
        match_id: int,
        actor: discord.abc.User,
    ) -> str:
        match = await self._load_match(match_kind, match_id)
        session = await self._session(match_kind, match_id)
        if not match or not session:
            raise ValueError("Le panneau de ce match n’est pas initialisé.")

        guild_id = str(session["guild_id"])
        actor_id = str(actor.id)
        participant = actor_id in {
            str(match.get("player1_id") or ""),
            str(match.get("player2_id") or ""),
        }
        if not participant and not await self._is_staff_user(guild_id, actor):
            raise ValueError("Seuls les joueurs du match ou le staff peuvent le démarrer.")
        if await self.is_tournament_paused(int(session["tournament_id"])):
            raise ValueError("Le tournoi est en pause. Le match ne peut pas démarrer.")
        if str(match.get("status") or "").lower() in FINAL_MATCH_STATUSES:
            raise ValueError("Ce match est déjà terminé.")

        status = str(session.get("status") or "waiting")
        if status in {"running", "paused", "expired"}:
            return "ℹ️ Ce match a déjà été démarré."
        if status in {"reported", "completed"}:
            raise ValueError("Le résultat de ce match a déjà été déclaré.")

        settings = await self._settings(guild_id)
        duration = int(settings.get("swiss_timer_minutes") or 50) * 60 if match_kind == MATCH_KIND_SWISS else 0
        await self.db.execute(
            """
            UPDATE match_center_sessions
            SET status = 'running', duration_seconds = ?,
                started_at = CURRENT_TIMESTAMP, paused_at = NULL,
                accumulated_pause_seconds = 0,
                warning_sent = 0, expired_sent = 0,
                started_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE match_kind = ? AND match_id = ?
            """,
            (duration, actor_id, match_kind, match_id),
        )
        await self.db.commit()

        thread = await self._get_channel(session.get("thread_id"))
        if isinstance(thread, discord.Thread):
            if match_kind == MATCH_KIND_SWISS:
                end_unix = int(_utcnow().timestamp()) + duration
                text = (
                    f"▶️ Match commencé par <@{actor_id}>.\n"
                    f"⏱️ Durée réglementaire : **{duration // 60} minutes**.\n"
                    f"🏁 Fin prévue : <t:{end_unix}:t> (<t:{end_unix}:R>)."
                )
            else:
                text = (
                    f"▶️ Match commencé par <@{actor_id}>.\n"
                    "Le chronomètre officiel est réservé aux rondes suisses."
                )
            try:
                await thread.send(
                    text,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

        await self._refresh_panel(match_kind, match_id)
        if match_kind == MATCH_KIND_SWISS:
            return f"✅ Match commencé. Chronomètre lancé pour {duration // 60} minutes."
        return "✅ Match marqué comme commencé."

    async def _remaining_seconds(self, session: dict[str, Any]) -> int | None:
        duration = int(session.get("duration_seconds") or 0)
        started = _parse_timestamp(session.get("started_at"))
        if duration <= 0 or started is None:
            return None
        end_reference = _utcnow()
        if str(session.get("status")) == "paused":
            end_reference = _parse_timestamp(session.get("paused_at")) or end_reference
        elapsed = int((end_reference - started).total_seconds())
        elapsed -= int(session.get("accumulated_pause_seconds") or 0)
        return duration - max(0, elapsed)

    async def build_status_embed(self, match_kind: str, match_id: int) -> discord.Embed:
        session = await self._session(match_kind, match_id)
        match = await self._load_match(match_kind, match_id)
        if not session or not match:
            return error_embed(title="Match introuvable", description="Le panneau n’est plus disponible.")
        status = str(session.get("status") or "waiting")
        embed = discord.Embed(
            title=f"ℹ️ État du match {match_kind}:{match_id}",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(name="État", value=SESSION_LABELS.get(status, status), inline=False)
        remaining = await self._remaining_seconds(session)
        if remaining is not None:
            if remaining > 0:
                minutes, seconds = divmod(remaining, 60)
                value = f"{minutes} min {seconds:02d} s restantes"
            else:
                value = "Temps réglementaire terminé"
            embed.add_field(name="Chronomètre", value=value, inline=False)
        runtime = await self._runtime_state(int(session["tournament_id"]))
        if runtime and runtime.get("status") == "paused":
            embed.add_field(
                name="Tournoi en pause",
                value=str(runtime.get("reason") or "Aucune raison précisée"),
                inline=False,
            )
        return embed

    # ==========================================================
    # RÉSULTAT RAPIDE
    # ==========================================================

    async def submit_quick_result(
        self,
        *,
        interaction: discord.Interaction,
        match_kind: str,
        match_id: int,
        player1_score: int,
        player2_score: int,
    ) -> tuple[bool, bool]:
        if player1_score < 0 or player2_score < 0:
            raise ValueError("Les scores ne peuvent pas être négatifs.")
        if player1_score == player2_score:
            raise ValueError(
                "Les matchs nuls n’existent pas. Le Double Loss doit être décidé par le staff."
            )

        results = self.bot.get_cog("ResultsCog")
        if results is None:
            raise ValueError("Le cog `results` n’est pas chargé.")

        context = await results._load_match_context(match_kind, match_id)
        user_id = str(interaction.user.id)
        participant = user_id in {
            str(context.get("player1_id") or ""),
            str(context.get("player2_id") or ""),
        }
        staff = await self._is_staff_user(str(interaction.guild_id), interaction.user)
        if not participant and not staff:
            raise ValueError("Tu ne peux déclarer que le résultat de ton propre match.")
        if context.get("is_bye"):
            raise ValueError("Un BYE ne nécessite aucun résultat.")
        if str(context.get("status") or "").lower() in FINAL_MATCH_STATUSES:
            raise ValueError("Ce match est déjà terminé.")

        winner_slot = "player1" if player1_score > player2_score else "player2"
        results._validate_result_data(
            match_kind=match_kind,
            result_type="normal",
            player1_score=player1_score,
            player2_score=player2_score,
            winner_slot=winner_slot,
        )

        async with results._lock_for(match_kind, match_id):
            existing = await results._get_request(match_kind, match_id)
            if existing and existing["status"] in OPEN_RESULT_STATUSES:
                raise ValueError("Ce match possède déjà un résultat en attente.")

            if match_kind == MATCH_KIND_BRACKET:
                reported = await results.brackets.report_result(
                    match_id=match_id,
                    player1_score=player1_score,
                    player2_score=player2_score,
                    reported_by=user_id,
                )
                context = results._match_context(match_kind, reported)

            request = await results._create_request(
                match_kind=match_kind,
                context=context,
                guild_id=str(interaction.guild_id),
                reporter_id=user_id,
                result_type="normal",
                winner_slot=winner_slot,
                player1_score=player1_score,
                player2_score=player2_score,
                proof_url=None,
                proof_is_image=False,
            )

        sent_staff = await results._send_validation_message(request)
        request = await results._get_request(match_kind, match_id) or request
        sent_opponent = await results._send_opponent_confirmation(request)
        await results._audit(
            guild_id=str(request["guild_id"]),
            match_kind=match_kind,
            match_id=match_id,
            action="player_reported_from_match_thread",
            actor_id=user_id,
            details={
                "score": f"{player1_score}-{player2_score}",
                "staff_message_sent": sent_staff,
                "opponent_message_sent": sent_opponent,
            },
        )
        await self.db.execute(
            """
            UPDATE match_center_sessions
            SET status = 'reported', updated_at = CURRENT_TIMESTAMP
            WHERE match_kind = ? AND match_id = ?
            """,
            (match_kind, match_id),
        )
        await self.db.commit()
        await self._refresh_panel(match_kind, match_id)
        return sent_staff, sent_opponent

    # ==========================================================
    # ASSISTANCE STAFF
    # ==========================================================

    async def create_assistance_request(
        self,
        *,
        interaction: discord.Interaction,
        match_kind: str,
        match_id: int,
        category: str,
        details: str,
    ) -> int:
        session = await self._session(match_kind, match_id)
        match = await self._load_match(match_kind, match_id)
        if not session or not match:
            raise ValueError("Le match est introuvable.")
        user_id = str(interaction.user.id)
        participant = user_id in {
            str(match.get("player1_id") or ""),
            str(match.get("player2_id") or ""),
        }
        staff = await self._is_staff_user(str(interaction.guild_id), interaction.user)
        if not participant and not staff:
            raise ValueError("Tu ne participes pas à ce match.")

        open_request = await self.db.fetchone(
            """
            SELECT id FROM staff_assistance_requests
            WHERE match_kind = ? AND match_id = ?
              AND status IN ('open', 'claimed')
            ORDER BY id DESC LIMIT 1
            """,
            (match_kind, match_id),
        )
        if open_request is not None:
            raise ValueError(
                f"Une demande d’assistance est déjà ouverte (`#{open_request['id']}`)."
            )

        cursor = await self.db.execute(
            """
            INSERT INTO staff_assistance_requests (
                guild_id, tournament_id, match_kind, match_id,
                thread_id, requester_id, category, details, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """,
            (
                str(session["guild_id"]),
                int(session["tournament_id"]),
                match_kind,
                match_id,
                session.get("thread_id"),
                user_id,
                category,
                details,
            ),
        )
        await self.db.commit()
        request_id = int(cursor.lastrowid)

        settings = await self._settings(str(session["guild_id"]))
        staff_channel = await self._get_channel(settings.get("staff_channel_id"))
        if not isinstance(staff_channel, discord.TextChannel):
            raise ValueError("Le salon staff n’est pas configuré ou inaccessible.")

        thread = await self._get_channel(session.get("thread_id"))
        thread_link = thread.jump_url if isinstance(thread, discord.Thread) else None
        embed = discord.Embed(
            title="🆘 Demande d’assistance",
            description=(
                f"Match : `{match_kind}:{match_id}`\n"
                f"Demandée par : <@{user_id}>\n"
                f"Motif : **{ASSISTANCE_LABELS.get(category, category)}**"
            ),
            colour=discord.Colour.red(),
        )
        embed.add_field(name="Détails", value=details[:1000], inline=False)
        if thread_link:
            embed.add_field(name="Fil du match", value=f"[Ouvrir le fil]({thread_link})", inline=False)
        embed.set_footer(text=f"{ASSISTANCE_FOOTER}{request_id}")
        message = await staff_channel.send(
            embed=embed,
            view=StaffAssistanceView(self),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await self.db.execute(
            """
            UPDATE staff_assistance_requests
            SET staff_channel_id = ?, staff_message_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (str(staff_channel.id), str(message.id), request_id),
        )
        await self.db.commit()

        if isinstance(thread, discord.Thread):
            try:
                await thread.send(
                    f"🆘 <@{user_id}> a demandé l’intervention du staff : "
                    f"**{ASSISTANCE_LABELS.get(category, category)}**.",
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
        return request_id

    async def _assistance(self, request_id: int) -> dict[str, Any] | None:
        return _row_to_dict(
            await self.db.fetchone(
                "SELECT * FROM staff_assistance_requests WHERE id = ?",
                (request_id,),
            )
        )

    async def _refresh_assistance_message(self, request: dict[str, Any], *, disabled: bool = False) -> None:
        channel = await self._get_channel(request.get("staff_channel_id"))
        if not isinstance(channel, discord.TextChannel) or not request.get("staff_message_id"):
            return
        try:
            message = await channel.fetch_message(int(request["staff_message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        status = str(request.get("status") or "open")
        colour = discord.Colour.red()
        if status == "claimed":
            colour = discord.Colour.orange()
        elif status == "resolved":
            colour = discord.Colour.green()
        embed = discord.Embed(
            title="🆘 Demande d’assistance",
            description=(
                f"Match : `{request['match_kind']}:{request['match_id']}`\n"
                f"Demandée par : <@{request['requester_id']}>\n"
                f"Motif : **{ASSISTANCE_LABELS.get(str(request['category']), request['category'])}**\n"
                f"État : **{status}**"
            ),
            colour=colour,
        )
        embed.add_field(name="Détails", value=str(request["details"])[:1000], inline=False)
        if request.get("claimed_by"):
            embed.add_field(name="Prise en charge", value=f"<@{request['claimed_by']}>", inline=False)
        if request.get("resolution"):
            embed.add_field(name="Résolution", value=str(request["resolution"])[:1000], inline=False)
        thread = await self._get_channel(request.get("thread_id"))
        if isinstance(thread, discord.Thread):
            embed.add_field(name="Fil du match", value=f"[Ouvrir le fil]({thread.jump_url})", inline=False)
        embed.set_footer(text=f"{ASSISTANCE_FOOTER}{request['id']}")
        try:
            await message.edit(embed=embed, view=StaffAssistanceView(self, disabled=disabled))
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def claim_assistance(self, request_id: int, actor: discord.abc.User) -> None:
        changed = await self.db.execute(
            """
            UPDATE staff_assistance_requests
            SET status = 'claimed', claimed_by = ?, claimed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'open'
            """,
            (str(actor.id), request_id),
        )
        await self.db.commit()
        if changed.rowcount != 1:
            request = await self._assistance(request_id)
            if request and request.get("status") == "claimed":
                raise ValueError("⚠️ Cette demande est déjà prise en charge.")
            raise ValueError("⚠️ Cette demande n’est plus ouverte.")
        request = await self._assistance(request_id)
        if request:
            await self._refresh_assistance_message(request)
            thread = await self._get_channel(request.get("thread_id"))
            if isinstance(thread, discord.Thread):
                try:
                    await thread.send(f"👀 La demande est prise en charge par <@{actor.id}>.")
                except (discord.Forbidden, discord.HTTPException):
                    pass

    async def resolve_assistance(
        self,
        *,
        request_id: int,
        actor: discord.abc.User,
        resolution: str,
    ) -> None:
        changed = await self.db.execute(
            """
            UPDATE staff_assistance_requests
            SET status = 'resolved', resolved_by = ?, resolution = ?,
                resolved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('open', 'claimed')
            """,
            (str(actor.id), resolution, request_id),
        )
        await self.db.commit()
        if changed.rowcount != 1:
            raise ValueError("Cette demande a déjà été fermée.")
        request = await self._assistance(request_id)
        if request:
            await self._refresh_assistance_message(request, disabled=True)
            thread = await self._get_channel(request.get("thread_id"))
            if isinstance(thread, discord.Thread):
                try:
                    await thread.send(
                        f"✅ Demande résolue par <@{actor.id}>.\n**Résolution :** {resolution}"
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

    # ==========================================================
    # CHRONOMÈTRE ET DÉCISIONS DE FIN DE TEMPS
    # ==========================================================

    async def add_timer_seconds(
        self,
        match_kind: str,
        match_id: int,
        seconds: int,
        actor: discord.abc.User,
    ) -> None:
        session = await self._session(match_kind, match_id)
        if not session:
            raise ValueError("Chronomètre introuvable.")
        await self.db.execute(
            """
            UPDATE match_center_sessions
            SET duration_seconds = duration_seconds + ?, status = 'running',
                expired_sent = 0, updated_at = CURRENT_TIMESTAMP
            WHERE match_kind = ? AND match_id = ?
            """,
            (seconds, match_kind, match_id),
        )
        await self.db.commit()
        thread = await self._get_channel(session.get("thread_id"))
        if isinstance(thread, discord.Thread):
            try:
                await thread.send(
                    f"➕ <@{actor.id}> a ajouté **{seconds // 60} minutes** au chronomètre."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
        await self._refresh_panel(match_kind, match_id)

    async def create_special_result_request(
        self,
        *,
        match_kind: str,
        match_id: int,
        actor: discord.abc.User,
        result_type: str,
        winner_slot: str | None,
        reason: str,
    ) -> None:
        if result_type == "double_loss" and match_kind != MATCH_KIND_SWISS:
            raise ValueError("Le Double Loss est réservé aux rondes suisses.")
        if result_type == "admin_win" and winner_slot not in {"player1", "player2"}:
            raise ValueError("Le gagnant doit être `player1` ou `player2`.")

        results = self.bot.get_cog("ResultsCog")
        if results is None:
            raise ValueError("Le cog `results` n’est pas chargé.")
        context = await results._load_match_context(match_kind, match_id)

        async with results._lock_for(match_kind, match_id):
            existing = await results._get_request(match_kind, match_id)
            if existing and existing["status"] in OPEN_RESULT_STATUSES:
                raise ValueError("Ce match possède déjà une décision en attente.")

            if result_type == "double_loss":
                score1, score2 = 0, 0
                final_winner_slot = None
            else:
                final_winner_slot = winner_slot
                score1, score2 = (1, 0) if winner_slot == "player1" else (0, 1)

            results._validate_result_data(
                match_kind=match_kind,
                result_type=result_type,
                player1_score=score1,
                player2_score=score2,
                winner_slot=final_winner_slot,
            )

            if match_kind == MATCH_KIND_BRACKET:
                winner_id = (
                    context["player1_id"] if final_winner_slot == "player1" else context["player2_id"]
                )
                winner_name = (
                    context["player1_name"] if final_winner_slot == "player1" else context["player2_name"]
                )
                await self.db.execute(
                    """
                    UPDATE matches
                    SET player1_score = ?, player2_score = ?,
                        winner_id = ?, winner_name = ?, score = ?,
                        reported_by = ?, reported_at = CURRENT_TIMESTAMP,
                        notes = ?, status = 'reported'
                    WHERE id = ?
                    """,
                    (
                        score1,
                        score2,
                        winner_id,
                        winner_name,
                        f"{score1}-{score2}",
                        str(actor.id),
                        reason,
                        match_id,
                    ),
                )
                await self.db.commit()

            session = await self._session(match_kind, match_id)
            if not session:
                raise ValueError("Session de match introuvable.")
            request = await results._create_request(
                match_kind=match_kind,
                context=context,
                guild_id=str(session["guild_id"]),
                reporter_id=str(actor.id),
                result_type=result_type,
                winner_slot=final_winner_slot,
                player1_score=score1,
                player2_score=score2,
                proof_url=None,
                proof_is_image=False,
            )

        sent = await results._send_validation_message(request)
        await results._audit(
            guild_id=str(request["guild_id"]),
            match_kind=match_kind,
            match_id=match_id,
            action="timer_staff_decision_created",
            actor_id=str(actor.id),
            details={"type": result_type, "reason": reason, "validation_message_sent": sent},
        )
        await self.db.execute(
            """
            UPDATE match_center_sessions
            SET status = 'reported', updated_at = CURRENT_TIMESTAMP
            WHERE match_kind = ? AND match_id = ?
            """,
            (match_kind, match_id),
        )
        await self.db.commit()
        await self._refresh_panel(match_kind, match_id)

    @tasks.loop(seconds=20)
    async def timer_watch(self) -> None:
        rows = await self.db.fetchall(
            """
            SELECT * FROM match_center_sessions
            WHERE match_kind = 'swiss'
              AND status = 'running'
              AND duration_seconds > 0
            ORDER BY tournament_id, match_id
            """
        )
        for raw in rows:
            session = dict(raw)
            try:
                await self._check_timer(session)
            except Exception as error:
                print(
                    f"⚠️ Chronomètre {session.get('match_kind')}:{session.get('match_id')} : {error}"
                )

    @timer_watch.before_loop
    async def before_timer_watch(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_timer(self, session: dict[str, Any]) -> None:
        if await self.is_tournament_paused(int(session["tournament_id"])):
            return
        remaining = await self._remaining_seconds(session)
        if remaining is None:
            return
        settings = await self._settings(str(session["guild_id"]))
        warning_seconds = max(1, int(settings.get("warning_minutes") or 10)) * 60
        thread = await self._get_channel(session.get("thread_id"))

        if remaining <= warning_seconds and remaining > 0 and int(session.get("warning_sent") or 0) == 0:
            await self.db.execute(
                """
                UPDATE match_center_sessions
                SET warning_sent = 1, updated_at = CURRENT_TIMESTAMP
                WHERE match_kind = ? AND match_id = ?
                """,
                (session["match_kind"], session["match_id"]),
            )
            await self.db.commit()
            if isinstance(thread, discord.Thread):
                try:
                    await thread.send(
                        f"⚠️ Il reste environ **{max(1, remaining // 60)} minutes** avant la fin du temps réglementaire."
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

        if remaining <= 0 and int(session.get("expired_sent") or 0) == 0:
            await self.db.execute(
                """
                UPDATE match_center_sessions
                SET status = 'expired', expired_sent = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE match_kind = ? AND match_id = ?
                """,
                (session["match_kind"], session["match_id"]),
            )
            await self.db.commit()
            if isinstance(thread, discord.Thread):
                embed = discord.Embed(
                    title="⏰ Temps réglementaire terminé",
                    description=(
                        "Le staff doit vérifier la situation du match. "
                        "Aucun Double Loss n’est appliqué automatiquement."
                    ),
                    colour=discord.Colour.red(),
                )
                embed.set_footer(
                    text=f"{TIMER_EXPIRED_FOOTER}{session['match_kind']}:{session['match_id']}"
                )
                try:
                    await thread.send(embed=embed, view=TimerExpiredView(self))
                except (discord.Forbidden, discord.HTTPException):
                    pass
            await self._refresh_panel(str(session["match_kind"]), int(session["match_id"]))

    # ==========================================================
    # PAUSE ET REPRISE DU TOURNOI
    # ==========================================================

    async def _runtime_state(self, tournament_id: int) -> dict[str, Any] | None:
        return _row_to_dict(
            await self.db.fetchone(
                "SELECT * FROM tournament_runtime_state WHERE tournament_id = ?",
                (tournament_id,),
            )
        )

    async def is_tournament_paused(self, tournament_id: int) -> bool:
        state = await self._runtime_state(tournament_id)
        return bool(state and str(state.get("status")) == "paused")

    async def pause_tournament_runtime(
        self,
        *,
        tournament: Any,
        actor: discord.abc.User,
        reason: str,
    ) -> None:
        tournament_id = int(_value(tournament, "id"))
        guild_id = str(_value(tournament, "guild_id"))
        if await self.is_tournament_paused(tournament_id):
            raise ValueError("Ce tournoi est déjà en pause.")
        await self.db.execute(
            """
            INSERT INTO tournament_runtime_state (
                tournament_id, guild_id, status, pause_started_at,
                reason, paused_by, updated_at
            )
            VALUES (?, ?, 'paused', CURRENT_TIMESTAMP, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(tournament_id)
            DO UPDATE SET
                status = 'paused', pause_started_at = CURRENT_TIMESTAMP,
                reason = excluded.reason, paused_by = excluded.paused_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (tournament_id, guild_id, reason, str(actor.id)),
        )
        await self.db.execute(
            """
            UPDATE match_center_sessions
            SET status = 'paused', paused_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE tournament_id = ? AND status = 'running'
            """,
            (tournament_id,),
        )
        await self.db.commit()
        await self._announce_pause_state(tournament, paused=True, actor=actor, reason=reason)

    async def resume_tournament_runtime(
        self,
        *,
        tournament: Any,
        actor: discord.abc.User,
    ) -> int:
        tournament_id = int(_value(tournament, "id"))
        state = await self._runtime_state(tournament_id)
        if not state or str(state.get("status")) != "paused":
            raise ValueError("Ce tournoi n’est pas en pause.")
        paused_at = _parse_timestamp(state.get("pause_started_at")) or _utcnow()
        pause_seconds = max(0, int((_utcnow() - paused_at).total_seconds()))
        await self.db.execute(
            """
            UPDATE match_center_sessions
            SET status = 'running',
                accumulated_pause_seconds = accumulated_pause_seconds + ?,
                paused_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE tournament_id = ? AND status = 'paused'
            """,
            (pause_seconds, tournament_id),
        )
        await self.db.execute(
            """
            UPDATE tournament_runtime_state
            SET status = 'running', pause_started_at = NULL,
                resumed_by = ?,
                total_pause_seconds = total_pause_seconds + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE tournament_id = ?
            """,
            (str(actor.id), pause_seconds, tournament_id),
        )
        await self.db.commit()
        await self._announce_pause_state(
            tournament,
            paused=False,
            actor=actor,
            reason=f"Pause totale : {pause_seconds // 60} min {pause_seconds % 60:02d} s",
        )
        return pause_seconds

    async def _announce_pause_state(
        self,
        tournament: Any,
        *,
        paused: bool,
        actor: discord.abc.User,
        reason: str,
    ) -> None:
        tournament_id = int(_value(tournament, "id"))
        guild_id = str(_value(tournament, "guild_id"))
        settings = await self._settings(guild_id)
        title = "⏸️ Tournoi en pause" if paused else "▶️ Tournoi repris"
        description = (
            f"**{_value(tournament, 'name', 'Tournoi Hamtaro')}**\n\n"
            f"{reason}\n\n"
            + (
                "Les chronomètres suisses sont suspendus et aucun nouveau match ne sera publié."
                if paused
                else "Les chronomètres suisses reprennent et la progression automatique est réactivée."
            )
        )
        embed = discord.Embed(
            title=title,
            description=description,
            colour=discord.Colour.orange() if paused else discord.Colour.green(),
        )
        embed.set_footer(text=f"Action effectuée par {actor}")
        channel = await self._get_channel(settings.get("matches_channel_id"))
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass
        sessions = await self.db.fetchall(
            """
            SELECT thread_id FROM match_center_sessions
            WHERE tournament_id = ? AND thread_id IS NOT NULL
              AND status IN ('running', 'paused', 'expired')
            """,
            (tournament_id,),
        )
        for row in sessions:
            thread = await self._get_channel(row["thread_id"])
            if isinstance(thread, discord.Thread):
                try:
                    await thread.send(embed=embed)
                except (discord.Forbidden, discord.HTTPException):
                    pass

    # ==========================================================
    # FIN DE MATCH
    # ==========================================================

    async def handle_result_approved(
        self,
        *,
        tournament_id: int,
        match_kind: str,
        match_id: int,
    ) -> None:
        session = await self._session(match_kind, match_id)
        if not session:
            return
        await self.db.execute(
            """
            UPDATE match_center_sessions
            SET status = 'completed', updated_at = CURRENT_TIMESTAMP
            WHERE match_kind = ? AND match_id = ?
            """,
            (match_kind, match_id),
        )
        await self.db.execute(
            """
            UPDATE staff_assistance_requests
            SET status = 'resolved', resolution = 'Résultat du match validé.',
                resolved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE match_kind = ? AND match_id = ?
              AND status IN ('open', 'claimed')
            """,
            (match_kind, match_id),
        )
        await self.db.commit()
        await self._refresh_panel(match_kind, match_id, disabled=True)
        thread = await self._get_channel(session.get("thread_id"))
        if isinstance(thread, discord.Thread):
            try:
                await thread.send("✅ Le résultat a été validé. Ce fil va être archivé.")
                await thread.edit(archived=True, reason="Match Hamtaro terminé")
            except (discord.Forbidden, discord.HTTPException):
                pass

    # ==========================================================
    # COMMANDES
    # ==========================================================

    @app_commands.command(
        name="match_center_setup",
        description="Configurer les chronomètres et les appels au staff",
    )
    @app_commands.describe(
        staff_channel="Salon privé recevant les appels des joueurs",
        staff_role="Rôle staff autorisé à traiter les demandes",
        swiss_timer_minutes="Durée réglementaire d’un match suisse",
        warning_minutes="Rappel avant la fin du temps",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def match_center_setup(
        self,
        interaction: discord.Interaction,
        staff_channel: discord.TextChannel,
        staff_role: discord.Role | None = None,
        swiss_timer_minutes: app_commands.Range[int, 5, 180] = 50,
        warning_minutes: app_commands.Range[int, 1, 60] = 10,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Serveur requis.", ephemeral=True)
            return
        if warning_minutes >= swiss_timer_minutes:
            await interaction.response.send_message(
                "❌ Le rappel doit arriver avant la fin du chronomètre.",
                ephemeral=True,
            )
            return
        await self.db.execute(
            """
            INSERT INTO match_center_settings (
                guild_id, staff_channel_id, staff_role_id,
                swiss_timer_minutes, warning_minutes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                staff_channel_id = excluded.staff_channel_id,
                staff_role_id = excluded.staff_role_id,
                swiss_timer_minutes = excluded.swiss_timer_minutes,
                warning_minutes = excluded.warning_minutes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                str(interaction.guild.id),
                str(staff_channel.id),
                str(staff_role.id) if staff_role else None,
                int(swiss_timer_minutes),
                int(warning_minutes),
            ),
        )
        await self.db.commit()
        await interaction.response.send_message(
            embed=success_embed(
                title="Centre de match configuré",
                description=(
                    f"Salon staff : {staff_channel.mention}\n"
                    f"Chronomètre suisse : **{swiss_timer_minutes} minutes**\n"
                    f"Rappel : **{warning_minutes} minutes avant la fin**"
                ),
            ),
            ephemeral=True,
        )

    @app_commands.command(name="pause_tournament", description="Mettre le tournoi en pause")
    @app_commands.describe(raison="Raison visible par les joueurs", code="Code facultatif du tournoi")
    @app_commands.default_permissions(manage_guild=True)
    async def pause_tournament_command(
        self,
        interaction: discord.Interaction,
        raison: str,
        code: str | None = None,
    ) -> None:
        if not await self.ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            tournament = await resolve_tournament(interaction, self.db, code=code)
            if tournament is None:
                raise ValueError("Aucun tournoi sélectionné.")
            await self.pause_tournament_runtime(
                tournament=tournament,
                actor=interaction.user,
                reason=raison,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        await interaction.followup.send("✅ Tournoi mis en pause.", ephemeral=True)

    @app_commands.command(name="resume_tournament", description="Reprendre un tournoi en pause")
    @app_commands.describe(code="Code facultatif du tournoi")
    @app_commands.default_permissions(manage_guild=True)
    async def resume_tournament_command(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ) -> None:
        if not await self.ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            tournament = await resolve_tournament(interaction, self.db, code=code)
            if tournament is None:
                raise ValueError("Aucun tournoi sélectionné.")
            seconds = await self.resume_tournament_runtime(
                tournament=tournament,
                actor=interaction.user,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        progression = self.bot.get_cog("TournamentProgressionCog")
        if progression is not None:
            try:
                await progression.publish_tournament(tournament)
            except Exception as error:
                print(f"⚠️ Reprise progression tournoi : {error}")
        await interaction.followup.send(
            f"✅ Tournoi repris après {seconds // 60} min {seconds % 60:02d} s de pause.",
            ephemeral=True,
        )

    @app_commands.command(
        name="match_center_status",
        description="Voir la configuration du centre de match",
    )
    async def match_center_status(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Serveur requis.", ephemeral=True)
            return
        settings = await self._settings(str(interaction.guild.id))
        embed = discord.Embed(
            title="⚙️ Centre de match Hamtaro",
            colour=discord.Colour.blurple(),
        )
        staff_channel = interaction.guild.get_channel(int(settings["staff_channel_id"])) if settings.get("staff_channel_id") else None
        embed.add_field(
            name="Salon staff",
            value=staff_channel.mention if staff_channel else "Non configuré",
            inline=False,
        )
        embed.add_field(
            name="Chronomètre suisse",
            value=f"{int(settings.get('swiss_timer_minutes') or 50)} minutes",
            inline=True,
        )
        embed.add_field(
            name="Rappel",
            value=f"{int(settings.get('warning_minutes') or 10)} minutes avant la fin",
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="match_center_repair",
        description="Ajouter les panneaux aux fils de match déjà créés",
    )
    @app_commands.describe(code="Code facultatif du tournoi")
    @app_commands.default_permissions(manage_guild=True)
    async def match_center_repair(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ) -> None:
        if not await self.ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        tournament = await resolve_tournament(interaction, self.db, code=code)
        if tournament is None:
            await interaction.followup.send("❌ Aucun tournoi sélectionné.", ephemeral=True)
            return
        rows = await self.db.fetchall(
            """
            SELECT * FROM progression_match_publications
            WHERE tournament_id = ? AND thread_id IS NOT NULL
            ORDER BY match_kind, match_id
            """,
            (int(_value(tournament, "id")),),
        )
        repaired = 0
        for row in rows:
            publication = dict(row)
            session = await self._session(str(publication["match_kind"]), int(publication["match_id"]))
            if session and session.get("panel_message_id"):
                continue
            thread = await self._get_channel(publication.get("thread_id"))
            match = await self._load_match(str(publication["match_kind"]), int(publication["match_id"]))
            if isinstance(thread, discord.Thread) and match:
                if await self.create_match_panel(
                    thread=thread,
                    tournament=tournament,
                    match_kind=str(publication["match_kind"]),
                    match=match,
                ):
                    repaired += 1
        await interaction.followup.send(
            f"✅ **{repaired}** panneau(x) ajouté(s).",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MatchCenterCog(bot))
