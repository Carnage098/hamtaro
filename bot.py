from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from config import TOKEN
from database import init_db

from services.database_service import DatabaseService

from utils.permissions import StaffOnly


COGS = [
    "cogs.registration",
    "cogs.tournament",
    "cogs.bracket",
    "cogs.results",
    "cogs.profile",
    "cogs.admin",
    "cogs.swiss",
    "cogs.match_history",
    "cogs.repair",
    "cogs.staff_logs",
    "cogs.tournament_status",
    "cogs.nextmatch",
    "cogs.bracket_full",
    "cogs.end_tournament",
    "cogs.help",
    "graphics_preview.py",
]


class HamtaroBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
        )

        self.db = DatabaseService()

    async def setup_hook(self):
        await init_db()

        await self.db.connect()

        for cog in COGS:
            try:
                await self.load_extension(cog)
                print(f"✅ Cog chargé : {cog}")

            except Exception as error:
                print(f"❌ Erreur chargement {cog} : {error}")

        synced = await self.tree.sync()

        print(f"✅ {len(synced)} commandes synchronisées")

    async def close(self):
        await self.db.close()

        await super().close()


bot = HamtaroBot()


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(error, StaffOnly):
        message = "⛔ Cette commande est réservée au staff."

        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )

        return

    print(f"❌ Erreur slash command : {error}")

    if interaction.response.is_done():
        await interaction.followup.send(
            "❌ Une erreur est survenue pendant l'exécution de la commande.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            "❌ Une erreur est survenue pendant l'exécution de la commande.",
            ephemeral=True,
        )


@bot.event
async def on_ready():
    print("------------------------")
    print("🐹 HAMTARO")
    print(bot.user)
    print("------------------------")


if TOKEN is None:
    raise RuntimeError(
        "DISCORD_TOKEN est introuvable dans les variables d'environnement."
    )


bot.run(TOKEN)
