import math
import random
import aiosqlite

from config import DATABASE


class BracketService:
    def __init__(self):
        self.database = DATABASE

    async def _connect(self):
        return await aiosqlite.connect(self.database)

    async def generate(self, tournament_id: int):
        """
        Génère entièrement le premier tour du tournoi.
        Les vainqueurs seront ensuite propagés automatiquement
        jusqu'à la finale.
        """

        async with aiosqlite.connect(self.database) as db:

            players = await db.execute_fetchall(
                '''
                SELECT player_id
                FROM tournament_players
                WHERE tournament_id = ?
                ORDER BY RANDOM()
                ''',
                (tournament_id,)
            )

            players = [p[0] for p in players]

            if len(players) < 2:
                raise ValueError("Il faut au moins deux joueurs.")

            bracket_size = 2 ** math.ceil(math.log2(len(players)))

            while len(players) < bracket_size:
                players.append(None)

            random.shuffle(players)

            round_number = 1
            match_number = 1

            for i in range(0, len(players), 2):

                player1 = players[i]
                player2 = players[i + 1]

                await db.execute(
                    '''
                    INSERT INTO matches(
                        tournament_id,
                        round,
                        match_number,
                        player1_id,
                        player2_id,
                        status
                    )
                    VALUES(?,?,?,?,?,?)
                    ''',
                    (
                        tournament_id,
                        round_number,
                        match_number,
                        player1,
                        player2,
                        "pending"
                    )
                )

                match_number += 1

            await db.commit()
# ------------------------------------------------------------------
# Propagation automatique des vainqueurs
# ------------------------------------------------------------------

async def advance_winner(self, match_id: int):
    """Fait avancer automatiquement le gagnant."""

    async with aiosqlite.connect(self.database) as db:

        cursor = await db.execute(
            '''
            SELECT id,
                   tournament_id,
                   round,
                   bracket_position,
                   winner
            FROM matches
            WHERE id = ?
            ''',
            (match_id,)
        )

        match = await cursor.fetchone()

        if not match:
            return

        tournament_id = match[1]
        current_round = match[2]
        position = match[3]
        winner = match[4]

        if winner is None:
            return

        next_round = current_round + 1
        next_position = position // 2

        cursor = await db.execute(
            '''
            SELECT id, player1, player2
            FROM matches
            WHERE tournament_id = ?
            AND round = ?
            AND bracket_position = ?
            ''',
            (
                tournament_id,
                next_round,
                next_position
            )
        )

        next_match = await cursor.fetchone()

        if next_match is None:
            return

        next_match_id = next_match[0]

        if next_match[1] is None:

            await db.execute(
                '''
                UPDATE matches
                SET player1 = ?
                WHERE id = ?
                ''',
                (
                    winner,
                    next_match_id
                )
            )

        else:

            await db.execute(
                '''
                UPDATE matches
                SET player2 = ?
                WHERE id = ?
                ''',
                (
                    winner,
                    next_match_id
                )
            )

        await db.commit()


# ------------------------------------------------------------------
# Détection du champion
# ------------------------------------------------------------------

async def get_champion(self, tournament_id: int):

    async with aiosqlite.connect(self.database) as db:

        cursor = await db.execute(
            '''
            SELECT winner
            FROM matches
            WHERE tournament_id = ?
            ORDER BY round DESC
            LIMIT 1
            ''',
            (tournament_id,)
        )

        row = await cursor.fetchone()

        if row:
            return row[0]

        return None

# ---------------------------------------------------------------
# Création automatique de tous les tours du bracket
# ---------------------------------------------------------------

async def create_next_rounds(self, tournament_id: int, bracket_size: int):

    async with aiosqlite.connect(self.database) as db:

        total_rounds = int(math.log2(bracket_size))

        # Round 2 -> Finale
        for current_round in range(2, total_rounds + 1):

            matches = bracket_size // (2 ** current_round)

            for position in range(matches):

                await db.execute(
                    """
                    INSERT INTO matches(
                        tournament_id,
                        round,
                        bracket_position,
                        player1,
                        player2,
                        winner,
                        status
                    )
                    VALUES (?, ?, ?, NULL, NULL, NULL, 'waiting')
                    """,
                    (
                        tournament_id,
                        current_round,
                        position
                    )
                )

        await db.commit()


# ---------------------------------------------------------------
# Validation automatique des BYE
# ---------------------------------------------------------------

async def process_byes(self, tournament_id: int):

    async with aiosqlite.connect(self.database) as db:

        cursor = await db.execute(
            """
            SELECT id, player1, player2
            FROM matches
            WHERE tournament_id = ?
            AND round = 1
            """,
            (tournament_id,)
        )

        matches = await cursor.fetchall()

        for match_id, p1, p2 in matches:

            if p1 == "BYE" and p2 != "BYE":

                await db.execute(
                    "UPDATE matches SET winner=?, status='approved' WHERE id=?",
                    (p2, match_id)
                )

                await self.advance_winner(match_id)

            elif p2 == "BYE" and p1 != "BYE":

                await db.execute(
                    "UPDATE matches SET winner=?, status='approved' WHERE id=?",
                    (p1, match_id)
                )

                await self.advance_winner(match_id)

        await db.commit()


