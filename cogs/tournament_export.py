from __future__ import annotations

import io

import discord
from discord import app_commands
from discord.ext import commands

from services.analytics_service import AnalyticsService
from utils.permissions import staff_only

try:
    from utils.tournament_resolver import tournament_code_autocomplete
except ImportError:
    async def tournament_code_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return []


class TournamentExportCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.analytics = AnalyticsService()

    @app_commands.command(
        name="export_tournament",
        description="Exporter toutes les données d'un tournoi en CSV ou JSON",
    )
    @app_commands.describe(
        format_export="Format du fichier",
        code="Code du tournoi, sinon le tournoi actif ou le plus récent",
    )
    @app_commands.choices(
        format_export=[
            app_commands.Choice(name="CSV — archive ZIP", value="csv"),
            app_commands.Choice(name="JSON — fichier complet", value="json"),
        ]
    )
    @app_commands.autocomplete(code=tournament_code_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def export_tournament(
        self,
        interaction: discord.Interaction,
        format_export: app_commands.Choice[str],
        code: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if interaction.guild is None:
            await interaction.followup.send(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild.id)
        if code:
            tournament = await self.analytics.get_tournament_by_code(guild_id, code)
        else:
            tournament = await self.analytics.get_latest_tournament(guild_id)
        if tournament is None:
            await interaction.followup.send(
                "❌ Aucun tournoi n’a été trouvé sur ce serveur.",
                ephemeral=True,
            )
            return

        try:
            payload, filename = await self.analytics.build_tournament_export(
                guild_id=guild_id,
                tournament_id=int(tournament["id"]),
                export_format=format_export.value,
            )
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        file = discord.File(io.BytesIO(payload), filename=filename)
        explanation = (
            "L’archive ZIP contient plusieurs fichiers CSV séparés : tournoi, joueurs, "
            "matchs, statistiques des decks et données administratives disponibles."
            if format_export.value == "csv"
            else "Le fichier JSON contient le tournoi et toutes les catégories de données disponibles."
        )
        embed = discord.Embed(
            title="📤 Export Hamtaro terminé",
            description=(
                f"Tournoi : **{tournament['name']}** (`{tournament['code']}`)\n"
                f"Format : **{format_export.name}**\n\n{explanation}"
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text="Commande réservée au staff · Le fichier peut contenir des identifiants Discord.")
        await interaction.followup.send(embed=embed, file=file, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentExportCog(bot))
