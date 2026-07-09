from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from utils.embeds import info_embed, error_embed
from utils.permissions import is_staff_member


class NextMatchCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.db = bot.db

    # ==========================================================
    # OUTILS INTERNES
    # ==========================================================

    def _guild_id(
        self,
        interaction: discord.Interaction,
    ) -> str:
        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(interaction.guild.id)

    async def _get_active_tournament(
        self,
        interaction: discord.Interaction,
    ):
        guild_id = self._guild_id(interaction)

        return await self.db.get_active_tournament(
            guild_id
        )

    async def _send_error(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        ephemeral: bool = True,
    ):
        embed = error_embed(
            title=title,
            description=description,
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                embed=embed,
                ephemeral=ephemeral,
            )
        else:
            await interaction.response.send_message(
                embed=embed,
                ephemeral=ephemeral,
            )

    def _round_number(
        self,
        match,
    ):
        round_number = getattr(
            match,
            "round_number",
            None,
        )

        if round_number is None:
            round_number = getattr(
                match,
                "round",
                None,
            )

        return round_number or "?"

    def _player_name(
        self,
        player_id: str | None,
        player_name: str | None,
    ) -> str:
        if player_id is None:
            return "BYE"

        return player_name or f"Joueur `{player_id}`"

    def _opponent_of(
        self,
        match,
        user_id: str,
    ) -> tuple[str | None, str | None]:
        player1_id = getattr(
            match,
            "player1_id",
            None,
        )

        player2_id = getattr(
            match,
            "player2_id",
            None,
        )

        player1_name = getattr(
            match,
            "player1_name",
            None,
        )

        player2_name = getattr(
            match,
            "player2_name",
            None,
        )

        if str(user_id) == str(player1_id):
            return player2_id, player2_name

        if str(user_id) == str(player2_id):
            return player1_id, player1_name

        return None, None

    # ==========================================================
    # NEXT MATCH
    # ==========================================================

    @app_commands.command(
        name="nextmatch",
        description="Voir ton prochain match dans le tournoi actif"
    )
    @app_commands.describe(
        joueur="Joueur à consulter, réservé au staff"
    )
    async def nextmatch(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member | None = None,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi actif",
                    description="Il n'y a actuellement aucun tournoi actif.",
                )
                return

            target = joueur or interaction.user

            if joueur is not None and joueur.id != interaction.user.id:
                if not is_staff_member(interaction.user):
                    await self._send_error(
                        interaction=interaction,
                        title="Action refusée",
                        description=(
                            "Tu ne peux consulter que ton propre prochain match.\n\n"
                            "Seul le staff peut consulter le match d'un autre joueur."
                        ),
                    )
                    return

            match = await self.db.get_next_match_for_player(
                tournament_id=tournament.id,
                discord_id=str(target.id),
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Erreur",
                description=str(error),
            )
            return

        if match is None:
            embed = info_embed(
                title="Aucun match actif",
                description=(
                    f"{target.mention} n'a aucun match actif pour le moment.\n\n"
                    "Soit le tournoi n'a pas encore commencé, soit son prochain adversaire "
                    "n'est pas encore connu."
                ),
            )

            embed.add_field(
                name="🏆 Tournoi",
                value=f"**{tournament.name}**",
                inline=False,
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )
            return

        player1_id = getattr(
            match,
            "player1_id",
            None,
        )

        player2_id = getattr(
            match,
            "player2_id",
            None,
        )

        player1_name = getattr(
            match,
            "player1_name",
            None,
        )

        player2_name = getattr(
            match,
            "player2_name",
            None,
        )

        opponent_id, opponent_name = self._opponent_of(
            match=match,
            user_id=str(target.id),
        )

        player1_display = self._player_name(
            player1_id,
            player1_name,
        )

        player2_display = self._player_name(
            player2_id,
            player2_name,
        )

        opponent_display = self._player_name(
            opponent_id,
            opponent_name,
        )

        status = getattr(
            match,
            "status",
            "unknown",
        )

        status_value = getattr(
            status,
            "value",
            str(status),
        )

        score = getattr(
            match,
            "score",
            None,
        )

        embed = info_embed(
            title="Ton prochain match",
            description=(
                f"Voici le match actif de {target.mention}."
            ),
        )

        embed.add_field(
            name="🏆 Tournoi",
            value=f"**{tournament.name}**",
            inline=False,
        )

        embed.add_field(
            name="🆔 Match ID",
            value=f"`{match.id}`",
            inline=True,
        )

        embed.add_field(
            name="🔄 Round",
            value=f"`{self._round_number(match)}`",
            inline=True,
        )

        embed.add_field(
            name="📌 Statut",
            value=f"`{status_value}`",
            inline=True,
        )

        embed.add_field(
            name="⚔️ Affiche",
            value=(
                f"**{player1_display}**\n"
                "vs\n"
                f"**{player2_display}**"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎯 Adversaire",
            value=f"**{opponent_display}**",
            inline=False,
        )

        if score:
            embed.add_field(
                name="📊 Score actuel",
                value=f"`{score}`",
                inline=True,
            )

        embed.add_field(
            name="🧾 Reporter le résultat",
            value=(
                f"`/result match_id:{match.id} player1_score:2 player2_score:1`\n\n"
                "Adapte le score selon le résultat réel."
            ),
            inline=False,
        )

        embed.set_footer(
            text="Hamtaro Tournament Manager"
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        NextMatchCog(bot)
    )
