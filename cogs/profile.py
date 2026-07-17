from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from services.analytics_service import AnalyticsService, DeckSummary, PlayerSummary

try:
    from utils.tournament_resolver import tournament_code_autocomplete
except ImportError:
    async def tournament_code_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return []


class ProfileView(discord.ui.View):
    def __init__(
        self,
        *,
        requester_id: int,
        target: discord.Member | discord.User,
        summary: PlayerSummary,
        matches: list[dict[str, Any]],
        decks: list[DeckSummary],
        scope: str,
    ) -> None:
        super().__init__(timeout=180)
        self.requester_id = requester_id
        self.target = target
        self.summary = summary
        self.matches = matches
        self.decks = decks
        self.scope = scope

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Seule la personne ayant ouvert ce profil peut utiliser ces boutons.",
                ephemeral=True,
            )
            return False
        return True

    def _base_embed(self, title: str) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description=f"Statistiques de {self.target.mention}\nPortée : **{self.scope}**",
            color=discord.Color.gold(),
        )
        avatar = self.target.display_avatar.url
        embed.set_thumbnail(url=avatar)
        return embed

    def overview_embed(self) -> discord.Embed:
        summary = self.summary
        embed = self._base_embed(f"🐹 Profil de {self.target.display_name}")
        embed.add_field(
            name="📊 Matchs",
            value=(
                f"Joués : **{summary.matches}**\n"
                f"✅ Victoires : **{summary.wins}**\n"
                f"❌ Défaites : **{summary.losses}**\n"
                f"🔴 Double Loss : **{summary.double_losses}**\n"
                f"🛋️ BYE : **{summary.byes}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="📈 Performances",
            value=(
                f"Taux de victoire : **{summary.win_rate:.1f} %**\n"
                f"Série actuelle : **{summary.current_streak} victoire(s)**\n"
                f"Meilleure série : **{summary.best_streak} victoire(s)**"
            ),
            inline=True,
        )
        embed.add_field(
            name="🏆 Tournois",
            value=(
                f"Participations : **{summary.tournaments_played}**\n"
                f"Titres : **{summary.tournaments_won}**\n"
                f"Finales : **{summary.finals}**\n"
                f"Top 4 : **{summary.top4}**"
            ),
            inline=True,
        )
        best_deck = (
            f"{summary.best_deck} — {summary.best_deck_win_rate:.1f} %"
            if summary.best_deck and summary.best_deck_win_rate is not None
            else "Pas assez de matchs"
        )
        embed.add_field(
            name="🎴 Decks",
            value=(
                f"Deck récent : **{summary.current_deck or 'Non renseigné'}**\n"
                f"Le plus utilisé : **{summary.most_used_deck or 'Non renseigné'}**\n"
                f"Meilleur résultat : **{best_deck}**"
            ),
            inline=False,
        )
        embed.set_footer(
            text="Les BYE ne sont pas comptés dans le taux de victoire. Les statistiques suivent les résultats réellement validés."
        )
        return embed

    def matches_embed(self) -> discord.Embed:
        embed = self._base_embed(f"⚔️ Derniers matchs — {self.target.display_name}")
        if not self.matches:
            embed.description += "\n\nAucun match terminé trouvé."
            return embed

        lines: list[str] = []
        target_id = str(self.target.id)
        for match in self.matches[:10]:
            player1_id = str(match.get("player1_id") or "")
            opponent = (
                match.get("player2_name")
                if player1_id == target_id
                else match.get("player1_name")
            ) or "BYE"
            if int(match.get("is_bye") or 0) == 1:
                result = "🛋️ BYE"
            elif int(match.get("is_double_loss") or 0) == 1:
                result = "🔴 Double Loss"
            elif str(match.get("winner_id") or "") == target_id:
                result = "✅ Victoire"
            else:
                result = "❌ Défaite"
            score = f"{match.get('player1_score', 0)}-{match.get('player2_score', 0)}"
            system = "🇨🇭" if match.get("match_kind") == "swiss" else "🌳"
            round_name = (
                f"Ronde {match.get('round_number')} · Table {match.get('table_number')}"
                if match.get("match_kind") == "swiss"
                else f"Round {match.get('round_number')} · Match {match.get('table_number')}"
            )
            lines.append(
                f"{system} **{match.get('tournament_name', 'Tournoi')}** "
                f"`{match.get('tournament_code', '?')}`\n"
                f"{result} contre **{opponent}** · `{score}` · {round_name}"
            )
        embed.description += "\n\n" + "\n\n".join(lines)
        return embed

    def decks_embed(self) -> discord.Embed:
        embed = self._base_embed(f"🎴 Decks de {self.target.display_name}")
        useful = [deck for deck in self.decks if deck.matches > 0]
        if not useful:
            embed.description += "\n\nAucun match avec un deck renseigné."
            return embed

        for deck in useful[:10]:
            warning = "\n⚠️ Échantillon faible" if deck.matches < 5 else ""
            embed.add_field(
                name=deck.deck,
                value=(
                    f"Matchs : **{deck.matches}**\n"
                    f"Bilan : **{deck.wins} V / {deck.losses} D / {deck.double_losses} DL**\n"
                    f"Taux de victoire : **{deck.win_rate:.1f} %**{warning}"
                ),
                inline=True,
            )
        return embed

    def records_embed(self) -> discord.Embed:
        summary = self.summary
        embed = self._base_embed(f"🏆 Palmarès de {self.target.display_name}")
        embed.add_field(name="Titres", value=str(summary.tournaments_won), inline=True)
        embed.add_field(name="Finales", value=str(summary.finals), inline=True)
        embed.add_field(name="Top 4", value=str(summary.top4), inline=True)
        embed.add_field(
            name="Séries",
            value=(
                f"Actuelle : **{summary.current_streak}**\n"
                f"Record : **{summary.best_streak}**"
            ),
            inline=True,
        )
        if summary.finals == 0 and summary.top4 == 0:
            embed.add_field(
                name="ℹ️ Classements historiques",
                value=(
                    "Les finales et Top 4 apparaissent lorsque `final_rank` est renseigné "
                    "dans les inscriptions des tournois terminés."
                ),
                inline=False,
            )
        return embed

    @discord.ui.button(label="Vue générale", emoji="👤", style=discord.ButtonStyle.primary)
    async def overview_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(embed=self.overview_embed(), view=self)

    @discord.ui.button(label="Derniers matchs", emoji="⚔️", style=discord.ButtonStyle.secondary)
    async def matches_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(embed=self.matches_embed(), view=self)

    @discord.ui.button(label="Decks", emoji="🎴", style=discord.ButtonStyle.secondary)
    async def decks_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(embed=self.decks_embed(), view=self)

    @discord.ui.button(label="Palmarès", emoji="🏆", style=discord.ButtonStyle.secondary)
    async def records_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(embed=self.records_embed(), view=self)


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.analytics = AnalyticsService()

    @app_commands.command(
        name="profile",
        description="Afficher le profil détaillé et les statistiques d'un joueur",
    )
    @app_commands.describe(
        member="Joueur à consulter, par défaut toi",
        code="Limiter les statistiques à un tournoi précis",
        visible="Afficher le profil publiquement",
    )
    @app_commands.autocomplete(code=tournament_code_autocomplete)
    async def profile(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        code: str | None = None,
        visible: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=not visible)
        if interaction.guild is None:
            await interaction.followup.send(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        target = member or interaction.user
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

        summary, matches, decks = await self.analytics.get_player_profile(
            guild_id=guild_id,
            player_id=str(target.id),
            fallback_name=target.display_name,
            tournament_id=tournament_id,
        )
        view = ProfileView(
            requester_id=interaction.user.id,
            target=target,
            summary=summary,
            matches=matches,
            decks=decks,
            scope=scope,
        )
        await interaction.followup.send(
            embed=view.overview_embed(),
            view=view,
            ephemeral=not visible,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCog(bot))
