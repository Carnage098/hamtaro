"""
services/bracket_service.py

Gestion complète des brackets Hamtaro.

Fonctions principales :
- Génération automatique du bracket
- Gestion des BYE
- Propagation des vainqueurs
- Validation des résultats
- Détection du champion
- Export du bracket
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import aiosqlite

from config import DATABASE


# ==========================================================
# ENUMS
# ==========================================================

class MatchStatus(str, Enum):
    WAITING = "waiting"
    PENDING = "pending"
    APPROVED = "approved"
    REFUSED = "refused"
    FINISHED = "finished"


# ==========================================================
# MODELS
# ==========================================================

@dataclass(slots=True)
class Match:

    id: int

    tournament_id: int

    round: int

    match_number: int

    bracket_position: int

    next_match_id: Optional[int]

    player1_id: Optional[str]

    player2_id: Optional[str]

    player1_name: Optional[str]

    player2_name: Optional[str]

    player1_score: int

    player2_score: int

    winner_id: Optional[str]

    status: MatchStatus


# ==========================================================
# BRACKET SERVICE
# ==========================================================

class BracketService:

    def __init__(self) -> None:
        self.database = DATABASE

    # ------------------------------------------------------
    # DATABASE
    # ------------------------------------------------------

    async def connect(self) -> aiosqlite.Connection:

        db = await aiosqlite.connect(self.database)

        db.row_factory = aiosqlite.Row

        return db

    # ------------------------------------------------------
    # CALCULS
    # ------------------------------------------------------

    @staticmethod
    def calculate_bracket_size(player_count: int) -> int:
        """Retourne la taille du bracket (2,4,8,16,32...)."""

        return 2 ** math.ceil(math.log2(player_count))

    @staticmethod
    def calculate_rounds(bracket_size: int) -> int:
        """Retourne le nombre total de tours."""

        return int(math.log2(bracket_size))

    @staticmethod
    def round_name(round_number: int, total_rounds: int) -> str:
        """Retourne le nom du tour."""

        remaining = total_rounds - round_number

        names = {
            0: "Finale",
            1: "Demi-finales",
            2: "Quarts de finale",
            3: "Huitièmes de finale",
            4: "Seizièmes de finale",
            5: "Trente-deuxièmes de finale"
        }

        return names.get(remaining, f"Round {round_number}")

    # ------------------------------------------------------
    # GÉNÉRATION DU BRACKET
    # ------------------------------------------------------

    async def generate_bracket(self, tournament_id: int) -> None:
        """
        Génère entièrement le bracket du tournoi.
        """

        async with await self.connect() as db:

            cursor = await db.execute(
                """
                SELECT
                    discord_id,
                    username
                FROM registrations
                WHERE tournament_id = ?
                ORDER BY registered_at
                """,
                (tournament_id,)
            )

            players = await cursor.fetchall()

            if len(players) < 2:
                raise ValueError(
                    "Au moins deux joueurs sont nécessaires."
                )

            player_count = len(players)

            bracket_size = self.calculate_bracket_size(
                player_count
            )

            total_rounds = self.calculate_rounds(
                bracket_size
            )

            # Mélange des joueurs
            random.shuffle(players)

            # Ajout des BYE
            while len(players) < bracket_size:
                players.append(
                    {
                        "discord_id": None,
                        "username": "BYE"
                    }
                )

            print(
                f"Bracket : {player_count} joueurs → "
                f"{bracket_size} places "
                f"({total_rounds} tours)"
            )

# ==========================================================
# MATCHES
# ==========================================================

async def get_match(self, match_id: int) -> Match | None:
    """
    Retourne un match.
    """

    async with await self.connect() as db:

        cursor = await db.execute(
            """
            SELECT *
            FROM matches
            WHERE id = ?
            """,
            (match_id,)
        )

        row = await cursor.fetchone()

        if row is None:
            return None

        return Match.from_row(row)

async def get_matches(
    self,
    tournament_id: int
) -> list[Match]:

    async with await self.connect() as db:

        cursor = await db.execute(
            """
            SELECT *
            FROM matches

            WHERE tournament_id = ?

            ORDER BY
                round,
                match_number
            """,
            (tournament_id,)
        )

        rows = await cursor.fetchall()

        return [
            Match.from_row(row)
            for row in rows
        ]

async def get_round(
    self,
    tournament_id: int,
    round_number: int
) -> list[Match]:

    async with await self.connect() as db:

        cursor = await db.execute(
            """
            SELECT *

            FROM matches

            WHERE
                tournament_id = ?
            AND
                round = ?

            ORDER BY match_number
            """,
            (
                tournament_id,
                round_number
            )
        )

        rows = await cursor.fetchall()

        return [
            Match.from_row(row)
            for row in rows
        ]

async def get_player_matches(
    self,
    tournament_id: int,
    discord_id: str
) -> list[Match]:

    async with await self.connect() as db:

        cursor = await db.execute(
            """
            SELECT *

            FROM matches

            WHERE
                tournament_id = ?

            AND

            (
                player1_id = ?
                OR
                player2_id = ?
            )

            ORDER BY
                round
            """,
            (
                tournament_id,
                discord_id,
                discord_id
            )
        )

        rows = await cursor.fetchall()

        return [
            Match.from_row(row)
            for row in rows
        ]

async def create_match(
    self,
    tournament_id: int,
    round_number: int,
    match_number: int,
    bracket_position: int,
    next_match_id: int | None,
    player1: Player | None,
    player2: Player | None
) -> int:
    """
    Crée un match.
    """

    async with await self.connect() as db:

        cursor = await db.execute(
            """
            INSERT INTO matches(

                tournament_id,

                round,

                match_number,

                bracket_position,

                next_match_id,

                player1_id,

                player2_id,

                player1_name,

                player2_name,

                status

            )

            VALUES(

                ?,?,?,?,?,?,?,?,?,?

            )
            """,
            (
                tournament_id,

                round_number,

                match_number,

                bracket_position,

                next_match_id,

                None if player1 is None else player1.discord_id,

                None if player2 is None else player2.discord_id,

                None if player1 is None else player1.username,

                None if player2 is None else player2.username,

                MatchStatus.WAITING.value
            )
        )

        await db.commit()

        return cursor.lastrowid

# ==========================================================
# GÉNÉRATION DU BRACKET
# ==========================================================

async def generate_bracket(self, tournament_id: int) -> None:
    """
    Génère complètement le bracket d'un tournoi.

    Étapes :
        1. Vérifie le tournoi
        2. Récupère les joueurs
        3. Mélange (ou seeding)
        4. Ajoute les BYE
        5. Vide les anciens matchs
        6. Crée tout le bracket
        7. Place les joueurs
        8. Relie les matchs
        9. Traite automatiquement les BYE
        10. Met à jour le tournoi
    """

    # -----------------------------
    # Joueurs
    # -----------------------------

    players = await self.get_registered_players(
        tournament_id
    )

    players = self.seed_players(players)

    bracket_size = self.calculate_bracket_size(
        len(players)
    )

    total_rounds = self.calculate_rounds(
        bracket_size
    )

    players = self.add_byes(
        players,
        bracket_size
    )

    # -----------------------------
    # Nettoyage
    # -----------------------------

    await self.clear_matches(
        tournament_id
    )

    # -----------------------------
    # Création des matchs
    # -----------------------------

    await self.create_empty_bracket(
        tournament_id=tournament_id,
        bracket_size=bracket_size,
        total_rounds=total_rounds
    )

    # -----------------------------
    # Placement des joueurs
    # -----------------------------

    await self.fill_first_round(
        tournament_id,
        players
    )

    # -----------------------------
    # Liaisons
    # -----------------------------

    await self.link_matches(
        tournament_id
    )

    # -----------------------------
    # BYE automatiques
    # -----------------------------

    await self.process_byes(
        tournament_id
    )

    # -----------------------------
    # Mise à jour du tournoi
    # -----------------------------

    await self.update_tournament_infos(
        tournament_id,
        total_rounds
    )

# ==========================================================
# CRÉATION DU BRACKET
# ==========================================================

async def create_empty_bracket(
    self,
    tournament_id: int,
    bracket_size: int,
    total_rounds: int
) -> None:
    """
    Crée tous les matchs du tournoi.

    Aucun joueur n'est placé ici.
    """

    match_number = 1

    async with await self.connect() as db:

        for round_number in range(1, total_rounds + 1):

            matches_in_round = (
                bracket_size //
                (2 ** round_number)
            )

            for position in range(matches_in_round):

                await db.execute(
                    """
                    INSERT INTO matches(

                        tournament_id,

                        round,

                        match_number,

                        bracket_position,

                        status

                    )

                    VALUES(

                        ?, ?, ?, ?, ?

                    )
                    """,
                    (
                        tournament_id,

                        round_number,

                        match_number,

                        position,

                        MatchStatus.WAITING.value
                    )
                )

                match_number += 1

        await db.commit()

# ==========================================================
# PREMIER TOUR
# ==========================================================

async def fill_first_round(
    self,
    tournament_id: int,
    players: list[Player]
) -> None:
    """
    Place les joueurs dans les matchs du premier tour.
    """

    async with await self.connect() as db:

        cursor = await db.execute(
            """
            SELECT id

            FROM matches

            WHERE
                tournament_id = ?
            AND
                round = 1

            ORDER BY match_number
            """,
            (tournament_id,)
        )

        matches = await cursor.fetchall()

        player_index = 0

        for row in matches:

            player1 = players[player_index]
            player2 = players[player_index + 1]

            await db.execute(
                """
                UPDATE matches

                SET

                    player1_id = ?,
                    player2_id = ?,

                    player1_name = ?,
                    player2_name = ?

                WHERE id = ?
                """,
                (
                    player1.discord_id,
                    player2.discord_id,

                    player1.username,
                    player2.username,

                    row["id"]
                )
            )

            player_index += 2

        await db.commit()

# ==========================================================
# LIAISON DES MATCHS
# ==========================================================

async def link_matches(
    self,
    tournament_id: int
) -> None:
    """
    Relie tous les matchs entre eux en remplissant
    automatiquement next_match_id.
    """

    matches = await self.get_matches(
        tournament_id
    )

    rounds: dict[int, list[Match]] = {}

    for match in matches:

        rounds.setdefault(
            match.round,
            []
        ).append(match)

    async with await self.connect() as db:

        round_numbers = sorted(
            rounds.keys()
        )

        for current_round in round_numbers[:-1]:

            current_matches = rounds[current_round]

            next_matches = rounds[
                current_round + 1
            ]

            for index, match in enumerate(
                current_matches
            ):

                next_match = next_matches[
                    index // 2
                ]

                await db.execute(
                    """
                    UPDATE matches

                    SET next_match_id = ?

                    WHERE id = ?
                    """,
                    (
                        next_match.id,
                        match.id
                    )
                )

        await db.commit()



