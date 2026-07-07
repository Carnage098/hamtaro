from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands


class ProfileCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot
        self.db = bot.db

    def _guild_id(
        self,
        interaction: discord.Interaction,
    ) -> str:

        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(interaction.guild.id)

    # ==========================================================
    # PROFIL JOUEUR
    # ==========================================================

    @app_commands.command(
        name="profile",
        description="Voir le profil d'un joueur"
    )
    @app_commands.describe(
        joueur="Joueur à afficher"
    )
    async def profile(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member | None = None,
    ):

        await interaction.response.defer(
            ephemeral=False
        )

        try:

            guild_id = self._guild_id(interaction)

            target = joueur or interaction.user

            player = await self.db.get_player(
                discord_id=str(target.id),
                guild_id=guild_id,
            )

            if player is None:

                await interaction.followup.send(
                    "❌ Ce joueur n'a pas encore de profil Hamtaro.",
                    ephemeral=True,
                )

                return

            rank = await self.db.get_player_rank(
                discord_id=player.discord_id,
                guild_id=guild_id,
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        matches_played = player.wins + player.losses

        if matches_played == 0:
            winrate = 0
        else:
            winrate = round(
                (player.wins / matches_played) * 100,
                2,
            )

        embed = discord.Embed(
            title=f"👤 Profil — {player.username}",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Classement",
            value=f"#{rank}" if rank is not None else "Non classé",
            inline=True,
        )

        embed.add_field(
            name="Matchs joués",
            value=str(matches_played),
            inline=True,
        )

        embed.add_field(
            name="Winrate",
            value=f"{winrate}%",
            inline=True,
        )

        embed.add_field(
            name="Victoires",
            value=str(player.wins),
            inline=True,
        )

        embed.add_field(
            name="Défaites",
            value=str(player.losses),
            inline=True,
        )

        embed.add_field(
            name="Tournois joués",
            value=str(player.tournaments_played),
            inline=True,
        )

        embed.add_field(
            name="Tournois gagnés",
            value=str(player.tournaments_won),
            inline=True,
        )

        if player.avatar_url:

            embed.set_thumbnail(
                url=player.avatar_url
            )

        await interaction.followup.send(
            embed=embed,
            ephemeral=False,
        )

    # ==========================================================
    # LEADERBOARD
    # ==========================================================

    @app_commands.command(
        name="leaderboard",
        description="Afficher le classement Hamtaro"
    )
    @app_commands.describe(
        limit="Nombre de joueurs à afficher"
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        limit: int = 10,
    ):

        await interaction.response.defer(
            ephemeral=False
        )

        try:

            guild_id = self._guild_id(interaction)

            if limit < 1:
                limit = 1

            if limit > 25:
                limit = 25

            players = await self.db.get_leaderboard(
                guild_id=guild_id,
                limit=limit,
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        if not players:

            await interaction.followup.send(
                "❌ Aucun joueur dans le classement pour le moment.",
                ephemeral=True,
            )

            return

        lines = []

        for index, player in enumerate(
            players,
            start=1,
        ):

            matches_played = player.wins + player.losses

            if matches_played == 0:
                winrate = 0
            else:
                winrate = round(
                    (player.wins / matches_played) * 100,
                    1,
                )

            if index == 1:
                medal = "🥇"
            elif index == 2:
                medal = "🥈"
            elif index == 3:
                medal = "🥉"
            else:
                medal = f"`#{index}`"

            lines.append(
                f"{medal} **{player.username}** — "
                f"🏆 {player.tournaments_won} tournoi(s) gagné(s) | "
                f"✅ {player.wins}V / ❌ {player.losses}D | "
                f"{winrate}% WR"
            )

        embed = discord.Embed(
            title="🏆 Classement Hamtaro",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=False,
        )


async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        ProfileCog(bot)
    )
