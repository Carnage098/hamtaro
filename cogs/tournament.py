from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from services.bracket_service import BracketService
from models.enums import TournamentStatus


FORMATS = [
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
]


class TournamentCog(commands.Cog):

    def __init__(self, bot: commands.Bot):

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

    # ==========================================================
    # CRÉATION TOURNOI
    # ==========================================================

    @app_commands.command(
        name="create_tournament",
        description="Créer un tournoi Hamtaro"
    )
    @app_commands.describe(
        name="Nom du tournoi",
        format="Format du tournoi",
        max_players="Nombre maximum de joueurs"
    )
    @app_commands.choices(
        format=[
            app_commands.Choice(
                name=format_name,
                value=format_name,
            )
            for format_name in FORMATS
        ]
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def create_tournament(
        self,
        interaction: discord.Interaction,
        name: str,
        format: app_commands.Choice[str],
        max_players: int,
    ):

        await interaction.response.defer(
            ephemeral=False
        )

        try:

            guild_id = self._guild_id(interaction)

            tournament = await self.db.create_tournament(
                guild_id=guild_id,
                name=name,
                format=format.value,
                max_players=max_players,
                created_by=str(interaction.user.id),
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        embed = discord.Embed(
            title="🏆 Tournoi créé",
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Nom",
            value=tournament.name,
            inline=False,
        )

        embed.add_field(
            name="Format",
            value=tournament.format,
            inline=True,
        )

        embed.add_field(
            name="Code",
            value=f"`{tournament.code}`",
            inline=True,
        )

        embed.add_field(
            name="Joueurs",
            value=f"0/{tournament.max_players}",
            inline=True,
        )

        embed.add_field(
            name="Statut",
            value="📋 Inscriptions ouvertes",
            inline=False,
        )

        embed.set_footer(
            text="Utilise /register pour t'inscrire."
        )

        await interaction.followup.send(
            embed=embed,
        )

    # ==========================================================
    # VOIR TOURNOI ACTIF
    # ==========================================================

    @app_commands.command(
        name="tournament",
        description="Voir le tournoi actif"
    )
    async def tournament(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=False
        )

        try:

            guild_id = self._guild_id(interaction)

            tournament = await self.db.get_active_tournament(
                guild_id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        if tournament is None:

            await interaction.followup.send(
                "❌ Aucun tournoi actif sur ce serveur.",
                ephemeral=True,
            )

            return

        registered = await self.db.count_registrations(
            tournament.id
        )

        checked_in = await self.db.count_checked_in(
            tournament.id
        )

        embed = discord.Embed(
            title="🏆 Tournoi actif",
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Nom",
            value=tournament.name,
            inline=False,
        )

        embed.add_field(
            name="Format",
            value=tournament.format,
            inline=True,
        )

        embed.add_field(
            name="Code",
            value=f"`{tournament.code}`",
            inline=True,
        )

        embed.add_field(
            name="Statut",
            value=tournament.status.value,
            inline=True,
        )

        embed.add_field(
            name="Inscriptions",
            value=f"{registered}/{tournament.max_players}",
            inline=True,
        )

        embed.add_field(
            name="Check-in",
            value=str(checked_in),
            inline=True,
        )

        embed.add_field(
            name="Round actuel",
            value=str(tournament.current_round),
            inline=True,
        )

        await interaction.followup.send(
            embed=embed,
        )

    # ==========================================================
    # LANCER TOURNOI
    # ==========================================================

    @app_commands.command(
        name="start_tournament",
        description="Lancer le tournoi et générer le bracket"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def start_tournament(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=False
        )

        try:

            guild_id = self._guild_id(interaction)

            tournament = await self.db.get_active_tournament(
                guild_id
            )

            if tournament is None:
                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )
                return

            error = await self.brackets.get_start_error(
                tournament.id
            )

            if error is not None:
                await interaction.followup.send(
                    f"❌ {error}",
                    ephemeral=True,
                )
                return

            await self.brackets.generate_bracket(
                tournament.id,
                shuffle=True,
                force=False,
            )

            text = await self.brackets.format_current_round(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ **Tournoi lancé !**\n\n{text}"
        )

    # ==========================================================
    # LISTE DES TOURNOIS
    # ==========================================================

    @app_commands.command(
        name="tournament_list",
        description="Lister les tournois du serveur"
    )
    async def tournament_list(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        try:

            guild_id = self._guild_id(interaction)

            tournaments = await self.db.list_tournaments(
                guild_id,
                include_finished=True,
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        if not tournaments:

            await interaction.followup.send(
                "❌ Aucun tournoi trouvé.",
                ephemeral=True,
            )

            return

        lines = []

        for tournament in tournaments[:10]:

            lines.append(
                f"🏆 **{tournament.name}** — `{tournament.code}` "
                f"({tournament.format}) — `{tournament.status.value}`"
            )

        await interaction.followup.send(
            "\n".join(lines),
            ephemeral=True,
        )

    # ==========================================================
    # ANNULER TOURNOI
    # ==========================================================

    @app_commands.command(
        name="cancel_tournament",
        description="Annuler le tournoi actif"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def cancel_tournament(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        try:

            guild_id = self._guild_id(interaction)

            tournament = await self.db.get_active_tournament(
                guild_id
            )

            if tournament is None:

                await interaction.followup.send(
                    "❌ Aucun tournoi actif à annuler.",
                    ephemeral=True,
                )

                return

            await self.brackets.cancel_tournament(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            "✅ Tournoi annulé.",
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        TournamentCog(bot)
    )