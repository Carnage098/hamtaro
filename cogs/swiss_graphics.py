from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.swiss_image_service import SwissImageService
from utils.tournament_resolver import (
    tournament_code_autocomplete,
    resolve_tournament,
)


class SwissGraphicsCog(commands.Cog):
    """Commandes d'images pour les rondes suisses Hamtaro."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db
        self.renderer = SwissImageService(self.db)

    async def _required_tournament(
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

    async def _send_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await interaction.followup.send(f"❌ {error}", ephemeral=True)

    @app_commands.command(
        name="swiss_round_image",
        description="Générer l'image des pairings d'une ronde suisse",
    )
    @app_commands.describe(
        ronde="Numéro de ronde à afficher, sinon la ronde actuelle",
        code="Code facultatif du tournoi",
        visible="Publier l'image pour tout le serveur",
    )
    @app_commands.autocomplete(
        code=tournament_code_autocomplete
    )
    async def swiss_round_image(
        self,
        interaction: discord.Interaction,
        ronde: int | None = None,
        code: str | None = None,
        visible: bool = True,
    ) -> None:
        await interaction.response.defer(ephemeral=not visible)

        try:
            tournament = await self._required_tournament(interaction, code)
            if ronde is not None and ronde < 1:
                raise ValueError("Le numéro de ronde doit être supérieur ou égal à 1.")

            output = await self.renderer.render_round(tournament, ronde)
            settings = await self.db.get_swiss_settings(tournament.id)
            displayed_round = ronde or int(settings["current_round"])
            filename = f"hamtaro_swiss_ronde_{displayed_round}.png"
        except (ValueError, RuntimeError) as error:
            await self._send_error(interaction, error)
            return

        await interaction.followup.send(
            content=f"🐹 **Ronde suisse {displayed_round}**",
            file=discord.File(output, filename=filename),
            ephemeral=not visible,
        )

    @app_commands.command(
        name="swiss_standings_image",
        description="Générer l'image du classement suisse actuel",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi",
        visible="Publier l'image pour tout le serveur"
    )
    @app_commands.autocomplete(
        code=tournament_code_autocomplete
    )
    async def swiss_standings_image(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
        visible: bool = True,
    ) -> None:
        await interaction.response.defer(ephemeral=not visible)

        try:
            tournament = await self._required_tournament(interaction, code)
            output = await self.renderer.render_standings(tournament)
        except (ValueError, RuntimeError) as error:
            await self._send_error(interaction, error)
            return

        await interaction.followup.send(
            content="🏆 **Classement actuel des rondes suisses**",
            file=discord.File(output, filename="hamtaro_swiss_classement.png"),
            ephemeral=not visible,
        )

    @app_commands.command(
        name="swiss_final_image",
        description="Générer l'image du classement final suisse",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi",
        visible="Publier l'image pour tout le serveur"
    )
    @app_commands.autocomplete(
        code=tournament_code_autocomplete
    )
    async def swiss_final_image(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
        visible: bool = True,
    ) -> None:
        await interaction.response.defer(ephemeral=not visible)

        try:
            tournament = await self._required_tournament(
                interaction,
                code,
                require_active=False,
            )
            settings = await self.db.get_swiss_settings(tournament.id)
            if settings is None:
                raise ValueError("Les rondes suisses ne sont pas lancées.")
            if str(settings["status"]).lower() != "finished":
                raise ValueError(
                    "Les rondes suisses ne sont pas encore terminées. "
                    "Utilise /swiss_standings_image pour le classement actuel."
                )
            output = await self.renderer.render_final(tournament)
        except (ValueError, RuntimeError) as error:
            await self._send_error(interaction, error)
            return

        await interaction.followup.send(
            content="🏆 **Classement final des rondes suisses**",
            file=discord.File(output, filename="hamtaro_swiss_classement_final.png"),
            ephemeral=not visible,
        )

    @app_commands.command(
        name="swiss_preview",
        description="Prévisualiser un rendu graphique suisse",
    )
    @app_commands.describe(
        mode="Type de rendu à prévisualiser",
        code="Code facultatif du tournoi"
    )
    @app_commands.autocomplete(
        code=tournament_code_autocomplete
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Ronde actuelle", value="round"),
            app_commands.Choice(name="Classement actuel", value="standings"),
            app_commands.Choice(name="Classement final", value="final"),
        ]
    )
    @app_commands.default_permissions(manage_guild=True)
    async def swiss_preview(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        code: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            tournament = await self._required_tournament(
                interaction,
                code,
                require_active=mode.value != "final",
            )
            if mode.value == "round":
                output = await self.renderer.render_round(tournament)
                filename = "preview_swiss_round.png"
            elif mode.value == "standings":
                output = await self.renderer.render_standings(tournament)
                filename = "preview_swiss_standings.png"
            else:
                output = await self.renderer.render_final(tournament)
                filename = "preview_swiss_final.png"
        except (ValueError, RuntimeError) as error:
            await self._send_error(interaction, error)
            return

        await interaction.followup.send(
            content=f"🧪 Prévisualisation : **{mode.name}**",
            file=discord.File(output, filename=filename),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SwissGraphicsCog(bot))
