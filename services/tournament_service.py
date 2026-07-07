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
                "Nombre de joueurs invalide."
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
    ) -> Tournament | None:

        async with aiosqlite.connect(DATABASE) as db:

            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM tournaments
                WHERE id=?
                """,
                (tournament_id,)
            )

            row = await cursor.fetchone()

        if row is None:
            return None

        return Tournament(**dict(row))

    async def get_by_code(
        self,
        code: str
    ) -> Tournament | None:

        async with aiosqlite.connect(DATABASE) as db:

            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM tournaments
                WHERE code=?
                """,
                (code,)
            )

            row = await cursor.fetchone()

        if row is None:
            return None

        return Tournament(**dict(row))

    async def list(
        self,
        guild_id: str
    ) -> list[Tournament]:

        tournaments = []

        async with aiosqlite.connect(DATABASE) as db:

            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM tournaments
                WHERE guild_id=?
                ORDER BY created_at DESC
                """,
                (guild_id,)
            )

            rows = await cursor.fetchall()

        for row in rows:

            tournaments.append(
                Tournament(**dict(row))
            )

        return tournaments

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
                (tournament_id,)
            )

            await db.commit()

    async def update_status(
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

                    status='finished',

                    winner_id=?

                WHERE id=?
                """,
                (
                    winner_id,
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

    async def _generate_code(
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

        random_code = "".join(
            random.choices(
                string.digits,
                k=4
            )
        )

        return f"{prefix}-{random_code}"
