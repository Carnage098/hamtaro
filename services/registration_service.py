import aiosqlite

from config import DATABASE
from models.registration import Registration


class RegistrationService:

    async def register(
        self,
        tournament_id: int,
        discord_id: str,
        username: str,
        deck: str
    ) -> Registration:

        if await self.is_registered(tournament_id, discord_id):
            raise ValueError("Le joueur est déjà inscrit.")

        async with aiosqlite.connect(DATABASE) as db:

            cursor = await db.execute(
                """
                INSERT INTO registrations(
                    tournament_id,
                    discord_id,
                    username,
                    deck
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    tournament_id,
                    discord_id,
                    username,
                    deck
                )
            )

            await db.commit()

            registration_id = cursor.lastrowid

        return Registration(
            id=registration_id,
            tournament_id=tournament_id,
            discord_id=discord_id,
            username=username,
            deck=deck
        )

    async def unregister(
        self,
        tournament_id: int,
        discord_id: str
    ):

        async with aiosqlite.connect(DATABASE) as db:

            await db.execute(
                """
                DELETE FROM registrations
                WHERE tournament_id=?
                AND discord_id=?
                """,
                (
                    tournament_id,
                    discord_id
                )
            )

            await db.commit()

    async def get_players(
        self,
        tournament_id: int
    ) -> list[Registration]:

        registrations = []

        async with aiosqlite.connect(DATABASE) as db:

            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM registrations
                WHERE tournament_id=?
                ORDER BY username
                """,
                (tournament_id,)
            )

            rows = await cursor.fetchall()

        for row in rows:

            registrations.append(
                Registration(**dict(row))
            )

        return registrations

    async def count(
        self,
        tournament_id: int
    ) -> int:

        async with aiosqlite.connect(DATABASE) as db:

            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM registrations
                WHERE tournament_id=?
                """,
                (tournament_id,)
            )

            return (await cursor.fetchone())[0]

    async def is_registered(
        self,
        tournament_id: int,
        discord_id: str
    ) -> bool:

        async with aiosqlite.connect(DATABASE) as db:

            cursor = await db.execute(
                """
                SELECT 1
                FROM registrations
                WHERE tournament_id=?
                AND discord_id=?
                """,
                (
                    tournament_id,
                    discord_id
                )
            )

            return await cursor.fetchone() is not None

    async def clear(
        self,
        tournament_id: int
    ):

        async with aiosqlite.connect(DATABASE) as db:

            await db.execute(
                """
                DELETE FROM registrations
                WHERE tournament_id=?
                """,
                (tournament_id,)
            )

            await db.commit()
