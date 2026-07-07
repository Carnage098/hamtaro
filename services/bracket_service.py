from __future__ import annotations

import math
import random

from models.match import Match
from models.registration import Registration
from models.tournament import Tournament

from models.enums import MatchStatus, TournamentStatus

from services.base_service import BaseService


class BracketService(BaseService):
    """
    Moteur complet des brackets Hamtaro.

    Ce service ne fait pas de SQL directement.
    Il passe uniquement par DatabaseService avec self.db.
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

    # ==========================================================
    # OUTILS
    # ==========================================================

    @staticmethod
    def next_power_of_two(value: int) -> int:
        """
        Retourne la prochaine puissance de 2.
        """

        if value <= 2:
            return 2

        return 1 << (value - 1).bit_length()

    @staticmethod
    def total_rounds(player_count: int) -> int:
        """
        Retourne le nombre de rounds.

        8 joueurs = 3 rounds :
        - round 3 : quarts
        - round 2 : demies
        - round 1 : finale
        """

        return int(math.log2(player_count))

    @classmethod
    def round_name(
        cls,
        round_number: int,
    ) -> str:
        """
        Retourne le nom humain d'un round.
        """

        return cls.ROUND_NAMES.get(
            round_number,
            f"Round {round_number}",
        )

    @staticmethod
    def shuffle_players(
        players: list[Registration],
    ) -> list[Registration]:
        """
        Mélange les joueurs.
        """

        shuffled = list(players)

        random.shuffle(shuffled)

        return shuffled

    # ==========================================================
    # GÉNÉRATION DU BRACKET
    # ==========================================================

    async def generate_bracket(
        self,
        tournament_id: int,
        *,
        shuffle: bool = True,
        force: bool = False,
    ) -> dict[int, list[Match]]:
        """
        Génère un bracket à élimination directe.

        Paramètres :
        - shuffle=True : mélange les joueurs avant génération.
        - force=True : supprime l'ancien bracket s'il existe déjà.

        Retourne :
        {
            3: [matchs du premier round],
            2: [demies],
            1: [finale]
        }
        """

        tournament = await self.db.get_tournament(tournament_id)

        if tournament is None:
            raise ValueError("Tournoi introuvable.")

        if tournament.status not in (
            TournamentStatus.REGISTRATION,
            TournamentStatus.CHECK_IN,
        ):
            raise ValueError(
                "Le bracket ne peut être généré que pendant les inscriptions ou le check-in."
            )

        already_has_matches = await self.db.has_matches(tournament_id)

        if already_has_matches and not force:
            raise ValueError(
                "Ce tournoi possède déjà un bracket. Utilise force=True pour le régénérer."
            )

        if already_has_matches and force:
            await self.db.clear_matches(tournament_id)

        registrations = await self.db.list_checked_in_registrations(
            tournament_id
        )

        if len(registrations) < 2:
            raise ValueError(
                "Il faut au moins 2 joueurs check-in pour générer un bracket."
            )

        if len(registrations) > tournament.max_players:
            raise ValueError(
                "Il y a plus d'inscrits que la limite du tournoi."
            )

        if shuffle:
            registrations = self.shuffle_players(registrations)

        bracket_size = self.next_power_of_two(
            len(registrations)
        )

        if bracket_size > tournament.max_players:
            raise ValueError(
                "Le nombre de joueurs dépasse la taille maximale du tournoi."
            )

        total_rounds = self.total_rounds(bracket_size)

        slots: list[Registration | None] = list(registrations)

        bye_count = bracket_size - len(slots)

        slots.extend([None] * bye_count)

        created_matches_by_round: dict[int, list[Match]] = {}

        # ------------------------------------------------------
        # Création de tous les rounds
        # ------------------------------------------------------

        for round_number in range(
            total_rounds,
            0,
            -1,
        ):

            match_count = 2 ** (round_number - 1)

            created_matches_by_round[round_number] = []

            for match_index in range(match_count):

                match_number = match_index + 1
                bracket_position = match_number

                if round_number == total_rounds:

                    slot_index = match_index * 2

                    player1 = slots[slot_index]
                    player2 = slots[slot_index + 1]

                    match = self._build_first_round_match(
                        tournament_id=tournament_id,
                        round_number=round_number,
                        match_number=match_number,
                        bracket_position=bracket_position,
                        player1=player1,
                        player2=player2,
                    )

                else:

                    match = Match(
                        id=None,
                        tournament_id=tournament_id,
                        round=round_number,
                        match_number=match_number,
                        bracket_position=bracket_position,
                        status=MatchStatus.WAITING,
                    )

                created = await self.db.create_match(match)

                created_matches_by_round[round_number].append(created)

        # ------------------------------------------------------
        # Liaison des matchs vers le round suivant
        # ------------------------------------------------------

        for round_number in range(
            total_rounds,
            1,
            -1,
        ):

            current_round_matches = created_matches_by_round[round_number]
            next_round_matches = created_matches_by_round[round_number - 1]

            for index, match in enumerate(current_round_matches):

                next_match = next_round_matches[index // 2]

                next_slot = 1 if index % 2 == 0 else 2

                if match.id is None or next_match.id is None:
                    raise RuntimeError(
                        "Impossible de lier les matchs : ID manquant."
                    )

                await self.db.set_match_next(
                    match_id=match.id,
                    next_match_id=next_match.id,
                    next_slot=next_slot,
                )

                match.next_match_id = next_match.id
                match.next_slot = next_slot

        # ------------------------------------------------------
        # Lancement officiel du tournoi
        # ------------------------------------------------------

        await self.db.start_tournament(
            tournament_id=tournament_id,
            total_rounds=total_rounds,
        )

        # ------------------------------------------------------
        # Propagation automatique des BYE
        # ------------------------------------------------------

        first_round = created_matches_by_round[total_rounds]

        for match in first_round:

            if (
                match.status == MatchStatus.COMPLETED
                and match.winner_id is not None
                and match.id is not None
            ):
                await self.advance_winner(match.id)

        return await self.db.get_bracket(tournament_id)

    def _build_first_round_match(
        self,
        *,
        tournament_id: int,
        round_number: int,
        match_number: int,
        bracket_position: int,
        player1: Registration | None,
        player2: Registration | None,
    ) -> Match:
        """
        Construit un match du premier round.

        Gère automatiquement les BYE.
        """

        player1_id = player1.discord_id if player1 else None
        player2_id = player2.discord_id if player2 else None

        player1_name = player1.username if player1 else None
        player2_name = player2.username if player2 else None

        winner_id: str | None = None
        winner_name: str | None = None

        status = MatchStatus.WAITING
        is_bye = False
        score: str | None = None
        notes: str | None = None

        if player1 is not None and player2 is not None:

            status = MatchStatus.PLAYING

        elif player1 is not None and player2 is None:

            winner_id = player1.discord_id
            winner_name = player1.username
            status = MatchStatus.COMPLETED
            is_bye = True
            score = "BYE"
            notes = "Victoire automatique par BYE."

        elif player1 is None and player2 is not None:

            winner_id = player2.discord_id
            winner_name = player2.username
            status = MatchStatus.COMPLETED
            is_bye = True
            score = "BYE"
            notes = "Victoire automatique par BYE."

        else:

            status = MatchStatus.CANCELLED
            is_bye = True
            notes = "Match vide annulé."

        return Match(
            id=None,
            tournament_id=tournament_id,
            round=round_number,
            match_number=match_number,
            bracket_position=bracket_position,
            player1_id=player1_id,
            player2_id=player2_id,
            player1_name=player1_name,
            player2_name=player2_name,
            winner_id=winner_id,
            winner_name=winner_name,
            score=score,
            status=status,
            is_bye=is_bye,
            notes=notes,
        )

    # ==========================================================
    # PROGRESSION DES VAINQUEURS
    # ==========================================================

    async def advance_winner(
        self,
        match_id: int,
    ) -> None:
        """
        Envoie le vainqueur d'un match vers le match suivant.

        Utilise :
        - next_match_id : le match suivant ;
        - next_slot : la place à remplir dans le match suivant.

        Si un joueur se retrouve seul parce que l'autre branche est vide
        ou annulée, il avance automatiquement.
        """

        match = await self.db.get_match(match_id)

        if match is None:
            raise ValueError("Match introuvable.")

        if match.winner_id is None or match.winner_name is None:
            return

        # Finale : il n'y a pas de match suivant.
        if match.next_match_id is None:
            return

        if match.next_slot not in (1, 2):
            raise ValueError(
                "Le match possède un next_slot invalide."
            )

        next_match = await self.db.get_match(
            match.next_match_id
        )

        if next_match is None:
            raise ValueError(
                "Match suivant introuvable."
            )

        # ------------------------------------------------------
        # Placement du vainqueur dans le bon slot
        # ------------------------------------------------------

        if match.next_slot == 1:

            if (
                next_match.player1_id is not None
                and next_match.player1_id != match.winner_id
            ):
                raise RuntimeError(
                    "Le slot 1 du match suivant est déjà occupé."
                )

            next_match = await self.db.place_player_in_match(
                match_id=next_match.id,
                slot=1,
                discord_id=match.winner_id,
                username=match.winner_name,
            )

        else:

            if (
                next_match.player2_id is not None
                and next_match.player2_id != match.winner_id
            ):
                raise RuntimeError(
                    "Le slot 2 du match suivant est déjà occupé."
                )

            next_match = await self.db.place_player_in_match(
                match_id=next_match.id,
                slot=2,
                discord_id=match.winner_id,
                username=match.winner_name,
            )

        # ------------------------------------------------------
        # Si les deux joueurs sont présents, le match est jouable.
        # ------------------------------------------------------

        if next_match.player1_id and next_match.player2_id:

            await self.db.set_match_status(
                next_match.id,
                MatchStatus.PLAYING,
            )

            return

        # ------------------------------------------------------
        # Cas spécial : l'autre branche du bracket est vide.
        #
        # Exemple avec 5 joueurs dans un bracket à 8 :
        #
        # Match A : Joueur 5 vs BYE
        # Match B : BYE vs BYE
        #
        # Le gagnant du Match A doit avancer automatiquement,
        # car le Match B n'aura jamais de vainqueur.
        # ------------------------------------------------------

        can_auto_advance = await self._can_auto_advance_single_player(
            next_match
        )

        if not can_auto_advance:
            return

        winner_id, winner_name = self._single_player_from_match(
            next_match
        )

        if winner_id is None or winner_name is None:
            return

        completed = await self.db.complete_match(
            match_id=next_match.id,
            winner_id=winner_id,
            winner_name=winner_name,
            score="BYE",
            notes="Victoire automatique : aucune opposition dans l'autre branche.",
            is_bye=True,
        )

        await self.advance_winner(
            completed.id
        )

    async def _can_auto_advance_single_player(
        self,
        match: Match,
    ) -> bool:
        """
        Détermine si un match avec un seul joueur peut être terminé
        automatiquement.

        On ne fait avancer le joueur que si l'autre slot ne pourra jamais
        être rempli, c'est-à-dire si le match source de l'autre slot est
        annulé ou terminé sans vainqueur.
        """

        if match.id is None:
            return False

        if match.player1_id and match.player2_id:
            return False

        if not match.player1_id and not match.player2_id:
            return False

        missing_slot = 2 if match.player1_id else 1

        all_matches = await self.db.list_matches(
            match.tournament_id
        )

        source_match = None

        for candidate in all_matches:

            if (
                candidate.next_match_id == match.id
                and candidate.next_slot == missing_slot
            ):
                source_match = candidate
                break

        # Si aucune source n'existe, on ne prend pas de risque.
        if source_match is None:
            return False

        # L'autre branche est vide / annulée.
        if (
            source_match.status == MatchStatus.CANCELLED
            and source_match.winner_id is None
        ):
            return True

        # L'autre branche est terminée mais n'a aucun vainqueur.
        if (
            source_match.status == MatchStatus.COMPLETED
            and source_match.winner_id is None
        ):
            return True

        return False

    @staticmethod
    def _single_player_from_match(
        match: Match,
    ) -> tuple[str | None, str | None]:
        """
        Retourne le seul joueur présent dans un match.

        Retour :
            (discord_id, username)
        """

        if match.player1_id and match.player1_name:
            return match.player1_id, match.player1_name

        if match.player2_id and match.player2_name:
            return match.player2_id, match.player2_name

        return None, None

    # ==========================================================
    # RÉSULTATS
    # ==========================================================

    async def report_result(
        self,
        match_id: int,
        player1_score: int,
        player2_score: int,
        reported_by: str,
    ) -> Match:
        """
        Reporte le résultat d'un match.

        Le match passe en statut REPORTED.
        Il devra ensuite être validé par le staff.
        """

        if player1_score < 0 or player2_score < 0:
            raise ValueError(
                "Les scores ne peuvent pas être négatifs."
            )

        if player1_score == player2_score:
            raise ValueError(
                "Un match à élimination directe ne peut pas finir en égalité."
            )

        match = await self.db.report_match(
            match_id=match_id,
            player1_score=player1_score,
            player2_score=player2_score,
            reported_by=reported_by,
        )

        return match

    async def approve_result(
        self,
        match_id: int,
        validated_by: str,
        guild_id: str,
        notes: str | None = None,
    ) -> Match:
        """
        Valide un résultat reporté.

        Cette méthode :
        - valide le match ;
        - enregistre les statistiques ;
        - avance le vainqueur ;
        - termine le tournoi si la finale est validée.
        """

        match = await self.db.validate_match(
            match_id=match_id,
            validated_by=validated_by,
            notes=notes,
        )

        await self.db.record_match_stats(
            match=match,
            guild_id=guild_id,
        )

        await self.advance_winner(match.id)

        if match.next_match_id is None:
            await self._try_finish_tournament(
                tournament_id=match.tournament_id,
                guild_id=guild_id,
            )

        return match

    async def reject_result(
        self,
        match_id: int,
        validated_by: str,
        notes: str | None = None,
    ) -> Match:
        """
        Refuse un résultat reporté.

        Le match redevient jouable.
        """

        match = await self.db.reject_match_report(
            match_id=match_id,
            validated_by=validated_by,
            notes=notes,
        )

        return match

    async def admin_win(
        self,
        match_id: int,
        winner_id: str,
        winner_name: str,
        validated_by: str,
        guild_id: str,
        notes: str | None = None,
    ) -> Match:
        """
        Donne une victoire administrative à un joueur.

        Utile pour :
        - no-show ;
        - abandon ;
        - disqualification ;
        - décision staff.
        """

        match = await self.db.get_match(match_id)

        if match is None:
            raise ValueError("Match introuvable.")

        if match.status == MatchStatus.COMPLETED:
            raise ValueError("Ce match est déjà terminé.")

        if winner_id not in (match.player1_id, match.player2_id):
            raise ValueError(
                "Le vainqueur doit être un des deux joueurs du match."
            )

        if winner_id == match.player1_id:

            player1_score = 1
            player2_score = 0
            score = "ADMIN 1-0"

        else:

            player1_score = 0
            player2_score = 1
            score = "ADMIN 0-1"

        completed = await self.db.complete_match(
            match_id=match_id,
            winner_id=winner_id,
            winner_name=winner_name,
            player1_score=player1_score,
            player2_score=player2_score,
            score=score,
            validated_by=validated_by,
            notes=notes or "Victoire administrative.",
        )

        await self.db.record_match_stats(
            match=completed,
            guild_id=guild_id,
        )

        await self.advance_winner(completed.id)

        if completed.next_match_id is None:
            await self._try_finish_tournament(
                tournament_id=completed.tournament_id,
                guild_id=guild_id,
            )

        return completed

    async def _try_finish_tournament(
        self,
        tournament_id: int,
        guild_id: str,
    ) -> Tournament | None:
        """
        Termine le tournoi si la finale possède un vainqueur.

        Retourne le tournoi terminé, ou None si le tournoi n'est pas encore fini.
        """

        final = await self.db.get_final_match(
            tournament_id
        )

        if final is None:
            return None

        if final.status != MatchStatus.COMPLETED:
            return None

        if final.winner_id is None or final.winner_name is None:
            return None

        tournament = await self.db.finalize_tournament_from_matches(
            tournament_id=tournament_id,
            guild_id=guild_id,
        )

        return tournament

    # ==========================================================
    # RÉCUPÉRATION DU BRACKET
    # ==========================================================

    async def get_bracket(
        self,
        tournament_id: int,
    ) -> dict[int, list[Match]]:
        """
        Retourne le bracket complet groupé par round.
        """

        return await self.db.get_bracket(
            tournament_id
        )

    async def get_round_matches(
        self,
        tournament_id: int,
        round_number: int,
    ) -> list[Match]:
        """
        Retourne les matchs d'un round précis.
        """

        return await self.db.list_round_matches(
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

        tournament = await self.db.get_tournament(
            tournament_id
        )

        if tournament is None:
            raise ValueError("Tournoi introuvable.")

        current = await self.db.get_current_round_from_matches(
            tournament_id
        )

        if current is None:
            return tournament.current_round or None

        return current

    async def get_current_round_matches(
        self,
        tournament_id: int,
    ) -> list[Match]:
        """
        Retourne les matchs du round actuellement en cours.
        """

        current_round = await self.get_current_round(
            tournament_id
        )

        if current_round is None:
            return []

        return await self.get_round_matches(
            tournament_id,
            current_round,
        )

    async def get_next_match(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> Match | None:
        """
        Retourne le prochain match jouable d'un joueur.
        """

        return await self.db.get_next_match_for_player(
            tournament_id,
            discord_id,
        )

    async def get_final(
        self,
        tournament_id: int,
    ) -> Match | None:
        """
        Retourne la finale.
        """

        return await self.db.get_final_match(
            tournament_id
        )

    async def get_winner(
        self,
        tournament_id: int,
    ) -> tuple[str, str] | None:
        """
        Retourne le vainqueur du tournoi.

        Retour :
            (winner_id, winner_name)
        """

        return await self.db.get_tournament_winner_from_matches(
            tournament_id
        )

    async def is_finished(
        self,
        tournament_id: int,
    ) -> bool:
        """
        Vérifie si le tournoi est terminé.
        """

        return await self.db.is_tournament_completed_by_matches(
            tournament_id
        )

    # ==========================================================
    # FORMATAGE TEXTE
    # ==========================================================

        def format_match(
        self,
        match: Match,
    ) -> str:
                """
                Formate un match pour Discord.
                """

        player1 = match.player1_name or "À déterminer"
        player2 = match.player2_name or "À déterminer"

        match_title = f"**Match {match.match_number}** — ID `{match.id}`"

        if match.status == MatchStatus.COMPLETED:

            winner = match.winner_name or "Inconnu"
            score = match.score or "Score non renseigné"

            if match.is_bye:
                return (
                    f"{match_title}\n"
                    f"{player1} vs {player2}\n"
                    f"✅ Victoire automatique : **{winner}**\n"
                    f"📊 Score : `{score}`"
                )

            return (
                f"{match_title}\n"
                f"{player1} vs {player2}\n"
                f"✅ Vainqueur : **{winner}**\n"
                f"📊 Score : `{score}`"
            )

        if match.status == MatchStatus.REPORTED:

            winner = match.winner_name or "Inconnu"
            score = match.score or "Score non renseigné"

            return (
                f"{match_title}\n"
                f"{player1} vs {player2}\n"
                f"📝 Résultat reporté : `{score}`\n"
                f"🏆 Vainqueur déclaré : **{winner}**\n"
                f"⏳ En attente de validation staff"
            )

        if match.status == MatchStatus.PLAYING:

            return (
                f"{match_title}\n"
                f"⚔️ {player1} vs {player2}\n"
                f"🟢 En cours\n"
                f"➡️ Pour reporter : `/result match_id:{match.id}`"
            )

        if match.status == MatchStatus.WAITING:

            return (
                f"{match_title}\n"
                f"{player1} vs {player2}\n"
                f"⏳ En attente"
            )

        if match.status == MatchStatus.CANCELLED:

            return (
                f"{match_title}\n"
                f"{player1} vs {player2}\n"
                f"🚫 Annulé"
            )

        return (
            f"{match_title}\n"
            f"{player1} vs {player2}\n"
            f"Statut : `{match.status.value}`"
        )

    def format_round(
        self,
        round_number: int,
        matches: list[Match],
    ) -> str:
        """
        Formate un round complet.
        """

        title = self.round_name(
            round_number
        )

        lines = [
            f"## {title}",
            "",
        ]

        for match in matches:

            lines.append(
                self.format_match(match)
            )

            lines.append("")

        return "\n".join(lines).strip()

    async def format_bracket(
        self,
        tournament_id: int,
    ) -> str:
        """
        Formate le bracket complet en texte Discord.
        """

        tournament = await self.db.get_tournament(
            tournament_id
        )

        if tournament is None:
            raise ValueError("Tournoi introuvable.")

        bracket = await self.get_bracket(
            tournament_id
        )

        if not bracket:
            return "❌ Aucun bracket généré."

        lines = [
            f"# 🐹 Bracket — {tournament.name}",
            f"Format : **{tournament.format}**",
            f"Code : `{tournament.code}`",
            "",
        ]

        for round_number, matches in bracket.items():

            lines.append(
                self.format_round(
                    round_number,
                    matches,
                )
            )

            lines.append("")

        text = "\n".join(lines).strip()

        # Discord limite les messages à 2000 caractères.
        if len(text) > 1900:

            return (
                f"# 🐹 Bracket — {tournament.name}\n"
                f"Format : **{tournament.format}**\n"
                f"Code : `{tournament.code}`\n\n"
                "⚠️ Le bracket est trop long pour être affiché en un seul message.\n"
                "Utilise une commande par round pour l'afficher proprement."
            )

        return text

    async def format_current_round(
        self,
        tournament_id: int,
    ) -> str:
        """
        Formate uniquement le round actuel.
        """

        current_round = await self.get_current_round(
            tournament_id
        )

        if current_round is None:
            return "❌ Aucun round en cours."

        matches = await self.get_round_matches(
            tournament_id,
            current_round,
        )

        if not matches:
            return "❌ Aucun match trouvé pour ce round."

        return self.format_round(
            current_round,
            matches,
        )

    async def format_next_match(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> str:
        """
        Formate le prochain match d'un joueur.
        """

        match = await self.get_next_match(
            tournament_id,
            discord_id,
        )

        if match is None:
            return "❌ Aucun match jouable trouvé pour ce joueur."

        return self.format_match(
            match
        )

    async def format_final(
        self,
        tournament_id: int,
    ) -> str:
        """
        Formate la finale.
        """

        final = await self.get_final(
            tournament_id
        )

        if final is None:
            return "❌ Finale introuvable."

        return self.format_round(
            1,
            [final],
        )
    # ==========================================================
    # OUTILS STAFF / CONTRÔLE
    # ==========================================================
    # ==========================================================
    # STAFF / ADMIN HELPERS
    # ==========================================================

    async def can_start(
        self,
        tournament_id: int,
    ) -> bool:
        """
        Vérifie si un tournoi peut démarrer.
        """

        error = await self.get_start_error(
            tournament_id
        )

        return error is None

    async def get_start_error(
        self,
        tournament_id: int,
    ) -> str | None:
        """
        Retourne une erreur si le tournoi ne peut pas démarrer.
        """

        tournament = await self.db.get_tournament(
            tournament_id
        )

        if tournament is None:
            return "Tournoi introuvable."

        if tournament.status not in (
            TournamentStatus.REGISTRATION,
            TournamentStatus.CHECK_IN,
        ):
            return "Le tournoi n'est pas en phase d'inscription ou de check-in."

        checked_in_count = await self.db.count_checked_in(
            tournament_id
        )

        if checked_in_count < 2:
            return "Il faut au moins 2 joueurs check-in pour démarrer."

        if checked_in_count > tournament.max_players:
            return "Il y a plus de joueurs check-in que de places disponibles."

        has_matches = await self.db.has_matches(
            tournament_id
        )

        if has_matches:
            return "Un bracket existe déjà pour ce tournoi."

        return None

    async def reset_bracket(
        self,
        tournament_id: int,
    ) -> None:
        """
        Supprime le bracket et remet le tournoi en inscription.
        """

        tournament = await self.db.get_tournament(
            tournament_id
        )

        if tournament is None:
            raise ValueError(
                "Tournoi introuvable."
            )

        await self.db.clear_matches(
            tournament_id
        )

        await self.db.execute(
            """
            UPDATE tournaments
            SET status = ?,
                current_round = NULL,
                total_rounds = NULL,
                winner_id = NULL,
                winner_name = NULL,
                started_at = NULL,
                finished_at = NULL
            WHERE id = ?
            """,
            (
                TournamentStatus.REGISTRATION.value,
                tournament_id,
            ),
            commit=True,
        )

    async def regenerate_bracket(
        self,
        tournament_id: int,
        *,
        shuffle: bool = True,
    ) -> list[Match]:
        """
        Supprime puis régénère le bracket.
        """

        await self.reset_bracket(
            tournament_id
        )

        return await self.generate_bracket(
            tournament_id,
            shuffle=shuffle,
            force=True,
        )

    async def get_ready_matches(
        self,
        tournament_id: int,
    ) -> list[Match]:
        """
        Retourne les matchs jouables.
        """

        return await self.db.get_ready_matches(
            tournament_id
        )

    async def get_waiting_matches(
        self,
        tournament_id: int,
    ) -> list[Match]:
        """
        Retourne les matchs en attente.
        """

        return await self.db.get_waiting_matches(
            tournament_id
        )

    async def get_playing_matches(
        self,
        tournament_id: int,
    ) -> list[Match]:
        """
        Retourne les matchs en cours.
        """

        return await self.db.get_playing_matches(
            tournament_id
        )

    async def get_reported_matches(
        self,
        tournament_id: int,
    ) -> list[Match]:
        """
        Retourne les matchs reportés.
        """

        return await self.db.get_reported_matches(
            tournament_id
        )

    async def get_completed_matches(
        self,
        tournament_id: int,
    ) -> list[Match]:
        """
        Retourne les matchs terminés.
        """

        return await self.db.get_completed_matches(
            tournament_id
        )

    async def format_reported_matches(
        self,
        tournament_id: int,
    ) -> str:
        """
        Formate les résultats en attente de validation.
        """

        matches = await self.get_reported_matches(
            tournament_id
        )

        if not matches:
            return "✅ Aucun résultat en attente de validation."

        lines = [
            "📝 **Résultats en attente de validation**",
            "",
        ]

        for match in matches:

            lines.append(
                self.format_match(match)
            )

            lines.append("")

        return "\n".join(lines)

    async def format_ready_matches(
        self,
        tournament_id: int,
    ) -> str:
        """
        Formate les matchs actuellement jouables.
        """

        matches = await self.get_ready_matches(
            tournament_id
        )

        if not matches:
            return "❌ Aucun match jouable pour le moment."

        lines = [
            "⚔️ **Matchs jouables**",
            "",
        ]

        for match in matches:

            lines.append(
                self.format_match(match)
            )

            lines.append("")

        return "\n".join(lines)

    async def cancel_tournament(
        self,
        tournament_id: int,
    ) -> None:
        """
        Annule un tournoi.
        """

        tournament = await self.db.get_tournament(
            tournament_id
        )

        if tournament is None:
            raise ValueError(
                "Tournoi introuvable."
            )

        await self.db.cancel_tournament(
            tournament_id
        )

    async def force_complete_match(
        self,
        match_id: int,
        winner_id: str,
        winner_name: str,
        validated_by: str,
        guild_id: str,
        *,
        score: str = "ADMIN",
        notes: str | None = None,
    ) -> Match:
        """
        Termine un match de force.
        """

        return await self.admin_win(
            match_id=match_id,
            winner_id=winner_id,
            winner_name=winner_name,
            validated_by=validated_by,
            guild_id=guild_id,
            score=score,
            notes=notes,
        )

    async def sync_current_round(
        self,
        tournament_id: int,
    ) -> int | None:
        """
        Recalcule le round actuel du tournoi.
        """

        tournament = await self.db.get_tournament(
            tournament_id
        )

        if tournament is None:
            raise ValueError(
                "Tournoi introuvable."
            )

        rounds = await self.db.get_tournament_rounds(
            tournament_id
        )

        if not rounds:

            await self.db.execute(
                """
                UPDATE tournaments
                SET current_round = NULL
                WHERE id = ?
                """,
                (
                    tournament_id,
                ),
                commit=True,
            )

            return None

        for round_number in sorted(
            rounds,
            reverse=True,
        ):

            matches = await self.db.list_round_matches(
                tournament_id=tournament_id,
                round_number=round_number,
            )

            unfinished = [
                match
                for match in matches
                if match.status not in (
                    MatchStatus.COMPLETED,
                    MatchStatus.CANCELLED,
                )
            ]

            if unfinished:

                await self.db.update_current_round(
                    tournament_id=tournament_id,
                    current_round=round_number,
                )

                return round_number

        await self._try_finish_tournament(
            tournament_id,
            guild_id=tournament.guild_id,
        )

        return None
   