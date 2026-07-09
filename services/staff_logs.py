from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from services.admin_log_service import AdminLogService

from utils.embeds import info_embed, error_embed
from utils.permissions import staff_only


class StaffLogsCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.logs = AdminLogService()

    def _guild_id(
        self,
        interaction: discord.Interaction,
    ) -> str:
        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(interaction.guild.id)

    async def _send_error(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
    ):
        embed = error_embed(
            title=title,
            description=description,
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
            )

    def _format_log(
        self,
        row,
        index: int,
    ) -> str:
        actor = row["actor_name"] or "Staff inconnu"
        action = row["action"] or "Action inconnue"
        target = row["target_name"]
        tournament = row["tournament_name"]
        details = row["details"]
        created_at = row["created_at"]

        line = (
            f"**{index}. `{action}`**\n"
            f"👤 Staff : **{actor}**\n"
        )

        if target:
            line += f"🎯 Cible : **{target}**\n"

        if tournament:
            line += f"🏆 Tournoi : **{tournament}**\n"

        if details:
            line += f"📝 Détails : {details}\n"

        line += f"🕒 Date : `{created_at}`"

        return line

    @app_commands.command(
        name="admin_logs",
        description="Voir les dernières actions staff Hamtaro"
    )
    @app_commands.describe(
        limit="Nombre de logs à afficher, maximum 25"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_logs(
        self,
        interaction: discord.Interaction,
        limit: int = 10,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            guild_id = self._guild_id(
                interaction
            )

            limit = max(
                1,
                min(limit, 25),
            )

            rows = await self.logs.list_recent(
                guild_id=guild_id,
                limit=limit,
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Erreur",
                description=str(error),
            )
            return

        if not rows:
            embed = info_embed(
                title="Aucun log staff",
                description="Aucune action staff n'a encore été enregistrée.",
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )
            return

        lines = [
            self._format_log(row, index)
            for index, row in enumerate(rows, start=1)
        ]

        embed = info_embed(
            title="Logs staff Hamtaro",
            description="\n\n".join(lines),
        )

        embed.set_footer(
            text=f"{len(rows)} action(s) affichée(s)"
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
):
    service = AdminLogService()

    await service.init_table()

    await bot.add_cog(
        StaffLogsCog(bot)
    )