# À appeler à la fin de generate():
#
# await self.create_next_rounds(tournament_id, bracket_size)
# await self.process_byes(tournament_id)

# ---------------------------------------------------------------
# Construction de l'affichage du bracket
# ---------------------------------------------------------------

ROUND_NAMES = {
    1: "Premier tour",
    2: "Quarts de finale",
    3: "Demi-finales",
    4: "Finale",
    5: "Grande Finale"
}

async def get_bracket_text(self, tournament_id: int):

    async with aiosqlite.connect(self.database) as db:

        cursor = await db.execute("""
            SELECT round,
                   bracket_position,
                   player1,
                   player2,
                   winner,
                   status
            FROM matches
            WHERE tournament_id = ?
            ORDER BY round, bracket_position
        """,(tournament_id,))

        matches = await cursor.fetchall()

    grouped = {}

    for row in matches:
        grouped.setdefault(row[0], []).append(row)

    lines = []

    for rnd in sorted(grouped.keys()):

        title = ROUND_NAMES.get(rnd, f"Round {rnd}")

        lines.append(f"🏆 **{title}**")

        for _, position, p1, p2, winner, status in grouped[rnd]:

            p1 = p1 or "???"
            p2 = p2 or "???"

            icon = {
                "waiting":"⏳",
                "pending":"🟡",
                "approved":"✅",
                "refused":"❌"
            }.get(status,"•")

            if winner:
                lines.append(
                    f"{icon} Match {position+1} : "
                    f"{p1} vs {p2} → **{winner}**"
                )
            else:
                lines.append(
                    f"{icon} Match {position+1} : "
                    f"{p1} vs {p2}"
                )

        lines.append("")

    return "\\n".join(lines)

# Utilisation dans une commande Discord :
#
# bracket = await bracket_service.get_bracket_text(tournament_id)
# await interaction.response.send_message(bracket)

# ---------------------------------------------------------------
# Validation d'un résultat
# ---------------------------------------------------------------

async def approve_result(self, match_id: int, winner: str):

    async with aiosqlite.connect(self.database) as db:

        cursor = await db.execute(
            """
            SELECT tournament_id, player1, player2
            FROM matches
            WHERE id = ?
            """,
            (match_id,)
        )

        match = await cursor.fetchone()

        if match is None:
            return False

        tournament_id, player1, player2 = match

        if winner not in (player1, player2):
            raise ValueError("Le vainqueur doit être un joueur du match.")

        await db.execute(
            """
            UPDATE matches
            SET
                winner = ?,
                status = 'approved'
            WHERE id = ?
            """,
            (winner, match_id)
        )

        await db.commit()

    # Le gagnant est propagé au tour suivant.
    await self.advance_winner(match_id)

    return True


# ---------------------------------------------------------------
# Refus d'un résultat
# ---------------------------------------------------------------

async def deny_result(self, match_id: int):

    async with aiosqlite.connect(self.database) as db:

        await db.execute(
            """
            UPDATE matches
            SET
                winner = NULL,
                status = 'refused'
            WHERE id = ?
            """,
            (match_id,)
        )

        await db.commit()


# ---------------------------------------------------------------
# Déclaration d'un résultat
# ---------------------------------------------------------------

async def report_result(self, match_id: int, winner: str):

    async with aiosqlite.connect(self.database) as db:

        await db.execute(
            """
            UPDATE matches
            SET
                winner = ?,
                status = 'pending'
            WHERE id = ?
            """,
            (winner, match_id)
        )

        await db.commit()

# Flux :
#
# Joueur -> report_result()
# Staff -> approve_result()
#         ou deny_result()
# approve_result() -> advance_winner()
# advance_winner() -> mise à jour automatique du tour suivant

from discord import app_commands
from discord.ext import commands

