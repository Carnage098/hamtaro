from __future__ import annotations

import aiosqlite

from config import DATABASE


class BaseService:
    """
    Service de base.

    Tous les autres services héritent de cette classe afin
    d'utiliser les mêmes méthodes d'accès à la base de données.
    """

    def __init__(self):

        self.database = DATABASE

    # ==========================================================
    # CONNEXION
    # ==========================================================

    async def connect(self) -> aiosqlite.Connection:

        db = await aiosqlite.connect(self.database)

        db.row_factory = aiosqlite.Row

        return db

    # ==========================================================
    # EXECUTE
    # ==========================================================

    async def execute(
        self,
        query: str,
        params: tuple = ()
    ):

        async with await self.connect() as db:

            cursor = await db.execute(
                query,
                params
            )

            await db.commit()

            return cursor

    # ==========================================================
    # FETCH ONE
    # ==========================================================

    async def fetchone(
        self,
        query: str,
        params: tuple = ()
    ):

        async with await self.connect() as db:

            cursor = await db.execute(
                query,
                params
            )

            return await cursor.fetchone()

    # ==========================================================
    # FETCH ALL
    # ==========================================================

    async def fetchall(
        self,
        query: str,
        params: tuple = ()
    ):

        async with await self.connect() as db:

            cursor = await db.execute(
                query,
                params
            )

            return await cursor.fetchall()

    # ==========================================================
    # EXISTS
    # ==========================================================

    async def exists(
        self,
        query: str,
        params: tuple = ()
    ) -> bool:

        row = await self.fetchone(
            query,
            params
        )

        return row is not None

    # ==========================================================
    # COUNT
    # ==========================================================

    async def count(
        self,
        query: str,
        params: tuple = ()
    ) -> int:

        row = await self.fetchone(
            query,
            params
        )

        if row is None:
            return 0

        return row[0]
