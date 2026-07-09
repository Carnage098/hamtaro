from __future__ import annotations

import aiosqlite
import discord

from discord.ext import commands
from discord import app_commands

from database import DATABASE
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

    async def _report_double_loss(
        self,
        match,
        reported_by: str,
    ) -> None:
        """
        Enregistre un double loss uniquement pour une ronde suisse.

        Règle Hamtaro :
        - pas de nul ;
        - double loss seulement en rondes suisses ;
        - 0 point pour les deux joueurs ;
        - pire qu'une défaite normale en cas d'égalité au classement.
        """

        if int(match["is_bye"] or 0) == 1:
            raise ValueError(
                "Impossible de mettre un double loss sur un BYE."
            )

        if match["player2_id"] is None:
            raise ValueError(
                "Impossible de mettre un double loss : il manque le joueur 2."
            )

        if str(match["status"]).lower() == "completed":
            raise ValueError(
                "Ce match suisse est déjà terminé."
            )

        match_id = int(match["id"])

        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("PRAGMA foreign_keys = ON;")

            await db.execute(
                """
                UPDATE swiss_matches
                SET player1_score = 0,
                    player2_score = 0,
                    winner_id = NULL,
                    winner_name = NULL,
                    is_draw = 0,
                    is_double_loss = 1,
                    result = 'double_loss',
                    status = 'completed',
                    reported_by = ?,
                    reported_at = CURRENT_TIMESTAMP,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    reported_by,
                    match_id,
                ),
            )

            await db.commit()

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
        """
        Classement suisse propre avec double loss.

        Tri :
        1. points décroissants ;
        2. double losses croissants ;
        3. victoires décroissantes ;
        4. défaites croissantes ;
        5. nom du joueur.
        """

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT discord_id, username
                FROM registrations
                WHERE tournament_id = ?
                AND dropped = 0
                AND disqualified = 0
                ORDER BY username ASC
                """,
                (tournament_id,),
            )

            registrations = list(await cursor.fetchall())

            cursor = await db.execute(
                """
                SELECT *
                FROM swiss_matches
                WHERE tournament_id = ?
                AND status = 'completed'
                ORDER BY round_number ASC, table_number ASC
                """,
                (tournament_id,),
            )

            matches = list(await cursor.fetchall())

        if not registrations:
            raise ValueError(
                "Aucun joueur inscrit pour calculer le classement."
            )

        standings: dict[str, dict] = {}

        for player in registrations:
            discord_id = str(player["discord_id"])
            username = str(player["username"])

            standings[discord_id] = self._empty_player_stats(
                discord_id=discord_id,
                username=username,
            )

        for match in matches:
            player1_id = match["player1_id"]
            player1_name = match["player1_name"]
            player2_id = match["player2_id"]
            player2_name = match["player2_name"]
            winner_id = match["winner_id"]

            self._ensure_player_in_standings(
                standings=standings,
                discord_id=player1_id,
                username=player1_name,
            )

            self._ensure_player_in_standings(
                standings=standings,
                discord_id=player2_id,
                username=player2_name,
            )

            is_bye = int(match["is_bye"] or 0) == 1
            is_draw = int(match["is_draw"] or 0) == 1

            try:
                is_double_loss = int(match["is_double_loss"] or 0) == 1
            except Exception:
                is_double_loss = False

            try:
                result = str(match["result"] or "none")
            except Exception:
                result = "none"

            if is_bye:
                if player1_id is not None:
                    player1_id = str(player1_id)

                    standings[player1_id]["points"] += 3
                    standings[player1_id]["wins"] += 1
                    standings[player1_id]["byes"] += 1
                    standings[player1_id]["matches_played"] += 1

                continue

            if is_double_loss or result == "double_loss":
                if player1_id is not None:
                    player1_id = str(player1_id)

                    standings[player1_id]["double_losses"] += 1
                    standings[player1_id]["matches_played"] += 1

                if player2_id is not None:
                    player2_id = str(player2_id)

                    standings[player2_id]["double_losses"] += 1
                    standings[player2_id]["matches_played"] += 1

                continue

            if is_draw or result == "draw":
                # Ancienne logique d'égalité supprimée.
                # Si une ancienne égalité existe encore en base,
                # on la traite comme un double loss pour respecter les nouvelles règles.
                if player1_id is not None:
                    player1_id = str(player1_id)

                    standings[player1_id]["double_losses"] += 1
                    standings[player1_id]["matches_played"] += 1

                if player2_id is not None:
                    player2_id = str(player2_id)

                    standings[player2_id]["double_losses"] += 1
                    standings[player2_id]["matches_played"] += 1

                continue

            if winner_id is None:
                continue

            winner_id = str(winner_id)

            if player1_id is not None:
                player1_id = str(player1_id)

            if player2_id is not None:
                player2_id = str(player2_id)

            if winner_id not in standings:
                if winner_id == player1_id:
                    winner_name = player1_name
                elif winner_id == player2_id:
                    winner_name = player2_name
                else:
                    winner_name = "Joueur inconnu"

                self._ensure_player_in_standings(
                    standings=standings,
                    discord_id=winner_id,
                    username=winner_name,
                )

            standings[winner_id]["points"] += 3
            standings[winner_id]["wins"] += 1
            standings[winner_id]["matches_played"] += 1

            if player1_id == winner_id:
                loser_id = player2_id
            else:
                loser_id = player1_id

            if loser_id is not None and loser_id in standings:
                standings[loser_id]["losses"] += 1
                standings[loser_id]["matches_played"] += 1

        ranked_players = sorted(
            standings.values(),
            key=lambda player: (
                -int(player["points"]),
                int(player["double_losses"]),
                -int(player["wins"]),
                int(player["losses"]),
                str(player["username"]).lower(),
            ),
        )

        lines = [
            "🏆 **Classement des rondes suisses**",
            "",
            "```",
        ]

        for index, player in enumerate(ranked_players, start=1):
            username = player["username"]
            points = player["points"]
            wins = player["wins"]
            losses = player["losses"]
            double_losses = player["double_losses"]
            byes = player["byes"]

            lines.append(
                f"{index:>2}. {username} — {points} pts | "
                f"{wins}V / {losses}D / {double_losses}DL / {byes}BYE"
            )

        lines.append("```")
        lines.append("")
        lines.append("`DL` = double loss, donc 0 point et pénalité au classement en cas d'égalité.")

        return "\n".join(lines)

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
