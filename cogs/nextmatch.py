from __future__ import annotations

import aiosqlite
import discord

from discord.ext import commands
from discord import app_commands

try:
    from config import DATABASE
except ImportError:
    from database import DATABASE


class NextMatchCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _guild_id(self, interaction: discord.Interaction) -> str:
        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(interaction.guild.id)

    async def _get_active_tournament(
        self,
        guild_id: str,
    ) -> aiosqlite.Row | None:

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT *
                FROM tournaments
                WHERE guild_id = ?
                AND status IN (
                    'registration',
                    'running'
                )
                ORDER BY created_at DESC
                LIMIT 1
            """, (guild_id,))

            return await cursor.fetchone()

    async def _get_next_bracket_match(
        self,
        tournament_id: int,
        player_id: str,
    ) -> aiosqlite.Row | None:

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                AND (
                    player1_id = ?
                    OR player2_id = ?
                )
                AND status IN (
                    'waiting',
                    'playing',
                    'reported'
                )
                AND is_bye = 0
                ORDER BY round ASC, match_number ASC, id ASC
                LIMIT 1
            """, (
                tournament_id,
                player_id,
                player_id,
            ))

            return await cursor.fetchone()

    async def _get_next_swiss_match(
        self,
        tournament_id: int,
        player_id: str,
    ) -> aiosqlite.Row | None:

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT *
                FROM swiss_matches
                WHERE tournament_id = ?
                AND (
                    player1_id = ?
                    OR player2_id = ?
                )
                AND status = 'pending'
                ORDER BY round_number ASC, table_number ASC, id ASC
                LIMIT 1
            """, (
                tournament_id,
                player_id,
                player_id,
            ))

            return await cursor.fetchone()

    def _format_bracket_embed(
        self,
        tournament: aiosqlite.Row,
        match: aiosqlite.Row,
        player_id: str,
        target: discord.abc.User,
    ) -> discord.Embed:

        player1_id = match["player1_id"]
        player2_id = match["player2_id"]

        player1_name = match["player1_name"] or "Joueur 1"
        player2_name = match["player2_name"] or "Joueur 2"

        if player_id == player1_id:
            opponent_name = player2_name
        else:
            opponent_name = player1_name

        embed = discord.Embed(
            title="⚔️ Prochain match",
            description=f"Prochain match de {target.mention}",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Tournoi",
            value=f"**{tournament['name']}** `({tournament['code']})`",
            inline=False,
        )

        embed.add_field(
            name="Format",
            value=tournament["format"],
            inline=True,
        )

        embed.add_field(
            name="Type",
            value="Bracket classique",
            inline=True,
        )

        embed.add_field(
            name="Round",
            value=str(match["round"]),
            inline=True,
        )

        embed.add_field(
            name="Match",
            value=f"#{match['match_number']}",
            inline=True,
        )

        embed.add_field(
            name="Adversaire",
            value=opponent_name or "Adversaire à déterminer",
            inline=True,
        )

        embed.add_field(
            name="Statut",
            value=match["status"],
            inline=True,
        )

        embed.add_field(
            name="Affiche",
            value=f"**{player1_name}** VS **{player2_name}**",
            inline=False,
        )

        embed.set_footer(
            text="Utilise /result pour déclarer le résultat du match."
        )

        return embed

    def _format_swiss_embed(
        self,
        tournament: aiosqlite.Row,
        match: aiosqlite.Row,
        player_id: str,
        target: discord.abc.User,
    ) -> discord.Embed:

        player1_id = match["player1_id"]

        player1_name = match["player1_name"] or "Joueur 1"
        player2_name = match["player2_name"] or "BYE"

        is_bye = match["is_bye"]

        if is_bye:
            opponent_name = "BYE"
        elif player_id == player1_id:
            opponent_name = player2_name
        else:
            opponent_name = player1_name

        embed = discord.Embed(
            title="⚔️ Prochain match",
            description=f"Prochain match de {target.mention}",
            color=discord.Color.green(),
        )

        embed.add_field(
            name="Tournoi",
            value=f"**{tournament['name']}** `({tournament['code']})`",
            inline=False,
        )

        embed.add_field(
            name="Format",
            value=tournament["format"],
            inline=True,
        )

        embed.add_field(
            name="Type",
            value="Rondes suisses",
            inline=True,
        )

        embed.add_field(
            name="Ronde",
            value=str(match["round_number"]),
            inline=True,
        )

        embed.add_field(
            name="Table",
            value=str(match["table_number"]),
            inline=True,
        )

        embed.add_field(
            name="Adversaire",
            value=opponent_name,
            inline=True,
        )

        embed.add_field(
            name="Statut",
            value=match["status"],
            inline=True,
        )

        embed.add_field(
            name="Affiche",
            value=f"**{player1_name}** VS **{player2_name}**",
            inline=False,
        )

        if is_bye:
            embed.set_footer(
                text="Tu as un BYE pour cette ronde."
            )
        else:
            embed.set_footer(
                text="Utilise /swiss_result ou la commande de résultat prévue pour déclarer le score."
            )

        return embed

    @app_commands.command(
        name="nextmatch",
        description="Voir ton prochain match dans le tournoi actif"
    )
    @app_commands.describe(
        member="Joueur à consulter"
    )
    async def nextmatch(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            guild_id = self._guild_id(interaction)

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        target = member or interaction.user
        player_id = str(target.id)

        tournament = await self._get_active_tournament(
            guild_id
        )

        if tournament is None:
            await interaction.followup.send(
                "❌ Aucun tournoi actif trouvé sur ce serveur.",
                ephemeral=True,
            )
            return

        if tournament["status"] == "registration":
            await interaction.followup.send(
                "📋 Le tournoi est encore en phase d'inscription. Aucun match n'a encore été généré.",
                ephemeral=True,
            )
            return

        bracket_match = await self._get_next_bracket_match(
            tournament_id=tournament["id"],
            player_id=player_id,
        )

        if bracket_match is not None:
            embed = self._format_bracket_embed(
                tournament=tournament,
                match=bracket_match,
                player_id=player_id,
                target=target,
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )
            return

        swiss_match = await self._get_next_swiss_match(
            tournament_id=tournament["id"],
            player_id=player_id,
        )

        if swiss_match is not None:
            embed = self._format_swiss_embed(
                tournament=tournament,
                match=swiss_match,
                player_id=player_id,
                target=target,
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Aucun match en attente trouvé pour {target.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    existing_command = bot.tree.get_command("nextmatch")

    if existing_command is not None:
        bot.tree.remove_command("nextmatch")

    await bot.add_cog(
        NextMatchCog(bot)
    )
