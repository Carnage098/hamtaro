from __future__ import annotations

import os
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import DATABASE, DATABASE_BACKUPS_ENABLED
from services.database_maintenance import create_backup, quick_check
from utils.permissions import staff_only


class SystemHealthCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="hamtaro_health",
        description="Vérifier l'état du bot, du site et de la base",
    )
    @staff_only()
    async def hamtaro_health(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        database_ok, database_message = await quick_check()
        started_at = getattr(self.bot, "started_at_monotonic", None)
        uptime_seconds = (
            max(0, int(time.monotonic() - started_at))
            if isinstance(started_at, (int, float))
            else 0
        )
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        loaded = len(self.bot.extensions)
        failed = getattr(self.bot, "failed_extensions", {})
        website_loaded = "cogs.public_website" in self.bot.extensions
        persistent = str(DATABASE).startswith("/data/") or bool(os.getenv("RAILWAY_VOLUME_MOUNT_PATH"))

        embed = discord.Embed(
            title="🐹 État de Hamtaro",
            colour=(
                discord.Colour.green()
                if database_ok and not failed
                else discord.Colour.orange()
            ),
        )
        embed.add_field(
            name="Discord",
            value=(
                f"Connecté : **{'oui' if self.bot.is_ready() else 'non'}**\n"
                f"Latence : **{round(self.bot.latency * 1000)} ms**\n"
                f"Uptime : **{hours} h {minutes} min {seconds} s**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Modules",
            value=(
                f"Chargés : **{loaded}**\n"
                f"Échecs : **{len(failed)}**\n"
                f"Site : **{'actif' if website_loaded else 'inactif'}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Base SQLite",
            value=(
                f"Intégrité : **{'OK' if database_ok else 'ERREUR'}**\n"
                f"Volume persistant : **{'oui' if persistent else 'non'}**\n"
                f"Sauvegardes : **{'actives' if DATABASE_BACKUPS_ENABLED else 'inactives'}**"
            ),
            inline=False,
        )
        if not database_ok:
            embed.add_field(
                name="Détail SQLite",
                value=discord.utils.escape_markdown(database_message)[:1000],
                inline=False,
            )
        if failed:
            names = "\n".join(f"• `{name}`" for name in sorted(failed))
            embed.add_field(
                name="Modules en échec",
                value=names[:1000],
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="hamtaro_backup",
        description="Créer immédiatement une sauvegarde de la base",
    )
    @staff_only()
    async def hamtaro_backup(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        destination = await create_backup(reason="manual")
        if destination is None:
            await interaction.followup.send(
                "ℹ️ Aucune base n'existe encore à sauvegarder.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Sauvegarde créée : `{destination.name}`",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SystemHealthCog(bot))
