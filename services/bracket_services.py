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

            # Les prochaines étapes seront :
            #
            # 1. Suppression des anciens matchs
            # 2. Création du premier tour
            # 3. Création des tours suivants
            # 4. Liaison des next_match_id
            # 5. Validation automatique des BYE
            # 6. Sauvegarde en base




