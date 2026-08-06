from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from services.expansion_database import dumps, expansion_connection, loads, utcnow_iso


class CommunityService:
    async def create_poll(
        self,
        *,
        guild_id: str,
        channel_id: str,
        question: str,
        options: list[str],
        multiple_choice: bool,
        closes_at: str | None,
        created_by: str,
    ) -> int:
        cleaned = [option.strip()[:80] for option in options if option.strip()]
        if len(cleaned) < 2 or len(cleaned) > 5:
            raise ValueError("Un sondage doit contenir entre 2 et 5 choix.")
        if len(set(option.casefold() for option in cleaned)) != len(cleaned):
            raise ValueError("Les choix doivent être différents.")
        if closes_at:
            try:
                datetime.fromisoformat(closes_at.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("Date de fermeture invalide.") from error
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO community_polls(
                    guild_id, channel_id, question, options_json,
                    status, multiple_choice, closes_at, created_by, created_at
                ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    channel_id,
                    question.strip()[:300],
                    dumps(cleaned),
                    int(multiple_choice),
                    closes_at,
                    created_by,
                    utcnow_iso(),
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def attach_message(self, poll_id: int, message_id: str) -> None:
        async with expansion_connection() as db:
            await db.execute(
                "UPDATE community_polls SET message_id=? WHERE id=?",
                (message_id, poll_id),
            )
            await db.commit()

    async def poll(self, poll_id: int) -> dict[str, Any] | None:
        async with expansion_connection() as db:
            row = await (
                await db.execute("SELECT * FROM community_polls WHERE id=?", (poll_id,))
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["options"] = loads(result.pop("options_json"), [])
            return result

    async def open_polls(self) -> list[dict[str, Any]]:
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    "SELECT * FROM community_polls WHERE status='open' ORDER BY id"
                )
            ).fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["options"] = loads(item.pop("options_json"), [])
                results.append(item)
            return results

    async def vote(self, poll_id: int, discord_id: str, option_index: int) -> dict[str, Any]:
        async with expansion_connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            poll = await (
                await db.execute("SELECT * FROM community_polls WHERE id=?", (poll_id,))
            ).fetchone()
            if poll is None or str(poll["status"]) != "open":
                await db.rollback()
                raise ValueError("Ce sondage est fermé.")
            options = loads(poll["options_json"], [])
            if option_index < 0 or option_index >= len(options):
                await db.rollback()
                raise ValueError("Choix invalide.")
            if int(poll["multiple_choice"]) == 0:
                await db.execute(
                    "DELETE FROM community_poll_votes WHERE poll_id=? AND discord_id=?",
                    (poll_id, discord_id),
                )
            existing = await (
                await db.execute(
                    """
                    SELECT 1 FROM community_poll_votes
                    WHERE poll_id=? AND discord_id=? AND option_index=?
                    """,
                    (poll_id, discord_id, option_index),
                )
            ).fetchone()
            if existing:
                await db.execute(
                    """
                    DELETE FROM community_poll_votes
                    WHERE poll_id=? AND discord_id=? AND option_index=?
                    """,
                    (poll_id, discord_id, option_index),
                )
                selected = False
            else:
                await db.execute(
                    """
                    INSERT INTO community_poll_votes(
                        poll_id, discord_id, option_index, voted_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (poll_id, discord_id, option_index, utcnow_iso()),
                )
                selected = True
            await db.commit()
            return {
                "selected": selected,
                "option": options[option_index],
                "multiple_choice": bool(poll["multiple_choice"]),
            }

    async def results(self, poll_id: int) -> dict[str, Any]:
        poll = await self.poll(poll_id)
        if poll is None:
            raise ValueError("Sondage introuvable.")
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT option_index, COUNT(*) AS votes
                    FROM community_poll_votes
                    WHERE poll_id=?
                    GROUP BY option_index
                    """,
                    (poll_id,),
                )
            ).fetchall()
            voters = await (
                await db.execute(
                    """
                    SELECT COUNT(DISTINCT discord_id) AS total
                    FROM community_poll_votes WHERE poll_id=?
                    """,
                    (poll_id,),
                )
            ).fetchone()
        counts = {int(row["option_index"]): int(row["votes"]) for row in rows}
        poll["counts"] = [counts.get(index, 0) for index in range(len(poll["options"]))]
        poll["voters"] = int(voters["total"] if voters else 0)
        return poll

    async def close_poll(self, poll_id: int, guild_id: str) -> dict[str, Any]:
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                UPDATE community_polls
                SET status='closed', closed_at=?
                WHERE id=? AND guild_id=? AND status='open'
                """,
                (utcnow_iso(), poll_id, guild_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Sondage introuvable ou déjà fermé.")
            await db.commit()
        return await self.results(poll_id)

    async def close_expired(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC).isoformat()
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT id, guild_id FROM community_polls
                    WHERE status='open' AND closes_at IS NOT NULL AND closes_at<=?
                    """,
                    (now,),
                )
            ).fetchall()
        results = []
        for row in rows:
            try:
                results.append(await self.close_poll(int(row["id"]), str(row["guild_id"])))
            except ValueError:
                continue
        return results
