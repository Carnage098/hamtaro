from __future__ import annotations



import aiosqlite

from config import DATABASE

from models.player import Player
from models.match import Match
from models.tournament import Tournament


class DatabaseService:

    def __init__(self):

        self.conn: aiosqlite.Connection | None = None

    async def connect(self):

        if self.conn is not None:
            return

        self.conn = await aiosqlite.connect(DATABASE)

        self.conn.row_factory = aiosqlite.Row

        await self.conn.execute(
            "PRAGMA foreign_keys = ON;"
        )

    async def close(self):

        if self.conn is None:
            return

        await self.conn.close()

        self.conn = None

    async def commit(self):

        await self.conn.commit()

    async def rollback(self):

        await self.conn.rollback()

    async def execute(
        self,
        query: str,
        parameters: tuple = (),
    ):

        return await self.conn.execute(
            query,
            parameters,
        )

    async def fetchone(
        self,
        query: str,
        parameters: tuple = (),
    ):

        cursor = await self.conn.execute(
            query,
            parameters,
        )

        return await cursor.fetchone()

    async def fetchall(
        self,
        query: str,
        parameters: tuple = (),
    ):

        cursor = await self.conn.execute(
            query,
            parameters,
        )

        return await cursor.fetchall()


