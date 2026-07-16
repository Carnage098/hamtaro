from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from services.bracket_service import BracketService
from utils.tournament_resolver import (
    active_tournament_code_autocomplete,
    tournament_code_autocomplete,
    resolve_tournament,
)


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

    def _guild_id(self, interaction: discord.Interaction) -> str:
        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(interaction.guild.id)

    async def _resolve_tournament(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
        *,
        require_active: bool = True,
    ):
        return await resolve_tournament(
            interaction,
            self.db,
            code=code,
            require_active=require_active,
        )

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

            if interaction.channel_id is not None:
                await self.db.select_tournament_for_channel(
                    guild_id=guild_id,
                    channel_id=str(interaction.channel_id),
                    tournament_id=int(tournament.id),
                    selected_by=str(interaction.user.id),
                )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🏆 Tournoi créé",
            description=(
                "Les inscriptions sont maintenant ouvertes.\n"
                "Ce tournoi a été sélectionné automatiquement dans ce salon."
            ),
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
            text="Inscris-toi avec /register. Le staff lancera le tournoi quand les inscriptions seront terminées."
        )

        await interaction.followup.send(
            embed=embed,
        )

    # ==========================================================
    # VOIR TOURNOI ACTIF
    # ==========================================================

    @app_commands.command(
        name="tournament",
        description="Voir le tournoi sélectionné dans ce salon"
    )
    @app_commands.describe(
        code="Code facultatif du tournoi à afficher"
    )
    @app_commands.autocomplete(
        code=tournament_code_autocomplete
    )
    async def tournament(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ):
        await interaction.response.defer(
            ephemeral=False
        )

        try:
            tournament = await self._resolve_tournament(
                interaction,
                code,
                require_active=False,
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

        embed = discord.Embed(
            title="🏆 Tournoi sélectionné",
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
        description="Lancer le tournoi sélectionné"
    )
    @app_commands.describe(
        code="Code facultatif du tournoi à lancer"
    )
    @app_commands.autocomplete(
        code=active_tournament_code_autocomplete
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def start_tournament(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._resolve_tournament(
                interaction,
                code,
            )

            if tournament is None:
                await interaction.followup.send(
                    "❌ Aucun tournoi actif trouvé.",
                    ephemeral=True,
                )
                return

            status = tournament.status.value

            if status == "running":
                await interaction.followup.send(
                    "❌ Le tournoi est déjà lancé.",
                    ephemeral=True,
                )
                return

            if status != "registration":
                await interaction.followup.send(
                    "❌ Le tournoi doit être en phase d'inscription pour être lancé.",
                    ephemeral=True,
                )
                return

            await self.brackets.generate(
                tournament.id
            )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        except Exception as error:
            print(
                "ERREUR /start_tournament :",
                error,
            )

            await interaction.followup.send(
                f"❌ Erreur pendant le lancement du tournoi : `{error}`",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Tournoi `{tournament.code}` lancé avec succès.",
            ephemeral=True,
        )

    # ==========================================================
    # ANNULER TOURNOI
    # ==========================================================

    @app_commands.command(
        name="cancel_tournament",
        description="Annuler le tournoi sélectionné"
    )
    @app_commands.describe(
        code="Code facultatif du tournoi à annuler"
    )
    @app_commands.autocomplete(
        code=active_tournament_code_autocomplete
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def cancel_tournament(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._resolve_tournament(
                interaction,
                code,
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
            f"✅ Tournoi `{tournament.code}` annulé.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(
        TournamentCog(bot)
    )
