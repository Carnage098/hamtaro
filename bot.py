import os
import discord

from discord.ext import commands

from config import TOKEN

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():

    print("---------------------")
    print("🐹 Hamtaro connecté")
    print(bot.user)
    print("---------------------")

    await bot.load_extension("cogs.registration")
    await bot.load_extension("cogs.tournament")
    await bot.load_extension("cogs.results")
    await bot.load_extension("cogs.statistics")
    await bot.load_extension("cogs.admin")
    await bot.load_extension("cogs.profile")

    synced = await bot.tree.sync()

    print(f"{len(synced)} commandes synchronisées")


bot.run(TOKEN)
