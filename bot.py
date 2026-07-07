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


COGS = [

    "cogs.registration",

    "cogs.tournament",

    "cogs.profile",

    "cogs.admin"

]


@bot.event
async def on_ready():

    print("------------------------")

    print("🐹 HAMTARO")

    print(bot.user)

    print("------------------------")

    for cog in COGS:

        try:

            await bot.load_extension(cog)

            print(f"✅ {cog}")

        except Exception as e:

            print(e)

    synced = await bot.tree.sync()

    print(f"{len(synced)} commandes synchronisées")


bot.run(TOKEN)
