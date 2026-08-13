from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from services.match_context_service import MatchContextService


def _phase_label(match: dict[str, Any]) -> str:
    label = str(match.get("round_label") or "").strip()
    if label:
        return label.replace("Bracket — ", "").replace("Ronde suisse ", "Ronde ")
    if match.get("table_number") is not None:
        return f"Ronde {match.get('round_number', '?')} · Table {match.get('table_number', '?')}"
    return f"Ronde {match.get('round_number', '?')}"


class NextMatchSelect(discord.ui.Select):
    def __init__(self, cog: "NextMatchCog", requester_id: int, matches: list[dict[str, Any]]) -> None:
        self.cog = cog
        self.requester_id = requester_id
        self.matches = matches
        options: list[discord.SelectOption] = []
        for index, match in enumerate(matches[:25]):
            options.append(
                discord.SelectOption(
                    label=str(match.get("tournament_name") or "Tournoi Hamtaro")[:100],
                    description=(
                        f"vs {match.get('opponent_name', 'Adversaire')} · {_phase_label(match)}"
                    )[:100],
                    value=str(index),
                )
            )
        super().__init__(
            placeholder="Choisir un de tes matchs",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Ce menu appartient au joueur qui a lancé la commande.",
                ephemeral=True,
            )
            return
        match = self.matches[int(self.values[0])]
        await interaction.response.edit_message(
            embed=self.cog._embed(match, str(interaction.user.id)),
            view=NextMatchView(self.cog, self.requester_id, match, self.matches),
        )


class NextMatchView(discord.ui.View):
    def __init__(
        self,
        cog: "NextMatchCog",
        requester_id: int,
        match: dict[str, Any],
        all_matches: list[dict[str, Any]],
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.requester_id = requester_id
        self.match = match
        if len(all_matches) > 1:
            self.add_item(NextMatchSelect(cog, requester_id, all_matches))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Ce panneau ne correspond pas à ton match.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Déclarer le résultat",
        emoji="✅",
        style=discord.ButtonStyle.success,
    )
    async def result_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        results = self.cog.bot.get_cog("ResultsCog")
        if results is None:
            await interaction.response.send_message(
                "❌ Le système de résultats n'est pas chargé.", ephemeral=True
            )
            return
        await results.open_result_flow(
            interaction,
            match_kind=str(self.match["match_kind"]),
            match_id=int(self.match["match_id"]),
        )


class NextMatchCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db
        self.contexts = MatchContextService(self.db)

    async def cog_load(self) -> None:
        await self.contexts.ensure_table()

    def _embed(self, match: dict[str, Any], user_id: str) -> discord.Embed:
        opponent = str(match.get("opponent_name") or "Adversaire")
        if not match.get("opponent_name"):
            opponent = (
                str(match.get("player2_name") or "Adversaire")
                if str(match.get("player1_id") or "") == user_id
                else str(match.get("player1_name") or "Adversaire")
            )

        embed = discord.Embed(
            title="🎯 Ton match Hamtaro",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="🏟️ Tournoi",
            value=(
                f"**{match.get('tournament_name', 'Tournoi Hamtaro')}**\n"
                f"`{match.get('tournament_code', '?')}`"
            ),
            inline=False,
        )
        tournament_format = str(match.get("tournament_format") or "").strip()
        if tournament_format:
            embed.add_field(name="🎴 Format", value=tournament_format, inline=True)
        embed.add_field(name="🔄 Phase", value=_phase_label(match), inline=True)
        embed.add_field(name="⚔️ Adversaire", value=f"**{opponent}**", inline=False)
        embed.add_field(
            name="📍 État",
            value=str(match.get("status") or "À jouer"),
            inline=True,
        )
        embed.set_footer(
            text="Bracket ou Suisse : Hamtaro gère la différence automatiquement. Utilise /result à la fin."
        )
        return embed

    async def _thread_match(self, interaction: discord.Interaction) -> dict[str, Any] | None:
        if interaction.guild is None or interaction.channel_id is None:
            return None
        context = await self.contexts.by_thread(
            guild_id=str(interaction.guild.id),
            thread_id=str(interaction.channel_id),
        )
        if context is None:
            match_center = self.bot.get_cog("MatchCenterCog")
            if match_center is not None:
                try:
                    context = await match_center.resolve_thread_match(
                        guild_id=str(interaction.guild.id),
                        thread_id=str(interaction.channel_id),
                    )
                except Exception:
                    context = None
        if context is None:
            return None
        user_id = str(interaction.user.id)
        if user_id not in {
            str(context.get("player1_id") or ""),
            str(context.get("player2_id") or ""),
        }:
            return None
        context["status"] = "Match de ce fil"
        context["opponent_name"] = (
            context.get("player2_name")
            if str(context.get("player1_id") or "") == user_id
            else context.get("player1_name")
        )
        return context

    @app_commands.command(
        name="nextmatch",
        description="Voir ton match Hamtaro sans choisir de tournoi ni de type",
    )
    async def nextmatch(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Serveur requis.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        current = await self._thread_match(interaction)
        if current is not None:
            await interaction.followup.send(
                embed=self._embed(current, str(interaction.user.id)),
                view=NextMatchView(self, interaction.user.id, current, [current]),
                ephemeral=True,
            )
            return

        results = self.bot.get_cog("ResultsCog")
        if results is None:
            await interaction.followup.send(
                "❌ Le système de matchs n'est pas chargé.", ephemeral=True
            )
            return

        matches = await results._list_player_open_matches(
            guild_id=str(interaction.guild.id),
            user_id=str(interaction.user.id),
        )
        if not matches:
            await interaction.followup.send(
                "✅ Aucun match à jouer n'a été trouvé pour toi.", ephemeral=True
            )
            return

        # Complète le format depuis le tournoi sans exposer match_kind au joueur.
        for match in matches:
            try:
                tournament = await self.db.get_tournament(int(match["tournament_id"]))
                match["tournament_format"] = getattr(tournament, "format", None)
            except Exception:
                pass

        selected = matches[0]
        content = None
        if len(matches) > 1:
            content = (
                f"Tu as **{len(matches)} matchs actifs**. Hamtaro n'impose plus de tournoi courant : "
                "choisis simplement le match dans le menu."
            )
        await interaction.followup.send(
            content=content,
            embed=self._embed(selected, str(interaction.user.id)),
            view=NextMatchView(self, interaction.user.id, selected, matches),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    existing = bot.tree.get_command("nextmatch")
    if existing is not None:
        bot.tree.remove_command("nextmatch", type=discord.AppCommandType.chat_input)
    await bot.add_cog(NextMatchCog(bot))
