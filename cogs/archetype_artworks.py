from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.archetype_meta_service import ArchetypeMetaService
from utils.permissions import staff_only


class ArchetypeArtworkCog(commands.Cog):
    artwork = app_commands.Group(
        name="artwork",
        description="Artworks des archétypes et decks affichés sur le site Hamtaro",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = ArchetypeMetaService()

    async def cog_load(self) -> None:
        await self.service.ensure_schema()

    @artwork.command(name="propose", description="Proposer un artwork pour un deck du serveur")
    @app_commands.describe(
        deck="Nom exact du deck tel qu'il apparaît dans Hamtaro",
        carte="Nom de la carte représentée",
        image_url="Facultatif : URL HTTPS. Sinon Hamtaro cherche la carte automatiquement",
    )
    async def propose(
        self,
        interaction: discord.Interaction,
        deck: str,
        carte: str,
        image_url: str | None = None,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Cette commande doit être utilisée sur le serveur.", ephemeral=True
            )
            return
        try:
            proposal_id = await self.service.submit_proposal(
                str(interaction.guild_id),
                deck,
                carte,
                image_url,
                str(interaction.user.id),
                interaction.user.display_name,
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎨 Proposition envoyée",
            description=(
                f"**Deck :** {deck}\n"
                f"**Carte :** {carte}\n"
                f"**Proposition :** #{proposal_id}\n\n"
                "Elle restera en attente jusqu'à validation ou refus du staff."
            ),
        )
        artwork = await self.service.current_artwork(str(interaction.guild_id), deck)
        proposal_rows = await self.service.list_pending(str(interaction.guild_id), limit=100)
        proposal = next((row for row in proposal_rows if int(row["id"]) == proposal_id), None)
        if proposal and proposal.get("image_url"):
            embed.set_image(url=str(proposal["image_url"]))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @artwork.command(name="current", description="Voir l'artwork actuellement utilisé pour un deck")
    @app_commands.describe(deck="Nom du deck")
    async def current(self, interaction: discord.Interaction, deck: str) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Serveur requis.", ephemeral=True)
            return
        artwork = await self.service.current_artwork(str(interaction.guild_id), deck)
        source = "Communauté" if artwork["source"] == "community" else "Hamtaro"
        embed = discord.Embed(
            title=f"🎴 {deck}",
            description=f"**Carte :** {artwork.get('card_name') or 'Non définie'}\n**Source :** {source}",
        )
        if artwork.get("submitted_name"):
            embed.add_field(name="Proposé par", value=str(artwork["submitted_name"]), inline=False)
        image_url = artwork.get("image_url")
        if image_url and str(image_url).startswith("http"):
            embed.set_image(url=str(image_url))
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @artwork.command(name="pending", description="Lister les propositions d'artworks en attente")
    @staff_only()
    async def pending(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Serveur requis.", ephemeral=True)
            return
        rows = await self.service.list_pending(str(interaction.guild_id), limit=25)
        if not rows:
            await interaction.response.send_message(
                "✅ Aucune proposition d'artwork en attente.", ephemeral=True
            )
            return
        lines = [
            f"**#{row['id']}** · {row['deck_name']} → {row['card_name']} · par {row.get('submitted_name') or row['submitted_by']}"
            for row in rows
        ]
        embed = discord.Embed(
            title="🛡️ Artworks en attente",
            description="\n".join(lines),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @artwork.command(name="approve", description="Approuver une proposition d'artwork")
    @staff_only()
    @app_commands.describe(proposition_id="ID affiché dans /artwork pending")
    async def approve(self, interaction: discord.Interaction, proposition_id: int) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Serveur requis.", ephemeral=True)
            return
        try:
            row = await self.service.approve_proposal(
                str(interaction.guild_id), proposition_id, str(interaction.user.id)
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        embed = discord.Embed(
            title="✅ Artwork approuvé",
            description=f"**{row['deck_name']}** utilise maintenant **{row['card_name']}**.",
        )
        embed.set_image(url=row["image_url"])
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @artwork.command(name="reject", description="Refuser une proposition d'artwork")
    @staff_only()
    @app_commands.describe(
        proposition_id="ID affiché dans /artwork pending",
        raison="Motif facultatif du refus",
    )
    async def reject(
        self,
        interaction: discord.Interaction,
        proposition_id: int,
        raison: str | None = None,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Serveur requis.", ephemeral=True)
            return
        try:
            row = await self.service.reject_proposal(
                str(interaction.guild_id),
                proposition_id,
                str(interaction.user.id),
                raison,
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        suffix = f"\n**Raison :** {raison}" if raison else ""
        await interaction.response.send_message(
            f"❌ Proposition **#{proposition_id}** pour **{row['deck_name']}** refusée.{suffix}",
            ephemeral=True,
        )

    @artwork.command(name="default", description="Définir l'artwork Hamtaro par défaut d'un deck")
    @staff_only()
    @app_commands.describe(
        deck="Nom du deck",
        carte="Carte choisie comme représentation officielle Hamtaro",
        image_url="Facultatif : URL HTTPS. Sinon Hamtaro cherche la carte automatiquement",
    )
    async def set_default(
        self,
        interaction: discord.Interaction,
        deck: str,
        carte: str,
        image_url: str | None = None,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Serveur requis.", ephemeral=True)
            return
        try:
            await self.service.set_hamtaro_default(
                str(interaction.guild_id),
                deck,
                carte,
                image_url,
                str(interaction.user.id),
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🐹 Artwork Hamtaro par défaut défini pour **{deck}** : **{carte}**.",
            ephemeral=True,
        )

    @artwork.command(name="reset", description="Revenir à l'artwork Hamtaro par défaut")
    @staff_only()
    @app_commands.describe(deck="Nom du deck")
    async def reset(self, interaction: discord.Interaction, deck: str) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Serveur requis.", ephemeral=True)
            return
        await self.service.reset_to_hamtaro_default(
            str(interaction.guild_id), deck, str(interaction.user.id)
        )
        await interaction.response.send_message(
            f"🐹 **{deck}** utilise de nouveau l'artwork Hamtaro par défaut.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ArchetypeArtworkCog(bot))
