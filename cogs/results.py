from __future__ import annotations

import os
import re

import discord

from discord.ext import commands
from discord import app_commands

from services.bracket_service import BracketService
from services.match_history_service import MatchHistoryService

from utils.embeds import success_embed, error_embed, info_embed
from utils.permissions import staff_only, is_staff_member
from utils.tournament_resolver import resolve_tournament


VALIDATION_RESULTS_CHANNEL_ENV = "VALIDATION_RESULTS_CHANNEL_ID"
MATCH_ID_FOOTER_PREFIX = "HAMTARO_MATCH_ID:"


class RejectResultModal(discord.ui.Modal):
    """Fenêtre facultative permettant au staff d'indiquer un motif de refus."""

    def __init__(
        self,
        cog: "ResultsCog",
        match_id: int,
        source_message: discord.Message,
    ):
        super().__init__(title=f"Refuser le résultat #{match_id}")

        self.cog = cog
        self.match_id = match_id
        self.source_message = source_message

        self.notes = discord.ui.TextInput(
            label="Motif du refus",
            placeholder="Exemple : score incorrect ou confirmation manquante",
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.notes)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            match = await self.cog._reject_reported_match(
                match_id=self.match_id,
                validated_by=str(interaction.user.id),
                notes=str(self.notes.value).strip() or None,
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
                "❌ Erreur pendant le refus du résultat "
                f"#{self.match_id} : {error}"
            )

            await interaction.followup.send(
                embed=error_embed(
                    title="Erreur inattendue",
                    description=(
                        "Le résultat n'a pas pu être refusé. "
                        "Consulte les logs de Hamtaro."
                    ),
                ),
                ephemeral=True,
            )
            return

        disabled_view = ResultValidationView(
            self.cog,
            disabled=True,
        )

        embed = self.cog._copy_validation_embed(
            self.source_message,
            title="❌ Résultat refusé",
            colour=discord.Colour.red(),
        )

        embed.add_field(
            name="❌ Refusé par",
            value=interaction.user.mention,
            inline=True,
        )

        if self.notes.value:
            embed.add_field(
                name="📝 Motif",
                value=str(self.notes.value),
                inline=False,
            )

        embed.set_footer(
            text=(
                f"{MATCH_ID_FOOTER_PREFIX}{match.id} | "
                "Le match est de nouveau jouable"
            )
        )

        try:
            await self.source_message.edit(
                embed=embed,
                view=disabled_view,
            )
        except discord.HTTPException as error:
            print(
                "⚠️ Résultat refusé, mais impossible de modifier "
                f"le message de validation : {error}"
            )

        await interaction.followup.send(
            embed=info_embed(
                title="Résultat refusé",
                description=(
                    f"Le résultat du match `{match.id}` a été refusé.\n"
                    "Le match est de nouveau jouable."
                ),
            ),
            ephemeral=True,
        )


