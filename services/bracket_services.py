from __future__ import annotations

import math
import random

from models.player import Player
from models.match import Match
from models.tournament import Tournament
from models.enums import MatchStatus

from services.base_service import BaseService


class BracketService(BaseService):
    """
    Service responsable de toute la logique des tournois à élimination directe.

    Fonctionnalités :
        - génération automatique du bracket
        - gestion des BYE
        - création des matchs
        - progression des vainqueurs
        - récupération des rounds
        - calcul des phases (Quart, Demi, Finale...)
    """

    ROUND_NAMES = {
        2: "Finale",
        4: "Demi-finale",
        8: "Quart de finale",
        16: "Huitième de finale",
        32: "Seizième de finale",
        64: "Trente-deuxième de finale",
    }

    def __init__(self, database):
        super().__init__(database)

    @staticmethod
    def _next_power_of_two(value: int) -> int:
        """
        Retourne la prochaine puissance de deux.
        Exemple :
            5 -> 8
            11 -> 16
            32 -> 32
        """
        if value <= 1:
            return 2

        return 1 << (value - 1).bit_length()

    @staticmethod
    def _shuffle_players(players: list[Player]) -> list[Player]:
        """
        Mélange les joueurs afin d'obtenir un bracket aléatoire.
        """
        shuffled = players[:]
        random.shuffle(shuffled)
        return shuffled

    @classmethod
    def _round_name(cls, player_count: int) -> str:
        """
        Retourne le nom du round.
        """
        return cls.ROUND_NAMES.get(player_count, f"Top {player_count}")

    @staticmethod
    def _total_rounds(player_count: int) -> int:
        """
        Calcule le nombre total de rounds.
        """
        if player_count <= 1:
            return 1

        return int(math.log2(player_count))

      async def generate(self, tournament_id: int) -> list[Match]:
        """
        Génère un arbre à élimination directe.

        Retourne la liste des matchs créés.
        """

        tournament: Tournament | None = await self.database.get_tournament(
            tournament_id
        )

        if tournament is None:
            raise ValueError("Tournoi introuvable.")

        players: list[Player] = await self.database.get_tournament_players(
            tournament_id
        )

        if len(players) < 2:
            raise ValueError(
                "Au moins deux joueurs sont nécessaires pour générer un bracket."
            )

        # Mélange aléatoire
        players = self._shuffle_players(players)

        bracket_size = self._next_power_of_two(len(players))
        bye_count = bracket_size - len(players)

        # Ajout des BYE (None représente une place vide)
        slots: list[Player | None] = players + [None] * bye_count

        first_round_matches: list[Match] = []

        current_round = self._total_rounds(bracket_size)

        match_number = 1

        # Création du premier tour
        for index in range(0, len(slots), 2):

            player1 = slots[index]
            player2 = slots[index + 1]

            # Détermination automatique du statut
            if player1 is None and player2 is None:
                status = MatchStatus.COMPLETED
                winner = None

            elif player1 is None:
                status = MatchStatus.COMPLETED
                winner = player2

            elif player2 is None:
                status = MatchStatus.COMPLETED
                winner = player1

            else:
                status = MatchStatus.PENDING
                winner = None

            match = Match(
                tournament_id=tournament_id,
                round=current_round,
                match_number=match_number,
                player1_id=player1.id if player1 else None,
                player2_id=player2.id if player2 else None,
                winner_id=winner.id if winner else None,
                status=status,
            )

            match = await self.database.create_match(match)

            first_round_matches.append(match)

            match_number += 1


        #
        # Création des rounds suivants
        #

        previous_round = first_round_matches

        round_number = current_round - 1

        while len(previous_round) > 1:

            current_matches: list[Match] = []

            match_number = 1

            for index in range(0, len(previous_round), 2):

                match = Match(
                    tournament_id=tournament_id,
                    round=round_number,
                    match_number=match_number,
                    player1_id=None,
                    player2_id=None,
                    winner_id=None,
                    status=MatchStatus.PENDING,
                )

                match = await self.database.create_match(match)

                current_matches.append(match)

                #
                # Les vainqueurs des deux matchs précédents
                # seront envoyés dans ce nouveau match.
                #

                previous_round[index].winner_to_match_id = match.id
                previous_round[index + 1].winner_to_match_id = match.id

                await self.database.update_match(previous_round[index])
                await self.database.update_match(previous_round[index + 1])

                match_number += 1

            previous_round = current_matches

            round_number -= 1

        #
        # Si certains matchs du premier tour sont gagnés automatiquement
        # (BYE), on propage directement les joueurs.
        #

        for match in first_round_matches:

            if (
                match.status == MatchStatus.COMPLETED
                and match.winner_id is not None
                and match.winner_to_match_id is not None
            ):
                await self.advance_winner(match.id)

        return first_round_matches

    async def advance_winner(self, match_id: int) -> None:
        """
        Envoie le vainqueur d'un match vers le match suivant.
        Si un nouveau BYE apparaît, il est automatiquement propagé.
        """

        match: Match | None = await self.database.get_match(match_id)

        if match is None:
            return

        if match.winner_id is None:
            return

        if match.winner_to_match_id is None:
            # Finale : aucun match suivant.
            return

        next_match: Match | None = await self.database.get_match(
            match.winner_to_match_id
        )

        if next_match is None:
            return

        #
        # Placement du joueur dans la première place libre.
        #

        if next_match.player1_id is None:
            next_match.player1_id = match.winner_id

        elif next_match.player2_id is None:
            next_match.player2_id = match.winner_id

        else:
            raise RuntimeError(
                f"Le match {next_match.id} est déjà complet."
            )

        #
        # Si les deux joueurs sont présents,
        # le match devient jouable.
        #

        if (
            next_match.player1_id is not None
            and next_match.player2_id is not None
        ):
            next_match.status = MatchStatus.PENDING

        #
        # Si un seul joueur est présent alors que l'autre côté
        # restera vide (BYE), on le qualifie automatiquement.
        #

        elif (
            next_match.player1_id is not None
            and next_match.player2_id is None
        ):
            next_match.status = MatchStatus.COMPLETED
            next_match.winner_id = next_match.player1_id

        elif (
            next_match.player2_id is not None
            and next_match.player1_id is None
        ):
            next_match.status = MatchStatus.COMPLETED
            next_match.winner_id = next_match.player2_id

        await self.database.update_match(next_match)

        #
        # Si un BYE provoque une nouvelle qualification automatique,
        # on continue jusqu'à la finale.
        #

        if (
            next_match.status == MatchStatus.COMPLETED
            and next_match.winner_to_match_id is not None
        ):
            await self.advance_winner(next_match.id)


    async def get_round_matches(
        self,
        tournament_id: int,
        round_number: int,
    ) -> list[Match]:
        """
        Retourne tous les matchs d'un round.
        """

        return await self.database.get_round_matches(
            tournament_id,
            round_number,
        )

    async def get_current_round(
        self,
        tournament_id: int,
    ) -> int | None:
        """
        Retourne le round actuellement en cours.
        """

        rounds = await self.database.get_tournament_rounds(
            tournament_id
        )

        if not rounds:
            return None

        for round_number in sorted(rounds, reverse=True):

            matches = await self.database.get_round_matches(
                tournament_id,
                round_number,
            )

            if any(
                match.status != MatchStatus.COMPLETED
                for match in matches
            ):
                return round_number

        return min(rounds)

    async def get_next_match(
        self,
        tournament_id: int,
        player_id: int,
    ) -> Match | None:
        """
        Retourne le prochain match d'un joueur.
        """

        matches = await self.database.get_tournament_matches(
            tournament_id
        )

        for match in matches:

            if (
                match.player1_id == player_id
                or match.player2_id == player_id
            ):

                if match.status != MatchStatus.COMPLETED:
                    return match

        return None

    async def get_final_match(
        self,
        tournament_id: int,
    ) -> Match | None:
        """
        Retourne la finale.
        """

        matches = await self.database.get_tournament_matches(
            tournament_id
        )

        if not matches:
            return None

        return min(matches, key=lambda m: m.round)

    async def is_finished(
        self,
        tournament_id: int,
    ) -> bool:
        """
        Indique si le tournoi est terminé.
        """

        final = await self.get_final_match(
            tournament_id
        )

        if final is None:
            return False

        return (
            final.status == MatchStatus.COMPLETED
            and final.winner_id is not None
        )

    async def get_winner(
        self,
        tournament_id: int,
    ) -> Player | None:
        """
        Retourne le vainqueur du tournoi.
        """

        final = await self.get_final_match(
            tournament_id
        )

        if (
            final is None
            or final.winner_id is None
        ):
            return None

        return await self.database.get_player(
            final.winner_id
        )

    async def get_bracket(
        self,
        tournament_id: int,
    ) -> dict[int, list[Match]]:
        """
        Retourne tous les matchs classés par round.

        Exemple :
        {
            3: [...],
            2: [...],
            1: [...]
        }
        """

        matches = await self.database.get_tournament_matches(
            tournament_id
        )

        bracket: dict[int, list[Match]] = {}

        for match in matches:
            bracket.setdefault(
                match.round,
                []
            ).append(match)

        for round_matches in bracket.values():
            round_matches.sort(
                key=lambda m: m.match_number
            )

        return dict(
            sorted(
                bracket.items(),
                reverse=True,
            )
        )
