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

        async with aiosqlite.connect(DATABASE) as db:

            # Vérifie que le joueur n'est pas déjà inscrit
            cursor = await db.execute(
                """
                SELECT id
                FROM registrations
                WHERE tournament_id=?
                AND discord_id=?
                """,
                (
                    tournament_id,
                    discord_id
                )
            )

            if await cursor.fetchone():
                raise ValueError(
                    "Ce joueur est déjà inscrit."
                )

            await db.execute(
                """
                INSERT INTO registrations(

                    tournament_id,

                    discord_id,

                    username,

                    deck

                )

                VALUES(?,?,?,?)
                """,
                (
                    tournament_id,
                    discord_id,
                    username,
                    deck
                )
            )

            await db.commit()

            cursor = await db.execute(
                """
                SELECT last_insert_rowid()
                """
            )

            registration_id = (
                await cursor.fetchone()
            )[0]

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

    async def players(
        self,
        tournament_id: int
    ):

        async with aiosqlite.connect(DATABASE) as db:

            cursor = await db.execute(
                """
                SELECT *

                FROM registrations

                WHERE tournament_id=?

                ORDER BY username
                """,
                (
                    tournament_id,
                )
            )

            return await cursor.fetchall()

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
                (
                    tournament_id,
                )
            )

            return (
                await cursor.fetchone()
            )[0]

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

            return (
                await cursor.fetchone()
            ) is not None

    async def is_full(
        self,
        tournament_id: int
    ) -> bool:

        async with aiosqlite.connect(DATABASE) as db:

            cursor = await db.execute(
                """
                SELECT max_players

                FROM tournaments

                WHERE id=?
                """,
                (
                    tournament_id,
                )
            )

            tournament = await cursor.fetchone()

            if tournament is None:
                return False

            max_players = tournament[0]

            cursor = await db.execute(
                """
                SELECT COUNT(*)

                FROM registrations

                WHERE tournament_id=?
                """,
                (
                    tournament_id,
                )
            )

            registered = (
                await cursor.fetchone()
            )[0]

            return registered >= max_players
