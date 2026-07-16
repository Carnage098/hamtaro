from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from services.swiss_service import SwissService
from utils.tournament_resolver import resolve_tournament


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

        return await resolve_tournament(
            interaction,
            self.db,
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
                "Aucun tournoi sélectionné."
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

    async def _report_double_loss(
        self,
        match,
        reported_by: str,
    ) -> None:
        """Enregistre un double loss via le service central de base de données."""

        if int(match["is_bye"] or 0) == 1 or match["player2_id"] is None:
            raise ValueError("Impossible de mettre un double loss sur un BYE.")

        await self.db.report_swiss_double_loss(
            match_id=int(match["id"]),
            reported_by=reported_by,
        )

    def _empty_player_stats(
        self,
        discord_id: str,
        username: str,
    ) -> dict:

        return {
            "discord_id": discord_id,
            "username": username,
            "points": 0,
            "wins": 0,
            "losses": 0,
            "double_losses": 0,
            "byes": 0,
            "matches_played": 0,
        }

    def _ensure_player_in_standings(
        self,
        standings: dict[str, dict],
        discord_id: str | None,
        username: str | None,
    ) -> None:

        if discord_id is None:
            return

        discord_id = str(discord_id)

        if username is None:
            username = "Joueur inconnu"

        if discord_id not in standings:
            standings[discord_id] = self._empty_player_stats(
                discord_id=discord_id,
                username=str(username),
            )

    async def _format_standings_with_double_loss(
        self,
        tournament_id: int,
    ) -> str:
        """Formate le classement calculé par DatabaseService."""

        ranked_players = await self.db.get_swiss_standings(tournament_id)

        if not ranked_players:
            raise ValueError("Aucun joueur inscrit pour calculer le classement.")

        lines = ["🏆 **Classement des rondes suisses**", "", "```"]

        for index, player in enumerate(ranked_players, start=1):
            lines.append(
                f"{index:>2}. {player['username']} — {player['points']} pts | "
                f"{player['wins']}V / {player['losses']}D / "
                f"{player['double_losses']}DL / {player['byes']}BYE"
            )

        lines.extend([
            "```",
            "",
            "`DL` = double loss : 0 point pour les deux joueurs et pénalité au départage.",
        ])
        return "\n".join(lines)

    # ==========================================================
    # START
    # ==========================================================

    @app_commands.command(
        name="swiss_start",
        description="Lancer les rondes suisses pour le tournoi sélectionné"
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
                name="Double loss",
                value="double_loss",
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

            if resultat.value == "double_loss":

                await self._report_double_loss(
                    match=match,
                    reported_by=str(interaction.user.id),
                )

            else:

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

        if resultat.value == "double_loss":

            await interaction.followup.send(
                f"⏱️ **Double loss validé pour la table `{table}`.**\n"
                "Les deux joueurs prennent **0 point**.\n"
                "Ce résultat est réservé aux **rondes suisses**.\n\n"
                f"{text}",
                ephemeral=True,
            )

        else:

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

            text = await self._format_standings_with_double_loss(
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
        description="Réinitialiser les rondes suisses du tournoi sélectionné"
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
            "✅ Les rondes suisses du tournoi sélectionné ont été réinitialisées.",
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        SwissCog(bot)
    )
