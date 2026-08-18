from __future__ import annotations

import aiosqlite
from typing import Any

from config import DATABASE, SQLITE_BUSY_TIMEOUT_MS


class BossService:
    """Stockage et logique persistante du format Boss Hamtaro."""

    async def _connect(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(
            str(DATABASE),
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
        )
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")
        return db

    async def ensure_schema(self) -> None:
        db = await self._connect()
        try:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS boss_state (
                    guild_id TEXT PRIMARY KEY,
                    boss_id TEXT,
                    boss_name TEXT,
                    successor_id TEXT,
                    successor_name TEXT,
                    status TEXT NOT NULL DEFAULT 'idle',
                    registrations_open INTEGER NOT NULL DEFAULT 0,
                    week_number INTEGER NOT NULL DEFAULT 1,
                    wins_current INTEGER NOT NULL DEFAULT 0,
                    reign_started_at TIMESTAMP,
                    announcement_channel_id TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS boss_challengers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    week_number INTEGER NOT NULL,
                    discord_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    scheduled_at TEXT,
                    status TEXT NOT NULL DEFAULT 'registered',
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, week_number, discord_id)
                );

                CREATE TABLE IF NOT EXISTS boss_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    week_number INTEGER NOT NULL,
                    challenger_id INTEGER,
                    challenger_discord_id TEXT NOT NULL,
                    challenger_name TEXT NOT NULL,
                    boss_id TEXT NOT NULL,
                    boss_name TEXT NOT NULL,
                    scheduled_at TEXT,
                    winner_id TEXT NOT NULL,
                    winner_name TEXT NOT NULL,
                    boss_won INTEGER NOT NULL DEFAULT 0,
                    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS boss_reigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    boss_id TEXT NOT NULL,
                    boss_name TEXT NOT NULL,
                    started_week INTEGER NOT NULL,
                    ended_week INTEGER,
                    wins INTEGER NOT NULL DEFAULT 0,
                    defeated_by_id TEXT,
                    defeated_by_name TEXT,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_boss_challengers_week
                    ON boss_challengers(guild_id, week_number, position);
                CREATE INDEX IF NOT EXISTS idx_boss_matches_week
                    ON boss_matches(guild_id, week_number, played_at);
                CREATE INDEX IF NOT EXISTS idx_boss_reigns_guild
                    ON boss_reigns(guild_id, id DESC);
                """
            )
            await db.commit()
        finally:
            await db.close()

    async def _ensure_state(self, db: aiosqlite.Connection, guild_id: str) -> None:
        await db.execute(
            "INSERT OR IGNORE INTO boss_state(guild_id) VALUES(?)",
            (guild_id,),
        )

    async def state(self, guild_id: str) -> dict[str, Any]:
        await self.ensure_schema()
        db = await self._connect()
        try:
            await self._ensure_state(db, guild_id)
            await db.commit()
            cur = await db.execute(
                "SELECT * FROM boss_state WHERE guild_id = ?",
                (guild_id,),
            )
            row = await cur.fetchone()
            return dict(row)
        finally:
            await db.close()

    async def set_boss(self, guild_id: str, boss_id: str, boss_name: str) -> dict[str, Any]:
        await self.ensure_schema()
        db = await self._connect()
        try:
            await self._ensure_state(db, guild_id)
            cur = await db.execute(
                "SELECT * FROM boss_state WHERE guild_id = ?",
                (guild_id,),
            )
            current = await cur.fetchone()
            week_number = int(current["week_number"] or 1) if current else 1

            if current and current["boss_id"] and str(current["boss_id"]) != str(boss_id):
                await db.execute(
                    """
                    UPDATE boss_reigns
                    SET ended_week = ?, wins = ?, ended_at = CURRENT_TIMESTAMP
                    WHERE id = (
                        SELECT id FROM boss_reigns
                        WHERE guild_id = ? AND ended_at IS NULL
                        ORDER BY id DESC LIMIT 1
                    )
                    """,
                    (week_number, int(current["wins_current"] or 0), guild_id),
                )

            await db.execute(
                """
                UPDATE boss_state
                SET boss_id = ?, boss_name = ?,
                    successor_id = NULL, successor_name = NULL,
                    status = 'active', wins_current = 0,
                    reign_started_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                (boss_id, boss_name, guild_id),
            )
            await db.execute(
                """
                INSERT INTO boss_reigns(guild_id, boss_id, boss_name, started_week)
                VALUES(?, ?, ?, ?)
                """,
                (guild_id, boss_id, boss_name, week_number),
            )
            await db.commit()
        finally:
            await db.close()
        return await self.state(guild_id)

    async def set_registrations(self, guild_id: str, opened: bool) -> dict[str, Any]:
        await self.ensure_schema()
        db = await self._connect()
        try:
            await self._ensure_state(db, guild_id)
            await db.execute(
                """
                UPDATE boss_state
                SET registrations_open = ?, updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                (1 if opened else 0, guild_id),
            )
            await db.commit()
        finally:
            await db.close()
        return await self.state(guild_id)

    async def set_announcement_channel(self, guild_id: str, channel_id: str | None) -> None:
        await self.ensure_schema()
        db = await self._connect()
        try:
            await self._ensure_state(db, guild_id)
            await db.execute(
                """
                UPDATE boss_state
                SET announcement_channel_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                (channel_id, guild_id),
            )
            await db.commit()
        finally:
            await db.close()

    async def register_challenger(
        self,
        guild_id: str,
        discord_id: str,
        username: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        await self.ensure_schema()
        db = await self._connect()
        try:
            await self._ensure_state(db, guild_id)
            cur = await db.execute(
                "SELECT * FROM boss_state WHERE guild_id = ?",
                (guild_id,),
            )
            state = await cur.fetchone()
            if not state or not state["boss_id"]:
                raise ValueError("Aucun Boss n'est actuellement défini.")
            if str(state["boss_id"]) == str(discord_id):
                raise ValueError("Le Boss ne peut pas s'inscrire contre lui-même.")
            if not force and not int(state["registrations_open"] or 0):
                raise ValueError("Les inscriptions Boss sont actuellement fermées.")
            if str(state["status"]) == "defeated":
                raise ValueError("Le Boss est déjà tombé. Attends la prochaine semaine.")

            week_number = int(state["week_number"] or 1)
            cur = await db.execute(
                """
                SELECT id, status FROM boss_challengers
                WHERE guild_id = ? AND week_number = ? AND discord_id = ?
                """,
                (guild_id, week_number, discord_id),
            )
            existing = await cur.fetchone()
            if existing and str(existing["status"]) != "removed":
                raise ValueError("Ce joueur est déjà inscrit contre le Boss.")

            cur = await db.execute(
                """
                SELECT COALESCE(MAX(position), 0) + 1 AS next_position
                FROM boss_challengers
                WHERE guild_id = ? AND week_number = ? AND status != 'removed'
                """,
                (guild_id, week_number),
            )
            position = int((await cur.fetchone())["next_position"] or 1)

            if existing:
                await db.execute(
                    """
                    UPDATE boss_challengers
                    SET username = ?, position = ?, scheduled_at = NULL,
                        status = 'registered', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (username, position, int(existing["id"])),
                )
                challenger_id = int(existing["id"])
            else:
                cur = await db.execute(
                    """
                    INSERT INTO boss_challengers(
                        guild_id, week_number, discord_id, username, position
                    )
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (guild_id, week_number, discord_id, username, position),
                )
                challenger_id = int(cur.lastrowid)

            await db.commit()
            cur = await db.execute(
                "SELECT * FROM boss_challengers WHERE id = ?",
                (challenger_id,),
            )
            return dict(await cur.fetchone())
        finally:
            await db.close()

    async def unregister_challenger(
        self,
        guild_id: str,
        discord_id: str,
        *,
        force: bool = False,
    ) -> None:
        state = await self.state(guild_id)
        db = await self._connect()
        try:
            week_number = int(state["week_number"] or 1)
            cur = await db.execute(
                """
                SELECT * FROM boss_challengers
                WHERE guild_id = ? AND week_number = ? AND discord_id = ?
                """,
                (guild_id, week_number, discord_id),
            )
            row = await cur.fetchone()
            if not row or str(row["status"]) == "removed":
                raise ValueError("Ce joueur n'est pas inscrit cette semaine.")
            if not force and str(row["status"]) in {"defeated", "boss_killer"}:
                raise ValueError("Ce duel a déjà été joué.")
            await db.execute(
                """
                UPDATE boss_challengers
                SET status = 'removed', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(row["id"]),),
            )
            await db.commit()
        finally:
            await db.close()

    async def challengers(self, guild_id: str) -> list[dict[str, Any]]:
        state = await self.state(guild_id)
        db = await self._connect()
        try:
            cur = await db.execute(
                """
                SELECT * FROM boss_challengers
                WHERE guild_id = ? AND week_number = ? AND status != 'removed'
                ORDER BY position ASC, id ASC
                """,
                (guild_id, int(state["week_number"] or 1)),
            )
            return [dict(row) for row in await cur.fetchall()]
        finally:
            await db.close()

    async def challenger_by_discord(self, guild_id: str, discord_id: str) -> dict[str, Any] | None:
        state = await self.state(guild_id)
        db = await self._connect()
        try:
            cur = await db.execute(
                """
                SELECT * FROM boss_challengers
                WHERE guild_id = ? AND week_number = ? AND discord_id = ?
                  AND status != 'removed'
                LIMIT 1
                """,
                (guild_id, int(state["week_number"] or 1), discord_id),
            )
            row = await cur.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def challenger_by_id(self, guild_id: str, challenger_id: int) -> dict[str, Any] | None:
        state = await self.state(guild_id)
        db = await self._connect()
        try:
            cur = await db.execute(
                """
                SELECT * FROM boss_challengers
                WHERE guild_id = ? AND week_number = ? AND id = ?
                  AND status != 'removed'
                LIMIT 1
                """,
                (guild_id, int(state["week_number"] or 1), challenger_id),
            )
            row = await cur.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def move_challenger(self, guild_id: str, discord_id: str, new_position: int) -> None:
        if new_position < 1:
            raise ValueError("La position doit être supérieure ou égale à 1.")
        rows = await self.challengers(guild_id)
        target = next((r for r in rows if str(r["discord_id"]) == str(discord_id)), None)
        if target is None:
            raise ValueError("Ce joueur n'est pas inscrit cette semaine.")
        ordered = [r for r in rows if int(r["id"]) != int(target["id"])]
        ordered.insert(min(new_position - 1, len(ordered)), target)
        db = await self._connect()
        try:
            for position, row in enumerate(ordered, start=1):
                await db.execute(
                    "UPDATE boss_challengers SET position = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (position, int(row["id"])),
                )
            await db.commit()
        finally:
            await db.close()

    async def swap_challengers(self, guild_id: str, first_id: str, second_id: str) -> None:
        first = await self.challenger_by_discord(guild_id, first_id)
        second = await self.challenger_by_discord(guild_id, second_id)
        if not first or not second:
            raise ValueError("Les deux joueurs doivent être inscrits cette semaine.")
        db = await self._connect()
        try:
            await db.execute(
                "UPDATE boss_challengers SET position = ? WHERE id = ?",
                (int(second["position"]), int(first["id"])),
            )
            await db.execute(
                "UPDATE boss_challengers SET position = ? WHERE id = ?",
                (int(first["position"]), int(second["id"])),
            )
            await db.commit()
        finally:
            await db.close()

    async def schedule_challenger(
        self,
        guild_id: str,
        discord_id: str,
        scheduled_at: str,
    ) -> None:
        row = await self.challenger_by_discord(guild_id, discord_id)
        if not row:
            raise ValueError("Ce joueur n'est pas inscrit cette semaine.")
        if str(row["status"]) in {"defeated", "boss_killer"}:
            raise ValueError("Ce duel a déjà été joué.")
        value = str(scheduled_at or "").strip()
        if len(value) < 3:
            raise ValueError("Indique une date/heure lisible, par ex. Vendredi 20h30.")
        db = await self._connect()
        try:
            await db.execute(
                """
                UPDATE boss_challengers
                SET scheduled_at = ?, status = 'scheduled', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (value[:120], int(row["id"])),
            )
            await db.commit()
        finally:
            await db.close()

    async def record_result(
        self,
        guild_id: str,
        challenger_discord_id: str,
        winner_id: str,
        winner_name: str,
    ) -> dict[str, Any]:
        state = await self.state(guild_id)
        if not state.get("boss_id"):
            raise ValueError("Aucun Boss n'est défini.")
        if str(state.get("status")) == "defeated":
            raise ValueError("Le Boss est déjà tombé cette semaine.")

        challenger = await self.challenger_by_discord(guild_id, challenger_discord_id)
        if not challenger:
            raise ValueError("Ce challenger n'est pas inscrit cette semaine.")
        if str(challenger["status"]) in {"defeated", "boss_killer"}:
            raise ValueError("Le résultat de ce duel est déjà enregistré.")

        boss_id = str(state["boss_id"])
        if str(winner_id) not in {boss_id, str(challenger["discord_id"])}:
            raise ValueError("Le gagnant doit être le Boss ou le challenger concerné.")

        boss_won = str(winner_id) == boss_id
        db = await self._connect()
        try:
            await db.execute(
                """
                INSERT INTO boss_matches(
                    guild_id, week_number, challenger_id,
                    challenger_discord_id, challenger_name,
                    boss_id, boss_name, scheduled_at,
                    winner_id, winner_name, boss_won
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    int(state["week_number"] or 1),
                    int(challenger["id"]),
                    str(challenger["discord_id"]),
                    str(challenger["username"]),
                    boss_id,
                    str(state["boss_name"] or boss_id),
                    challenger.get("scheduled_at"),
                    str(winner_id),
                    winner_name,
                    1 if boss_won else 0,
                ),
            )
            if boss_won:
                await db.execute(
                    "UPDATE boss_challengers SET status = 'defeated', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (int(challenger["id"]),),
                )
                await db.execute(
                    "UPDATE boss_state SET wins_current = wins_current + 1, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ?",
                    (guild_id,),
                )
                await db.execute(
                    """
                    UPDATE boss_reigns SET wins = wins + 1
                    WHERE id = (
                        SELECT id FROM boss_reigns
                        WHERE guild_id = ? AND ended_at IS NULL
                        ORDER BY id DESC LIMIT 1
                    )
                    """,
                    (guild_id,),
                )
            else:
                await db.execute(
                    "UPDATE boss_challengers SET status = 'boss_killer', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (int(challenger["id"]),),
                )
                await db.execute(
                    """
                    UPDATE boss_state
                    SET status = 'defeated',
                        successor_id = ?, successor_name = ?,
                        registrations_open = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE guild_id = ?
                    """,
                    (str(challenger["discord_id"]), str(challenger["username"]), guild_id),
                )
                await db.execute(
                    """
                    UPDATE boss_reigns
                    SET defeated_by_id = ?, defeated_by_name = ?
                    WHERE id = (
                        SELECT id FROM boss_reigns
                        WHERE guild_id = ? AND ended_at IS NULL
                        ORDER BY id DESC LIMIT 1
                    )
                    """,
                    (str(challenger["discord_id"]), str(challenger["username"]), guild_id),
                )
            await db.commit()
        finally:
            await db.close()

        return {
            "boss_won": boss_won,
            "state": await self.state(guild_id),
            "challenger": challenger,
        }

    async def next_week(self, guild_id: str) -> dict[str, Any]:
        state = await self.state(guild_id)
        if not state.get("boss_id"):
            raise ValueError("Aucun Boss n'est défini.")

        old_week = int(state["week_number"] or 1)
        new_week = old_week + 1
        successor_id = state.get("successor_id")
        successor_name = state.get("successor_name")
        db = await self._connect()
        try:
            if successor_id:
                await db.execute(
                    """
                    UPDATE boss_reigns
                    SET ended_week = ?, wins = ?, ended_at = CURRENT_TIMESTAMP
                    WHERE id = (
                        SELECT id FROM boss_reigns
                        WHERE guild_id = ? AND ended_at IS NULL
                        ORDER BY id DESC LIMIT 1
                    )
                    """,
                    (old_week, int(state["wins_current"] or 0), guild_id),
                )
                await db.execute(
                    """
                    UPDATE boss_state
                    SET boss_id = ?, boss_name = ?,
                        successor_id = NULL, successor_name = NULL,
                        status = 'active', registrations_open = 0,
                        week_number = ?, wins_current = 0,
                        reign_started_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE guild_id = ?
                    """,
                    (str(successor_id), str(successor_name), new_week, guild_id),
                )
                await db.execute(
                    """
                    INSERT INTO boss_reigns(guild_id, boss_id, boss_name, started_week)
                    VALUES(?, ?, ?, ?)
                    """,
                    (guild_id, str(successor_id), str(successor_name), new_week),
                )
            else:
                await db.execute(
                    """
                    UPDATE boss_state
                    SET status = 'active', registrations_open = 0,
                        week_number = ?, successor_id = NULL, successor_name = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE guild_id = ?
                    """,
                    (new_week, guild_id),
                )
            await db.commit()
        finally:
            await db.close()
        return await self.state(guild_id)

    async def history(self, guild_id: str, limit: int = 20) -> list[dict[str, Any]]:
        await self.ensure_schema()
        db = await self._connect()
        try:
            cur = await db.execute(
                """
                SELECT * FROM boss_reigns
                WHERE guild_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (guild_id, max(1, min(int(limit), 50))),
            )
            return [dict(row) for row in await cur.fetchall()]
        finally:
            await db.close()

    async def public_data(self, guild_id: str) -> dict[str, Any]:
        return {
            "state": await self.state(guild_id),
            "challengers": await self.challengers(guild_id),
            "history": await self.history(guild_id),
        }

    async def public_format_card(self, guild_id: str | None = None) -> dict[str, Any]:
        card: dict[str, Any] = {
            "id": "boss",
            "name": "Boss",
            "emoji": "👑",
            "format_version": "1",
            "description": (
                "Un Boss affronte les challengers du serveur jusqu'à sa chute. "
                "Le joueur qui le bat prend le trône la semaine suivante."
            ),
            "pool_count": 0,
            "pool_revision": "Trône hebdomadaire",
            "meta_left": "Inscriptions + programme live",
            "meta_right": "Règne persistant",
        }
        if not guild_id:
            return card
        try:
            state = await self.state(guild_id)
            challengers = await self.challengers(guild_id)
            if state.get("boss_name"):
                card["meta_left"] = f"Boss : {state['boss_name']}"
                card["meta_right"] = (
                    f"{len(challengers)} challenger(s) · "
                    f"{int(state.get('wins_current') or 0)} victoire(s)"
                )
        except Exception:
            pass
        return card
