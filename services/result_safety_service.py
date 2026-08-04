from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class ResultSafetyError(ValueError):
    pass


class ResultSafetyService:
    """Verrous et vérifications communs aux opérations sensibles de résultat."""

    _locks: dict[tuple[str, int], asyncio.Lock] = {}

    def __init__(self, db) -> None:
        self.db = db

    def _lock(self, match_kind: str, match_id: int) -> asyncio.Lock:
        key = (match_kind, int(match_id))
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def ensure_match_can_change(
        self,
        *,
        match_kind: str,
        match_id: int,
    ) -> dict:
        if match_kind == "bracket":
            row = await self.db.fetchone(
                "SELECT * FROM matches WHERE id = ?",
                (match_id,),
            )
            allowed = {"waiting", "playing", "reported"}
        elif match_kind == "swiss":
            row = await self.db.fetchone(
                "SELECT * FROM swiss_matches WHERE id = ?",
                (match_id,),
            )
            allowed = {"pending"}
        else:
            raise ResultSafetyError("Type de match invalide.")

        if row is None:
            raise ResultSafetyError("Match introuvable.")
        data = dict(row)
        if str(data.get("status")) not in allowed:
            raise ResultSafetyError(
                "Ce match est déjà terminé, annulé ou verrouillé. "
                "Utilise l'annulation sécurisée avant de le modifier."
            )
        if data.get("player1_id") and data.get("player1_id") == data.get("player2_id"):
            raise ResultSafetyError("Le match contient deux fois le même joueur.")
        return data

    @asynccontextmanager
    async def operation(
        self,
        *,
        match_kind: str,
        match_id: int,
        action: str,
        actor_id: str,
    ) -> AsyncIterator[dict]:
        lock = self._lock(match_kind, match_id)
        async with lock:
            match = await self.ensure_match_can_change(
                match_kind=match_kind,
                match_id=match_id,
            )
            conn = self.db._connection()
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await conn.execute(
                    """
                    INSERT INTO result_operation_log (
                        match_kind, match_id, action, actor_id, status
                    )
                    VALUES (?, ?, ?, ?, 'processing')
                    """,
                    (match_kind, match_id, action, actor_id),
                )
                operation_id = int(cursor.lastrowid)
                yield match
            except Exception:
                await conn.rollback()
                raise
            else:
                await conn.execute(
                    """
                    UPDATE result_operation_log
                    SET status = 'completed', finished_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (operation_id,),
                )
                await conn.commit()
