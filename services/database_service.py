from __future__ import annotations
import random
import string


from collections.abc import Sequence
from typing import Any

import aiosqlite

from config import DATABASE

from models.player import Player
from models.match import Match
from models.tournament import Tournament
from models.registration import Registration

from models.enums import MatchStatus, TournamentStatus


class DatabaseService:
    """
    Service central d'accès à SQLite.

    Important :
    - ce fichier contient les requêtes SQL ;
    - les autres services ne doivent pas ouvrir aiosqlite directement ;
    - BracketService, TournamentService, etc. devront passer par self.db.
    """

    def __init__(self):

        self.conn: aiosqlite.Connection | None = None

    # ==========================================================
    # CONNEXION
    # ==========================================================

    async def connect(self) -> None:
        """
        Ouvre la connexion SQLite.
        À appeler une seule fois au démarrage du bot.
        """

        if self.conn is not None:
            return

        self.conn = await aiosqlite.connect(DATABASE)

        self.conn.row_factory = aiosqlite.Row

        await self.conn.execute("PRAGMA foreign_keys = ON;")
        await self.conn.execute("PRAGMA journal_mode = WAL;")
        await self.conn.execute("PRAGMA synchronous = NORMAL;")

    async def close(self) -> None:
        """
        Ferme proprement la connexion SQLite.
        """

        if self.conn is None:
            return

        await self.conn.close()

        self.conn = None

    def _connection(self) -> aiosqlite.Connection:
        """
        Retourne la connexion active.

        Cela évite les erreurs silencieuses si on oublie d'appeler connect().
        """

        if self.conn is None:
            raise RuntimeError(
                "DatabaseService n'est pas connecté. "
                "Appelle await db.connect() au démarrage du bot."
            )

        return self.conn

    # ==========================================================
    # TRANSACTIONS
    # ==========================================================

    async def commit(self) -> None:

        await self._connection().commit()

    async def rollback(self) -> None:

        await self._connection().rollback()

    # ==========================================================
    # HELPERS SQL
    # ==========================================================

    async def execute(
        self,
        query: str,
        parameters: Sequence[Any] = (),
        *,
        commit: bool = False,
    ) -> aiosqlite.Cursor:
        """
        Exécute une requête SQL.

        commit=True permet d'enregistrer directement les changements.
        """

        cursor = await self._connection().execute(
            query,
            tuple(parameters),
        )

        if commit:
            await self.commit()

        return cursor

    async def executemany(
        self,
        query: str,
        parameters: Sequence[Sequence[Any]],
        *,
        commit: bool = False,
    ) -> aiosqlite.Cursor:
        """
        Exécute une requête SQL plusieurs fois.
        Utile pour créer plusieurs matchs d'un coup.
        """

        cursor = await self._connection().executemany(
            query,
            parameters,
        )

        if commit:
            await self.commit()

        return cursor

    async def fetchone(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> aiosqlite.Row | None:
        """
        Retourne une seule ligne.
        """

        cursor = await self._connection().execute(
            query,
            tuple(parameters),
        )

        return await cursor.fetchone()

    async def fetchall(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> list[aiosqlite.Row]:
        """
        Retourne toutes les lignes.
        """

        cursor = await self._connection().execute(
            query,
            tuple(parameters),
        )

        rows = await cursor.fetchall()

        return list(rows)

    async def fetchval(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> Any:
        """
        Retourne la première colonne de la première ligne.

        Exemple :
            SELECT COUNT(*) ...
        """

        row = await self.fetchone(
            query,
            parameters,
        )

        if row is None:
            return None

        return row[0]

    async def insert(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> int:
        """
        Exécute un INSERT et retourne l'id créé.
        """

        cursor = await self.execute(
            query,
            parameters,
        )

        await self.commit()

        return cursor.lastrowid

    async def update(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> int:
        """
        Exécute un UPDATE ou DELETE.

        Retourne le nombre de lignes modifiées.
        """

        cursor = await self.execute(
            query,
            parameters,
        )

        await self.commit()

        return cursor.rowcount

    # ==========================================================
    # TOURNOIS
    # ==========================================================

    async def create_tournament(
        self,
        guild_id: str,
        name: str,
        format: str,
        max_players: int,
        created_by: str,
    ) -> Tournament:
        """
        Crée un tournoi en phase d'inscription.
        """

        if max_players not in (4, 8, 16, 32, 64):
            raise ValueError(
                "Le tournoi doit contenir 4, 8, 16, 32 ou 64 joueurs."
            )

        active = await self.get_active_tournament(guild_id)

        if active is not None:
            raise ValueError(
                "Un tournoi est déjà actif sur ce serveur."
            )

        code = await self.generate_unique_tournament_code(format)

        tournament_id = await self.insert(
            """
            INSERT INTO tournaments (
                guild_id,
                code,
                name,
                format,
                max_players,
                status,
                created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                code,
                name,
                format,
                max_players,
                TournamentStatus.REGISTRATION.value,
                created_by,
            ),
        )

        tournament = await self.get_tournament(tournament_id)

        if tournament is None:
            raise RuntimeError(
                "Le tournoi a été créé, mais impossible de le récupérer."
            )

        return tournament

    async def get_tournament(
        self,
        tournament_id: int,
    ) -> Tournament | None:
        """
        Récupère un tournoi par son ID.
        """

        row = await self.fetchone(
            """
            SELECT *
            FROM tournaments
            WHERE id = ?
            """,
            (tournament_id,),
        )

        if row is None:
            return None

        return Tournament.from_row(row)

    async def get_tournament_by_code(
        self,
        code: str,
    ) -> Tournament | None:
        """
        Récupère un tournoi par son code.
        Exemple : TCG-1234, MD-4821, RD-9012.
        """

        row = await self.fetchone(
            """
            SELECT *
            FROM tournaments
            WHERE code = ?
            """,
            (code,),
        )

        if row is None:
            return None

        return Tournament.from_row(row)

    async def get_active_tournament(
        self,
        guild_id: str,
    ) -> Tournament | None:
        """
        Récupère le tournoi actif d'un serveur.

        Un tournoi actif est un tournoi qui n'est pas terminé
        et qui n'est pas annulé.
        """

        row = await self.fetchone(
            """
            SELECT *
            FROM tournaments
            WHERE guild_id = ?
            AND status NOT IN ('finished', 'cancelled')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (guild_id,),
        )

        if row is None:
            return None

        return Tournament.from_row(row)

    async def list_tournaments(
        self,
        guild_id: str,
        *,
        include_finished: bool = True,
    ) -> list[Tournament]:
        """
        Liste les tournois d'un serveur.
        """

        if include_finished:

            rows = await self.fetchall(
                """
                SELECT *
                FROM tournaments
                WHERE guild_id = ?
                ORDER BY created_at DESC
                """,
                (guild_id,),
            )

        else:

            rows = await self.fetchall(
                """
                SELECT *
                FROM tournaments
                WHERE guild_id = ?
                AND status NOT IN ('finished', 'cancelled')
                ORDER BY created_at DESC
                """,
                (guild_id,),
            )

        return [
            Tournament.from_row(row)
            for row in rows
        ]

    async def update_tournament_status(
        self,
        tournament_id: int,
        status: TournamentStatus | str,
    ) -> None:
        """
        Modifie le statut d'un tournoi.
        """

        if isinstance(status, TournamentStatus):
            status_value = status.value
        else:
            status_value = status

        await self.update(
            """
            UPDATE tournaments
            SET status = ?
            WHERE id = ?
            """,
            (
                status_value,
                tournament_id,
            ),
        )

    async def start_tournament(
        self,
        tournament_id: int,
        total_rounds: int,
    ) -> None:
        """
        Lance un tournoi.

        Utilisé au moment où le bracket est généré.
        """

        await self.update(
            """
            UPDATE tournaments
            SET
                status = ?,
                current_round = ?,
                total_rounds = ?,
                started_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                TournamentStatus.RUNNING.value,
                total_rounds,
                total_rounds,
                tournament_id,
            ),
        )

    async def update_current_round(
        self,
        tournament_id: int,
        current_round: int,
    ) -> None:
        """
        Met à jour le round actuel.
        """

        await self.update(
            """
            UPDATE tournaments
            SET current_round = ?
            WHERE id = ?
            """,
            (
                current_round,
                tournament_id,
            ),
        )

    async def update_bracket_message(
        self,
        tournament_id: int,
        message_id: str | None,
    ) -> None:
        """
        Sauvegarde l'ID du message Discord qui affiche le bracket.
        """

        await self.update(
            """
            UPDATE tournaments
            SET bracket_message_id = ?
            WHERE id = ?
            """,
            (
                message_id,
                tournament_id,
            ),
        )

    async def finish_tournament(
        self,
        tournament_id: int,
        winner_id: str,
        winner_name: str,
    ) -> None:
        """
        Termine un tournoi avec son vainqueur.
        """

        await self.update(
            """
            UPDATE tournaments
            SET
                status = ?,
                winner_id = ?,
                winner_name = ?,
                finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                TournamentStatus.FINISHED.value,
                winner_id,
                winner_name,
                tournament_id,
            ),
        )

    async def cancel_tournament(
        self,
        tournament_id: int,
    ) -> None:
        """
        Annule un tournoi.
        """

        await self.update(
            """
            UPDATE tournaments
            SET
                status = ?,
                finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                TournamentStatus.CANCELLED.value,
                tournament_id,
            ),
        )

    async def delete_tournament(
        self,
        tournament_id: int,
    ) -> None:
        """
        Supprime un tournoi.

        Les inscriptions et les matchs sont supprimés automatiquement
        grâce au ON DELETE CASCADE.
        """

        await self.update(
            """
            DELETE FROM tournaments
            WHERE id = ?
            """,
            (tournament_id,),
        )

    async def tournament_exists(
        self,
        tournament_id: int,
    ) -> bool:
        """
        Vérifie si un tournoi existe.
        """

        value = await self.fetchval(
            """
            SELECT 1
            FROM tournaments
            WHERE id = ?
            """,
            (tournament_id,),
        )

        return value is not None

    async def generate_unique_tournament_code(
        self,
        format: str,
    ) -> str:
        """
        Génère un code unique pour un tournoi.

        Exemple :
        - TCG-1234
        - MD-4028
        - RD-9931
        """

        prefix = self.get_format_prefix(format)

        for _ in range(20):

            digits = "".join(
                random.choices(
                    string.digits,
                    k=4,
                )
            )

            code = f"{prefix}-{digits}"

            existing = await self.get_tournament_by_code(code)

            if existing is None:
                return code

        raise RuntimeError(
            "Impossible de générer un code de tournoi unique."
        )

    @staticmethod
    def get_format_prefix(
        format: str,
    ) -> str:
        """
        Transforme un format en préfixe court.
        """

        prefixes = {
            "Format Actuel": "TCG",
            "Master Duel": "MD",
            "Genesys": "GEN",
            "GOAT": "GOAT",
            "Edison": "EDI",
            "HAT": "HAT",
            "Tengu Plant": "TP",
            "Dragon Ruler": "DR",
            "TeleDAD": "TD",
            "Rush Duel": "RD",
            "Speed Duel": "SD",
        }

        return prefixes.get(
            format,
            "T",
        )

    # ==========================================================
    # JOUEURS
    # ==========================================================

    async def upsert_player(
        self,
        discord_id: str,
        guild_id: str,
        username: str,
        display_name: str | None = None,
        avatar_url: str | None = None,
    ) -> Player:
        """
        Crée ou met à jour un joueur.

        Utilisé au moment de l'inscription ou lorsqu'un joueur interagit
        avec le bot.
        """

        await self.update(
            """
            INSERT INTO players (
                discord_id,
                guild_id,
                username,
                display_name,
                avatar_url
            )
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(discord_id, guild_id)
            DO UPDATE SET
                username = excluded.username,
                display_name = excluded.display_name,
                avatar_url = excluded.avatar_url
            """,
            (
                discord_id,
                guild_id,
                username,
                display_name,
                avatar_url,
            ),
        )

        player = await self.get_player(
            discord_id,
            guild_id,
        )

        if player is None:
            raise RuntimeError(
                "Le joueur a été créé, mais impossible de le récupérer."
            )

        return player

    async def get_player(
        self,
        discord_id: str,
        guild_id: str,
    ) -> Player | None:
        """
        Récupère un joueur sur un serveur.
        """

        row = await self.fetchone(
            """
            SELECT *
            FROM players
            WHERE discord_id = ?
            AND guild_id = ?
            """,
            (
                discord_id,
                guild_id,
            ),
        )

        if row is None:
            return None

        return Player.from_row(row)

    async def list_players(
        self,
        guild_id: str,
    ) -> list[Player]:
        """
        Liste tous les joueurs connus d'un serveur.
        """

        rows = await self.fetchall(
            """
            SELECT *
            FROM players
            WHERE guild_id = ?
            ORDER BY wins DESC, tournaments_won DESC, username ASC
            """,
            (guild_id,),
        )

        return [
            Player.from_row(row)
            for row in rows
        ]

    async def search_players(
        self,
        guild_id: str,
        query: str,
        limit: int = 25,
    ) -> list[Player]:
        """
        Recherche des joueurs par pseudo.
        Utile pour l'autocomplétion Discord.
        """

        rows = await self.fetchall(
            """
            SELECT *
            FROM players
            WHERE guild_id = ?
            AND username LIKE ?
            ORDER BY username ASC
            LIMIT ?
            """,
            (
                guild_id,
                f"%{query}%",
                limit,
            ),
        )

        return [
            Player.from_row(row)
            for row in rows
        ]

    async def count_players(
        self,
        guild_id: str,
    ) -> int:
        """
        Compte les joueurs connus d'un serveur.
        """

        value = await self.fetchval(
            """
            SELECT COUNT(*)
            FROM players
            WHERE guild_id = ?
            """,
            (guild_id,),
        )

        return int(value or 0)

    async def update_player_profile(
        self,
        discord_id: str,
        guild_id: str,
        username: str | None = None,
        display_name: str | None = None,
        avatar_url: str | None = None,
    ) -> None:
        """
        Met à jour les informations visibles d'un joueur.
        """

        fields: list[str] = []
        params: list[Any] = []

        if username is not None:
            fields.append("username = ?")
            params.append(username)

        if display_name is not None:
            fields.append("display_name = ?")
            params.append(display_name)

        if avatar_url is not None:
            fields.append("avatar_url = ?")
            params.append(avatar_url)

        if not fields:
            return

        fields.append("updated_at = CURRENT_TIMESTAMP")

        params.append(discord_id)
        params.append(guild_id)

        await self.execute(
            f"""
            UPDATE players
            SET {", ".join(fields)}
            WHERE discord_id = ?
            AND guild_id = ?
            """,
            tuple(params),
            commit=True,
        )
    async def add_player_win(
        self,
        discord_id: str,
        guild_id: str,
    ) -> None:
        """
        Ajoute une victoire au joueur.
        """

        await self.update(
            """
            UPDATE players
            SET wins = wins + 1
            WHERE discord_id = ?
            AND guild_id = ?
            """,
            (
                discord_id,
                guild_id,
            ),
        )

    async def add_player_loss(
        self,
        discord_id: str,
        guild_id: str,
    ) -> None:
        """
        Ajoute une défaite au joueur.
        """

        await self.update(
            """
            UPDATE players
            SET losses = losses + 1
            WHERE discord_id = ?
            AND guild_id = ?
            """,
            (
                discord_id,
                guild_id,
            ),
        )

    async def add_tournament_played(
        self,
        discord_id: str,
        guild_id: str,
    ) -> None:
        """
        Incrémente le nombre de tournois joués.
        """

        await self.update(
            """
            UPDATE players
            SET tournaments_played = tournaments_played + 1
            WHERE discord_id = ?
            AND guild_id = ?
            """,
            (
                discord_id,
                guild_id,
            ),
        )

    async def add_tournament_won(
        self,
        discord_id: str,
        guild_id: str,
    ) -> None:
        """
        Incrémente le nombre de tournois gagnés.
        """

        await self.update(
            """
            UPDATE players
            SET tournaments_won = tournaments_won + 1
            WHERE discord_id = ?
            AND guild_id = ?
            """,
            (
                discord_id,
                guild_id,
            ),
        )

    async def reset_player_stats(
        self,
        discord_id: str,
        guild_id: str,
    ) -> None:
        """
        Réinitialise les statistiques d'un joueur.
        """

        await self.update(
            """
            UPDATE players
            SET
                wins = 0,
                losses = 0,
                tournaments_played = 0,
                tournaments_won = 0
            WHERE discord_id = ?
            AND guild_id = ?
            """,
            (
                discord_id,
                guild_id,
            ),
        )

    async def delete_player(
        self,
        discord_id: str,
        guild_id: str,
    ) -> None:
        """
        Supprime un joueur du serveur.

        Attention : cela ne supprime pas forcément ses anciennes inscriptions.
        """
        
        await self.update(
            """
            DELETE FROM players
            WHERE discord_id = ?
            AND guild_id = ?
            """,
            (
                discord_id,
                guild_id,
            ),
        )

    # ==========================================================
    # INSCRIPTIONS
    # ==========================================================

    async def register_player(
        self,
        tournament_id: int,
        guild_id: str,
        discord_id: str,
        username: str,
        deck: str | None = None,
        display_name: str | None = None,
        avatar_url: str | None = None,
    ) -> Registration:
        """
        Inscrit un joueur à un tournoi.

        Crée aussi le joueur dans la table players si nécessaire.
        """

        tournament = await self.get_tournament(tournament_id)

        if tournament is None:
            raise ValueError("Tournoi introuvable.")

        if not tournament.is_registration:
            raise ValueError(
                "Les inscriptions ne sont pas ouvertes pour ce tournoi."
            )

        if await self.is_registered(tournament_id, discord_id):
            raise ValueError("Ce joueur est déjà inscrit à ce tournoi.")

        current = await self.count_registrations(tournament_id)

        if current >= tournament.max_players:
            raise ValueError("Le tournoi est déjà complet.")

        await self.upsert_player(
            discord_id=discord_id,
            guild_id=guild_id,
            username=username,
            display_name=display_name,
            avatar_url=avatar_url,
        )

        registration_id = await self.insert(
            """
            INSERT INTO registrations (
                tournament_id,
                discord_id,
                username,
                deck,
                checked_in,
                dropped,
                disqualified
            )
            VALUES (?, ?, ?, ?, 1, 0, 0)
            """,
            (
                tournament_id,
                discord_id,
                username,
                deck,
            ),
        )

        registration = await self.get_registration(registration_id)

        if registration is None:
            raise RuntimeError(
                "L'inscription a été créée, mais impossible de la récupérer."
            )

        return registration

    async def unregister_player(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> None:
        """
        Désinscrit un joueur d'un tournoi.
        """

        await self.update(
            """
            DELETE FROM registrations
            WHERE tournament_id = ?
            AND discord_id = ?
            """,
            (
                tournament_id,
                discord_id,
            ),
        )

    async def get_registration(
        self,
        registration_id: int,
    ) -> Registration | None:
        """
        Récupère une inscription par son ID.
        """

        row = await self.fetchone(
            """
            SELECT *
            FROM registrations
            WHERE id = ?
            """,
            (registration_id,),
        )

        if row is None:
            return None

        return Registration.from_row(row)

    async def get_registration_by_user(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> Registration | None:
        """
        Récupère l'inscription d'un joueur dans un tournoi.
        """

        row = await self.fetchone(
            """
            SELECT *
            FROM registrations
            WHERE tournament_id = ?
            AND discord_id = ?
            """,
            (
                tournament_id,
                discord_id,
            ),
        )

        if row is None:
            return None

        return Registration.from_row(row)

    async def is_registered(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> bool:
        """
        Vérifie si un joueur est inscrit.
        """

        value = await self.fetchval(
            """
            SELECT 1
            FROM registrations
            WHERE tournament_id = ?
            AND discord_id = ?
            """,
            (
                tournament_id,
                discord_id,
            ),
        )

        return value is not None

    async def list_registrations(
        self,
        tournament_id: int,
        *,
        include_dropped: bool = False,
        include_disqualified: bool = False,
    ) -> list[Registration]:
        """
        Liste les inscriptions d'un tournoi.

        Par défaut, les joueurs ayant drop ou été disqualifiés
        ne sont pas retournés.
        """

        conditions = [
            "tournament_id = ?",
        ]

        parameters: list[object] = [
            tournament_id,
        ]

        if not include_dropped:
            conditions.append("dropped = 0")

        if not include_disqualified:
            conditions.append("disqualified = 0")

        where_clause = " AND ".join(conditions)

        rows = await self.fetchall(
            f"""
            SELECT *
            FROM registrations
            WHERE {where_clause}
            ORDER BY
                seed IS NULL,
                seed ASC,
                registered_at ASC,
                username ASC
            """,
            parameters,
        )

        return [
            Registration.from_row(row)
            for row in rows
        ]

    async def list_checked_in_registrations(
        self,
        tournament_id: int,
    ) -> list[Registration]:
        """
        Liste uniquement les joueurs check-in et encore actifs.
        """

        rows = await self.fetchall(
            """
            SELECT *
            FROM registrations
            WHERE tournament_id = ?
            AND checked_in = 1
            AND dropped = 0
            AND disqualified = 0
            ORDER BY
                seed IS NULL,
                seed ASC,
                registered_at ASC,
                username ASC
            """,
            (tournament_id,),
        )

        return [
            Registration.from_row(row)
            for row in rows
        ]

    async def count_registrations(
        self,
        tournament_id: int,
        *,
        active_only: bool = True,
    ) -> int:
        """
        Compte les inscrits d'un tournoi.
        """

        if active_only:

            value = await self.fetchval(
                """
                SELECT COUNT(*)
                FROM registrations
                WHERE tournament_id = ?
                AND dropped = 0
                AND disqualified = 0
                """,
                (tournament_id,),
            )

        else:

            value = await self.fetchval(
                """
                SELECT COUNT(*)
                FROM registrations
                WHERE tournament_id = ?
                """,
                (tournament_id,),
            )

        return int(value or 0)

    async def count_checked_in(
        self,
        tournament_id: int,
    ) -> int:
        """
        Compte les joueurs check-in.
        """

        value = await self.fetchval(
            """
            SELECT COUNT(*)
            FROM registrations
            WHERE tournament_id = ?
            AND checked_in = 1
            AND dropped = 0
            AND disqualified = 0
            """,
            (tournament_id,),
        )

        return int(value or 0)

    async def update_registration_deck(
        self,
        tournament_id: int,
        discord_id: str,
        deck: str | None,
    ) -> None:
        """
        Modifie le deck déclaré d'un joueur.
        """

        await self.update(
            """
            UPDATE registrations
            SET deck = ?
            WHERE tournament_id = ?
            AND discord_id = ?
            """,
            (
                deck,
                tournament_id,
                discord_id,
            ),
        )

    async def set_check_in(
        self,
        tournament_id: int,
        discord_id: str,
        checked_in: bool,
    ) -> None:
        """
        Active ou désactive le check-in d'un joueur.
        """

        await self.update(
            """
            UPDATE registrations
            SET checked_in = ?
            WHERE tournament_id = ?
            AND discord_id = ?
            """,
            (
                int(checked_in),
                tournament_id,
                discord_id,
            ),
        )

    async def check_in_player(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> None:
        """
        Marque un joueur comme présent.
        """

        await self.set_check_in(
            tournament_id,
            discord_id,
            True,
        )

    async def uncheck_player(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> None:
        """
        Marque un joueur comme non présent.
        """

        await self.set_check_in(
            tournament_id,
            discord_id,
            False,
        )

    async def drop_player(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> None:
        """
        Marque un joueur comme ayant abandonné le tournoi.
        """

        await self.update(
            """
            UPDATE registrations
            SET dropped = 1
            WHERE tournament_id = ?
            AND discord_id = ?
            """,
            (
                tournament_id,
                discord_id,
            ),
        )

    async def disqualify_player(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> None:
        """
        Disqualifie un joueur.
        """

        await self.update(
            """
            UPDATE registrations
            SET disqualified = 1
            WHERE tournament_id = ?
            AND discord_id = ?
            """,
            (
                tournament_id,
                discord_id,
            ),
        )

    async def restore_player_registration(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> None:
        """
        Annule un drop ou une disqualification.
        """

        await self.update(
            """
            UPDATE registrations
            SET
                dropped = 0,
                disqualified = 0
            WHERE tournament_id = ?
            AND discord_id = ?
            """,
            (
                tournament_id,
                discord_id,
            ),
        )

    async def set_registration_seed(
        self,
        tournament_id: int,
        discord_id: str,
        seed: int | None,
    ) -> None:
        """
        Définit le seed d'un joueur.
        """

        await self.update(
            """
            UPDATE registrations
            SET seed = ?
            WHERE tournament_id = ?
            AND discord_id = ?
            """,
            (
                seed,
                tournament_id,
                discord_id,
            ),
        )

    async def set_final_rank(
        self,
        tournament_id: int,
        discord_id: str,
        final_rank: int,
    ) -> None:
        """
        Enregistre le classement final d'un joueur.
        """

        await self.update(
            """
            UPDATE registrations
            SET final_rank = ?
            WHERE tournament_id = ?
            AND discord_id = ?
            """,
            (
                final_rank,
                tournament_id,
                discord_id,
            ),
        )

    async def clear_registrations(
        self,
        tournament_id: int,
    ) -> None:
        """
        Supprime toutes les inscriptions d'un tournoi.
        """

        await self.update(
            """
            DELETE FROM registrations
            WHERE tournament_id = ?
            """,
            (tournament_id,),
        )

    # ==========================================================
    # MATCHS
    # ==========================================================

    async def create_match(
        self,
        match: Match,
    ) -> Match:
        """
        Crée un match dans la base et retourne le match complet avec son ID.
        """

        match_id = await self.insert(
            """
            INSERT INTO matches (
                tournament_id,
                round,
                match_number,
                bracket_position,
                next_match_id,
                next_slot,
                player1_id,
                player2_id,
                player1_name,
                player2_name,
                player1_score,
                player2_score,
                winner_id,
                winner_name,
                score,
                reported_by,
                validated_by,
                reported_at,
                validated_at,
                status,
                is_bye,
                notes
            )
            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?
            )
            """,
            (
                match.tournament_id,
                match.round,
                match.match_number,
                match.bracket_position,
                match.next_match_id,
                match.next_slot,
                match.player1_id,
                match.player2_id,
                match.player1_name,
                match.player2_name,
                match.player1_score,
                match.player2_score,
                match.winner_id,
                match.winner_name,
                match.score,
                match.reported_by,
                match.validated_by,
                match.reported_at,
                match.validated_at,
                match.status.value,
                int(match.is_bye),
                match.notes,
            ),
        )

        created = await self.get_match(match_id)

        if created is None:
            raise RuntimeError(
                "Le match a été créé, mais impossible de le récupérer."
            )

        return created

    async def get_match(
        self,
        match_id: int,
    ) -> Match | None:
        """
        Récupère un match par son ID.
        """

        row = await self.fetchone(
            """
            SELECT *
            FROM matches
            WHERE id = ?
            """,
            (match_id,),
        )

        if row is None:
            return None

        return Match.from_row(row)

    async def update_match(
        self,
        match: Match,
    ) -> None:
        """
        Met à jour un match complet.
        """

        if match.id is None:
            raise ValueError(
                "Impossible de mettre à jour un match sans ID."
            )

        await self.update(
            """
            UPDATE matches
            SET
                tournament_id = ?,
                round = ?,
                match_number = ?,
                bracket_position = ?,
                next_match_id = ?,
                next_slot = ?,
                player1_id = ?,
                player2_id = ?,
                player1_name = ?,
                player2_name = ?,
                player1_score = ?,
                player2_score = ?,
                winner_id = ?,
                winner_name = ?,
                score = ?,
                reported_by = ?,
                validated_by = ?,
                reported_at = ?,
                validated_at = ?,
                status = ?,
                is_bye = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                match.tournament_id,
                match.round,
                match.match_number,
                match.bracket_position,
                match.next_match_id,
                match.next_slot,
                match.player1_id,
                match.player2_id,
                match.player1_name,
                match.player2_name,
                match.player1_score,
                match.player2_score,
                match.winner_id,
                match.winner_name,
                match.score,
                match.reported_by,
                match.validated_by,
                match.reported_at,
                match.validated_at,
                match.status.value,
                int(match.is_bye),
                match.notes,
                match.id,
            ),
        )

    async def delete_match(
        self,
        match_id: int,
    ) -> None:
        """
        Supprime un match.
        """

        await self.update(
            """
            DELETE FROM matches
            WHERE id = ?
            """,
            (match_id,),
        )

    async def clear_matches(
        self,
        tournament_id: int,
    ) -> None:
        """
        Supprime tous les matchs d'un tournoi.
        Utile si on régénère un bracket.
        """

        await self.update(
            """
            DELETE FROM matches
            WHERE tournament_id = ?
            """,
            (tournament_id,),
        )

    async def list_matches(
        self,
        tournament_id: int,
    ) -> list[Match]:
        """
        Liste tous les matchs d'un tournoi.
        """

        rows = await self.fetchall(
            """
            SELECT *
            FROM matches
            WHERE tournament_id = ?
            ORDER BY round DESC, match_number ASC
            """,
            (tournament_id,),
        )

        return [
            Match.from_row(row)
            for row in rows
        ]

    async def list_round_matches(
        self,
        tournament_id: int,
        round_number: int,
    ) -> list[Match]:
        """
        Liste les matchs d'un round précis.
        """

        rows = await self.fetchall(
            """
            SELECT *
            FROM matches
            WHERE tournament_id = ?
            AND round = ?
            ORDER BY match_number ASC
            """,
            (
                tournament_id,
                round_number,
            ),
        )

        return [
            Match.from_row(row)
            for row in rows
        ]

    async def list_player_matches(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> list[Match]:
        """
        Liste tous les matchs d'un joueur dans un tournoi.
        """

        rows = await self.fetchall(
            """
            SELECT *
            FROM matches
            WHERE tournament_id = ?
            AND (
                player1_id = ?
                OR player2_id = ?
            )
            ORDER BY round DESC, match_number ASC
            """,
            (
                tournament_id,
                discord_id,
                discord_id,
            ),
        )

        return [
            Match.from_row(row)
            for row in rows
        ]

    async def get_player_active_match(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> Match | None:
        """
        Récupère le match actuel d'un joueur.

        Un match actuel est un match non terminé où le joueur est présent.
        """

        row = await self.fetchone(
            """
            SELECT *
            FROM matches
            WHERE tournament_id = ?
            AND (
                player1_id = ?
                OR player2_id = ?
            )
            AND status IN ('waiting', 'playing', 'reported')
            ORDER BY round DESC, match_number ASC
            LIMIT 1
            """,
            (
                tournament_id,
                discord_id,
                discord_id,
            ),
        )

        if row is None:
            return None

        return Match.from_row(row)

    async def get_final_match(
        self,
        tournament_id: int,
    ) -> Match | None:
        """
        Récupère la finale d'un tournoi.
        Dans notre système, la finale est toujours round = 1.
        """

        row = await self.fetchone(
            """
            SELECT *
            FROM matches
            WHERE tournament_id = ?
            AND round = 1
            ORDER BY match_number ASC
            LIMIT 1
            """,
            (tournament_id,),
        )

        if row is None:
            return None

        return Match.from_row(row)

    async def get_tournament_rounds(
        self,
        tournament_id: int,
    ) -> list[int]:
        """
        Récupère les rounds existants d'un tournoi.
        Exemple : [4, 3, 2, 1]
        """

        rows = await self.fetchall(
            """
            SELECT DISTINCT round
            FROM matches
            WHERE tournament_id = ?
            ORDER BY round DESC
            """,
            (tournament_id,),
        )

        return [
            int(row["round"])
            for row in rows
        ]

    async def count_unfinished_matches(
        self,
        tournament_id: int,
        round_number: int | None = None,
    ) -> int:
        """
        Compte les matchs non terminés.
        """

        if round_number is None:

            value = await self.fetchval(
                """
                SELECT COUNT(*)
                FROM matches
                WHERE tournament_id = ?
                AND status NOT IN ('completed', 'cancelled')
                """,
                (tournament_id,),
            )

        else:

            value = await self.fetchval(
                """
                SELECT COUNT(*)
                FROM matches
                WHERE tournament_id = ?
                AND round = ?
                AND status NOT IN ('completed', 'cancelled')
                """,
                (
                    tournament_id,
                    round_number,
                ),
            )

        return int(value or 0)

    async def count_round_matches(
        self,
        tournament_id: int,
        round_number: int,
    ) -> int:
        """
        Compte les matchs d'un round.
        """

        value = await self.fetchval(
            """
            SELECT COUNT(*)
            FROM matches
            WHERE tournament_id = ?
            AND round = ?
            """,
            (
                tournament_id,
                round_number,
            ),
        )

        return int(value or 0)

    async def set_match_next(
        self,
        match_id: int,
        next_match_id: int | None,
        next_slot: int | None,
    ) -> None:
        """
        Définit vers quel match le vainqueur doit avancer.

        next_slot :
        - 1 = player1 du prochain match
        - 2 = player2 du prochain match
        - None = finale / aucun match suivant
        """

        if next_slot is not None and next_slot not in (1, 2):
            raise ValueError("next_slot doit être 1, 2 ou None.")

        await self.update(
            """
            UPDATE matches
            SET
                next_match_id = ?,
                next_slot = ?
            WHERE id = ?
            """,
            (
                next_match_id,
                next_slot,
                match_id,
            ),
        )

    async def place_player_in_match(
        self,
        match_id: int,
        slot: int,
        discord_id: str,
        username: str,
    ) -> Match:
        """
        Place un joueur dans un match.

        slot :
        - 1 = player1
        - 2 = player2
        """

        if slot not in (1, 2):
            raise ValueError("Le slot doit être 1 ou 2.")

        match = await self.get_match(match_id)

        if match is None:
            raise ValueError("Match introuvable.")

        if slot == 1:

            await self.update(
                """
                UPDATE matches
                SET
                    player1_id = ?,
                    player1_name = ?
                WHERE id = ?
                """,
                (
                    discord_id,
                    username,
                    match_id,
                ),
            )

        else:

            await self.update(
                """
                UPDATE matches
                SET
                    player2_id = ?,
                    player2_name = ?
                WHERE id = ?
                """,
                (
                    discord_id,
                    username,
                    match_id,
                ),
            )

        updated = await self.get_match(match_id)

        if updated is None:
            raise RuntimeError(
                "Le joueur a été placé, mais le match est introuvable."
            )

        if updated.player1_id and updated.player2_id:

            await self.update(
                """
                UPDATE matches
                SET status = ?
                WHERE id = ?
                """,
                (
                    MatchStatus.PLAYING.value,
                    match_id,
                ),
            )

            updated.status = MatchStatus.PLAYING

        return updated

    async def clear_match_slot(
        self,
        match_id: int,
        slot: int,
    ) -> None:
        """
        Vide un slot de match.
        Utile en cas d'erreur staff.
        """

        if slot not in (1, 2):
            raise ValueError("Le slot doit être 1 ou 2.")

        if slot == 1:

            await self.update(
                """
                UPDATE matches
                SET
                    player1_id = NULL,
                    player1_name = NULL
                WHERE id = ?
                """,
                (match_id,),
            )

        else:

            await self.update(
                """
                UPDATE matches
                SET
                    player2_id = NULL,
                    player2_name = NULL
                WHERE id = ?
                """,
                (match_id,),
            )

    async def set_match_status(
        self,
        match_id: int,
        status: MatchStatus | str,
    ) -> None:
        """
        Change le statut d'un match.
        """

        if isinstance(status, MatchStatus):
            status_value = status.value
        else:
            status_value = status

        await self.update(
            """
            UPDATE matches
            SET status = ?
            WHERE id = ?
            """,
            (
                status_value,
                match_id,
            ),
        )

    async def report_match(
        self,
        match_id: int,
        player1_score: int,
        player2_score: int,
        reported_by: str,
    ) -> Match:
        """
        Reporte un résultat.

        Le match n'est pas encore terminé :
        il passe en statut REPORTED et attend validation staff.
        """

        match = await self.get_match(match_id)

        if match is None:
            raise ValueError("Match introuvable.")

        if not match.player1_id or not match.player2_id:
            raise ValueError(
                "Impossible de reporter un résultat : le match n'a pas deux joueurs."
            )

        if match.status == MatchStatus.COMPLETED:
            raise ValueError("Ce match est déjà terminé.")

        if player1_score == player2_score:
            raise ValueError(
                "Un match à élimination directe ne peut pas finir en égalité."
            )

        if player1_score > player2_score:

            winner_id = match.player1_id
            winner_name = match.player1_name

        else:

            winner_id = match.player2_id
            winner_name = match.player2_name

        score = f"{player1_score}-{player2_score}"

        await self.update(
            """
            UPDATE matches
            SET
                player1_score = ?,
                player2_score = ?,
                winner_id = ?,
                winner_name = ?,
                score = ?,
                reported_by = ?,
                reported_at = CURRENT_TIMESTAMP,
                status = ?
            WHERE id = ?
            """,
            (
                player1_score,
                player2_score,
                winner_id,
                winner_name,
                score,
                reported_by,
                MatchStatus.REPORTED.value,
                match_id,
            ),
        )

        updated = await self.get_match(match_id)

        if updated is None:
            raise RuntimeError(
                "Le résultat a été reporté, mais le match est introuvable."
            )

        return updated

    async def reject_match_report(
        self,
        match_id: int,
        validated_by: str,
        notes: str | None = None,
    ) -> Match:
        """
        Refuse un résultat reporté.

        Le match redevient jouable.
        """

        match = await self.get_match(match_id)

        if match is None:
            raise ValueError("Match introuvable.")

        if match.status != MatchStatus.REPORTED:
            raise ValueError(
                "Seul un match reporté peut être refusé."
            )

        new_status = (
            MatchStatus.PLAYING.value
            if match.player1_id and match.player2_id
            else MatchStatus.WAITING.value
        )

        await self.update(
            """
            UPDATE matches
            SET
                player1_score = 0,
                player2_score = 0,
                winner_id = NULL,
                winner_name = NULL,
                score = NULL,
                validated_by = ?,
                validated_at = CURRENT_TIMESTAMP,
                status = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                validated_by,
                new_status,
                notes,
                match_id,
            ),
        )

        updated = await self.get_match(match_id)

        if updated is None:
            raise RuntimeError(
                "Le report a été refusé, mais le match est introuvable."
            )

        return updated

    async def complete_match(
        self,
        match_id: int,
        winner_id: str,
        winner_name: str,
        *,
        player1_score: int | None = None,
        player2_score: int | None = None,
        score: str | None = None,
        validated_by: str | None = None,
        notes: str | None = None,
        is_bye: bool | None = None,
    ) -> Match:
        """
        Termine directement un match.

        Utilisé pour :
        - validation staff ;
        - BYE ;
        - victoire administrative.
        """

        updates = [
            "winner_id = ?",
            "winner_name = ?",
            "validated_by = ?",
            "validated_at = CURRENT_TIMESTAMP",
            "status = ?",
        ]

        parameters: list[object] = [
            winner_id,
            winner_name,
            validated_by,
            MatchStatus.COMPLETED.value,
        ]

        if player1_score is not None:

            updates.append("player1_score = ?")
            parameters.append(player1_score)

        if player2_score is not None:

            updates.append("player2_score = ?")
            parameters.append(player2_score)

        if score is not None:

            updates.append("score = ?")
            parameters.append(score)

        if notes is not None:

            updates.append("notes = ?")
            parameters.append(notes)

        if is_bye is not None:

            updates.append("is_bye = ?")
            parameters.append(int(is_bye))

        parameters.append(match_id)

        set_clause = ", ".join(updates)

        await self.update(
            f"""
            UPDATE matches
            SET {set_clause}
            WHERE id = ?
            """,
            parameters,
        )

        updated = await self.get_match(match_id)

        if updated is None:
            raise RuntimeError(
                "Le match a été terminé, mais il est introuvable."
            )

        return updated

    async def validate_match(
        self,
        match_id: int,
        validated_by: str,
        notes: str | None = None,
    ) -> Match:
        """
        Valide un match reporté.

        Important :
        une fois validé, le match passe directement en COMPLETED.
        Le BracketService pourra ensuite avancer le vainqueur.
        """

        match = await self.get_match(match_id)

        if match is None:
            raise ValueError("Match introuvable.")

        if match.status != MatchStatus.REPORTED:
            raise ValueError(
                "Seul un match reporté peut être validé."
            )

        if not match.winner_id or not match.winner_name:
            raise ValueError(
                "Impossible de valider : aucun vainqueur n'est enregistré."
            )

        return await self.complete_match(
            match_id=match.id,
            winner_id=match.winner_id,
            winner_name=match.winner_name,
            player1_score=match.player1_score,
            player2_score=match.player2_score,
            score=match.score,
            validated_by=validated_by,
            notes=notes,
        )

    async def cancel_match(
        self,
        match_id: int,
        notes: str | None = None,
    ) -> None:
        """
        Annule un match.
        """

        await self.update(
            """
            UPDATE matches
            SET
                status = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                MatchStatus.CANCELLED.value,
                notes,
                match_id,
            ),
        )

    async def get_bracket(
        self,
        tournament_id: int,
    ) -> dict[int, list[Match]]:
        """
        Retourne le bracket complet, groupé par round.

        Exemple :
        {
            3: [matchs des quarts],
            2: [matchs des demies],
            1: [finale]
        }
        """

        matches = await self.list_matches(tournament_id)

        bracket: dict[int, list[Match]] = {}

        for match in matches:
            bracket.setdefault(
                match.round,
                []
            ).append(match)

        for round_matches in bracket.values():
            round_matches.sort(
                key=lambda match: match.match_number
            )

        return dict(
            sorted(
                bracket.items(),
                reverse=True,
            )
        )

    async def get_ready_matches(
        self,
        tournament_id: int,
        round_number: int | None = None,
    ) -> list[Match]:
        """
        Retourne les matchs prêts à être joués.

        Un match prêt possède deux joueurs et n'est pas terminé.
        """

        if round_number is None:

            rows = await self.fetchall(
                """
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                AND player1_id IS NOT NULL
                AND player2_id IS NOT NULL
                AND status IN ('waiting', 'playing')
                ORDER BY round DESC, match_number ASC
                """,
                (tournament_id,),
            )

        else:

            rows = await self.fetchall(
                """
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                AND round = ?
                AND player1_id IS NOT NULL
                AND player2_id IS NOT NULL
                AND status IN ('waiting', 'playing')
                ORDER BY match_number ASC
                """,
                (
                    tournament_id,
                    round_number,
                ),
            )

        return [
            Match.from_row(row)
            for row in rows
        ]

    async def get_waiting_matches(
        self,
        tournament_id: int,
        round_number: int | None = None,
    ) -> list[Match]:
        """
        Retourne les matchs en attente.

        Cela peut inclure des matchs incomplets, par exemple :
        - une demi-finale qui attend encore un vainqueur ;
        - une finale pas encore remplie.
        """

        if round_number is None:

            rows = await self.fetchall(
                """
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                AND status = ?
                ORDER BY round DESC, match_number ASC
                """,
                (
                    tournament_id,
                    MatchStatus.WAITING.value,
                ),
            )

        else:

            rows = await self.fetchall(
                """
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                AND round = ?
                AND status = ?
                ORDER BY match_number ASC
                """,
                (
                    tournament_id,
                    round_number,
                    MatchStatus.WAITING.value,
                ),
            )

        return [
            Match.from_row(row)
            for row in rows
        ]

    async def get_playing_matches(
        self,
        tournament_id: int,
        round_number: int | None = None,
    ) -> list[Match]:
        """
        Retourne les matchs en cours.
        """

        if round_number is None:

            rows = await self.fetchall(
                """
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                AND status = ?
                ORDER BY round DESC, match_number ASC
                """,
                (
                    tournament_id,
                    MatchStatus.PLAYING.value,
                ),
            )

        else:

            rows = await self.fetchall(
                """
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                AND round = ?
                AND status = ?
                ORDER BY match_number ASC
                """,
                (
                    tournament_id,
                    round_number,
                    MatchStatus.PLAYING.value,
                ),
            )

        return [
            Match.from_row(row)
            for row in rows
        ]

    async def get_reported_matches(
        self,
        tournament_id: int,
        round_number: int | None = None,
    ) -> list[Match]:
        """
        Retourne les matchs reportés, en attente de validation staff.
        """

        if round_number is None:

            rows = await self.fetchall(
                """
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                AND status = ?
                ORDER BY round DESC, match_number ASC
                """,
                (
                    tournament_id,
                    MatchStatus.REPORTED.value,
                ),
            )

        else:

            rows = await self.fetchall(
                """
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                AND round = ?
                AND status = ?
                ORDER BY match_number ASC
                """,
                (
                    tournament_id,
                    round_number,
                    MatchStatus.REPORTED.value,
                ),
            )

        return [
            Match.from_row(row)
            for row in rows
        ]

    async def get_completed_matches(
        self,
        tournament_id: int,
        round_number: int | None = None,
    ) -> list[Match]:
        """
        Retourne les matchs terminés.
        """

        if round_number is None:

            rows = await self.fetchall(
                """
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                AND status = ?
                ORDER BY round DESC, match_number ASC
                """,
                (
                    tournament_id,
                    MatchStatus.COMPLETED.value,
                ),
            )

        else:

            rows = await self.fetchall(
                """
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                AND round = ?
                AND status = ?
                ORDER BY match_number ASC
                """,
                (
                    tournament_id,
                    round_number,
                    MatchStatus.COMPLETED.value,
                ),
            )

        return [
            Match.from_row(row)
            for row in rows
        ]

    async def get_match_waiting_for_slot(
        self,
        tournament_id: int,
        round_number: int,
        bracket_position: int,
    ) -> Match | None:
        """
        Récupère un match précis par sa position dans le bracket.

        Utile pour vérifier où un joueur doit arriver.
        """

        row = await self.fetchone(
            """
            SELECT *
            FROM matches
            WHERE tournament_id = ?
            AND round = ?
            AND bracket_position = ?
            LIMIT 1
            """,
            (
                tournament_id,
                round_number,
                bracket_position,
            ),
        )

        if row is None:
            return None

        return Match.from_row(row)

    async def get_current_round_from_matches(
        self,
        tournament_id: int,
    ) -> int | None:
        """
        Déduit le round actuel à partir des matchs.

        Comme le premier round a le plus grand numéro
        et la finale a round = 1, on prend le plus grand round
        qui contient encore des matchs non terminés.
        """

        value = await self.fetchval(
            """
            SELECT MAX(round)
            FROM matches
            WHERE tournament_id = ?
            AND status NOT IN ('completed', 'cancelled')
            """,
            (tournament_id,),
        )

        if value is None:
            return None

        return int(value)

    async def is_round_completed(
        self,
        tournament_id: int,
        round_number: int,
    ) -> bool:
        """
        Vérifie si tous les matchs d'un round sont terminés.
        """

        unfinished = await self.count_unfinished_matches(
            tournament_id,
            round_number,
        )

        return unfinished == 0

    async def is_tournament_completed_by_matches(
        self,
        tournament_id: int,
    ) -> bool:
        """
        Vérifie si le tournoi est terminé en regardant la finale.
        """

        final = await self.get_final_match(tournament_id)

        if final is None:
            return False

        return (
            final.status == MatchStatus.COMPLETED
            and final.winner_id is not None
        )

    async def get_tournament_winner_from_matches(
        self,
        tournament_id: int,
    ) -> tuple[str, str] | None:
        """
        Retourne le vainqueur du tournoi depuis la finale.

        Retour :
            (winner_id, winner_name)
        """

        final = await self.get_final_match(tournament_id)

        if final is None:
            return None

        if final.status != MatchStatus.COMPLETED:
            return None

        if final.winner_id is None or final.winner_name is None:
            return None

        return (
            final.winner_id,
            final.winner_name,
        )

    async def get_next_match_for_player(
        self,
        tournament_id: int,
        discord_id: str,
    ) -> Match | None:
        """
        Retourne le prochain match jouable d'un joueur.

        Contrairement à get_player_active_match(),
        cette méthode privilégie les vrais matchs avec deux joueurs.
        """

        row = await self.fetchone(
            """
            SELECT *
            FROM matches
            WHERE tournament_id = ?
            AND (
                player1_id = ?
                OR player2_id = ?
            )
            AND player1_id IS NOT NULL
            AND player2_id IS NOT NULL
            AND status IN ('waiting', 'playing')
            ORDER BY round DESC, match_number ASC
            LIMIT 1
            """,
            (
                tournament_id,
                discord_id,
                discord_id,
            ),
        )

        if row is None:
            return None

        return Match.from_row(row)

    async def get_open_match_slot(
        self,
        match_id: int,
    ) -> int | None:
        """
        Retourne le premier slot libre d'un match.

        Retour :
        - 1 si player1 est vide
        - 2 si player2 est vide
        - None si le match est complet
        """

        match = await self.get_match(match_id)

        if match is None:
            raise ValueError("Match introuvable.")

        if match.player1_id is None:
            return 1

        if match.player2_id is None:
            return 2

        return None

    async def has_matches(
        self,
        tournament_id: int,
    ) -> bool:
        """
        Vérifie si un tournoi possède déjà un bracket.
        """

        value = await self.fetchval(
            """
            SELECT 1
            FROM matches
            WHERE tournament_id = ?
            LIMIT 1
            """,
            (tournament_id,),
        )

        return value is not None
    # ==========================================================
    # STATISTIQUES
    # ==========================================================

    async def record_match_stats(
        self,
        match: Match,
        guild_id: str,
    ) -> None:
        """
        Enregistre les statistiques d'un match terminé.

        Ajoute :
        - 1 victoire au gagnant
        - 1 défaite au perdant

        Attention :
        cette méthode doit être appelée uniquement une fois,
        au moment où le match est validé.
        """

        if match.status != MatchStatus.COMPLETED:
            raise ValueError(
                "Impossible d'enregistrer les stats d'un match non terminé."
            )

        if not match.winner_id:
            raise ValueError(
                "Impossible d'enregistrer les stats : aucun vainqueur."
            )

        if not match.player1_id or not match.player2_id:
            # Les BYE ne comptent pas comme une vraie victoire jouée.
            return

        if match.winner_id == match.player1_id:

            loser_id = match.player2_id

        elif match.winner_id == match.player2_id:

            loser_id = match.player1_id

        else:

            raise ValueError(
                "Le vainqueur ne correspond à aucun joueur du match."
            )

        await self.add_player_win(
            match.winner_id,
            guild_id,
        )

        await self.add_player_loss(
            loser_id,
            guild_id,
        )

    async def record_match_stats_by_id(
        self,
        match_id: int,
        guild_id: str,
    ) -> None:
        """
        Version pratique de record_match_stats() avec l'ID du match.
        """

        match = await self.get_match(match_id)

        if match is None:
            raise ValueError("Match introuvable.")

        await self.record_match_stats(
            match,
            guild_id,
        )

    async def mark_tournament_players_as_played(
        self,
        tournament_id: int,
        guild_id: str,
    ) -> None:
        """
        Ajoute +1 tournoi joué à tous les inscrits actifs.
        """

        registrations = await self.list_registrations(
            tournament_id,
            include_dropped=False,
            include_disqualified=False,
        )

        for registration in registrations:

            await self.add_tournament_played(
                registration.discord_id,
                guild_id,
            )

    async def mark_tournament_winner(
        self,
        winner_id: str,
        guild_id: str,
    ) -> None:
        """
        Ajoute +1 tournoi gagné au vainqueur.
        """

        await self.add_tournament_won(
            winner_id,
            guild_id,
        )

    async def get_leaderboard(
        self,
        guild_id: str,
        limit: int = 10,
    ) -> list[Player]:
        """
        Retourne le classement des joueurs du serveur.
        """

        rows = await self.fetchall(
            """
            SELECT *
            FROM players
            WHERE guild_id = ?
            ORDER BY
                tournaments_won DESC,
                wins DESC,
                losses ASC,
                username ASC
            LIMIT ?
            """,
            (
                guild_id,
                limit,
            ),
        )

        return [
            Player.from_row(row)
            for row in rows
        ]

    async def get_player_rank(
        self,
        discord_id: str,
        guild_id: str,
    ) -> int | None:
        """
        Retourne le rang d'un joueur dans le classement.
        """

        players = await self.list_players(guild_id)

        for index, player in enumerate(players, start=1):

            if player.discord_id == discord_id:
                return index

        return None

    # ==========================================================
    # FINALISATION TOURNOI
    # ==========================================================

    async def finalize_tournament_from_matches(
        self,
        tournament_id: int,
        guild_id: str,
    ) -> Tournament:
        """
        Termine un tournoi à partir de la finale.

        Cette méthode :
        - vérifie que la finale est terminée ;
        - récupère le vainqueur ;
        - met le tournoi en FINISHED ;
        - ajoute +1 tournoi joué aux participants ;
        - ajoute +1 tournoi gagné au vainqueur.
        """

        tournament = await self.get_tournament(tournament_id)

        if tournament is None:
            raise ValueError("Tournoi introuvable.")

        if tournament.status == TournamentStatus.FINISHED:
            return tournament

        winner = await self.get_tournament_winner_from_matches(
            tournament_id
        )

        if winner is None:
            raise ValueError(
                "Impossible de terminer le tournoi : la finale n'est pas terminée."
            )

        winner_id, winner_name = winner

        await self.finish_tournament(
            tournament_id=tournament_id,
            winner_id=winner_id,
            winner_name=winner_name,
        )

        await self.mark_tournament_players_as_played(
            tournament_id,
            guild_id,
        )

        await self.mark_tournament_winner(
            winner_id,
            guild_id,
        )

        updated = await self.get_tournament(tournament_id)

        if updated is None:
            raise RuntimeError(
                "Le tournoi a été terminé, mais impossible de le récupérer."
            )

        return updated

    # ==========================================================
    # METADATA
    # ==========================================================

    async def get_metadata(
        self,
        key: str,
    ) -> str | None:
        """
        Récupère une valeur dans la table metadata.
        """

        value = await self.fetchval(
            """
            SELECT value
            FROM metadata
            WHERE key = ?
            """,
            (key,),
        )

        if value is None:
            return None

        return str(value)

    async def set_metadata(
        self,
        key: str,
        value: str,
    ) -> None:
        """
        Ajoute ou modifie une valeur dans metadata.
        """

        await self.update(
            """
            INSERT INTO metadata (
                key,
                value
            )
            VALUES (?, ?)

            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value
            """,
            (
                key,
                value,
            ),
        )

    async def get_database_version(self) -> int:
        """
        Retourne la version actuelle de la base.
        """

        value = await self.get_metadata("db_version")

        if value is None:
            return 0

        return int(value)

    # ==========================================================
    # DEBUG / SANTÉ
    # ==========================================================

    async def health_check(self) -> bool:
        """
        Vérifie rapidement que SQLite répond.
        """

        value = await self.fetchval(
            """
            SELECT 1
            """
        )

        return value == 1


