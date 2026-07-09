from __future__ import annotations

import aiosqlite
import discord

from discord.ext import commands
from discord import app_commands

try:
    from config import DATABASE
except ImportError:
    from database import DATABASE


class MatchHistoryCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _guild_id(self, interaction: discord.Interaction) -> str:
        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(interaction.guild.id)

    async def _get_bracket_matches(
        self,
        guild_id: str,
        player_id: str,
        limit: int,
    ) -> list[aiosqlite.Row]:

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    matches.id,
                    matches.round,
                    matches.player1_id,
                    matches.player2_id,
                    matches.player1_name,
                    matches.player2_name,
                    matches.player1_score,
                    matches.player2_score,
                    matches.winner_id,
                    matches.winner_name,
                    matches.status,
                    matches.validated_at,
                    matches.created_at,
                    tournaments.name AS tournament_name,
                    tournaments.format AS tournament_format,
                    tournaments.code AS tournament_code
                FROM matches
                JOIN tournaments
                    ON tournaments.id = matches.tournament_id
                WHERE tournaments.guild_id = ?
                AND (
                    matches.player1_id = ?
                    OR matches.player2_id = ?
                )
                ORDER BY
                    COALESCE(matches.validated_at, matches.created_at) DESC
                LIMIT ?
            """, (
                guild_id,
                player_id,
                player_id,
                limit,
            ))

            return list(await cursor.fetchall())

    async def _get_swiss_matches(
        self,
        guild_id: str,
        player_id: str,
        limit: int,
    ) -> list[aiosqlite.Row]:

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    swiss_matches.id,
                    swiss_matches.round_number,
                    swiss_matches.table_number,
                    swiss_matches.player1_id,
                    swiss_matches.player2_id,
                    swiss_matches.player1_name,
                    swiss_matches.player2_name,
                    swiss_matches.player1_score,
                    swiss_matches.player2_score,
                    swiss_matches.winner_id,
                    swiss_matches.winner_name,
                    swiss_matches.is_draw,
                    swiss_matches.is_bye,
                    swiss_matches.status,
                    swiss_matches.reported_at,
                    swiss_matches.created_at,
                    tournaments.name AS tournament_name,
                    tournaments.format AS tournament_format,
                    tournaments.code AS tournament_code
                FROM swiss_matches
                JOIN tournaments
                    ON tournaments.id = swiss_matches.tournament_id
                WHERE tournaments.guild_id = ?
                AND (
                    swiss_matches.player1_id = ?
                    OR swiss_matches.player2_id = ?
                )
                ORDER BY
                    COALESCE(swiss_matches.reported_at, swiss_matches.created_at) DESC
                LIMIT ?
            """, (
                guild_id,
                player_id,
                player_id,
                limit,
            ))

            return list(await cursor.fetchall())

    def _format_bracket_match(
        self,
        match: aiosqlite.Row,
        player_id: str,
    ) -> str:

        player1_id = match["player1_id"]
        player2_id = match["player2_id"]

        player1_name = match["player1_name"] or "Joueur 1"
        player2_name = match["player2_name"] or "Joueur 2"

        player1_score = match["player1_score"]
        player2_score = match["player2_score"]

        winner_id = match["winner_id"]
        status = match["status"]

        if player_id == winner_id:
            result = "✅ Victoire"
        elif winner_id is not None:
            result = "❌ Défaite"
        else:
            result = "⏳ En attente"

        if player_id == player1_id:
            opponent = player2_name
        else:
            opponent = player1_name

        score = f"{player1_score}-{player2_score}"

        return (
            f"{result} — **{match['tournament_name']}** "
            f"`{match['tournament_code']}`\n"
            f"Format : **{match['tournament_format']}** | "
            f"Round : **{match['round']}** | "
            f"Adversaire : **{opponent}** | "
            f"Score : `{score}` | "
            f"Statut : `{status}`"
        )

    def _format_swiss_match(
        self,
        match: aiosqlite.Row,
        player_id: str,
    ) -> str:

        player1_id = match["player1_id"]
        player1_name = match["player1_name"] or "Joueur 1"
        player2_name = match["player2_name"] or "BYE"

        player1_score = match["player1_score"]
        player2_score = match["player2_score"]

        winner_id = match["winner_id"]
        is_draw = match["is_draw"]
        is_bye = match["is_bye"]
        status = match["status"]

        if is_bye:
            result = "🟢 BYE"
            opponent = "BYE"
        elif is_draw:
            result = "➖ Égalité"
            opponent = player2_name if player_id == player1_id else player1_name
        elif player_id == winner_id:
            result = "✅ Victoire"
            opponent = player2_name if player_id == player1_id else player1_name
        elif winner_id is not None:
            result = "❌ Défaite"
            opponent = player2_name if player_id == player1_id else player1_name
        else:
            result = "⏳ En attente"
            opponent = player2_name if player_id == player1_id else player1_name

        score = f"{player1_score}-{player2_score}"

        return (
            f"{result} — **{match['tournament_name']}** "
            f"`{match['tournament_code']}`\n"
            f"Format : **{match['tournament_format']}** | "
            f"Ronde suisse : **{match['round_number']}** | "
            f"Table : **{match['table_number']}** | "
            f"Adversaire : **{opponent}** | "
            f"Score : `{score}` | "
            f"Statut : `{status}`"
        )

    @app_commands.command(
        name="match_history",
        description="Voir l'historique des matchs d'un joueur"
    )
    @app_commands.describe(
        member="Joueur à consulter"
    )
    async def match_history(
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

        bracket_matches = await self._get_bracket_matches(
            guild_id=guild_id,
            player_id=player_id,
            limit=5,
        )

        swiss_matches = await self._get_swiss_matches(
            guild_id=guild_id,
            player_id=player_id,
            limit=5,
        )

        lines = []

        for match in bracket_matches:
            lines.append(
                self._format_bracket_match(
                    match,
                    player_id,
                )
            )

        for match in swiss_matches:
            lines.append(
                self._format_swiss_match(
                    match,
                    player_id,
                )
            )

        if not lines:
            await interaction.followup.send(
                f"❌ Aucun historique trouvé pour {target.mention}.",
                ephemeral=True,
            )
            return

        lines = lines[:10]

        embed = discord.Embed(
            title="📜 Historique des matchs",
            description=f"Historique de {target.mention}",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Derniers matchs",
            value="\n\n".join(lines),
            inline=False,
        )

        embed.set_footer(
            text="Historique basé sur les matchs enregistrés par Hamtaro."
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(
        MatchHistoryCog(bot)
    )
