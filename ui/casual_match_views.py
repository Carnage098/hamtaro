from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from cogs.casual_matches import CasualMatchesCog


CASUAL_FOOTER_PREFIX = "HAMTARO_CASUAL:"


def match_id_from_message(message: discord.Message | None) -> int | None:
    if message is None or not message.embeds:
        return None

    footer = message.embeds[0].footer.text or ""
    if not footer.startswith(CASUAL_FOOTER_PREFIX):
        return None

    raw_match_id = footer.removeprefix(CASUAL_FOOTER_PREFIX).strip()
    try:
        return int(raw_match_id)
    except ValueError:
        return None


class CasualSearchView(discord.ui.View):
    """Vue persistante utilisée par toutes les recherches casual."""

    def __init__(
        self,
        cog: "CasualMatchesCog",
        *,
        disabled: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.cog = cog

        if disabled:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

    @discord.ui.button(
        label="Accepter",
        emoji="⚔️",
        style=discord.ButtonStyle.success,
        custom_id="hamtaro:casual:accept",
    )
    async def accept(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        match_id = match_id_from_message(interaction.message)
        if match_id is None:
            await interaction.response.send_message(
                "❌ Hamtaro ne retrouve pas cette recherche.",
                ephemeral=True,
            )
            return
        await self.cog.accept_from_button(interaction, match_id)

    @discord.ui.button(
        label="Refuser",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
        custom_id="hamtaro:casual:decline",
    )
    async def decline(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        match_id = match_id_from_message(interaction.message)
        if match_id is None:
            await interaction.response.send_message(
                "❌ Hamtaro ne retrouve pas cette recherche.",
                ephemeral=True,
            )
            return
        await self.cog.decline_from_button(interaction, match_id)
