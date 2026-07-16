"""
services/swiss_service.py

Gestion des rondes suisses pour Hamtaro.

Fonctionnalités :
- Démarrer un tournoi en rondes suisses
- Générer automatiquement les pairings
- Éviter les rematchs autant que possible
- Gérer les BYE
- Afficher la ronde actuelle
- Afficher le classement
- Terminer les rondes suisses
"""

from __future__ import annotations

import random

from dataclasses import dataclass


@dataclass(slots=True)
class SwissPlayer:
    discord_id: str
    username: str
    points: int = 0
    played: int = 0
    wins: int = 0
    double_losses: int = 0
    losses: int = 0
    byes: int = 0
    seed: int | None = None


class SwissService:

    def __init__(
        self,
        db,
    ):

        self.db = db

    # ==========================================================
    # JOUEURS
    # ==========================================================

    async def list_active_players(
        self,
        tournament_id: int,
    ) -> list[SwissPlayer]:
        """
        Liste les joueurs actifs du tournoi.

        Les joueurs drop ou disqualifiés sont exclus.
        """

        rows = await self.db.fetchall(
            """
            SELECT
                discord_id,
                username,
                seed
            FROM registrations
            WHERE tournament_id = ?
            AND dropped = 0
            AND disqualified = 0
            ORDER BY
                CASE
                    WHEN seed IS NULL THEN 999999
                    ELSE seed
                END ASC,
                username ASC
            """,
            (tournament_id,),
        )

        players: list[SwissPlayer] = []

        for row in rows:

            players.append(
                SwissPlayer(
                    discord_id=row["discord_id"],
                    username=row["username"],
                    seed=row["seed"],
                )
            )

        return players

    async def list_players_with_standings(
        self,
        tournament_id: int,
    ) -> list[SwissPlayer]:
        """
        Liste les joueurs avec leur classement suisse.
        """

        standings = await self.db.get_swiss_standings(
            tournament_id
        )

        players: list[SwissPlayer] = []

        for row in standings:

            players.append(
                SwissPlayer(
                    discord_id=row["discord_id"],
                    username=row["username"],
                    points=int(row["points"] or 0),
                    played=int(row["played"] or 0),
                    wins=int(row["wins"] or 0),
                    double_losses=int(row["double_losses"] or 0),
                    losses=int(row["losses"] or 0),
                    byes=int(row["byes"] or 0),
                )
            )

        return players

    # ==========================================================
    # LANCEMENT
    # ==========================================================

    async def start(
        self,
        tournament_id: int,
        total_rounds: int,
        *,
        shuffle_first_round: bool = True,
    ) -> str:
        """
        Démarre les rondes suisses et génère la ronde 1.
        """

        if total_rounds < 1:

            raise ValueError(
                "Le nombre de rondes doit être supérieur ou égal à 1."
            )

        players = await self.list_active_players(
            tournament_id
        )

        if len(players) < 2:

            raise ValueError(
                "Il faut au moins 2 joueurs pour lancer des rondes suisses."
            )

        existing_settings = await self.db.get_swiss_settings(
            tournament_id
        )

        if existing_settings is not None:

            await self.db.reset_swiss_tournament(
                tournament_id
            )

        await self.db.start_swiss_tournament(
            tournament_id=tournament_id,
            total_rounds=total_rounds,
        )

        await self.generate_round(
            tournament_id=tournament_id,
            round_number=1,
            shuffle_first_round=shuffle_first_round,
        )

        return await self.format_round(
            tournament_id=tournament_id,
            round_number=1,
        )

    # ==========================================================
    # GÉNÉRATION DES RONDES
    # ==========================================================

    async def generate_round(
        self,
        tournament_id: int,
        round_number: int,
        *,
        shuffle_first_round: bool = False,
    ) -> None:
        """
        Génère une ronde suisse.
        """

        if round_number < 1:

            raise ValueError(
                "Le numéro de ronde doit être supérieur ou égal à 1."
            )

        settings = await self.db.get_swiss_settings(
            tournament_id
        )

        if settings is None:

            raise ValueError(
                "Les rondes suisses ne sont pas lancées pour ce tournoi."
            )

        if settings["status"] != "running":

            raise ValueError(
                "Les rondes suisses ne sont pas en cours."
            )

        total_rounds = int(settings["total_rounds"])

        if round_number > total_rounds:

            raise ValueError(
                "Toutes les rondes suisses ont déjà été générées."
            )

        round_exists = await self.db.swiss_round_exists(
            tournament_id=tournament_id,
            round_number=round_number,
        )

        if round_exists:

            raise ValueError(
                f"La ronde {round_number} existe déjà."
            )

        if round_number > 1:

            previous_pending = await self.db.count_pending_swiss_matches(
                tournament_id=tournament_id,
                round_number=round_number - 1,
            )

            if previous_pending > 0:

                raise ValueError(
                    "La ronde précédente n'est pas encore terminée."
                )

        if round_number == 1:

            players = await self.list_active_players(
                tournament_id
            )

            if shuffle_first_round:

                random.shuffle(players)

        else:

            players = await self.list_players_with_standings(
                tournament_id
            )

        if len(players) < 2:

            raise ValueError(
                "Il faut au moins 2 joueurs actifs pour générer une ronde."
            )

        pairings = await self._build_pairings(
            tournament_id=tournament_id,
            players=players,
        )

        table_number = 1

        for player1, player2, is_bye in pairings:

            await self.db.create_swiss_match(
                tournament_id=tournament_id,
                round_number=round_number,
                table_number=table_number,
                player1_id=player1.discord_id,
                player1_name=player1.username,
                player2_id=player2.discord_id if player2 else None,
                player2_name=player2.username if player2 else None,
                is_bye=is_bye,
            )

            table_number += 1

        await self.db.set_swiss_current_round(
            tournament_id=tournament_id,
            round_number=round_number,
        )

    async def next_round(
        self,
        tournament_id: int,
    ) -> str:
        """
        Génère la prochaine ronde suisse.
        """

        settings = await self.db.get_swiss_settings(
            tournament_id
        )

        if settings is None:

            raise ValueError(
                "Les rondes suisses ne sont pas lancées pour ce tournoi."
            )

        current_round = int(settings["current_round"])
        total_rounds = int(settings["total_rounds"])

        if current_round >= total_rounds:

            await self.db.finish_swiss_tournament(
                tournament_id
            )

            raise ValueError(
                "Toutes les rondes suisses sont terminées."
            )

        pending = await self.db.count_pending_swiss_matches(
            tournament_id=tournament_id,
            round_number=current_round,
        )

        if pending > 0:

            raise ValueError(
                "Impossible de passer à la ronde suivante : des matchs sont encore en attente."
            )

        next_round_number = current_round + 1

        await self.generate_round(
            tournament_id=tournament_id,
            round_number=next_round_number,
        )

        return await self.format_round(
            tournament_id=tournament_id,
            round_number=next_round_number,
        )

    # ==========================================================
    # PAIRINGS
    # ==========================================================

    async def _build_pairings(
        self,
        tournament_id: int,
        players: list[SwissPlayer],
    ) -> list[tuple[SwissPlayer, SwissPlayer | None, bool]]:
        """
        Construit les pairings.

        Retourne une liste :
        [
            (joueur1, joueur2, is_bye),
            ...
        ]
        """

        players = list(players)

        players.sort(
            key=lambda player: (
                -player.points,
                player.double_losses,
                -player.wins,
                player.losses,
                player.byes,
                player.username.lower(),
            )
        )

        pairings: list[tuple[SwissPlayer, SwissPlayer | None, bool]] = []

        if len(players) % 2 == 1:

            bye_player = await self._choose_bye_player(
                tournament_id=tournament_id,
                players=players,
            )

            players.remove(bye_player)

            pairings.append(
                (
                    bye_player,
                    None,
                    True,
                )
            )

        while players:

            player1 = players.pop(0)

            opponent_index = await self._find_best_opponent_index(
                tournament_id=tournament_id,
                player=player1,
                candidates=players,
            )

            player2 = players.pop(opponent_index)

            pairings.append(
                (
                    player1,
                    player2,
                    False,
                )
            )

        return pairings

    async def _choose_bye_player(
        self,
        tournament_id: int,
        players: list[SwissPlayer],
    ) -> SwissPlayer:
        """
        Choisit le joueur qui reçoit le BYE.

        Priorité :
        - joueur sans BYE
        - joueur avec le moins de points
        - joueur avec le moins de victoires
        """

        candidates: list[SwissPlayer] = []

        for player in players:

            already_had_bye = await self.db.has_received_swiss_bye(
                tournament_id=tournament_id,
                discord_id=player.discord_id,
            )

            if not already_had_bye:

                candidates.append(player)

        if not candidates:

            candidates = list(players)

        candidates.sort(
            key=lambda player: (
                player.points,
                player.wins,
                player.double_losses,
                player.username.lower(),
            )
        )

        return candidates[0]

    async def _find_best_opponent_index(
        self,
        tournament_id: int,
        player: SwissPlayer,
        candidates: list[SwissPlayer],
    ) -> int:
        """
        Trouve le meilleur adversaire possible.

        Le bot essaye d'abord d'éviter les rematchs.
        S'il n'y a pas d'autre solution, il accepte un rematch.
        """

        previous_opponents = await self.db.get_swiss_opponents(
            tournament_id=tournament_id,
            discord_id=player.discord_id,
        )

        best_index = 0
        best_score = None

        for index, candidate in enumerate(candidates):

            already_played = candidate.discord_id in previous_opponents

            score_gap = abs(player.points - candidate.points)

            penalty = 1000 if already_played else 0

            score = (
                penalty,
                score_gap,
                -candidate.points,
                -candidate.wins,
                candidate.byes,
                candidate.username.lower(),
            )

            if best_score is None or score < best_score:

                best_score = score
                best_index = index

        return best_index

    # ==========================================================
    # RÉSULTATS
    # ==========================================================

    async def report_result(
        self,
        match_id: int,
        result: str,
        *,
        reported_by: str | None = None,
    ) -> None:
        """Enregistre une victoire ou un double loss en ronde suisse."""

        match = await self.db.get_swiss_match(match_id)

        if match is None:
            raise ValueError("Match suisse introuvable.")

        if str(match["status"]).lower() != "pending":
            raise ValueError("Ce match est déjà terminé.")

        if int(match["is_bye"] or 0) == 1:
            raise ValueError("Un BYE est déjà automatiquement validé.")

        result = result.lower().strip()

        if result == "double_loss":
            await self.db.report_swiss_double_loss(
                match_id=match_id,
                reported_by=reported_by,
            )
            return

        if result == "player1":
            await self.db.report_swiss_result(
                match_id=match_id,
                winner_id=str(match["player1_id"]),
                winner_name=str(match["player1_name"]),
                player1_score=1,
                player2_score=0,
                reported_by=reported_by,
            )
            return

        if result == "player2":
            if match["player2_id"] is None:
                raise ValueError("Ce match n'a pas de joueur 2.")

            await self.db.report_swiss_result(
                match_id=match_id,
                winner_id=str(match["player2_id"]),
                winner_name=str(match["player2_name"]),
                player1_score=0,
                player2_score=1,
                reported_by=reported_by,
            )
            return

        raise ValueError(
            "Résultat invalide. Utilise : player1, player2 ou double_loss."
        )

    # ==========================================================
    # AFFICHAGE
    # ==========================================================

    async def format_current_round(
        self,
        tournament_id: int,
    ) -> str:
        """
        Affiche la ronde actuelle.
        """

        settings = await self.db.get_swiss_settings(
            tournament_id
        )

        if settings is None:

            raise ValueError(
                "Les rondes suisses ne sont pas lancées pour ce tournoi."
            )

        current_round = int(settings["current_round"])

        return await self.format_round(
            tournament_id=tournament_id,
            round_number=current_round,
        )

    async def format_round(
        self,
        tournament_id: int,
        round_number: int,
    ) -> str:
        """Affiche une ronde suisse sans match nul."""

        matches = await self.db.list_swiss_matches(
            tournament_id=tournament_id,
            round_number=round_number,
        )

        if not matches:
            return f"📭 Aucun match trouvé pour la ronde {round_number}."

        lines = [f"🐹 **Ronde suisse {round_number}**", ""]

        for match in matches:
            table = match["table_number"]

            if int(match["is_bye"] or 0) == 1:
                lines.append(
                    f"**Table {table}** — {match['player1_name']} reçoit un **BYE** ✅"
                )
                continue

            if str(match["status"]).lower() == "completed":
                is_double_loss = int(match["is_double_loss"] or 0) == 1
                legacy_draw = int(match["is_draw"] or 0) == 1
                result = str(match["result"] or "none").lower()

                if is_double_loss or legacy_draw or result in {"double_loss", "draw"}:
                    result_text = "Double loss — 0 point pour les deux joueurs"
                else:
                    result_text = f"Victoire : {match['winner_name']}"

                lines.append(
                    f"**Table {table}** — {match['player1_name']} vs "
                    f"{match['player2_name']} ✅ `{result_text}`"
                )
            else:
                lines.append(
                    f"**Table {table}** — {match['player1_name']} vs "
                    f"{match['player2_name']} 🕒 En attente"
                )

        return "\n".join(lines)

    async def format_standings(
        self,
        tournament_id: int,
    ) -> str:
        """Affiche le classement suisse avec les double losses."""

        standings = await self.db.get_swiss_standings(tournament_id)

        if not standings:
            return "📭 Aucun classement disponible."

        lines = ["🏆 **Classement suisse**", "", "```"]

        for rank, row in enumerate(standings, start=1):
            lines.append(
                f"{rank:>2}. {row['username']} — {row['points']} pts | "
                f"{row['wins']}V / {row['losses']}D / "
                f"{row['double_losses']}DL / {row['byes']}BYE"
            )

        lines.extend([
            "```",
            "",
            "`DL` = double loss : 0 point pour les deux joueurs.",
        ])
        return "\n".join(lines)

    async def format_status(
        self,
        tournament_id: int,
    ) -> str:
        """
        Affiche l'état des rondes suisses.
        """

        settings = await self.db.get_swiss_settings(
            tournament_id
        )

        if settings is None:

            return "📭 Les rondes suisses ne sont pas lancées."

        current_round = int(settings["current_round"])
        total_rounds = int(settings["total_rounds"])
        status = settings["status"]

        pending = 0

        if current_round > 0:

            pending = await self.db.count_pending_swiss_matches(
                tournament_id=tournament_id,
                round_number=current_round,
            )

        return (
            "🐹 **Statut des rondes suisses**\n\n"
            f"Statut : `{status}`\n"
            f"Ronde actuelle : `{current_round}/{total_rounds}`\n"
            f"Matchs en attente : `{pending}`"
        )
