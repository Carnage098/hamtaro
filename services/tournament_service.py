import random
import string
import aiosqlite

from config import DATABASE
from models.tournament import Tournament


class TournamentService:

    async def create(
        self,
        guild_id: str,
        name: str,
        format: str,
        max_players: int
    ) -> Tournament:

        if max_players not in [4, 8, 16, 32, 64]:
            raise ValueError(
                "Le nombre de joueurs doit être 4, 8, 16, 32 ou 64."
            )

        code = await self.generate_code(format)

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

                VALUES(?,?,?,?,?,?)
                """,
                (
                    guild_id,
                    code,
                    name,
                    format,
                    max_players,
                    "registration"
                )
            )

            await db.commit()

            tournament_id = cursor.lastrowid

        return Tournament(
            id=tournament_id,
            guild_id=guild_id,
            code=code,
            name=name,
            format=format,
            max_players=max_players,
            status="registration"
        )

    async def get(
        self,
        tournament_id: int
    ):

        async with aiosqlite.connect(DATABASE) as db:

            cursor = await db.execute(
                """
                SELECT *

                FROM tournaments

                WHERE id = ?
                """,
                (
                    tournament_id,
                )
            )

            row = await cursor.fetchone()

        return row

    async def get_by_code(
        self,
        code: str
    ):

        async with aiosqlite.connect(DATABASE) as db:

            cursor = await db.execute(
                """
                SELECT *

                FROM tournaments

                WHERE code = ?
                """,
                (
                    code,
                )
            )

            return await cursor.fetchone()

    async def list(
        self,
        guild_id: str
    ):

        async with aiosqlite.connect(DATABASE) as db:

            cursor = await db.execute(
                """
                SELECT *

                FROM tournaments

                WHERE guild_id=?

                ORDER BY created_at DESC
                """,
                (
                    guild_id,
                )
            )

            return await cursor.fetchall()

    async def delete(
        self,
        tournament_id: int
    ):

        async with aiosqlite.connect(DATABASE) as db:

            await db.execute(
                """
                DELETE FROM tournaments

                WHERE id=?
                """,
                (
                    tournament_id,
                )
            )

            await db.commit()

    async def open_registration(
        self,
        tournament_id: int
    ):

        await self.change_status(
            tournament_id,
            "registration"
        )

    async def close_registration(
        self,
        tournament_id: int
    ):

        await self.change_status(
            tournament_id,
            "closed"
        )

    async def start(
        self,
        tournament_id: int
    ):

        await self.change_status(
            tournament_id,
            "running"
        )

    async def finish(
        self,
        tournament_id: int,
        winner_id: str
    ):

        async with aiosqlite.connect(DATABASE) as db:

            await db.execute(
                """
                UPDATE tournaments

                SET

                status=?,

                winner_id=?

                WHERE id=?
                """,
                (
                    "finished",
                    winner_id,
                    tournament_id
                )
            )

            await db.commit()

    async def change_status(
        self,
        tournament_id: int,
        status: str
    ):

        async with aiosqlite.connect(DATABASE) as db:

            await db.execute(
                """
                UPDATE tournaments

                SET status=?

                WHERE id=?
                """,
                (
                    status,
                    tournament_id
                )
            )

            await db.commit()

    async def exists(
        self,
        tournament_id: int
    ) -> bool:

        tournament = await self.get(
            tournament_id
        )

        return tournament is not None

    async def generate_code(
        self,
        format: str
    ) -> str:

        prefixes = {

            "Format Actuel": "TCG",

            "Master Duel": "MD",

            "Genesys": "GEN",

            "GOAT": "GOAT",

            "Edison": "EDI",

            "HAT": "HAT",

            "Rush Duel": "RD",

            "Speed Duel": "SD"

        }

        prefix = prefixes.get(
            format,
            "T"
        )

        random_part = "".join(

            random.choices(

                string.digits,

                k=4

            )

        )

        return f"{prefix}-{random_part}"
