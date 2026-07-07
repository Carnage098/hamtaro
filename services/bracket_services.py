from __future__ import annotations

import math
import random

from models.match import Match
from models.tournament import Tournament

from models.enums import MatchStatus

from services.base_service import BaseService


class BracketService(BaseService):
    """
    Gestion complète des tournois à élimination directe.

    Fonctionnalités :

    • génération du bracket
    • création de tous les matchs
    • gestion automatique des BYE
    • progression automatique
    • validation des résultats
    • récupération du bracket
    • finale
    • vainqueur
    """

    ROUND_NAMES = {
        1: "Finale",
        2: "Demi-finale",
        3: "Quart de finale",
        4: "Huitième de finale",
        5: "Seizième de finale",
        6: "Trente-deuxième de finale",
        7: "Soixante-quatrième de finale",
    }

    def __init__(self, database):
        super().__init__(database)

    # --------------------------------------------------
    # OUTILS
    # --------------------------------------------------

    @staticmethod
    def next_power_of_two(value: int) -> int:

        if value <= 2:
            return 2

        return 1 << (value - 1).bit_length()

    @staticmethod
    def total_rounds(player_count: int) -> int:

        return int(math.log2(player_count))

    @classmethod
    def round_name(cls, round_number: int):

        return cls.ROUND_NAMES.get(
            round_number,
            f"Round {round_number}",
        )

    @staticmethod
    def shuffle(players):

        players = list(players)

        random.shuffle(players)

        return players

