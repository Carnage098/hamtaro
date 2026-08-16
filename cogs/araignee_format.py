from __future__ import annotations

import io
import os

import discord
from discord import app_commands
from discord.ext import commands

from services.araignee_format_service import AraigneeFormatService


class AraigneeFormatCog(commands.Cog):
    araignee = app_commands.Group(
        name="araignee",
        description="Règles et outils du Format Araignée",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = AraigneeFormatService()

    def _site_url(self) -> str:
        return os.getenv("WEBSITE_BASE_URL", "").strip().rstrip("/")

    @araignee.command(
        name="rules",
        description="Afficher les règles du Format Araignée",
    )
    async def rules(self, interaction: discord.Interaction) -> None:
        data = self.service.data()
        main = data["main_deck"]
        extra = data["extra_deck"]
        side = data["side_deck"]

        embed = discord.Embed(
            title="🕷️ Format Araignée",
            description=data["description"],
            color=discord.Color.dark_purple(),
        )
        embed.add_field(
            name="Main Deck",
            value=(
                f"• exactement **{main['exact_cards']} cartes**\n"
                f"• **{main['spider_min']} à {main['spider_max']}** cartes Araignée\n"
                f"• un seul archétype secondaire : "
                f"**{main['secondary_archetype_min']} à "
                f"{main['secondary_archetype_max']} cartes**\n"
                "• maximum 2 archétypes : Araignée + secondaire\n"
                "• génériques uniquement via la whitelist du format"
            ),
            inline=False,
        )
        embed.add_field(
            name="Extra & Side",
            value=(
                f"• Extra Deck libre jusqu'à **{extra['max_cards']} cartes**\n"
                f"• Side Deck : **{side['exact_cards']} cartes**, uniquement "
                "de l'archétype secondaire déclaré"
            ),
            inline=False,
        )
        embed.add_field(
            name="Tournoi & banlists",
            value=(
                "• archétype secondaire verrouillé pendant tout le tournoi\n"
                "• Banlist TCG + banlist spéciale du Format Araignée"
            ),
            inline=False,
        )
        embed.add_field(
            name="Pool officiel",
            value=(
                f"**{len(self.service.pool())} cartes** · "
                f"révision `{self.service.pool_revision()}`"
            ),
            inline=False,
        )

        site = self._site_url()
        if site:
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label="Ouvrir la fiche du format",
                    url=f"{site}/formats/araignee",
                    emoji="🕷️",
                )
            )
        else:
            view = None

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )

    @araignee.command(
        name="pool",
        description="Télécharger la liste officielle des cartes Araignée",
    )
    async def pool(self, interaction: discord.Interaction) -> None:
        content = "\n".join(
            f"{index}. {card}"
            for index, card in enumerate(self.service.pool(), start=1)
        )
        file = discord.File(
            io.BytesIO(content.encode("utf-8")),
            filename="pool_format_araignee.txt",
        )
        await interaction.response.send_message(
            (
                f"🕷️ Pool officiel : **{len(self.service.pool())} cartes** "
                f"· révision `{self.service.pool_revision()}`."
            ),
            file=file,
            ephemeral=True,
        )

    @araignee.command(
        name="check",
        description="Vérifier une decklist du Format Araignée",
    )
    @app_commands.describe(
        decklist=(
            "Decklist en noms de cartes. Sections Main/Extra/Side acceptées."
        ),
    )
    async def check(
        self,
        interaction: discord.Interaction,
        decklist: str,
    ) -> None:
        try:
            result = self.service.validate_text(decklist)
        except ValueError as error:
            await interaction.response.send_message(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=(
                "✅ Deck conforme aux contrôles automatiques"
                if result.valid
                else "❌ Deck non conforme"
            ),
            color=(
                discord.Color.green()
                if result.valid
                else discord.Color.red()
            ),
        )
        embed.add_field(
            name="Main",
            value=f"**{result.main_count}/40**",
            inline=True,
        )
        embed.add_field(
            name="Araignée",
            value=f"**{result.spider_count}/10–15**",
            inline=True,
        )
        embed.add_field(
            name="Extra / Side",
            value=f"**{result.extra_count}/15 · {result.side_count}/3**",
            inline=True,
        )

        if result.matched_cards:
            text = "\n".join(
                f"• {item['quantity']}× {item['name']}"
                for item in result.matched_cards
            )
            embed.add_field(
                name="Cartes Araignée reconnues",
                value=text[:1024],
                inline=False,
            )

        if result.errors:
            embed.add_field(
                name="À corriger",
                value="\n".join(
                    f"• {error}" for error in result.errors
                )[:1024],
                inline=False,
            )

        if result.suggestions:
            embed.add_field(
                name="Noms proches du pool",
                value="\n".join(
                    f"• `{item['entered']}` → **{item['suggested']}**"
                    for item in result.suggestions
                )[:1024],
                inline=False,
            )

        if result.warnings:
            embed.add_field(
                name="À savoir",
                value="\n".join(
                    f"• {warning}" for warning in result.warnings
                )[:1024],
                inline=False,
            )

        embed.set_footer(
            text=f"Pool Araignée · révision {self.service.pool_revision()}"
        )
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    @araignee.command(
        name="card",
        description="Vérifier si une carte appartient au pool Araignée",
    )
    @app_commands.describe(nom="Nom de la carte à rechercher")
    async def card(
        self,
        interaction: discord.Interaction,
        nom: str,
    ) -> None:
        normalized = self.service.normalize_name(nom)
        pool = self.service.normalized_pool()
        exact = pool.get(normalized)

        if exact:
            await interaction.response.send_message(
                f"✅ **{exact}** appartient au pool officiel Araignée.",
                ephemeral=True,
            )
            return

        from difflib import get_close_matches

        close = get_close_matches(
            normalized,
            list(pool.keys()),
            n=3,
            cutoff=0.72,
        )
        if close:
            suggestions = "\n".join(
                f"• {pool[item]}" for item in close
            )
            message = (
                "❌ Cette écriture n'est pas dans le pool officiel.\n"
                f"Noms proches :\n{suggestions}"
            )
        else:
            message = "❌ Cette carte n'appartient pas au pool officiel Araignée."

        await interaction.response.send_message(
            message,
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AraigneeFormatCog(bot))
