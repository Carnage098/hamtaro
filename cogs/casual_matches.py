from __future__ import annotations

import logging
import os
import re
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from models.casual_match import CasualMatch, CasualMatchStatus
from services.casual_match_service import CasualMatchService
from ui.casual_match_views import (
    CASUAL_FOOTER_PREFIX,
    CasualSearchView,
)

import config as hamtaro_config

# La configuration centralisée reste prioritaire. Le repli permet au cog de
# fonctionner immédiatement si l'utilisateur a seulement créé la variable
# Railway avant d'ajouter le bloc correspondant dans config.py.
CASUAL_MATCH_CHANNEL_ID = getattr(
    hamtaro_config,
    "CASUAL_MATCH_CHANNEL_ID",
    os.getenv("CASUAL_MATCH_CHANNEL_ID", "").strip(),
)


LOGGER = logging.getLogger("hamtaro.casual_matches")

FORMAT_SUGGESTIONS = (
    "Format Actuel",
    "Master Duel",
    "Genesys",
    "GOAT",
    "Edison",
    "HAT",
    "Tengu Plant",
    "Dragon Ruler",
    "TeleDAD",
    "Rush Duel",
    "Speed Duel",
)

SIMULATOR_SUGGESTIONS = (
    "DuelingBook",
    "EDOPro",
    "YGO Omega",
    "Master Duel",
    "Remote Duel",
)


