from __future__ import annotations

import os

import discord
from discord import app_commands
from discord.ext import commands

from services.competitive_service import CompetitiveService
from services.expansion_database import init_expansion_schema
from services.player_experience_service import PlayerExperienceService
from services.tournament_extensions_service import TournamentExtensionsService
from utils.expansion_permissions import is_staff_member


class ExpansionHubView(discord.ui.View):
    def __init__(self, cog: "ExpansionHubCog", requester_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            "❌ Ce menu appartient à une autre personne. Utilise `/hamtaro_plus`.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Mon tableau de bord", emoji="⚡", style=discord.ButtonStyle.primary, row=0)
    async def dashboard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.defer(ephemeral=True)
        embed = await self.cog.dashboard_embed(interaction)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Mon profil", emoji="👤", style=discord.ButtonStyle.secondary, row=0)
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.defer(ephemeral=True)
        embed = await self.cog.profile_embed(interaction)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Classements", emoji="📈", style=discord.ButtonStyle.secondary, row=0)
    async def rankings(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message(
            "Utilise `/competitive ranking` en indiquant le format souhaité.",
            ephemeral=True,
        )

    @discord.ui.button(label="Tournois", emoji="🏟️", style=discord.ButtonStyle.secondary, row=1)
    async def tournaments(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None:
            await interaction.response.send_message("❌ Serveur introuvable.", ephemeral=True)
            return
        try:
            data = await self.cog.tournaments.tournament_info(str(interaction.guild.id), None)
        except ValueError:
            await interaction.response.send_message("ℹ️ Aucun tournoi actif.", ephemeral=True)
            return
        tournament = data["tournament"]
        await interaction.response.send_message(
            f"🏟️ **{tournament['name']}** (`{tournament['code']}`) • "
            f"{data['registrations']}/{tournament['max_players']} joueur(s) • {tournament['status']}",
            ephemeral=True,
        )

    @discord.ui.button(label="Decks", emoji="🎴", style=discord.ButtonStyle.secondary, row=1)
    async def decks(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message(
            "Bibliothèque : `/duelist deck_list` • ajouter : `/duelist deck_add`.",
            ephemeral=True,
        )

    @discord.ui.button(label="Aide commandes", emoji="❓", style=discord.ButtonStyle.secondary, row=1)
    async def help(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        embed = discord.Embed(title="❓ Hamtaro Plus — commandes", color=discord.Color.blurple())
        embed.description = (
            "`/competitive` : ELO, saisons et comparaisons\n"
            "`/duelist` : profil, dashboard, decks, succès et notifications\n"
            "`/tourney_plus` : tournoi, arbitres, attente, suisse, programmation\n"
            "`/community_poll` : sondages communautaires\n"
            "`/setup_plus` : configuration des nouveaux salons"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Centre staff", emoji="🛡️", style=discord.ButtonStyle.danger, row=2)
    async def staff(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if not await is_staff_member(interaction.user):
            await interaction.response.send_message("⛔ Accès réservé au staff.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Ouvre le panneau complet avec `/tourney_plus staff_panel`.",
            ephemeral=True,
        )


class ExpansionHubCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.players = PlayerExperienceService()
        self.competitive = CompetitiveService()
        self.tournaments = TournamentExtensionsService()

    async def cog_load(self) -> None:
        await init_expansion_schema()

    @app_commands.command(name="hamtaro_plus", description="Ouvrir le centre avancé Hamtaro")
    async def hamtaro_plus(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🐹 Centre Hamtaro Plus",
            description=(
                "Compétition permanente, profils enrichis, decks, outils staff, "
                "rondes suisses avancées et fonctions communautaires."
            ),
            color=discord.Color.gold(),
        )
        try:
            data = await self.tournaments.tournament_info(str(interaction.guild.id), None)
            tournament = data["tournament"]
            embed.add_field(
                name="🏟️ Tournoi actif",
                value=f"**{tournament['name']}** (`{tournament['code']}`) • {data['registrations']}/{tournament['max_players']}",
                inline=False,
            )
        except ValueError:
            embed.add_field(name="🏟️ Tournoi actif", value="Aucun tournoi actif.", inline=False)
        website = os.getenv("WEBSITE_BASE_URL", "").strip().rstrip("/")
        if website:
            embed.add_field(name="🌐 Site", value=f"{website}/competitive", inline=False)
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(
            embed=embed,
            view=ExpansionHubView(self, interaction.user.id),
            ephemeral=True,
        )

    async def dashboard_embed(self, interaction: discord.Interaction) -> discord.Embed:
        assert interaction.guild is not None
        data = await self.players.dashboard(str(interaction.guild.id), str(interaction.user.id))
        embed = discord.Embed(title="⚡ Mon tableau de bord", color=discord.Color.blurple())
        embed.add_field(name="Tournois actifs", value=str(len(data.active_tournaments)), inline=True)
        embed.add_field(name="Matchs à jouer", value=str(len(data.next_matches)), inline=True)
        embed.add_field(name="Problèmes ouverts", value=str(data.open_issues), inline=True)
        if data.next_matches:
            embed.add_field(
                name="Prochaine rencontre",
                value=(
                    f"**{data.next_matches[0]['tournament_name']}** • "
                    f"ronde {data.next_matches[0]['round_number']}"
                ),
                inline=False,
            )
        if data.ratings:
            embed.add_field(
                name="Meilleur ELO",
                value=f"**{data.ratings[0]['format']}** : {data.ratings[0]['rating']}",
                inline=False,
            )
        return embed

    async def profile_embed(self, interaction: discord.Interaction) -> discord.Embed:
        assert interaction.guild is not None
        data = await self.players.profile(str(interaction.guild.id), str(interaction.user.id))
        stats = data["tournament_stats"]
        embed = discord.Embed(
            title=f"👤 {interaction.user.display_name}",
            description=data["profile"].get("about") or "Profil non complété.",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Tournois", value=str(int(stats.get("tournaments") or 0)), inline=True)
        embed.add_field(name="Titres", value=str(int(stats.get("titles") or 0)), inline=True)
        embed.add_field(name="Succès", value=str(len(data["achievements"])), inline=True)
        if data["active_deck"]:
            embed.add_field(name="Deck actif", value=data["active_deck"]["name"], inline=False)
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ExpansionHubCog(bot))
