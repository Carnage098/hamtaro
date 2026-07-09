from __future__ import annotations

import aiosqlite

from config import DATABASE


class AdminLogService:

    async def init_table(self):
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    guild_id TEXT NOT NULL,

                    actor_id TEXT NOT NULL,
                    actor_name TEXT NOT NULL,

                    action TEXT NOT NULL,

                    target_id TEXT,
                    target_name TEXT,

                    tournament_id INTEGER,
                    tournament_name TEXT,

                    details TEXT,

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_admin_logs_guild
                ON admin_logs(guild_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_admin_logs_tournament
                ON admin_logs(tournament_id)
            """)

            await db.commit()

    async def record(
        self,
        guild_id: str,
        actor_id: str,
        actor_name: str,
        action: str,
        target_id: str | None = None,
        target_name: str | None = None,
        tournament_id: int | None = None,
        tournament_name: str | None = None,
        details: str | None = None,
    ):
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("""
                INSERT INTO admin_logs (
                    guild_id,
                    actor_id,
                    actor_name,
                    action,
                    target_id,
                    target_name,
                    tournament_id,
                    tournament_name,
                    details
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                guild_id,
                actor_id,
                actor_name,
                action,
                target_id,
                target_name,
                tournament_id,
                tournament_name,
                details,
            ))

            await db.commit()

    async def list_recent(
        self,
        guild_id: str,
        limit: int = 15,
    ):
        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT *
                FROM admin_logs
                WHERE guild_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (
                guild_id,
                limit,
            ))

            return await cursor.fetchall()
