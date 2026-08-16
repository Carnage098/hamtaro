from __future__ import annotations

import re
import unicodedata
from typing import Any

import aiosqlite

try:
    from config import DATABASE
except ImportError:
    from database import DATABASE


class SpidermanTrophyAwardService:
    """Attribution persistante du trophée HT-003 au tournoi Spiderman."""

    TROPHY_ID = "HT-003"

    @staticmethod
    def _value(row: Any, key: str, default: Any = None) -> Any:
        try:
            value = row[key]
        except (KeyError, IndexError, TypeError):
            value = getattr(row, key, default)
        return default if value is None else value

    @staticmethod
    def normalize_tournament_name(value: str) -> str:
        text = str(value or "").strip().casefold()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def is_spiderman_tournament(cls, value: str) -> bool:
        normalized = cls.normalize_tournament_name(value)
        return normalized in {"spiderman", "spider man"}

    async def _ensure_schema(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS spiderman_trophy_awards (
                trophy_id TEXT PRIMARY KEY,
                tournament_id INTEGER NOT NULL UNIQUE,
                tournament_code TEXT,
                tournament_name TEXT NOT NULL,
                guild_id TEXT,
                discord_id TEXT NOT NULL,
                holder_name TEXT NOT NULL,
                deck TEXT,
                format TEXT,
                awarded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_spiderman_trophy_holder
            ON spiderman_trophy_awards(discord_id)
        """)

    async def _winner_deck(self, db, tournament_id: int, winner_id: str) -> str | None:
        cursor = await db.execute(
            "SELECT deck FROM registrations WHERE tournament_id=? AND discord_id=? LIMIT 1",
            (tournament_id, winner_id),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def award_if_matching_tournament(self, tournament: Any, winner_id: str | None, winner_name: str | None) -> dict[str, Any] | None:
        tournament_name = str(self._value(tournament, "name", "") or "")
        if not self.is_spiderman_tournament(tournament_name) or not winner_id or not winner_name:
            return None
        tournament_id = int(self._value(tournament, "id", 0) or 0)
        if tournament_id <= 0:
            return None
        tournament_code = str(self._value(tournament, "code", "") or "") or None
        guild_id = str(self._value(tournament, "guild_id", "") or "") or None
        format_name = str(self._value(tournament, "format", "") or "") or None

        async with aiosqlite.connect(str(DATABASE)) as db:
            db.row_factory = aiosqlite.Row
            await self._ensure_schema(db)
            deck = await self._winner_deck(db, tournament_id, str(winner_id))
            await db.execute("""
                INSERT INTO spiderman_trophy_awards (
                    trophy_id,tournament_id,tournament_code,tournament_name,guild_id,
                    discord_id,holder_name,deck,format,awarded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(trophy_id) DO UPDATE SET
                    tournament_id=excluded.tournament_id,
                    tournament_code=excluded.tournament_code,
                    tournament_name=excluded.tournament_name,
                    guild_id=excluded.guild_id,
                    discord_id=excluded.discord_id,
                    holder_name=excluded.holder_name,
                    deck=excluded.deck,
                    format=excluded.format
            """, (
                self.TROPHY_ID,tournament_id,tournament_code,tournament_name,guild_id,
                str(winner_id),str(winner_name),deck,format_name,
            ))
            await db.commit()
            cursor = await db.execute("SELECT * FROM spiderman_trophy_awards WHERE trophy_id=?", (self.TROPHY_ID,))
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def all_awards(self) -> dict[str, dict[str, Any]]:
        async with aiosqlite.connect(str(DATABASE)) as db:
            db.row_factory = aiosqlite.Row
            await self._ensure_schema(db)
            await db.commit()
            rows = await (await db.execute("SELECT * FROM spiderman_trophy_awards")).fetchall()
        result = {}
        for row in rows:
            item = dict(row)
            result[str(item["trophy_id"])] = {
                "discord_id": item.get("discord_id"),
                "holder_name": item.get("holder_name"),
                "deck": item.get("deck"),
                "format": item.get("format"),
                "tournament_name": item.get("tournament_name"),
                "tournament_id": item.get("tournament_id"),
                "tournament_code": item.get("tournament_code"),
                "guild_id": item.get("guild_id"),
                "awarded_at": item.get("awarded_at"),
            }
        return result
