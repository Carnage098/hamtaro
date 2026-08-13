from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.archetype_repair_service import ArchetypeRepairService
from utils.permissions import staff_only


class ArchetypeRepairCog(commands.Cog):
    archetype_repair = app_commands.Group(
        name="archetype_repair",
        description="Diagnostic et réparation de la méta Archétypes",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = ArchetypeRepairService()

    @archetype_repair.command(
        name="preview",
        description="Prévisualiser les alias/doublons qui seront fusionnés",
    )
    @staff_only()
    async def preview(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        report = await self.service.preview(str(interaction.guild.id))

        embed = discord.Embed(
            title="🔎 Diagnostic Archétypes",
            description=(
                f"**{report['change_count']}** inscription(s) seront renommées.\n"
                f"**{report['merged_group_count']}** groupe(s) d'alias seront fusionnés."
            ),
            color=discord.Color.blurple(),
        )
        examples = report["changes"][:15]
        if examples:
            lines = [
                f"`{item['before']}` → **{item['after']}**"
                for item in examples
            ]
            embed.add_field(
                name="Exemples",
                value="\n".join(lines),
                inline=False,
            )
        if report["change_count"] > len(examples):
            embed.set_footer(
                text=(
                    f"+ {report['change_count'] - len(examples)} "
                    "autre(s) modification(s)"
                )
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @archetype_repair.command(
        name="apply",
        description="Réparer les anciens noms de decks après sauvegarde SQLite",
    )
    @app_commands.describe(
        confirmer="Doit être activé pour appliquer réellement les modifications"
    )
    @staff_only()
    async def apply(
        self,
        interaction: discord.Interaction,
        confirmer: bool = False,
    ) -> None:
        if interaction.guild is None:
            return
        if not confirmer:
            await interaction.response.send_message(
                "⚠️ Lance d'abord `/archetype_repair preview`, puis relance "
                "`/archetype_repair apply` avec **confirmer: True**.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        report = await self.service.apply(str(interaction.guild.id))

        embed = discord.Embed(
            title="✅ Archétypes réparés",
            description=(
                f"**{report['change_count']}** inscription(s) normalisées.\n"
                f"**{report['artwork_changes']}** état(s) d'artwork fusionné(s).\n"
                f"**{report['proposal_changes']}** proposition(s) d'artwork ajustée(s)."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name="🛡️ Sauvegarde",
            value=f"`{report['backup_path']}`",
            inline=False,
        )
        embed.set_footer(
            text="Recharge /archetypes après le redéploiement ou quelques secondes."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ArchetypeRepairCog(bot))