class CasualMatchesCog(commands.Cog):
    """Recherche, organisation et clôture des matchs casual."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db
        self.service = CasualMatchService(self.db)

    async def cog_load(self) -> None:
        await self.service.initialize_schema()
        self.bot.add_view(CasualSearchView(self))

        if not self._configured_channel_id():
            LOGGER.error(
                "CASUAL_MATCH_CHANNEL_ID est absent ou invalide. "
                "Les commandes casual resteront indisponibles."
            )
        else:
            LOGGER.info(
                "Système casual chargé avec le salon %s.",
                self._configured_channel_id(),
            )

    # ==========================================================
    # CONFIGURATION ET RÉSOLUTION DISCORD
    # ==========================================================

    @staticmethod
    def _configured_channel_id() -> int | None:
        value = str(CASUAL_MATCH_CHANNEL_ID or "").strip()
        if not value.isdigit():
            return None
        channel_id = int(value)
        return channel_id if channel_id > 0 else None

    async def _casual_channel(
        self,
        guild: discord.Guild,
    ) -> discord.TextChannel:
        channel_id = self._configured_channel_id()
        if channel_id is None:
            raise ValueError(
                "La variable Railway CASUAL_MATCH_CHANNEL_ID "
                "est absente ou invalide."
            )

        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden) as error:
                raise ValueError(
                    "Le salon configuré dans CASUAL_MATCH_CHANNEL_ID "
                    "est introuvable sur ce serveur."
                ) from error
            except discord.HTTPException as error:
                raise ValueError(
                    "Discord n'a pas permis de récupérer le salon casual."
                ) from error

        if not isinstance(channel, discord.TextChannel):
            raise ValueError(
                "CASUAL_MATCH_CHANNEL_ID doit désigner un salon textuel."
            )
        if channel.guild.id != guild.id:
            raise ValueError(
                "Le salon casual configuré appartient à un autre serveur."
            )

        return channel

    @staticmethod
    def _missing_bot_permissions(
        channel: discord.TextChannel,
        bot_member: discord.Member,
    ) -> list[str]:
        permissions = channel.permissions_for(bot_member)
        checks = {
            "Voir le salon": permissions.view_channel,
            "Envoyer des messages": permissions.send_messages,
            "Intégrer des liens": permissions.embed_links,
            "Lire l'historique": permissions.read_message_history,
            "Créer des fils privés": permissions.create_private_threads,
            "Écrire dans les fils": permissions.send_messages_in_threads,
            "Gérer les fils": permissions.manage_threads,
        }
        return [label for label, enabled in checks.items() if not enabled]

    async def _member(
        self,
        guild: discord.Guild,
        user_id: str,
    ) -> discord.Member:
        member = guild.get_member(int(user_id))
        if member is not None:
            return member
        try:
            return await guild.fetch_member(int(user_id))
        except (discord.NotFound, discord.Forbidden) as error:
            raise ValueError(
                "Un des joueurs n'est plus accessible sur le serveur."
            ) from error
        except discord.HTTPException as error:
            raise ValueError(
                "Discord n'a pas permis de récupérer un des joueurs."
            ) from error

    async def _thread(
        self,
        guild: discord.Guild,
        thread_id: str | None,
    ) -> discord.Thread | None:
        if not thread_id:
            return None

        thread = guild.get_thread(int(thread_id))
        if thread is not None:
            return thread

        try:
            channel = await guild.fetch_channel(int(thread_id))
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            return None

        return channel if isinstance(channel, discord.Thread) else None

    async def _public_message(
        self,
        guild: discord.Guild,
        match: CasualMatch,
    ) -> discord.Message | None:
        if match.message_id is None:
            return None

        try:
            channel = await self._casual_channel(guild)
            if str(channel.id) != match.channel_id:
                old_channel = guild.get_channel(int(match.channel_id))
                if isinstance(old_channel, discord.TextChannel):
                    channel = old_channel
            return await channel.fetch_message(int(match.message_id))
        except (
            ValueError,
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            return None

    @staticmethod
    def _is_staff(member: discord.Member | discord.User) -> bool:
        if not isinstance(member, discord.Member):
            return False

        permissions = member.guild_permissions
        if permissions.administrator or permissions.manage_guild:
            return True

        staff_names = {
            "admin",
            "staff",
            "modo",
            "modérateur",
            "moderateur",
            "🛑modo",
        }
        return any(role.name.casefold() in staff_names for role in member.roles)

    # ==========================================================
    # EMBEDS
    # ==========================================================

    @staticmethod
    def _search_embed(match: CasualMatch) -> discord.Embed:
        embed = discord.Embed(
            title="⚔️ Recherche d'adversaire — Match casual",
            description=(
                f"<@{match.requester_id}> cherche un adversaire.\n\n"
                "Le premier joueur qui accepte obtient le match. "
                "Un refus personnel ne ferme pas l'annonce."
            ),
            colour=discord.Colour.orange(),
        )
        embed.add_field(
            name="👤 Joueur",
            value=match.requester_name,
            inline=True,
        )
        embed.add_field(
            name="🎮 Format",
            value=match.format_name,
            inline=True,
        )
        embed.add_field(
            name="🖥️ Simulateur",
            value=match.simulator,
            inline=True,
        )
        embed.add_field(
            name="🏁 Type de match",
            value=f"BO{match.best_of}",
            inline=True,
        )
        embed.add_field(
            name="📌 Statut",
            value="En attente d'un adversaire",
            inline=False,
        )
        embed.set_footer(text=f"{CASUAL_FOOTER_PREFIX}{match.id}")
        return embed

    @staticmethod
    def _accepted_embed(
        match: CasualMatch,
        thread: discord.Thread,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="✅ Adversaire trouvé — Match casual",
            description=(
                f"<@{match.requester_id}> affrontera "
                f"<@{match.opponent_id}>."
            ),
            colour=discord.Colour.green(),
        )
        embed.add_field(
            name="🎮 Format",
            value=match.format_name,
            inline=True,
        )
        embed.add_field(
            name="🖥️ Simulateur",
            value=match.simulator,
            inline=True,
        )
        embed.add_field(
            name="🏁 Match",
            value=f"BO{match.best_of}",
            inline=True,
        )
        embed.add_field(
            name="🔒 Fil privé",
            value=thread.mention,
            inline=False,
        )
        embed.add_field(
            name="📌 Statut",
            value="Match en cours",
            inline=False,
        )
        embed.set_footer(text=f"{CASUAL_FOOTER_PREFIX}{match.id}")
        return embed

    @staticmethod
    def _completed_embed(match: CasualMatch) -> discord.Embed:
        score = f"{match.player1_score} - {match.player2_score}"
        embed = discord.Embed(
            title="🏆 Match casual terminé",
            description=f"Victoire de <@{match.winner_id}>.",
            colour=discord.Colour.gold(),
        )
        embed.add_field(
            name="⚔️ Affiche",
            value=(
                f"<@{match.requester_id}> contre "
                f"<@{match.opponent_id}>"
            ),
            inline=False,
        )
        embed.add_field(name="📊 Score", value=score, inline=True)
        embed.add_field(
            name="🎮 Format",
            value=match.format_name,
            inline=True,
        )
        embed.add_field(
            name="🖥️ Simulateur",
            value=match.simulator,
            inline=True,
        )
        embed.add_field(name="📌 Statut", value="Terminé", inline=False)
        embed.set_footer(text=f"{CASUAL_FOOTER_PREFIX}{match.id}")
        return embed

    @staticmethod
    def _cancelled_embed(match: CasualMatch) -> discord.Embed:
        embed = discord.Embed(
            title="❌ Match casual annulé",
            description=(
                f"La recherche de <@{match.requester_id}> "
                "n'est plus disponible."
            ),
            colour=discord.Colour.red(),
        )
        embed.add_field(
            name="🎮 Format",
            value=match.format_name,
            inline=True,
        )
        embed.add_field(
            name="🖥️ Simulateur",
            value=match.simulator,
            inline=True,
        )
        embed.add_field(
            name="🏁 Match",
            value=f"BO{match.best_of}",
            inline=True,
        )
        embed.set_footer(text=f"{CASUAL_FOOTER_PREFIX}{match.id}")
        return embed

    # ==========================================================
    # BOUTONS
    # ==========================================================

    async def decline_from_button(
        self,
        interaction: discord.Interaction,
        match_id: int,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette action doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        try:
            await self.service.record_decline(
                match_id=match_id,
                guild_id=str(interaction.guild.id),
                user_id=str(interaction.user.id),
            )
        except ValueError as error:
            await interaction.response.send_message(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Tu as refusé cette proposition. L'annonce reste active.",
            ephemeral=True,
        )

    async def accept_from_button(
        self,
        interaction: discord.Interaction,
        match_id: int,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Cette action doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        opponent_id = str(interaction.user.id)
        thread: discord.Thread | None = None
        claimed = False

        try:
            match = await self.service.claim_match(
                match_id=match_id,
                guild_id=str(guild.id),
                opponent_id=opponent_id,
                opponent_name=interaction.user.display_name,
            )
            claimed = True

            channel = await self._casual_channel(guild)
            if str(channel.id) != match.channel_id:
                raise ValueError(
                    "Cette annonce ne correspond plus au salon casual "
                    "actuellement configuré."
                )

            requester = await self._member(guild, match.requester_id)
            opponent = await self._member(guild, opponent_id)

            thread_name = (
                f"casual-{match.id}-"
                f"{_safe_thread_name(requester.display_name)}-vs-"
                f"{_safe_thread_name(opponent.display_name)}"
            )[:100]

            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=(
                    channel.default_auto_archive_duration or 1440
                ),
                reason="Hamtaro : match casual accepté.",
            )
            await thread.add_user(requester)
            await thread.add_user(opponent)

            await thread.send(
                embed=discord.Embed(
                    title=f"⚔️ Match casual #{match.id}",
                    description=(
                        f"<@{match.requester_id}> contre "
                        f"<@{match.opponent_id}>\n\n"
                        f"**Format :** {match.format_name}\n"
                        f"**Simulateur :** {match.simulator}\n"
                        f"**Type :** BO{match.best_of}\n\n"
                        "À la fin du duel, l'un des deux joueurs utilise :\n"
                        "`/result_casual mon_score:... "
                        "score_adversaire:...`\n\n"
                        "Le premier résultat valide clôt immédiatement "
                        "le match. Hamtaro retirera ensuite les deux "
                        "joueurs et archivera le fil."
                    ),
                    colour=discord.Colour.blurple(),
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )

            match = await self.service.attach_thread(
                match_id=match.id,
                thread_id=str(thread.id),
            )

            if interaction.message is not None:
                try:
                    await interaction.message.edit(
                        embed=self._accepted_embed(match, thread),
                        view=CasualSearchView(self, disabled=True),
                    )
                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ):
                    LOGGER.warning(
                        "Le match casual %s est créé, mais l'annonce "
                        "publique n'a pas pu être verrouillée.",
                        match.id,
                    )

        except ValueError as error:
            if thread is not None:
                await self._delete_failed_thread(thread)
            if claimed:
                await self.service.rollback_claim(
                    match_id=match_id,
                    opponent_id=opponent_id,
                )
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return
        except Exception:
            LOGGER.exception(
                "Erreur pendant l'acceptation du match casual %s",
                match_id,
            )
            if thread is not None:
                await self._delete_failed_thread(thread)
            if claimed:
                await self.service.rollback_claim(
                    match_id=match_id,
                    opponent_id=opponent_id,
                )
            await interaction.followup.send(
                "❌ Hamtaro n'a pas pu préparer ce match.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Match accepté. Ton fil privé est prêt : {thread.mention}",
            ephemeral=True,
        )

    @staticmethod
    async def _delete_failed_thread(thread: discord.Thread) -> None:
        try:
            await thread.delete(
                reason="Hamtaro : création du match casual annulée."
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    # ==========================================================
    # FERMETURE ET NOTIFICATIONS
    # ==========================================================

    async def _update_public_message(
        self,
        guild: discord.Guild,
        match: CasualMatch,
    ) -> None:
        message = await self._public_message(guild, match)
        if message is None:
            return

        embed = (
            self._completed_embed(match)
            if match.status is CasualMatchStatus.COMPLETED
            else self._cancelled_embed(match)
        )
        try:
            await message.edit(
                embed=embed,
                view=CasualSearchView(self, disabled=True),
            )
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            LOGGER.warning(
                "Impossible de mettre à jour l'annonce casual %s.",
                match.id,
            )

    async def _notify_players_by_dm(self, match: CasualMatch) -> None:
        if match.status is not CasualMatchStatus.COMPLETED:
            return

        embed = self._completed_embed(match)
        for user_id in match.participant_ids:
            try:
                user = self.bot.get_user(int(user_id))
                if user is None:
                    user = await self.bot.fetch_user(int(user_id))
                await user.send(embed=embed)
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                continue

    async def _close_thread(
        self,
        guild: discord.Guild,
        match: CasualMatch,
    ) -> None:
        thread = await self._thread(guild, match.thread_id)
        if thread is None:
            return

        for user_id in match.participant_ids:
            try:
                await thread.remove_user(discord.Object(id=int(user_id)))
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                LOGGER.warning(
                    "Impossible de retirer %s du fil casual %s.",
                    user_id,
                    thread.id,
                )

        try:
            await thread.edit(
                locked=True,
                archived=True,
                reason=(
                    "Hamtaro : match casual terminé, "
                    "accès joueurs retiré."
                ),
            )
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            LOGGER.exception(
                "Impossible d'archiver le fil casual %s.",
                thread.id,
            )

    # ==========================================================
    # COMMANDES
    # ==========================================================

    @app_commands.command(
        name="casual",
        description="Chercher un adversaire pour un match casual",
    )
    @app_commands.describe(
        bo="Nombre maximal de manches du match",
        format_duel="Format Yu-Gi-Oh! utilisé",
        simulateur="Plateforme ou simulateur utilisé",
    )
    @app_commands.choices(
        bo=[
            app_commands.Choice(name="BO1", value=1),
            app_commands.Choice(name="BO3", value=3),
            app_commands.Choice(name="BO5", value=5),
        ]
    )
    async def casual(
        self,
        interaction: discord.Interaction,
        bo: app_commands.Choice[int],
        format_duel: str,
        simulateur: str,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            channel = await self._casual_channel(guild)
            bot_member = guild.me
            if bot_member is None and self.bot.user is not None:
                bot_member = guild.get_member(self.bot.user.id)
            if bot_member is None:
                raise ValueError(
                    "Hamtaro ne retrouve pas son propre membre Discord."
                )

            missing_permissions = self._missing_bot_permissions(
                channel,
                bot_member,
            )
            if missing_permissions:
                raise ValueError(
                    "Permissions manquantes pour Hamtaro dans le salon "
                    f"{channel.mention} : "
                    + ", ".join(missing_permissions)
                    + "."
                )

            match = await self.service.create_search(
                guild_id=str(guild.id),
                channel_id=str(channel.id),
                requester_id=str(interaction.user.id),
                requester_name=interaction.user.display_name,
                format_name=format_duel,
                simulator=simulateur,
                best_of=bo.value,
            )
        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        try:
            message = await channel.send(
                embed=self._search_embed(match),
                view=CasualSearchView(self),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
            match = await self.service.attach_public_message(
                match_id=match.id,
                message_id=str(message.id),
            )
        except Exception:
            await self.service.delete_unpublished_search(match.id)
            LOGGER.exception(
                "Impossible de publier la recherche casual %s.",
                match.id,
            )
            await interaction.followup.send(
                "❌ Hamtaro n'a pas pu publier la recherche.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Recherche casual `#{match.id}` publiée dans "
            f"{channel.mention}.",
            ephemeral=True,
        )

    @casual.autocomplete("format_duel")
    async def format_duel_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        del interaction
        return _autocomplete_values(current, FORMAT_SUGGESTIONS)

    @casual.autocomplete("simulateur")
    async def simulateur_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        del interaction
        return _autocomplete_values(current, SIMULATOR_SUGGESTIONS)

    @app_commands.command(
        name="result_casual",
        description="Enregistrer et clôturer un match casual",
    )
    @app_commands.describe(
        mon_score="Ton nombre de manches gagnées",
        score_adversaire="Nombre de manches gagnées par l'adversaire",
        match_id="Facultatif dans le fil privé ; requis ailleurs",
    )
    async def result_casual(
        self,
        interaction: discord.Interaction,
        mon_score: app_commands.Range[int, 0, 3],
        score_adversaire: app_commands.Range[int, 0, 3],
        match_id: int | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        match: CasualMatch | None = None
        if match_id is not None:
            match = await self.service.get_match(match_id)
        elif isinstance(interaction.channel, discord.Thread):
            match = await self.service.get_match_by_thread(
                guild_id=str(guild.id),
                thread_id=str(interaction.channel.id),
            )

        if match is None:
            await interaction.followup.send(
                "❌ Match casual introuvable. Utilise la commande dans "
                "son fil privé ou indique `match_id`.",
                ephemeral=True,
            )
            return

        try:
            completed = await self.service.complete_match(
                match_id=match.id,
                guild_id=str(guild.id),
                reporter_id=str(interaction.user.id),
                reporter_score=int(mon_score),
                opponent_score=int(score_adversaire),
            )
        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        thread = await self._thread(guild, completed.thread_id)
        if thread is not None:
            try:
                await thread.send(embed=self._completed_embed(completed))
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                pass

        # La confirmation est envoyée avant le retrait du joueur du fil.
        await interaction.followup.send(
            "✅ Résultat enregistré. Le fil privé va être fermé et "
            "l'accès des deux joueurs va être retiré.",
            ephemeral=True,
        )

        await self._update_public_message(guild, completed)
        await self._notify_players_by_dm(completed)
        await self._close_thread(guild, completed)

    @app_commands.command(
        name="cancel_casual",
        description="Annuler une recherche ou un match casual",
    )
    @app_commands.describe(
        match_id=(
            "Identifiant du match ; facultatif pour ta recherche active"
        )
    )
    async def cancel_casual(
        self,
        interaction: discord.Interaction,
        match_id: int | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        match = (
            await self.service.get_match(match_id)
            if match_id is not None
            else await self.service.active_match_for_player(
                guild_id=str(guild.id),
                user_id=str(interaction.user.id),
            )
        )
        if match is None:
            await interaction.followup.send(
                "❌ Aucun match casual correspondant.",
                ephemeral=True,
            )
            return

        try:
            cancelled = await self.service.cancel_match(
                match_id=match.id,
                guild_id=str(guild.id),
                actor_id=str(interaction.user.id),
                actor_is_staff=self._is_staff(interaction.user),
            )
        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        await self._update_public_message(guild, cancelled)
        if cancelled.thread_id is not None:
            await self._close_thread(guild, cancelled)

        await interaction.followup.send(
            f"✅ Match casual `#{cancelled.id}` annulé.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CasualMatchesCog(bot))


def _safe_thread_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip())
    return cleaned.strip("-_")[:24] or "joueur"


def _autocomplete_values(
    current: str,
    suggestions: tuple[str, ...],
) -> list[app_commands.Choice[str]]:
    current = current.strip()
    lowered = current.casefold()
    values = [
        value
        for value in suggestions
        if lowered in value.casefold()
    ]

    if current and all(
        current.casefold() != value.casefold()
        for value in values
    ):
        values.insert(0, current)

    return [
        app_commands.Choice(name=value[:100], value=value[:100])
        for value in values[:25]
    ]
