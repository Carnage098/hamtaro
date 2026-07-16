from __future__ import annotations

import random
import string

import aiosqlite

from config import DATABASE
from models.tournament import Tournament


class TournamentService:
    """
    Service chargé de créer, récupérer, modifier et résoudre
    les tournois Hamtaro.

    Une référence de tournoi peut être :
    - un ID numérique : 12 ;
    - un ID sous forme de texte : "12" ;
    - un code public : "TCG-4821" ;
    - None : tournoi actif le plus récent du serveur.
    """

    VALID_PLAYER_COUNTS = {4, 8, 16, 32, 64}

    ACTIVE_STATUSES = (
        "in_progress",
        "started",
        "active",
        "registration",
    )

    # ==========================================================
    # CRÉATION
    # ==========================================================

    async def create(
        self,
        guild_id: str,
        name: str,
        format: str,
        max_players: int,
    ) -> Tournament:
        """Crée un tournoi et retourne son modèle Tournament."""

        if max_players not in self.VALID_PLAYER_COUNTS:
            raise ValueError(
                "Nombre de joueurs invalide. "
                "Valeurs autorisées : 4, 8, 16, 32 ou 64."
            )

        code = await self._generate_code(format)

        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute(
                """
                INSERT INTO tournaments(
                    guild_id,
                    code,
                    name,
                    format,
                    max_players,
                    status
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    str(guild_id),
                    code,
                    name,
                    format,
                    max_players,
                    "registration",
                ),
            )

            await db.commit()
            tournament_id = cursor.lastrowid

        if tournament_id is None:
            raise RuntimeError(
                "La base de données n'a pas retourné l'ID du tournoi créé."
            )

        return Tournament(
            id=tournament_id,
            guild_id=str(guild_id),
            code=code,
            name=name,
            format=format,
            max_players=max_players,
            status="registration",
        )

    # ==========================================================
    # RÉCUPÉRATION PAR ID
    # ==========================================================

    async def get(
        self,
        tournament_id: int,
    ) -> Tournament | None:
        """Recherche un tournoi par son ID interne."""

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM tournaments
                WHERE id = ?
                LIMIT 1
                """,
                (tournament_id,),
            )

            row = await cursor.fetchone()

        return self._row_to_tournament(row)

    async def get_for_guild(
        self,
        tournament_id: int,
        guild_id: str,
    ) -> Tournament | None:
        """
        Recherche un tournoi par ID en vérifiant qu'il appartient
        au serveur Discord concerné.
        """

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM tournaments
                WHERE id = ?
                  AND guild_id = ?
                LIMIT 1
                """,
                (
                    tournament_id,
                    str(guild_id),
                ),
            )

            row = await cursor.fetchone()

        return self._row_to_tournament(row)

    # ==========================================================
    # RÉCUPÉRATION PAR CODE
    # ==========================================================

    async def get_by_code(
        self,
        code: str,
        guild_id: str | None = None,
    ) -> Tournament | None:
        """
        Recherche un tournoi par son code public.

        La comparaison ne tient pas compte des majuscules
        et des minuscules.
        """

        normalized_code = code.strip()

        if not normalized_code:
            return None

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            if guild_id is None:
                cursor = await db.execute(
                    """
                    SELECT *
                    FROM tournaments
                    WHERE UPPER(code) = UPPER(?)
                    LIMIT 1
                    """,
                    (normalized_code,),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT *
                    FROM tournaments
                    WHERE UPPER(code) = UPPER(?)
                      AND guild_id = ?
                    LIMIT 1
                    """,
                    (
                        normalized_code,
                        str(guild_id),
                    ),
                )

            row = await cursor.fetchone()

        return self._row_to_tournament(row)

    # ==========================================================
    # TOURNOI ACTIF
    # ==========================================================

    async def get_active(
        self,
        guild_id: str,
    ) -> Tournament | None:
        """Retourne le tournoi actif le plus récent du serveur."""

        placeholders = ", ".join(
            "?" for _ in self.ACTIVE_STATUSES
        )

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                f"""
                SELECT *
                FROM tournaments
                WHERE guild_id = ?
                  AND LOWER(status) IN ({placeholders})
                ORDER BY
                    CASE LOWER(status)
                        WHEN 'in_progress' THEN 0
                        WHEN 'started' THEN 1
                        WHEN 'active' THEN 2
                        WHEN 'registration' THEN 3
                        ELSE 4
                    END,
                    id DESC
                LIMIT 1
                """,
                (
                    str(guild_id),
                    *self.ACTIVE_STATUSES,
                ),
            )

            row = await cursor.fetchone()

        return self._row_to_tournament(row)

    # ==========================================================
    # RÉSOLUTION ID / CODE / ACTIF
    # ==========================================================

    async def resolve(
        self,
        reference: str | int | None,
        *,
        guild_id: str,
        allow_active: bool = True,
    ) -> Tournament | None:
        """
        Résout une référence de tournoi.

        Exemples :
            12          -> recherche par ID
            "12"        -> recherche par ID
            "TCG-4821"  -> recherche par code
            None        -> tournoi actif, si allow_active=True
        """

        if reference is None:
            if allow_active:
                return await self.get_active(guild_id)
            return None

        value = str(reference).strip()

        if not value:
            if allow_active:
                return await self.get_active(guild_id)
            return None

        if value.isdigit():
            return await self.get_for_guild(
                int(value),
                guild_id,
            )

        return await self.get_by_code(
            value,
            guild_id,
        )

    # ==========================================================
    # LISTE DES TOURNOIS
    # ==========================================================

    async def list(
        self,
        guild_id: str,
    ) -> list[Tournament]:
        """Retourne tous les tournois du serveur, du plus récent au plus ancien."""

        tournaments: list[Tournament] = []

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM tournaments
                WHERE guild_id = ?
                ORDER BY id DESC
                """,
                (str(guild_id),),
            )

            rows = await cursor.fetchall()

        for row in rows:
            tournament = self._row_to_tournament(row)

            if tournament is not None:
                tournaments.append(tournament)

        return tournaments

    # ==========================================================
    # SUPPRESSION
    # ==========================================================

    async def delete(
        self,
        tournament_id: int,
    ) -> bool:
        """Supprime un tournoi et indique si une ligne a été supprimée."""

        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute(
                """
                DELETE FROM tournaments
                WHERE id = ?
                """,
                (tournament_id,),
            )

            await db.commit()

            return cursor.rowcount > 0

    # ==========================================================
    # MISE À JOUR DU STATUT
    # ==========================================================

    async def update_status(
        self,
        tournament_id: int,
        status: str,
    ) -> bool:
        """Modifie le statut d'un tournoi."""

        normalized_status = status.strip().lower()

        if not normalized_status:
            raise ValueError(
                "Le statut du tournoi ne peut pas être vide."
            )

        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute(
                """
                UPDATE tournaments
                SET status = ?
                WHERE id = ?
                """,
                (
                    normalized_status,
                    tournament_id,
                ),
            )

            await db.commit()

            return cursor.rowcount > 0

    # ==========================================================
    # FIN DU TOURNOI
    # ==========================================================

    async def finish(
        self,
        tournament_id: int,
        winner_id: str,
    ) -> bool:
        """Termine un tournoi et enregistre son vainqueur."""

        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute(
                """
                UPDATE tournaments
                SET
                    status = 'finished',
                    winner_id = ?
                WHERE id = ?
                """,
                (
                    str(winner_id),
                    tournament_id,
                ),
            )

            await db.commit()

            return cursor.rowcount > 0

    # ==========================================================
    # EXISTENCE
    # ==========================================================

    async def exists(
        self,
        tournament_id: int,
    ) -> bool:
        """Indique si un tournoi existe à partir de son ID."""

        tournament = await self.get(tournament_id)
        return tournament is not None

    async def code_exists(
        self,
        code: str,
    ) -> bool:
        """Indique si un code public est déjà utilisé."""

        tournament = await self.get_by_code(code)
        return tournament is not None

    # ==========================================================
    # CONVERSION SQL -> MODÈLE
    # ==========================================================

    @staticmethod
    def _row_to_tournament(
        row: aiosqlite.Row | None,
    ) -> Tournament | None:
        """Convertit une ligne SQLite en modèle Tournament."""

        if row is None:
            return None

        return Tournament(**dict(row))

    # ==========================================================
    # GÉNÉRATION DU CODE PUBLIC
    # ==========================================================

    async def _generate_code(
        self,
        format: str,
    ) -> str:
        """Génère un code public unique selon le format du tournoi."""

        prefixes = {
            "Format Actuel": "TCG",
            "Master Duel": "MD",
            "Genesys": "GEN",
            "GOAT": "GOAT",
            "Edison": "EDI",
            "HAT": "HAT",
            "Rush Duel": "RD",
            "Speed Duel": "SD",
        }

        prefix = prefixes.get(
            format,
            "T",
        )

        for _ in range(100):
            random_code = "".join(
                random.choices(
                    string.digits,
                    k=4,
                )
            )

            code = f"{prefix}-{random_code}"

            if not await self.code_exists(code):
                return code

        raise RuntimeError(
            "Impossible de générer un code de tournoi unique après 100 tentatives."
        )