class ResultValidationView(discord.ui.View):
    """
    Boutons persistants du salon de validation.

    Le match_id n'est pas conservé dans l'objet Python : il est lu dans le
    footer de l'embed. La même vue peut donc être réenregistrée après un
    redémarrage du bot et continuer à traiter les anciens messages.
    """

    def __init__(
        self,
        cog: "ResultsCog",
        disabled: bool = False,
    ):
        super().__init__(timeout=None)
        self.cog = cog

        if disabled:
            self.disable_all_buttons()

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "❌ Cette action doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return False

        if not is_staff_member(interaction.user):
            await interaction.response.send_message(
                "❌ Seuls les membres du staff peuvent traiter ce résultat.",
                ephemeral=True,
            )
            return False

        return True

    def disable_all_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    @discord.ui.button(
        label="Valider",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="hamtaro:result_validation:approve",
    )
    async def approve_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        match_id = self.cog._extract_match_id_from_message(
            interaction.message
        )

        if match_id is None:
            await interaction.response.send_message(
                embed=error_embed(
                    title="Match introuvable",
                    description=(
                        "Hamtaro ne parvient pas à retrouver l'ID du match "
                        "dans ce message."
                    ),
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            guild_id = self.cog._guild_id(interaction)

            (
                match,
                tournament,
                current_round,
                winner,
            ) = await self.cog._approve_reported_match(
                match_id=match_id,
                validated_by=str(interaction.user.id),
                guild_id=guild_id,
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
            print(
                "❌ Erreur pendant la validation du résultat "
                f"#{match_id} : {error}"
            )

            await interaction.followup.send(
                embed=error_embed(
                    title="Erreur inattendue",
                    description=(
                        "Le résultat n'a pas pu être validé. "
                        "Consulte les logs de Hamtaro."
                    ),
                ),
                ephemeral=True,
            )
            return

        disabled_view = ResultValidationView(
            self.cog,
            disabled=True,
        )

        embed = self.cog._copy_validation_embed(
            interaction.message,
            title="✅ Résultat validé",
            colour=discord.Colour.green(),
        )

        embed.add_field(
            name="✅ Validé par",
            value=interaction.user.mention,
            inline=True,
        )

        if tournament is not None:
            embed.add_field(
                name="🏟️ Tournoi",
                value=f"**{tournament.name}**",
                inline=False,
            )

        if winner is not None:
            _, winner_name = winner
            embed.add_field(
                name="👑 Tournoi terminé",
                value=f"Champion : **{winner_name}**",
                inline=False,
            )

        elif current_round is not None:
            embed.add_field(
                name="🔄 Round actuel",
                value=f"`{current_round}`",
                inline=False,
            )

        embed.set_footer(
            text=(
                f"{MATCH_ID_FOOTER_PREFIX}{match.id} | "
                "Résultat appliqué au tournoi"
            )
        )

        if interaction.message is not None:
            try:
                await interaction.message.edit(
                    embed=embed,
                    view=disabled_view,
                )
            except discord.HTTPException as error:
                print(
                    "⚠️ Résultat validé, mais impossible de modifier "
                    f"le message de validation : {error}"
                )

        await interaction.followup.send(
            embed=success_embed(
                title="Résultat validé",
                description=(
                    f"Le résultat du match `{match.id}` a été validé "
                    "et appliqué au tournoi."
                ),
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Refuser",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="hamtaro:result_validation:reject",
    )
    async def reject_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        match_id = self.cog._extract_match_id_from_message(
            interaction.message
        )

        if match_id is None or interaction.message is None:
            await interaction.response.send_message(
                embed=error_embed(
                    title="Match introuvable",
                    description=(
                        "Hamtaro ne parvient pas à retrouver l'ID du match "
                        "dans ce message."
                    ),
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            RejectResultModal(
                cog=self.cog,
                match_id=match_id,
                source_message=interaction.message,
            )
        )


class ResultsCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.db = bot.db
        self.brackets = BracketService(self.db)
        self.history = MatchHistoryService()

    async def cog_load(self) -> None:
        """Réactive les boutons persistants au démarrage de Hamtaro."""
        self.bot.add_view(
            ResultValidationView(self)
        )

    # ==========================================================
    # OUTILS INTERNES
    # ==========================================================

    def _guild_id(
        self,
        interaction: discord.Interaction,
    ) -> str:
        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(interaction.guild.id)

    def _is_staff(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        return is_staff_member(
            interaction.user
        )

    async def _get_active_tournament(
        self,
        interaction: discord.Interaction,
    ):
        return await resolve_tournament(
            interaction,
            self.db,
        )

    async def _send_error(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        ephemeral: bool = True,
    ):
        embed = error_embed(
            title=title,
            description=description,
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                embed=embed,
                ephemeral=ephemeral,
            )
        else:
            await interaction.response.send_message(
                embed=embed,
                ephemeral=ephemeral,
            )

    def _get_validation_channel_id(self) -> int | None:
        raw_channel_id = os.getenv(
            VALIDATION_RESULTS_CHANNEL_ENV,
            "",
        ).strip()

        if not raw_channel_id:
            return None

        try:
            channel_id = int(raw_channel_id)
        except ValueError:
            print(
                "⚠️ VALIDATION_RESULTS_CHANNEL_ID doit contenir "
                "uniquement l'identifiant numérique du salon."
            )
            return None

        if channel_id <= 0:
            return None

        return channel_id

    async def _get_validation_channel(self):
        channel_id = self._get_validation_channel_id()

        if channel_id is None:
            return None

        channel = self.bot.get_channel(channel_id)

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ) as error:
                print(
                    "⚠️ Impossible de récupérer le salon de validation "
                    f"{channel_id} : {error}"
                )
                return None

        if not hasattr(channel, "send"):
            print(
                "⚠️ VALIDATION_RESULTS_CHANNEL_ID ne correspond pas "
                "à un salon dans lequel Hamtaro peut envoyer un message."
            )
            return None

        return channel

    def _player_display(
        self,
        guild: discord.Guild | None,
        discord_id: str | None,
        fallback_name: str | None,
    ) -> str:
        if discord_id is not None and guild is not None:
            try:
                member = guild.get_member(int(discord_id))
            except (TypeError, ValueError):
                member = None

            if member is not None:
                return f"{member.mention}\n`{member.id}`"

        name = fallback_name or "Joueur inconnu"

        if discord_id is None:
            return f"**{name}**"

        return f"**{name}**\n`{discord_id}`"

    def _extract_match_id_from_message(
        self,
        message: discord.Message | None,
    ) -> int | None:
        if message is None or not message.embeds:
            return None

        footer_text = message.embeds[0].footer.text or ""
        pattern = rf"{re.escape(MATCH_ID_FOOTER_PREFIX)}\s*(\d+)"
        match = re.search(pattern, footer_text)

        if match is None:
            return None

        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _copy_validation_embed(
        self,
        message: discord.Message | None,
        title: str,
        colour: discord.Colour,
    ) -> discord.Embed:
        if message is not None and message.embeds:
            embed = discord.Embed.from_dict(
                message.embeds[0].to_dict()
            )
        else:
            embed = discord.Embed()

        embed.title = title
        embed.colour = colour
        return embed

    async def _send_result_to_validation_channel(
        self,
        interaction: discord.Interaction,
        tournament,
        reported,
    ) -> bool:
        channel = await self._get_validation_channel()

        if channel is None:
            print(
                "⚠️ Résultat enregistré, mais aucun salon de validation "
                "n'est configuré. Ajoute VALIDATION_RESULTS_CHANNEL_ID "
                "dans Railway."
            )
            return False

        round_number = getattr(
            reported,
            "round_number",
            None,
        )

        if round_number is None:
            round_number = getattr(
                reported,
                "round",
                None,
            )

        tournament_id = getattr(
            reported,
            "tournament_id",
            getattr(tournament, "id", None),
        )

        player1_id = getattr(reported, "player1_id", None)
        player2_id = getattr(reported, "player2_id", None)
        winner_id = getattr(reported, "winner_id", None)

        player1_name = getattr(reported, "player1_name", None)
        player2_name = getattr(reported, "player2_name", None)
        winner_name = getattr(reported, "winner_name", None)

        embed = discord.Embed(
            title="⏳ Résultat en attente de validation",
            description=(
                "Un résultat vient d'être déclaré. "
                "Le staff doit le valider ou le refuser."
            ),
            colour=discord.Colour.orange(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="🏟️ Tournoi",
            value=f"**{getattr(tournament, 'name', 'Tournoi Hamtaro')}**",
            inline=False,
        )

        embed.add_field(
            name="🆔 Tournoi ID",
            value=f"`{tournament_id}`" if tournament_id is not None else "Inconnu",
            inline=True,
        )

        embed.add_field(
            name="🔄 Ronde",
            value=f"`{round_number}`" if round_number is not None else "Inconnue",
            inline=True,
        )

        embed.add_field(
            name="🆔 Match ID",
            value=f"`{reported.id}`",
            inline=True,
        )

        embed.add_field(
            name="👤 Joueur 1",
            value=self._player_display(
                guild=interaction.guild,
                discord_id=player1_id,
                fallback_name=player1_name,
            ),
            inline=True,
        )

        embed.add_field(
            name="👤 Joueur 2",
            value=self._player_display(
                guild=interaction.guild,
                discord_id=player2_id,
                fallback_name=player2_name,
            ),
            inline=True,
        )

        embed.add_field(
            name="🏆 Vainqueur déclaré",
            value=self._player_display(
                guild=interaction.guild,
                discord_id=winner_id,
                fallback_name=winner_name,
            ),
            inline=False,
        )

        embed.add_field(
            name="📊 Score",
            value=f"`{getattr(reported, 'score', 'Non renseigné')}`",
            inline=True,
        )

        embed.add_field(
            name="📨 Déclaré par",
            value=interaction.user.mention,
            inline=True,
        )

        avatar = interaction.user.display_avatar
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=avatar.url,
        )

        embed.set_footer(
            text=(
                f"{MATCH_ID_FOOTER_PREFIX}{reported.id} | "
                "En attente du staff"
            )
        )

        try:
            await channel.send(
                embed=embed,
                view=ResultValidationView(self),
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            print(
                "⚠️ Résultat enregistré, mais Hamtaro n'a pas pu "
                f"l'envoyer dans le salon de validation : {error}"
            )
            return False

        return True

    async def _get_registration_deck(
        self,
        tournament_id: int,
        discord_id: str | None,
    ) -> str | None:
        if discord_id is None:
            return None

        try:
            registration = await self.db.get_registration_by_user(
                tournament_id=tournament_id,
                discord_id=str(discord_id),
            )

        except (ValueError, AttributeError):
            return None

        if registration is None:
            return None

        return getattr(
            registration,
            "deck",
            None,
        )

    async def _record_match_history(
        self,
        guild_id: str,
        match,
        status: str = "approved",
    ) -> None:
        """
        Enregistre un match dans l'historique.

        Si l'historique échoue, on ne bloque pas la validation du résultat.
        Le tournoi doit continuer même si la table d'historique a un souci.
        """

        try:
            tournament_id = getattr(
                match,
                "tournament_id",
                None,
            )

            if tournament_id is None:
                return

            player1_id = getattr(
                match,
                "player1_id",
                None,
            )

            player2_id = getattr(
                match,
                "player2_id",
                None,
            )

            player1_name = getattr(
                match,
                "player1_name",
                None,
            )

            player2_name = getattr(
                match,
                "player2_name",
                None,
            )

            winner_id = getattr(
                match,
                "winner_id",
                None,
            )

            winner_name = getattr(
                match,
                "winner_name",
                None,
            )

            score = getattr(
                match,
                "score",
                None,
            )

            round_number = getattr(
                match,
                "round_number",
                None,
            )

            if round_number is None:
                round_number = getattr(
                    match,
                    "round",
                    None,
                )

            player1_deck = await self._get_registration_deck(
                tournament_id=tournament_id,
                discord_id=player1_id,
            )

            player2_deck = await self._get_registration_deck(
                tournament_id=tournament_id,
                discord_id=player2_id,
            )

            await self.history.record_match(
                guild_id=guild_id,
                tournament_id=tournament_id,
                match_id=getattr(match, "id", None),
                round_number=round_number,
                player1_id=player1_id,
                player1_name=player1_name,
                player2_id=player2_id,
                player2_name=player2_name,
                winner_id=winner_id,
                winner_name=winner_name,
                score=score,
                player1_deck=player1_deck,
                player2_deck=player2_deck,
                status=status,
            )

        except Exception as error:
            print(
                f"⚠️ Impossible d'enregistrer l'historique du match : {error}"
            )

    async def _approve_reported_match(
        self,
        match_id: int,
        validated_by: str,
        guild_id: str,
        notes: str | None = None,
    ):
        match = await self.brackets.approve_result(
            match_id=match_id,
            validated_by=validated_by,
            guild_id=guild_id,
            notes=notes,
        )

        await self._record_match_history(
            guild_id=guild_id,
            match=match,
            status="approved",
        )

        tournament = await self.db.get_tournament(
            match.tournament_id
        )

        current_round = await self.brackets.sync_current_round(
            match.tournament_id
        )

        winner = await self.brackets.get_winner(
            match.tournament_id
        )

        return match, tournament, current_round, winner

    async def _reject_reported_match(
        self,
        match_id: int,
        validated_by: str,
        notes: str | None = None,
    ):
        return await self.brackets.reject_result(
            match_id=match_id,
            validated_by=validated_by,
            notes=notes,
        )

    # ==========================================================
    # REPORT RESULT
    # Joueurs autorisés :
    # - les deux joueurs du match
    # - le staff
    # ==========================================================

    @app_commands.command(
        name="result",
        description="Reporter le résultat de ton match"
    )
    @app_commands.describe(
        player1_score="Score du joueur 1",
        player2_score="Score du joueur 2",
        match_id="ID du match, facultatif si tu n'as qu'un match actif"
    )
    async def result(
        self,
        interaction: discord.Interaction,
        player1_score: int,
        player2_score: int,
        match_id: int | None = None,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            if match_id is None:
                match = await self.db.get_next_match_for_player(
                    tournament_id=tournament.id,
                    discord_id=str(interaction.user.id),
                )

                if match is None:
                    await self._send_error(
                        interaction=interaction,
                        title="Aucun match actif",
                        description=(
                            "Aucun match actif trouvé.\n\n"
                            "Utilise `/nextmatch` ou indique un `match_id`."
                        ),
                    )
                    return

                match_id = match.id

            match = await self.db.get_match(
                match_id
            )

            if match is None:
                await self._send_error(
                    interaction=interaction,
                    title="Match introuvable",
                    description="Le match demandé est introuvable.",
                )
                return

            is_player = str(interaction.user.id) in (
                match.player1_id,
                match.player2_id,
            )

            if not is_player and not self._is_staff(interaction):
                await self._send_error(
                    interaction=interaction,
                    title="Action refusée",
                    description=(
                        "Tu ne peux reporter que le résultat de ton propre match."
                    ),
                )
                return

            reported = await self.brackets.report_result(
                match_id=match_id,
                player1_score=player1_score,
                player2_score=player2_score,
                reported_by=str(interaction.user.id),
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Résultat impossible",
                description=str(error),
            )
            return

        sent_to_staff = await self._send_result_to_validation_channel(
            interaction=interaction,
            tournament=tournament,
            reported=reported,
        )

        if sent_to_staff:
            status_text = (
                "📨 Hamtaro l'a envoyé dans le salon "
                "`✅・validation-résultats`."
            )
        else:
            status_text = (
                "⚠️ Le résultat est enregistré, mais Hamtaro n'a pas pu "
                "l'envoyer dans le salon staff. Vérifie la variable "
                "`VALIDATION_RESULTS_CHANNEL_ID` et ses permissions."
            )

        embed = success_embed(
            title="Résultat reporté",
            description=(
                "Le résultat a bien été enregistré.\n\n"
                "⏳ Il est maintenant en attente de validation staff.\n"
                f"{status_text}"
            ),
        )

        embed.add_field(
            name="🆔 Match ID",
            value=f"`{reported.id}`",
            inline=True,
        )

        embed.add_field(
            name="📊 Score",
            value=f"`{reported.score}`",
            inline=True,
        )

        embed.add_field(
            name="🏆 Vainqueur déclaré",
            value=f"**{reported.winner_name}**",
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # APPROVE RESULT
    # Staff uniquement
    # ==========================================================

    @app_commands.command(
        name="approve_result",
        description="Valider un résultat reporté"
    )
    @app_commands.describe(
        match_id="ID du match à valider",
        notes="Note staff facultative"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def approve_result(
        self,
        interaction: discord.Interaction,
        match_id: int,
        notes: str | None = None,
    ):
        await interaction.response.defer(
            ephemeral=False
        )

        try:
            guild_id = self._guild_id(interaction)

            (
                match,
                tournament,
                current_round,
                winner,
            ) = await self._approve_reported_match(
                match_id=match_id,
                validated_by=str(interaction.user.id),
                guild_id=guild_id,
                notes=notes,
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Validation impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Résultat validé",
            description="Le résultat a été approuvé par le staff.",
        )

        embed.add_field(
            name="🆔 Match ID",
            value=f"`{match.id}`",
            inline=True,
        )

        embed.add_field(
            name="📊 Score",
            value=f"`{match.score}`",
            inline=True,
        )

        embed.add_field(
            name="🏆 Vainqueur",
            value=f"**{match.winner_name}**",
            inline=False,
        )

        if tournament is not None:
            embed.add_field(
                name="🏟️ Tournoi",
                value=f"**{tournament.name}**",
                inline=False,
            )

        if winner is not None:
            _, winner_name = winner

            embed.add_field(
                name="👑 Tournoi terminé",
                value=f"Champion : **{winner_name}**",
                inline=False,
            )

        elif current_round is not None:
            embed.add_field(
                name="🔄 Round actuel",
                value=f"`{current_round}`",
                inline=False,
            )

        embed.set_footer(
            text="Match enregistré dans l'historique Hamtaro"
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=False,
        )

    # ==========================================================
    # REJECT RESULT
    # Staff uniquement
    # ==========================================================

    @app_commands.command(
        name="reject_result",
        description="Refuser un résultat reporté"
    )
    @app_commands.describe(
        match_id="ID du match à refuser",
        notes="Raison du refus"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def reject_result(
        self,
        interaction: discord.Interaction,
        match_id: int,
        notes: str | None = None,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            match = await self._reject_reported_match(
                match_id=match_id,
                validated_by=str(interaction.user.id),
                notes=notes,
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Refus impossible",
                description=str(error),
            )
            return

        embed = info_embed(
            title="Résultat refusé",
            description=(
                "Le résultat a été refusé par le staff.\n\n"
                "Le match est de nouveau jouable."
            ),
        )

        embed.add_field(
            name="🆔 Match ID",
            value=f"`{match.id}`",
            inline=True,
        )

        if notes:
            embed.add_field(
                name="📝 Note staff",
                value=notes,
                inline=False,
            )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # PENDING RESULTS
    # Staff uniquement
    # ==========================================================

    @app_commands.command(
        name="pending_results",
        description="Voir les résultats en attente de validation"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def pending_results(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            text = await self.brackets.format_reported_matches(
                tournament.id
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Erreur",
                description=str(error),
            )
            return

        embed = info_embed(
            title="Résultats en attente",
            description=text or "Aucun résultat en attente de validation.",
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # ADMIN WIN
    # Staff uniquement
    # ==========================================================

    @app_commands.command(
        name="admin_win",
        description="Donner une victoire administrative"
    )
    @app_commands.describe(
        match_id="ID du match",
        winner="Joueur gagnant",
        notes="Raison de la décision staff"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_win(
        self,
        interaction: discord.Interaction,
        match_id: int,
        winner: discord.Member,
        notes: str | None = None,
    ):
        await interaction.response.defer(
            ephemeral=False
        )

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

            await self._record_match_history(
                guild_id=guild_id,
                match=completed,
                status="approved",
            )

            current_round = await self.brackets.sync_current_round(
                completed.tournament_id
            )

            tournament = await self.db.get_tournament(
                completed.tournament_id
            )

            final_winner = await self.brackets.get_winner(
                completed.tournament_id
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Victoire administrative impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Victoire administrative validée",
            description="Le staff a validé une victoire administrative.",
        )

        embed.add_field(
            name="🆔 Match ID",
            value=f"`{completed.id}`",
            inline=True,
        )

        embed.add_field(
            name="🏆 Vainqueur",
            value=f"**{completed.winner_name}**",
            inline=True,
        )

        embed.add_field(
            name="📊 Score",
            value=f"`{completed.score}`",
            inline=True,
        )

        if notes:
            embed.add_field(
                name="📝 Note staff",
                value=notes,
                inline=False,
            )

        if tournament is not None:
            embed.add_field(
                name="🏟️ Tournoi",
                value=f"**{tournament.name}**",
                inline=False,
            )

        if final_winner is not None:
            _, final_winner_name = final_winner

            embed.add_field(
                name="👑 Tournoi terminé",
                value=f"Champion : **{final_winner_name}**",
                inline=False,
            )

        elif current_round is not None:
            embed.add_field(
                name="🔄 Round actuel",
                value=f"`{current_round}`",
                inline=False,
            )

        embed.set_footer(
            text="Match enregistré dans l'historique Hamtaro"
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=False,
        )


async def setup(
    bot: commands.Bot,
):
    service = MatchHistoryService()

    await service.init_table()

    await bot.add_cog(
        ResultsCog(bot)
    )
