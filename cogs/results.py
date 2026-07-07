from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from services.bracket_service import BracketService


class ResultsCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot
        self.db = bot.db
        self.brackets = BracketService(self.db)

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

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )

                return

            if match_id is None:

                match = await self.db.get_next_match_for_player(
                    tournament_id=tournament.id,
                    discord_id=str(interaction.user.id),
                )

                if match is None:

                    await interaction.followup.send(
                        "❌ Aucun match actif trouvé. Utilise `/nextmatch` ou indique un `match_id`.",
                        ephemeral=True,
                    )

                    return

                match_id = match.id

            match = await self.db.get_match(
                match_id
            )

            if match is None:

                await interaction.followup.send(
                    "❌ Match introuvable.",
                    ephemeral=True,
                )

                return

            is_player = str(interaction.user.id) in (
                match.player1_id,
                match.player2_id,
            )

            if not is_player and not self._is_staff(interaction):

                await interaction.followup.send(
                    "❌ Tu ne peux reporter que le résultat de ton propre match.",
                    ephemeral=True,
                )

                return

            reported = await self.brackets.report_result(
                match_id=match_id,
                player1_score=player1_score,
                player2_score=player2_score,
                reported_by=str(interaction.user.id),
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            (
                "✅ **Résultat reporté !**\n\n"
                f"Match ID : `{reported.id}`\n"
                f"Score : `{reported.score}`\n"
                f"Vainqueur déclaré : **{reported.winner_name}**\n\n"
                "⏳ En attente de validation staff."
            ),
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

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        message = (
            "✅ **Résultat validé !**\n\n"
            f"Match ID : `{match.id}`\n"
            f"Score : `{match.score}`\n"
            f"Vainqueur : **{match.winner_name}**"
        )

        if winner is not None:

            _, winner_name = winner

            message += (
                "\n\n"
                f"🏆 **Tournoi terminé !**\n"
                f"Champion : **{winner_name}**"
            )

        elif current_round is not None:

            message += (
                "\n\n"
                f"Round actuel : `{current_round}`"
            )

        if tournament is not None:

            message += (
                f"\nTournoi : **{tournament.name}**"
            )

        await interaction.followup.send(
            message,
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

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            (
                "✅ **Résultat refusé.**\n\n"
                f"Match ID : `{match.id}`\n"
                "Le match est de nouveau jouable."
            ),
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

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )

                return

            text = await self.brackets.format_reported_matches(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            text,
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

            await self.brackets.sync_current_round(
                completed.tournament_id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            (
                "✅ **Victoire administrative validée.**\n\n"
                f"Match ID : `{completed.id}`\n"
                f"Vainqueur : **{completed.winner_name}**\n"
                f"Score : `{completed.score}`"
            ),
            ephemeral=False,
        )


async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        ResultsCog(bot)
    )
