import discord
import aiosqlite

from discord.ext import commands
from discord import app_commands

from config import DATABASE


class Registration(commands.Cog):

    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(
        name="register",
        description="S'inscrire au tournoi"
    )
    async def register(
        self,
        interaction: discord.Interaction
    ):

        guild_id = str(interaction.guild.id)
        discord_id = str(interaction.user.id)

        async with aiosqlite.connect(DATABASE) as db:

            cursor = await db.execute(
                """
                SELECT id,size
                FROM tournaments
                WHERE guild_id=?
                AND status='registration'
                """,
                (guild_id,)
            )

            tournament = await cursor.fetchone()

            if tournament is None:

                await interaction.response.send_message(
                    "❌ Aucun tournoi en inscription.",
                    ephemeral=True
                )

                return

            tournament_id = tournament[0]
            max_players = tournament[1]

            cursor = await db.execute(
                """
                SELECT 1
                FROM registrations
                WHERE tournament_id=?
                AND discord_id=?
                """,
                (
                    tournament_id,
                    discord_id
                )
            )

            if await cursor.fetchone():

                await interaction.response.send_message(
                    "❌ Tu es déjà inscrit.",
                    ephemeral=True
                )

                return

            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM registrations
                WHERE tournament_id=?
                """,
                (tournament_id,)
            )

            current = (await cursor.fetchone())[0]

            if current >= max_players:

                await interaction.response.send_message(
                    "❌ Les inscriptions sont complètes.",
                    ephemeral=True
                )

                return

            await db.execute(
                """
                INSERT INTO registrations(
                    tournament_id,
                    discord_id,
                    deck
                )
                VALUES(?,?,NULL)
                """,
                (
                    tournament_id,
                    discord_id
                )
            )

            current += 1

            if current == max_players:

                await db.execute(
                    """
                    UPDATE tournaments
                    SET status='ready'
                    WHERE id=?
                    """,
                    (tournament_id,)
                )

            await db.commit()

        await interaction.response.send_message(
            f"""
✅ Inscription validée !

👤 {interaction.user.mention}

📊 {current}/{max_players} joueurs inscrits.
"""
        )


async def setup(bot):
    await bot.add_cog(Registration(bot))
