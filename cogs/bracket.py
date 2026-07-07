from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from services.bracket_service import BracketService


class BracketCog(commands.Cog):

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

    async def _get_active_tournament(
        self,
        interaction: discord.Interaction,
    ):

        guild_id = self._guild_id(interaction)

        return await self.db.get_active_tournament(
            guild_id
        )

    async def _send_text(
        self,
        interaction: discord.Interaction,
        text: str,
        *,
        ephemeral: bool = False,
    ) -> None:
        """
        Envoie un texte Discord en évitant la limite des 2000 caractères.
        """

        if len(text) <= 1900:

            await interaction.followup.send(
                text,
                ephemeral=ephemeral,
            )

            return

        chunks = []

        current = ""

        for line in text.splitlines():

            if len(current) + len(line) + 1 > 1900:

                chunks.append(current)
                current = line

            else:

                current += "\n" + line if current else line

        if current:
            chunks.append(current)

        for chunk in chunks:

            await interaction.followup.send(
                chunk,
                ephemeral=ephemeral,
            )

    # ==========================================================
    # BRACKET COMPLET
    # ==========================================================

    @app_commands.command(
        name="bracket",
        description="Afficher le bracket du tournoi actif"
    )
    async def bracket(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=False
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

            text = await self.brackets.format_bracket(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await self._send_text(
            interaction,
            text,
            ephemeral=False,
        )

    # ==========================================================
    # ROUND ACTUEL
    # ==========================================================

    @app_commands.command(
        name="round",
        description="Afficher le round actuel"
    )
    async def current_round(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=False
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

            text = await self.brackets.format_current_round(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await self._send_text(
            interaction,
            text,
            ephemeral=False,
        )

    # ==========================================================
    # ROUND PRÉCIS
    # ==========================================================

    @app_commands.command(
        name="round_show",
        description="Afficher un round précis du tournoi"
    )
    @app_commands.describe(
        round_number="Numéro du round à afficher"
    )
    async def round_show(
        self,
        interaction: discord.Interaction,
        round_number: int,
    ):

        await interaction.response.defer(
            ephemeral=False
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

            matches = await self.brackets.get_round_matches(
                tournament.id,
                round_number,
            )

            if not matches:

                await interaction.followup.send(
                    "❌ Aucun match trouvé pour ce round.",
                    ephemeral=True,
                )

                return

            text = self.brackets.format_round(
                round_number,
                matches,
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await self._send_text(
            interaction,
            text,
            ephemeral=False,
        )

    # ==========================================================
    # PROCHAIN MATCH
    # ==========================================================

    @app_commands.command(
        name="nextmatch",
        description="Voir ton prochain match"
    )
    async def nextmatch(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member | None = None,
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

            target = joueur or interaction.user

            text = await self.brackets.format_next_match(
                tournament.id,
                str(target.id),
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
    # FINALE
    # ==========================================================

    @app_commands.command(
        name="finale",
        description="Afficher la finale du tournoi"
    )
    async def finale(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=False
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

            text = await self.brackets.format_final(
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
    # MATCHS JOUABLES
    # ==========================================================

    @app_commands.command(
        name="matches",
        description="Afficher les matchs jouables"
    )
    async def matches(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=False
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

            text = await self.brackets.format_ready_matches(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await self._send_text(
            interaction,
            text,
            ephemeral=False,
        )

    # ==========================================================
    # VAINQUEUR
    # ==========================================================

    @app_commands.command(
        name="winner",
        description="Afficher le vainqueur du tournoi"
    )
    async def winner(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=False
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

            winner = await self.brackets.get_winner(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        if winner is None:

            await interaction.followup.send(
                "❌ Le tournoi n'a pas encore de vainqueur.",
                ephemeral=True,
            )

            return

        winner_id, winner_name = winner

        await interaction.followup.send(
            f"🏆 Le vainqueur du tournoi est **{winner_name}** !",
            ephemeral=False,
        )


async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        BracketCog(bot)
    )