from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from models.casual_match import CasualMatch, CasualMatchStatus


class CasualMatchService:
    """Règles métier et persistance SQLite des matchs casual."""

    VALID_BEST_OF = frozenset({1, 3, 5})
    ACTIVE_STATUSES = (
        CasualMatchStatus.SEARCHING.value,
        CasualMatchStatus.ACCEPTED.value,
    )

    def __init__(self, database: Any) -> None:
        self.db = database
        # Un même verrou protège la création et l'acceptation afin qu'un
        # joueur ne puisse pas devenir actif dans deux matchs au même instant.
        self._activity_lock = asyncio.Lock()
        self._match_locks: defaultdict[int, asyncio.Lock] = defaultdict(
            asyncio.Lock
        )

    async def initialize_schema(self) -> None:
        """Crée uniquement les tables propres au système casual."""

        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS casual_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message_id TEXT,
                thread_id TEXT,

                requester_id TEXT NOT NULL,
                requester_name TEXT NOT NULL,
                opponent_id TEXT,
                opponent_name TEXT,

                format_name TEXT NOT NULL,
                simulator TEXT NOT NULL,
                best_of INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'searching',

                player1_score INTEGER,
                player2_score INTEGER,
                winner_id TEXT,
                reported_by TEXT,

                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                accepted_at TIMESTAMP,
                completed_at TIMESTAMP,
                cancelled_at TIMESTAMP,

                CHECK (best_of IN (1, 3, 5)),
                CHECK (
                    status IN (
                        'searching',
                        'accepted',
                        'completed',
                        'cancelled'
                    )
                )
            )
            """
        )

        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS casual_declines (
                match_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                declined_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (match_id, user_id),
                FOREIGN KEY (match_id)
                    REFERENCES casual_matches(id)
                    ON DELETE CASCADE
            )
            """
        )

        for statement in (
            """
            CREATE INDEX IF NOT EXISTS idx_casual_guild_status
            ON casual_matches(guild_id, status)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_casual_requester
            ON casual_matches(guild_id, requester_id, status)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_casual_opponent
            ON casual_matches(guild_id, opponent_id, status)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_casual_thread
            ON casual_matches(thread_id)
            """,
        ):
            await self.db.execute(statement)

        await self.db.commit()

    async def get_match(self, match_id: int) -> CasualMatch | None:
        row = await self.db.fetchone(
            "SELECT * FROM casual_matches WHERE id = ?",
            (match_id,),
        )
        return CasualMatch.from_row(row) if row is not None else None

    async def get_match_by_thread(
        self,
        *,
        guild_id: str,
        thread_id: str,
    ) -> CasualMatch | None:
        row = await self.db.fetchone(
            """
            SELECT *
            FROM casual_matches
            WHERE guild_id = ?
              AND thread_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (guild_id, thread_id),
        )
        return CasualMatch.from_row(row) if row is not None else None

    async def active_match_for_player(
        self,
        *,
        guild_id: str,
        user_id: str,
    ) -> CasualMatch | None:
        row = await self.db.fetchone(
            """
            SELECT *
            FROM casual_matches
            WHERE guild_id = ?
              AND status IN ('searching', 'accepted')
              AND (requester_id = ? OR opponent_id = ?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (guild_id, user_id, user_id),
        )
        return CasualMatch.from_row(row) if row is not None else None

    async def create_search(
        self,
        *,
        guild_id: str,
        channel_id: str,
        requester_id: str,
        requester_name: str,
        format_name: str,
        simulator: str,
        best_of: int,
    ) -> CasualMatch:
        if best_of not in self.VALID_BEST_OF:
            raise ValueError("Le match doit être un BO1, BO3 ou BO5.")

        format_name = format_name.strip()
        simulator = simulator.strip()
        requester_name = requester_name.strip() or "Joueur"

        if not 1 <= len(format_name) <= 80:
            raise ValueError(
                "Le format doit contenir entre 1 et 80 caractères."
            )
        if not 1 <= len(simulator) <= 80:
            raise ValueError(
                "Le simulateur doit contenir entre 1 et 80 caractères."
            )

        async with self._activity_lock:
            active = await self.active_match_for_player(
                guild_id=guild_id,
                user_id=requester_id,
            )
            if active is not None:
                raise ValueError(
                    "Tu as déjà une recherche ou un match casual actif "
                    f"(#{active.id})."
                )

            cursor = await self.db.execute(
                """
                INSERT INTO casual_matches(
                    guild_id,
                    channel_id,
                    requester_id,
                    requester_name,
                    format_name,
                    simulator,
                    best_of,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'searching')
                """,
                (
                    guild_id,
                    channel_id,
                    requester_id,
                    requester_name,
                    format_name,
                    simulator,
                    best_of,
                ),
            )
            await self.db.commit()

        created = await self.get_match(int(cursor.lastrowid))
        if created is None:
            raise RuntimeError("La recherche créée est introuvable.")
        return created

    async def attach_public_message(
        self,
        *,
        match_id: int,
        message_id: str,
    ) -> CasualMatch:
        await self.db.execute(
            """
            UPDATE casual_matches
            SET message_id = ?
            WHERE id = ?
            """,
            (message_id, match_id),
        )
        await self.db.commit()
        return await self._required_match(match_id)

    async def delete_unpublished_search(self, match_id: int) -> None:
        await self.db.execute(
            """
            DELETE FROM casual_matches
            WHERE id = ?
              AND status = 'searching'
              AND message_id IS NULL
            """,
            (match_id,),
        )
        await self.db.commit()

    async def record_decline(
        self,
        *,
        match_id: int,
        guild_id: str,
        user_id: str,
    ) -> CasualMatch:
        match = await self._required_match(match_id)
        if match.guild_id != guild_id:
            raise ValueError("Cette recherche appartient à un autre serveur.")
        if match.status is not CasualMatchStatus.SEARCHING:
            raise ValueError("Cette recherche n'est plus disponible.")
        if user_id == match.requester_id:
            raise ValueError(
                "Tu ne peux pas refuser ta propre recherche. "
                "Utilise /cancel_casual."
            )

        await self.db.execute(
            """
            INSERT OR IGNORE INTO casual_declines(match_id, user_id)
            VALUES (?, ?)
            """,
            (match_id, user_id),
        )
        await self.db.commit()
        return match

    async def claim_match(
        self,
        *,
        match_id: int,
        guild_id: str,
        opponent_id: str,
        opponent_name: str,
    ) -> CasualMatch:
        """Réserve une recherche à la première acceptation valide."""

        async with self._activity_lock:
            match = await self._required_match(match_id)
            if match.guild_id != guild_id:
                raise ValueError(
                    "Cette recherche appartient à un autre serveur."
                )
            if match.status is not CasualMatchStatus.SEARCHING:
                raise ValueError(
                    "Un autre joueur a déjà accepté cette recherche."
                )
            if opponent_id == match.requester_id:
                raise ValueError(
                    "Tu ne peux pas accepter ta propre recherche."
                )

            active = await self.active_match_for_player(
                guild_id=guild_id,
                user_id=opponent_id,
            )
            if active is not None:
                raise ValueError(
                    "Tu as déjà une recherche ou un match casual actif "
                    f"(#{active.id})."
                )

            cursor = await self.db.execute(
                """
                UPDATE casual_matches
                SET
                    opponent_id = ?,
                    opponent_name = ?,
                    status = 'accepted',
                    accepted_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND guild_id = ?
                  AND status = 'searching'
                """,
                (
                    opponent_id,
                    opponent_name.strip() or "Adversaire",
                    match_id,
                    guild_id,
                ),
            )
            await self.db.commit()

            if cursor.rowcount != 1:
                raise ValueError(
                    "Un autre joueur a déjà accepté cette recherche."
                )

        return await self._required_match(match_id)

    async def attach_thread(
        self,
        *,
        match_id: int,
        thread_id: str,
    ) -> CasualMatch:
        cursor = await self.db.execute(
            """
            UPDATE casual_matches
            SET thread_id = ?
            WHERE id = ?
              AND status = 'accepted'
            """,
            (thread_id, match_id),
        )
        await self.db.commit()
        if cursor.rowcount != 1:
            raise ValueError("Le match n'est plus en attente de son fil.")
        return await self._required_match(match_id)

    async def rollback_claim(
        self,
        *,
        match_id: int,
        opponent_id: str,
    ) -> None:
        """Rouvre la recherche si la création du fil a échoué."""

        await self.db.execute(
            """
            UPDATE casual_matches
            SET
                opponent_id = NULL,
                opponent_name = NULL,
                status = 'searching',
                accepted_at = NULL
            WHERE id = ?
              AND status = 'accepted'
              AND opponent_id = ?
              AND thread_id IS NULL
            """,
            (match_id, opponent_id),
        )
        await self.db.commit()

    @classmethod
    def normalize_score(
        cls,
        *,
        best_of: int,
        player1_score: int,
        player2_score: int,
    ) -> str:
        """Valide un score et retourne `player1` ou `player2`."""

        if best_of not in cls.VALID_BEST_OF:
            raise ValueError("Le type de match enregistré est invalide.")
        if player1_score < 0 or player2_score < 0:
            raise ValueError("Les scores ne peuvent pas être négatifs.")
        if player1_score == player2_score:
            raise ValueError(
                "Un match casual ne peut pas se terminer sur une égalité."
            )

        target = (best_of // 2) + 1
        winner_score = max(player1_score, player2_score)
        loser_score = min(player1_score, player2_score)

        if winner_score != target:
            raise ValueError(
                f"En BO{best_of}, le gagnant doit atteindre "
                f"{target} victoire(s)."
            )
        if loser_score >= target:
            raise ValueError("Ce score n'est pas valide.")

        return "player1" if player1_score > player2_score else "player2"

    async def complete_match(
        self,
        *,
        match_id: int,
        guild_id: str,
        reporter_id: str,
        reporter_score: int,
        opponent_score: int,
    ) -> CasualMatch:
        async with self._match_locks[match_id]:
            match = await self._required_match(match_id)

            if match.guild_id != guild_id:
                raise ValueError("Ce match appartient à un autre serveur.")
            if match.status is not CasualMatchStatus.ACCEPTED:
                raise ValueError("Ce match n'est pas actuellement en cours.")
            if not match.contains_player(reporter_id):
                raise ValueError(
                    "Seuls les deux joueurs peuvent enregistrer le résultat."
                )
            if match.opponent_id is None:
                raise ValueError("L'adversaire de ce match est introuvable.")

            if reporter_id == match.requester_id:
                player1_score = reporter_score
                player2_score = opponent_score
            else:
                player1_score = opponent_score
                player2_score = reporter_score

            winner_slot = self.normalize_score(
                best_of=match.best_of,
                player1_score=player1_score,
                player2_score=player2_score,
            )
            winner_id = (
                match.requester_id
                if winner_slot == "player1"
                else match.opponent_id
            )

            cursor = await self.db.execute(
                """
                UPDATE casual_matches
                SET
                    player1_score = ?,
                    player2_score = ?,
                    winner_id = ?,
                    reported_by = ?,
                    status = 'completed',
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND guild_id = ?
                  AND status = 'accepted'
                """,
                (
                    player1_score,
                    player2_score,
                    winner_id,
                    reporter_id,
                    match_id,
                    guild_id,
                ),
            )
            await self.db.commit()

            if cursor.rowcount != 1:
                raise ValueError("Ce résultat a déjà été enregistré.")

        return await self._required_match(match_id)

    async def cancel_match(
        self,
        *,
        match_id: int,
        guild_id: str,
        actor_id: str,
        actor_is_staff: bool,
    ) -> CasualMatch:
        async with self._match_locks[match_id]:
            match = await self._required_match(match_id)

            if match.guild_id != guild_id:
                raise ValueError("Ce match appartient à un autre serveur.")

            if match.status is CasualMatchStatus.SEARCHING:
                if actor_id != match.requester_id and not actor_is_staff:
                    raise ValueError(
                        "Seul le demandeur ou le staff peut annuler "
                        "cette recherche."
                    )
            elif match.status is CasualMatchStatus.ACCEPTED:
                if not actor_is_staff:
                    raise ValueError(
                        "Une fois le match accepté, seul le staff peut "
                        "l'annuler."
                    )
            else:
                raise ValueError("Ce match est déjà terminé.")

            cursor = await self.db.execute(
                """
                UPDATE casual_matches
                SET
                    status = 'cancelled',
                    cancelled_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND guild_id = ?
                  AND status IN ('searching', 'accepted')
                """,
                (match_id, guild_id),
            )
            await self.db.commit()

            if cursor.rowcount != 1:
                raise ValueError("Ce match n'est plus annulable.")

        return await self._required_match(match_id)

    async def _required_match(self, match_id: int) -> CasualMatch:
        match = await self.get_match(match_id)
        if match is None:
            raise ValueError("Ce match casual est introuvable.")
        return match
