from __future__ import annotations

import discord

from discord.ext import commands

from config import TOKEN
from database import init_db

from services.database_service import DatabaseService


COGS = [
    "cogs.registration",
    "cogs.tournament",
    "cogs.bracket",
    "cogs.results",
    "cogs.profile",
    "cogs.admin",
    "cogs.swiss",
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