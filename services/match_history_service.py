from __future__ import annotations

import aiosqlite

from config import DATABASE


class MatchHistoryService:

    async def init_table(self):
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS match_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    guild_id TEXT NOT NULL,
                    tournament_id INTEGER NOT NULL,

                    match_id INTEGER,
                    round_number INTEGER,

                    player1_id TEXT,
                    player1_name TEXT,

                    player2_id TEXT,
                    player2_name TEXT,

                    winner_id TEXT,
                    winner_name TEXT,

                    score TEXT,

                    player1_deck TEXT,
                    player2_deck TEXT,

                    status TEXT DEFAULT 'approved',

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_match_history_tournament
                ON match_history(tournament_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_match_history_players
                ON match_history(player1_id, player2_id, winner_id)
            """)

            await db.commit()

    async def record_match(
        self,
        guild_id: str,
        tournament_id: int,
        match_id: int | None,
        round_number: int | None,
        player1_id: str | None,
        player1_name: str | None,
        player2_id: str | None,
        player2_name: str | None,
        winner_id: str | None,
        winner_name: str | None,
        score: str | None = None,
        player1_deck: str | None = None,
        player2_deck: str | None = None,
        status: str = "approved",
    ):
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("""
                INSERT INTO match_history (
                    guild_id,
                    tournament_id,
                    match_id,
                    round_number,
                    player1_id,
                    player1_name,
                    player2_id,
                    player2_name,
                    winner_id,
                    winner_name,
                    score,
                    player1_deck,
                    player2_deck,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                guild_id,
                tournament_id,
                match_id,
                round_number,
                player1_id,
                player1_name,
                player2_id,
                player2_name,
                winner_id,
                winner_name,
                score,
                player1_deck,
                player2_deck,
                status,
            ))

            await db.commit()

    async def list_tournament_history(
        self,
        tournament_id: int,
        limit: int = 20,
    ):
        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT *
                FROM match_history
                WHERE tournament_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (
                tournament_id,
                limit,
            ))

            return await cursor.fetchall()

    async def list_player_history(
        self,
        guild_id: str,
        player_id: str,
        limit: int = 20,
    ):
        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT *
                FROM match_history
                WHERE guild_id = ?
                AND (
                    player1_id = ?
                    OR player2_id = ?
                    OR winner_id = ?
                )
                ORDER BY id DESC
                LIMIT ?
            """, (
                guild_id,
                player_id,
                player_id,
                player_id,
                limit,
            ))

            return await cursor.fetchall()

    async def get_match_history(
        self,
        tournament_id: int,
        match_id: int,
    ):
        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT *
                FROM match_history
                WHERE tournament_id = ?
                AND match_id = ?
                ORDER BY id DESC
            """, (
                tournament_id,
                match_id,
            ))

            return await cursor.fetchall()

    async def count_player_wins(
        self,
        guild_id: str,
        player_id: str,
    ) -> int:
        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute("""
                SELECT COUNT(*)
                FROM match_history
                WHERE guild_id = ?
                AND winner_id = ?
                AND status = 'approved'
            """, (
                guild_id,
                player_id,
            ))

            row = await cursor.fetchone()

            return int(row[0] or 0)

    async def count_player_matches(
        self,
        guild_id: str,
        player_id: str,
    ) -> int:
        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute("""
                SELECT COUNT(*)
                FROM match_history
                WHERE guild_id = ?
                AND (
                    player1_id = ?
                    OR player2_id = ?
                )
                AND status = 'approved'
            """, (
                guild_id,
                player_id,
                player_id,
            ))

            row = await cursor.fetchone()

            return int(row[0] or 0)
