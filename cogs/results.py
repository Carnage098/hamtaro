from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from services.bracket_service import BracketService
from services.match_history_service import MatchHistoryService

from utils.embeds import success_embed, error_embed, info_embed


class ResultsCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.db = bot.db
        self.brackets = BracketService(self.db)
        self.history = MatchHistoryService()

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
        permissions = getattr(
            interaction.user,
            "guild_permissions",
            None,
        )

        if permissions is None:
            return False

        return bool(
            permissions.manage_guild
            or permissions.administrator
        )

    async def _get_active_tournament(
        self,
        interaction: discord.Interaction,
    ):
        guild_id = self._guild_id(interaction)

        return await self.db.get_active_tournament(
            guild_id
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

        Important :
        si l'historique échoue, on ne bloque pas la validation du résultat.
        Le tournoi doit continuer même si la table history a un souci.
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

    # ==========================================================
    # REPORT RESULT
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
                    title="Aucun tournoi actif",
                    description="Il n'y a actuellement aucun tournoi actif.",
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

        embed = success_embed(
            title="Résultat reporté",
            description=(
                "Le résultat a bien été envoyé.\n\n"
                "⏳ Il est maintenant en attente de validation staff."
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

            match = await self.brackets.approve_result(
                match_id=match_id,
                validated_by=str(interaction.user.id),
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
            match = await self.brackets.reject_result(
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
    # ==========================================================

    @app_commands.command(
        name="pending_results",
        description="Voir les résultats en attente de validation"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
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
                    title="Aucun tournoi actif",
                    description="Il n'y a actuellement aucun tournoi actif.",
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
