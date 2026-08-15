from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite

try:
    from config import DATABASE, SQLITE_BUSY_TIMEOUT_MS
except ImportError:  # fallback local / anciens builds
    from database import DATABASE
    SQLITE_BUSY_TIMEOUT_MS = 5000


class TrophyAwardService:
    """Persistance des attributions de trophées Hamtaro.

    Le catalogue JSON décrit le trophée lui-même.
    Cette table SQLite décrit qui l'a remporté et dans quel tournoi.
    """

    FIRST_TROPHY_ID = "HT-001"

    def __init__(
        self,
        bot: Any | None = None,
        *,
        database_path: str | Path | None = None,
    ) -> None:
        self.bot = bot
        self.database_path = str(database_path or DATABASE)

    async def _connect(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(
            self.database_path,
            timeout=max(1.0, float(SQLITE_BUSY_TIMEOUT_MS) / 1000.0),
        )
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(f"PRAGMA busy_timeout = {int(SQLITE_BUSY_TIMEOUT_MS)};")
        return db

    async def ensure_schema(self) -> None:
        db = await self._connect()
        try:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS trophy_awards (
                    trophy_id TEXT PRIMARY KEY COLLATE NOCASE,
                    discord_id TEXT NOT NULL,
                    holder_name TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    tournament_id INTEGER NOT NULL,
                    tournament_name TEXT NOT NULL,
                    deck TEXT,
                    format TEXT,
                    awarded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trophy_awards_discord
                ON trophy_awards(discord_id)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trophy_awards_tournament
                ON trophy_awards(tournament_id)
                """
            )
            await db.commit()
        finally:
            await db.close()

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    async def get_award(self, trophy_id: str) -> dict[str, Any] | None:
        await self.ensure_schema()
        db = await self._connect()
        try:
            cursor = await db.execute(
                """
                SELECT *
                FROM trophy_awards
                WHERE UPPER(trophy_id) = UPPER(?)
                LIMIT 1
                """,
                (str(trophy_id),),
            )
            return self._row_to_dict(await cursor.fetchone())
        finally:
            await db.close()

    async def all_awards(self) -> dict[str, dict[str, Any]]:
        await self.ensure_schema()
        db = await self._connect()
        try:
            cursor = await db.execute(
                """
                SELECT *
                FROM trophy_awards
                ORDER BY awarded_at ASC, trophy_id ASC
                """
            )
            rows = await cursor.fetchall()
            return {
                str(row["trophy_id"]).upper(): self._row_to_dict(row) or {}
                for row in rows
            }
        finally:
            await db.close()

    async def award_ht001_first_champion(
        self,
        *,
        tournament_id: int,
        winner_id: str,
        winner_name: str,
    ) -> dict[str, Any]:
        """Attribue HT-001 une seule fois.

        INSERT OR IGNORE + PRIMARY KEY(trophy_id) rendent l'opération idempotente :
        relancer /end_tournament ne peut jamais changer le propriétaire de HT-001.
        """

        trophy_id = self.FIRST_TROPHY_ID
        winner_id = str(winner_id or "").strip()
        winner_name = str(winner_name or "").strip()

        if not winner_id or not winner_name:
            raise ValueError("Impossible d'attribuer HT-001 sans vainqueur valide.")

        await self.ensure_schema()
        db = await self._connect()
        try:
            await db.execute("BEGIN IMMEDIATE")

            existing_cursor = await db.execute(
                "SELECT * FROM trophy_awards WHERE trophy_id = ? LIMIT 1",
                (trophy_id,),
            )
            existing = await existing_cursor.fetchone()
            if existing is not None:
                await db.commit()
                result = self._row_to_dict(existing) or {}
                result["newly_awarded"] = False
                return result

            tournament_cursor = await db.execute(
                """
                SELECT
                    id,
                    guild_id,
                    name,
                    format,
                    finished_at
                FROM tournaments
                WHERE id = ?
                LIMIT 1
                """,
                (int(tournament_id),),
            )
            tournament = await tournament_cursor.fetchone()
            if tournament is None:
                await db.rollback()
                raise ValueError(f"Tournoi {tournament_id} introuvable.")

            deck_cursor = await db.execute(
                """
                SELECT deck
                FROM registrations
                WHERE tournament_id = ?
                  AND discord_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(tournament_id), winner_id),
            )
            deck_row = await deck_cursor.fetchone()
            deck = (
                str(deck_row["deck"]).strip()
                if deck_row is not None and deck_row["deck"] is not None
                else None
            )
            if deck == "":
                deck = None

            await db.execute(
                """
                INSERT OR IGNORE INTO trophy_awards (
                    trophy_id,
                    discord_id,
                    holder_name,
                    guild_id,
                    tournament_id,
                    tournament_name,
                    deck,
                    format,
                    awarded_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    COALESCE(?, CURRENT_TIMESTAMP)
                )
                """,
                (
                    trophy_id,
                    winner_id,
                    winner_name,
                    str(tournament["guild_id"]),
                    int(tournament["id"]),
                    str(tournament["name"]),
                    deck,
                    str(tournament["format"]),
                    tournament["finished_at"],
                ),
            )

            changes_cursor = await db.execute("SELECT changes()")
            inserted = int((await changes_cursor.fetchone())[0]) > 0

            final_cursor = await db.execute(
                "SELECT * FROM trophy_awards WHERE trophy_id = ? LIMIT 1",
                (trophy_id,),
            )
            final_row = await final_cursor.fetchone()
            await db.commit()

            result = self._row_to_dict(final_row) or {}
            result["newly_awarded"] = inserted
            return result
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass
            raise
        finally:
            await db.close()
