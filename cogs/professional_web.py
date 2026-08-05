from __future__ import annotations

import logging

from discord.ext import commands


LOGGER = logging.getLogger(__name__)


class ProfessionalWebCompatibilityCog(commands.Cog):
    """
    Module conservé uniquement pour compatibilité.

    Les routes staff sont maintenant intégrées directement dans
    cogs.public_website via services.staff_dashboard_routes.
    Aucun patch de classe et aucun redémarrage du serveur ne sont effectués.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    LOGGER.warning(
        "cogs.professional_web est obsolète : "
        "les routes staff sont intégrées directement à public_website."
    )
    await bot.add_cog(ProfessionalWebCompatibilityCog(bot))
