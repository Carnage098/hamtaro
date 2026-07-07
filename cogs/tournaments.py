import discord
import aiosqlite

from discord.ext import commands
from discord import app_commands

from config import DATABASE


FORMATS = [
    "Format Actuel",
    "Master Duel",
    "Genesys",
    "GOAT",
    "Edison",
    "HAT",
    "Tengu Plant",
    "Dragon Ruler",
    "TeleDAD",
    "Rush Duel",
    "Speed Duel"
]


class Tournament(commands.Cog):

    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(
        name="create_tournament",
        description="Créer un tournoi"
    )
    @app_commands.describe(
        name="Nom du tournoi",
        format="Format du tournoi",
        size="Nombre de joueurs"
    )
    @app_commands.choices(
        format=[
            app_commands.Choice(name=f, value=f)
            for f in FORMATS
        ]
    )
    async def create_tournament(
        self,
        interaction: discord.Interaction,
        name: str,
        format: app_commands.Choice[str],
        size: int
    ):

        if size not in [4, 8, 16, 32, 64]:

            await interaction.response.send_message(
                "❌ Le tournoi doit comporter 4, 8, 16, 32 ou 64 joueurs.",
                ephemeral=True
            )
            return

        guild_id = str(interaction.guild.id)

        async with aiosqlite.connect(DATABASE) as db:

            cursor = await db.execute(
                """
                SELECT id
                FROM tournaments
                WHERE guild_id=?
                AND status!='finished'
                """,
                (guild_id,)
            )

            if await cursor.fetchone():

                await interaction.response.send_message(
                    "❌ Un tournoi est déjà en cours.",
                    ephemeral=True
                )

                return

            await db.execute(
                """
                INSERT INTO tournaments(
                    guild_id,
                    name,
                    format,
                    size,
                    status
                )
                VALUES(?,?,?,?,?)
                """,
                (
                    guild_id,
                    name,
                    format.value,
                    size,
                    "registration"
                )
            )

            await db.commit()

        await interaction.response.send_message(
            f"""
🏆 **Tournoi créé**

Nom : **{name}**

Format : **{format.value}**

Joueurs : **{size}**

📋 Les inscriptions sont ouvertes.
"""
        )
@app_commands.command(
    name="tournament",
    description="Voir le tournoi en cours"
)
async def tournament(
    self,
    interaction: discord.Interaction
):

    guild_id = str(interaction.guild.id)

    async with aiosqlite.connect(DATABASE) as db:

        cursor = await db.execute(
            """
            SELECT
                id,
                name,
                format,
                size,
                status
            FROM tournaments
            WHERE guild_id=?
            AND status!='finished'
            """,
            (guild_id,)
        )

        tournament = await cursor.fetchone()

        if tournament is None:

            await interaction.response.send_message(
                "❌ Aucun tournoi.",
                ephemeral=True
            )

            return

        cursor = await db.execute(
            """
            SELECT COUNT(*)
            FROM registrations
            WHERE tournament_id=?
            """,
            (tournament[0],)
        )

        registered = (await cursor.fetchone())[0]

    embed = discord.Embed(
        title="🏆 Tournoi en cours",
        color=discord.Color.gold()
    )

    embed.add_field(name="Nom", value=tournament[1], inline=False)
    embed.add_field(name="Format", value=tournament[2], inline=True)
    embed.add_field(name="Statut", value=tournament[4], inline=True)
    embed.add_field(
        name="Inscriptions",
        value=f"{registered}/{tournament[3]}",
        inline=False
    )

    await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Tournament(bot))