class Tournament(commands.Cog):

    def __init__(self, bot):

        self.bot = bot
        self.bracket = BracketService()


    @app_commands.command(
        name="bracket",
        description="Affiche le bracket du tournoi."
    )
    async def bracket_cmd(
        self,
        interaction,
        tournament_id: int
    ):

        text = await self.bracket.get_bracket_text(
            tournament_id
        )

        await interaction.response.send_message(text)


    @app_commands.command(
        name="report_result",
        description="Déclare un résultat."
    )
    async def report_result(

        self,
        interaction,
        match_id: int,
        winner: str

    ):

        await self.bracket.report_result(
            match_id,
            winner
        )

        await interaction.response.send_message(
            "✅ Résultat envoyé au staff."
        )


    @app_commands.command(
        name="approve_result",
        description="Valider un résultat."
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def approve_result(

        self,
        interaction,
        match_id: int,
        winner: str

    ):

        await self.bracket.approve_result(
            match_id,
            winner
        )

        await interaction.response.send_message(
            "🏆 Résultat validé."
        )


    @app_commands.command(
        name="deny_result",
        description="Refuser un résultat."
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def deny_result(

        self,
        interaction,
        match_id: int

    ):

        await self.bracket.deny_result(match_id)

        await interaction.response.send_message(
            "❌ Résultat refusé."
        )


async def setup(bot):

    await bot.add_cog(
        Tournament(bot)
    )

import discord
from discord.ui import View, Button

class MatchValidationView(View):

    def __init__(self, bracket_service, match_id):
        super().__init__(timeout=None)
        self.bracket_service = bracket_service
        self.match_id = match_id

    @discord.ui.button(
        label="✅ Valider",
        style=discord.ButtonStyle.success
    )
    async def validate(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        await interaction.response.send_message(
            "Choisissez ensuite le vainqueur.",
            ephemeral=True
        )

    @discord.ui.button(
        label="❌ Refuser",
        style=discord.ButtonStyle.danger
    )
    async def deny(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        await self.bracket_service.deny_result(self.match_id)

        await interaction.response.edit_message(
            content="❌ Résultat refusé.",
            view=None
        )

    @discord.ui.button(
        label="🏆 Voir le bracket",
        style=discord.ButtonStyle.primary
    )
    async def bracket(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        text = await self.bracket_service.get_bracket_text(
            interaction.guild.id
        )

        await interaction.response.send_message(
            text,
            ephemeral=True
        )

import discord
from discord.ui import Select, View

class WinnerSelect(Select):

    def __init__(self, bracket_service, match_id, player1, player2):
        self.bracket_service = bracket_service
        self.match_id = match_id

        options = [
            discord.SelectOption(label=player1, value=player1),
            discord.SelectOption(label=player2, value=player2)
        ]

        super().__init__(
            placeholder="Choisir le vainqueur...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        winner = self.values[0]

        await self.bracket_service.approve_result(
            self.match_id,
            winner
        )

        bracket = await self.bracket_service.get_bracket_text(
            interaction.guild.id
        )

        await interaction.response.edit_message(
            content=(
                f"✅ Résultat validé.\n\n"
                f"{bracket}"
            ),
            view=None
        )


class WinnerView(View):

    def __init__(self, bracket_service, match_id, player1, player2):
        super().__init__(timeout=300)
        self.add_item(
            WinnerSelect(
                bracket_service,
                match_id,
                player1,
                player2
            )
        )

# Exemple :
#
# view = WinnerView(
#     bracket_service,
#     match.id,
#     match.player1,
#     match.player2
# )
#
# await channel.send(
#     "Sélectionnez le vainqueur du duel :",
#     view=view
# )

# Améliorations futures :
# - Désactiver automatiquement les composants après validation.
# - Modifier le message du tournoi au lieu d'en envoyer un nouveau.
# - Mentionner les deux joueurs qualifiés pour le prochain match.
# - Historique des validations (staff + date).
# ----------------------------------------------------------
# Notification des joueurs qualifiés
# ----------------------------------------------------------

async def notify_next_match(
    self,
    guild,
    next_match_id
):

    match = await self.get_match(next_match_id)

    if match is None:
        return

    if match.player1 is None or match.player2 is None:
        return

    p1 = guild.get_member(match.player1_id)
    p2 = guild.get_member(match.player2_id)

    if p1:
        await p1.send(
            f"🏆 Ton prochain match est prêt !\n"
            f"Adversaire : {match.player2}"
        )

    if p2:
        await p2.send(
            f"🏆 Ton prochain match est prêt !\n"
            f"Adversaire : {match.player1}"
        )


# ----------------------------------------------------------
# Mise à jour du message du bracket
# ----------------------------------------------------------

async def refresh_bracket_message(
    self,
    channel,
    message_id,
    tournament_id
):

    bracket = await self.get_bracket_text(
        tournament_id
    )

    try:
        message = await channel.fetch_message(message_id)

        await message.edit(
            content=(
                "## 🏆 Bracket du tournoi\n\n"
                + bracket
            )
        )

    except Exception:
        pass

from PIL import Image, ImageDraw, ImageFont
import io
import discord

class BracketRenderer:

    WIDTH = 1800
    HEIGHT = 900

    def __init__(self):
        self.font = ImageFont.load_default()

    async def render(self, rounds):

        image = Image.new(
            "RGB",
            (self.WIDTH, self.HEIGHT),
            (30, 30, 30)
        )

        draw = ImageDraw.Draw(image)

        x_spacing = 320
        y_spacing = 80

        for round_index, matches in enumerate(rounds):

            x = 40 + round_index * x_spacing

            for match_index, match in enumerate(matches):

                y = 40 + match_index * y_spacing * (2 ** round_index)

                draw.rectangle(
                    (x, y, x + 220, y + 50),
                    outline="white",
                    width=2
                )

                draw.text(
                    (x + 10, y + 8),
                    match.player1 or "???",
                    font=self.font,
                    fill="white"
                )

                draw.text(
                    (x + 10, y + 28),
                    match.player2 or "???",
                    font=self.font,
                    fill="white"
                )

                if match.winner:

                    draw.text(
                        (x + 170, y + 16),
                        "🏆",
                        font=self.font,
                        fill="gold"
                    )

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)

        return discord.File(
            buffer,
            filename="bracket.png"
        )



