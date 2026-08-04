from __future__ import annotations
from discord.ext import commands

class PublicRoundsCog(commands.Cog):
    """Marqueur de la mise à jour web des rondes Hamtaro."""
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PublicRoundsCog(bot))
