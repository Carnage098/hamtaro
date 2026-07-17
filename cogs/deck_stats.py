from __future__ import annotations

import math

import discord
from discord import app_commands
from discord.ext import commands

from services.analytics_service import AnalyticsService, DeckSummary

try:
    from utils.tournament_resolver import tournament_code_autocomplete
except ImportError:
    async def tournament_code_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return []


class DeckStatsView(discord.ui.View):
    def __init__(
        self,
        *,
        requester_id: int,
        decks: list[DeckSummary],
        scope: str,
        minimum_matches: int,
    ) -> None:
        super().__init__(timeout=180)
        self.requester_id = requester_id
        self.decks = decks
        self.scope = scope
        self.minimum_matches = minimum_matches
        self.page = 0
        self.per_page = 6
        self._sync_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Seule la personne ayant lancé la commande peut changer la page.",
                ephemeral=True,
            )
            return False
        return True

    @property
    def page_count(self) -> int:
        return max(1, math.ceil(len(self.decks) / self.per_page))

    def _sync_buttons(self) -> None:
        self.previous.disabled = self.page <= 0
        self.next.disabled = self.page >= self.page_count - 1

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎴 Statistiques des decks",
            description=(
                f"Portée : **{self.scope}**\n"
                f"Classement principal par nombre de matchs, puis taux de victoire."
            ),
            color=discord.Color.purple(),
        )
        if not self.decks:
            embed.description += "\n\nAucun deck avec des matchs validés n’a été trouvé."
            return embed

        start = self.page * self.per_page
        for index, deck in enumerate(self.decks[start:start + self.per_page], start=start + 1):
            sample = (
                "⚠️ Échantillon faible"
                if deck.matches < self.minimum_matches
                else "✅ Échantillon suffisant"
            )
            achievements = []
            if deck.top4:
                achievements.append(f"Top 4 : {deck.top4}")
            if deck.tournament_wins:
                achievements.append(f"Titres : {deck.tournament_wins}")
            achievement_text = " · ".join(achievements) or "Aucun placement final enregistré"
            embed.add_field(
                name=f"#{index} — {deck.deck}",
                value=(
                    f"Joueurs : **{deck.players}**\n"
                    f"Matchs : **{deck.matches}**\n"
                    f"Bilan : **{deck.wins} V / {deck.losses} D / {deck.double_losses} DL**\n"
                    f"Taux de victoire : **{deck.win_rate:.1f} %**\n"
                    f"{achievement_text}\n{sample}"
                ),
                inline=True,
            )
        embed.set_footer(text=f"Page {self.page + 1}/{self.page_count} · Minimum conseillé : {self.minimum_matches} matchs")
        return embed

    @discord.ui.button(label="Précédent", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.page = max(0, self.page - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Suivant", emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.page = min(self.page_count - 1, self.page + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class DeckStatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.analytics = AnalyticsService()

    @app_commands.command(
        name="deck_stats",
        description="Afficher les statistiques des decks du serveur ou d'un tournoi",
    )
    @app_commands.describe(
        code="Code du tournoi, vide pour tous les tournois",
        minimum_matchs="Seuil avant de considérer le taux comme suffisamment représentatif",
        visible="Publier les statistiques dans le salon",
    )
    @app_commands.autocomplete(code=tournament_code_autocomplete)
    async def deck_stats(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
        minimum_matchs: app_commands.Range[int, 1, 50] = 5,
        visible: bool = True,
    ) -> None:
        await interaction.response.defer(ephemeral=not visible)
        if interaction.guild is None:
            await interaction.followup.send(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild.id)
        tournament_id: int | None = None
        scope = "tous les tournois du serveur"
        if code:
            tournament = await self.analytics.get_tournament_by_code(guild_id, code)
            if tournament is None:
                await interaction.followup.send(
                    f"❌ Aucun tournoi ne correspond au code `{code}`.",
                    ephemeral=True,
                )
                return
            tournament_id = int(tournament["id"])
            scope = f"{tournament['name']} (`{tournament['code']}`)"

        decks = await self.analytics.get_deck_statistics(guild_id, tournament_id)
        view = DeckStatsView(
            requester_id=interaction.user.id,
            decks=decks,
            scope=scope,
            minimum_matches=int(minimum_matchs),
        )
        await interaction.followup.send(
            embed=view.build_embed(),
            view=view,
            ephemeral=not visible,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DeckStatsCog(bot))
