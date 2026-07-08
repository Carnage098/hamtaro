from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from services.swiss_service import SwissService


class SwissCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot
        self.db = bot.db
        self.swiss = SwissService(self.db)

    def _guild_id(
        self,
        interaction: discord.Interaction,
    ) -> str:

        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(interaction.guild.id)

    async def _get_active_tournament(
        self,
        interaction: discord.Interaction,
    ):

        guild_id = self._guild_id(interaction)

        return await self.db.get_active_tournament(
            guild_id
        )

    async def _get_required_tournament(
        self,
        interaction: discord.Interaction,
    ):

        tournament = await self._get_active_tournament(
            interaction
        )

        if tournament is None:
            raise ValueError(
                "Aucun tournoi actif."
            )

        return tournament

    async def _get_match_by_table(
        self,
        tournament_id: int,
        round_number: int,
        table_number: int,
    ):

        return await self.db.fetchone(
            """
            SELECT *
            FROM swiss_matches
            WHERE tournament_id = ?
            AND round_number = ?
            AND table_number = ?
            """,
            (
                tournament_id,
                round_number,
                table_number,
            ),
        )

    # ==========================================================
    # START
    # ==========================================================

    @app_commands.command(
        name="swiss_start",
        description="Lancer les rondes suisses pour le tournoi actif"
    )
    @app_commands.describe(
        rondes="Nombre total de rondes suisses",
        visible="Afficher publiquement la ronde générée"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def swiss_start(
        self,
        interaction: discord.Interaction,
        rondes: int,
        visible: bool = True,
    ):

        await interaction.response.defer(
            ephemeral=not visible
        )

        try:

            tournament = await self._get_required_tournament(
                interaction
            )

            text = await self.swiss.start(
                tournament_id=tournament.id,
                total_rounds=rondes,
                shuffle_first_round=True,
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ **Rondes suisses lancées !**\n\n{text}",
            ephemeral=not visible,
        )

    # ==========================================================
    # PAIRINGS
    # ==========================================================

    @app_commands.command(
        name="swiss_pairings",
        description="Afficher les pairings suisses"
    )
    @app_commands.describe(
        ronde="Numéro de ronde à afficher, optionnel"
    )
    async def swiss_pairings(
        self,
        interaction: discord.Interaction,
        ronde: int | None = None,
    ):

        await interaction.response.defer(
            ephemeral=False
        )

        try:

            tournament = await self._get_required_tournament(
                interaction
            )

            if ronde is None:

                text = await self.swiss.format_current_round(
                    tournament.id
                )

            else:

                text = await self.swiss.format_round(
                    tournament_id=tournament.id,
                    round_number=ronde,
                )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            text,
            ephemeral=False,
        )

    # ==========================================================
    # RESULT
    # ==========================================================

    @app_commands.command(
        name="swiss_result",
        description="Valider le résultat d'une table suisse"
    )
    @app_commands.describe(
        table="Numéro de table",
        resultat="Résultat du match"
    )
    @app_commands.choices(
        resultat=[
            app_commands.Choice(
                name="Victoire joueur 1",
                value="player1",
            ),
            app_commands.Choice(
                name="Victoire joueur 2",
                value="player2",
            ),
            app_commands.Choice(
                name="Égalité",
                value="draw",
            ),
        ]
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def swiss_result(
        self,
        interaction: discord.Interaction,
        table: int,
        resultat: app_commands.Choice[str],
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        if table < 1:

            await interaction.followup.send(
                "❌ Le numéro de table doit être supérieur ou égal à 1.",
                ephemeral=True,
            )

            return

        try:

            tournament = await self._get_required_tournament(
                interaction
            )

            settings = await self.db.get_swiss_settings(
                tournament.id
            )

            if settings is None:

                await interaction.followup.send(
                    "❌ Les rondes suisses ne sont pas lancées.",
                    ephemeral=True,
                )

                return

            current_round = int(settings["current_round"])

            match = await self._get_match_by_table(
                tournament_id=tournament.id,
                round_number=current_round,
                table_number=table,
            )

            if match is None:

                await interaction.followup.send(
                    f"❌ Aucun match trouvé à la table `{table}` pour la ronde `{current_round}`.",
                    ephemeral=True,
                )

                return

            await self.swiss.report_result(
                match_id=match["id"],
                result=resultat.value,
                reported_by=str(interaction.user.id),
            )

            text = await self.swiss.format_current_round(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ Résultat validé pour la table `{table}`.\n\n{text}",
            ephemeral=True,
        )

    # ==========================================================
    # NEXT ROUND
    # ==========================================================

    @app_commands.command(
        name="swiss_next",
        description="Générer la ronde suisse suivante"
    )
    @app_commands.describe(
        visible="Afficher publiquement la nouvelle ronde"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def swiss_next(
        self,
        interaction: discord.Interaction,
        visible: bool = True,
    ):

        await interaction.response.defer(
            ephemeral=not visible
        )

        try:

            tournament = await self._get_required_tournament(
                interaction
            )

            text = await self.swiss.next_round(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ **Nouvelle ronde générée !**\n\n{text}",
            ephemeral=not visible,
        )

    # ==========================================================
    # STANDINGS
    # ==========================================================

    @app_commands.command(
        name="swiss_standings",
        description="Afficher le classement suisse"
    )
    async def swiss_standings(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=False
        )

        try:

            tournament = await self._get_required_tournament(
                interaction
            )

            text = await self.swiss.format_standings(
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
            ephemeral=False,
        )

    # ==========================================================
    # STATUS
    # ==========================================================

    @app_commands.command(
        name="swiss_status",
        description="Afficher le statut des rondes suisses"
    )
    async def swiss_status(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        try:

            tournament = await self._get_required_tournament(
                interaction
            )

            text = await self.swiss.format_status(
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
    # RESET
    # ==========================================================

    @app_commands.command(
        name="swiss_reset",
        description="Réinitialiser les rondes suisses du tournoi actif"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def swiss_reset(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        try:

            tournament = await self._get_required_tournament(
                interaction
            )

            await self.db.reset_swiss_tournament(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            "✅ Les rondes suisses du tournoi actif ont été réinitialisées.",
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        SwissCog(bot)
    )