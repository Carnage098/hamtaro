from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from services.expansion_database import expansion_connection, utcnow_iso


class AutomationService:
    async def due_schedule_events(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC).isoformat()
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT s.*, t.name AS tournament_name, t.code, t.format,
                           tp.name AS template_name, tp.tournament_name AS template_tournament_name,
                           tp.format AS template_format
                    FROM scheduled_tournaments_plus s
                    LEFT JOIN tournaments t ON t.id=s.tournament_id
                    LEFT JOIN tournament_templates_plus tp ON tp.id=s.template_id
                    WHERE s.status='scheduled'
                      AND (
                        (s.announce_at IS NOT NULL AND s.announcement_sent=0 AND s.announce_at<=?)
                        OR (s.reminder_at IS NOT NULL AND s.reminder_sent=0 AND s.reminder_at<=?)
                        OR (s.start_prompt_at IS NOT NULL AND s.start_prompt_sent=0 AND s.start_prompt_at<=?)
                      )
                    ORDER BY s.id
                    """,
                    (now, now, now),
                )
            ).fetchall()
            events: list[dict[str, Any]] = []
            for row in rows:
                data = dict(row)
                if data.get("announce_at") and not data.get("announcement_sent") and data["announce_at"] <= now:
                    events.append({**data, "event_type": "announcement"})
                if data.get("reminder_at") and not data.get("reminder_sent") and data["reminder_at"] <= now:
                    events.append({**data, "event_type": "reminder"})
                if data.get("start_prompt_at") and not data.get("start_prompt_sent") and data["start_prompt_at"] <= now:
                    events.append({**data, "event_type": "start_prompt"})
            return events

    async def mark_schedule_event_sent(self, schedule_id: int, event_type: str) -> None:
        columns = {
            "announcement": "announcement_sent",
            "reminder": "reminder_sent",
            "start_prompt": "start_prompt_sent",
        }
        column = columns[event_type]
        async with expansion_connection() as db:
            await db.execute(
                f"UPDATE scheduled_tournaments_plus SET {column}=1 WHERE id=?",
                (schedule_id,),
            )
            row = await (
                await db.execute(
                    """
                    SELECT announce_at, reminder_at, start_prompt_at,
                           announcement_sent, reminder_sent, start_prompt_sent
                    FROM scheduled_tournaments_plus WHERE id=?
                    """,
                    (schedule_id,),
                )
            ).fetchone()
            if row:
                all_done = (
                    (row["announce_at"] is None or int(row["announcement_sent"]) == 1)
                    and (row["reminder_at"] is None or int(row["reminder_sent"]) == 1)
                    and (row["start_prompt_at"] is None or int(row["start_prompt_sent"]) == 1)
                )
                if all_done:
                    await db.execute(
                        "UPDATE scheduled_tournaments_plus SET status='completed' WHERE id=?",
                        (schedule_id,),
                    )
            await db.commit()


    async def due_player_notifications(self, limit: int = 100) -> list[dict[str, Any]]:
        """Retourne les notifications DM encore jamais envoyées."""
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    WITH candidates AS (
                        SELECT
                            t.guild_id AS guild_id,
                            m.player1_id AS discord_id,
                            'next:bracket:'||m.id AS event_key,
                            'next_match' AS event_type,
                            'Ton prochain match dans '||t.name||' est contre '||
                            COALESCE(m.player2_name, m.player2_id)||'.' AS message
                        FROM matches m
                        JOIN tournaments t ON t.id=m.tournament_id
                        WHERE m.player1_id IS NOT NULL AND m.player2_id IS NOT NULL
                          AND COALESCE(m.is_bye,0)=0
                          AND m.status IN ('waiting','playing')
                        UNION ALL
                        SELECT
                            t.guild_id, m.player2_id, 'next:bracket:'||m.id, 'next_match',
                            'Ton prochain match dans '||t.name||' est contre '||
                            COALESCE(m.player1_name, m.player1_id)||'.'
                        FROM matches m
                        JOIN tournaments t ON t.id=m.tournament_id
                        WHERE m.player1_id IS NOT NULL AND m.player2_id IS NOT NULL
                          AND COALESCE(m.is_bye,0)=0
                          AND m.status IN ('waiting','playing')
                        UNION ALL
                        SELECT
                            t.guild_id, sm.player1_id, 'next:swiss:'||sm.id, 'next_match',
                            'Ta table '||sm.table_number||' dans '||t.name||' est contre '||
                            COALESCE(sm.player2_name, sm.player2_id)||'.'
                        FROM swiss_matches sm
                        JOIN tournaments t ON t.id=sm.tournament_id
                        WHERE sm.player2_id IS NOT NULL AND COALESCE(sm.is_bye,0)=0
                          AND sm.status='pending'
                        UNION ALL
                        SELECT
                            t.guild_id, sm.player2_id, 'next:swiss:'||sm.id, 'next_match',
                            'Ta table '||sm.table_number||' dans '||t.name||' est contre '||
                            COALESCE(sm.player1_name, sm.player1_id)||'.'
                        FROM swiss_matches sm
                        JOIN tournaments t ON t.id=sm.tournament_id
                        WHERE sm.player2_id IS NOT NULL AND COALESCE(sm.is_bye,0)=0
                          AND sm.status='pending'
                        UNION ALL
                        SELECT
                            t.guild_id, m.player1_id, 'confirm:bracket:'||m.id,
                            'result_confirmation',
                            'Un résultat est en attente de confirmation pour ton match dans '||t.name||'.'
                        FROM matches m
                        JOIN tournaments t ON t.id=m.tournament_id
                        WHERE m.player1_id IS NOT NULL AND m.status='reported'
                        UNION ALL
                        SELECT
                            t.guild_id, m.player2_id, 'confirm:bracket:'||m.id,
                            'result_confirmation',
                            'Un résultat est en attente de confirmation pour ton match dans '||t.name||'.'
                        FROM matches m
                        JOIN tournaments t ON t.id=m.tournament_id
                        WHERE m.player2_id IS NOT NULL AND m.status='reported'
                        UNION ALL
                        SELECT
                            h.guild_id, h.discord_id, 'ranking:'||h.id,
                            'ranking_change',
                            'Ton ELO '||h.format||' est passé de '||h.old_rating||' à '||h.new_rating
                            ||' ('||CASE WHEN h.delta>=0 THEN '+' ELSE '' END||h.delta||').'
                        FROM rating_history h
                    )
                    SELECT c.*
                    FROM candidates c
                    JOIN notification_preferences p
                      ON p.guild_id=c.guild_id AND p.discord_id=c.discord_id
                    LEFT JOIN notification_deliveries d
                      ON d.guild_id=c.guild_id AND d.discord_id=c.discord_id
                     AND d.event_key=c.event_key
                    WHERE d.event_key IS NULL
                      AND p.delivery_mode='dm'
                      AND (
                           (c.event_type='next_match' AND p.next_match=1)
                        OR (c.event_type='result_confirmation' AND p.result_confirmation=1)
                        OR (c.event_type='ranking_change' AND p.ranking_change=1)
                      )
                    ORDER BY c.event_key
                    LIMIT ?
                    """,
                    (max(1, min(limit, 500)),),
                )
            ).fetchall()
            return [dict(row) for row in rows]

    async def mark_player_notification_sent(
        self,
        *,
        guild_id: str,
        discord_id: str,
        event_key: str,
        event_type: str,
    ) -> None:
        async with expansion_connection() as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO notification_deliveries(
                    guild_id, discord_id, event_key, event_type, sent_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, discord_id, event_key, event_type, utcnow_iso()),
            )
            await db.commit()

    async def sync_deck_statistics(self, guild_id: str | None = None) -> int:
        pending: list[dict[str, Any]] = []
        async with expansion_connection() as db:
            guild_filter = "AND t.guild_id=?" if guild_id else ""
            params: tuple[Any, ...] = (guild_id,) if guild_id else ()
            bracket = await (
                await db.execute(
                    f"""
                    SELECT 'bracket:'||m.id AS source_key, t.guild_id, m.tournament_id,
                           m.player1_id, m.player2_id, m.winner_id,
                           r1.deck AS player1_deck, r2.deck AS player2_deck,
                           t.format
                    FROM matches m
                    JOIN tournaments t ON t.id=m.tournament_id
                    LEFT JOIN registrations r1 ON r1.tournament_id=m.tournament_id AND r1.discord_id=m.player1_id
                    LEFT JOIN registrations r2 ON r2.tournament_id=m.tournament_id AND r2.discord_id=m.player2_id
                    WHERE m.winner_id IS NOT NULL AND COALESCE(m.is_bye,0)=0
                      AND m.player1_id IS NOT NULL AND m.player2_id IS NOT NULL
                      {guild_filter}
                    """,
                    params,
                )
            ).fetchall()
            swiss = await (
                await db.execute(
                    f"""
                    SELECT 'swiss:'||sm.id AS source_key, t.guild_id, sm.tournament_id,
                           sm.player1_id, sm.player2_id, sm.winner_id,
                           r1.deck AS player1_deck, r2.deck AS player2_deck,
                           t.format
                    FROM swiss_matches sm
                    JOIN tournaments t ON t.id=sm.tournament_id
                    LEFT JOIN registrations r1 ON r1.tournament_id=sm.tournament_id AND r1.discord_id=sm.player1_id
                    LEFT JOIN registrations r2 ON r2.tournament_id=sm.tournament_id AND r2.discord_id=sm.player2_id
                    WHERE sm.winner_id IS NOT NULL AND COALESCE(sm.is_bye,0)=0
                      AND COALESCE(sm.is_double_loss,0)=0
                      AND sm.player2_id IS NOT NULL
                      {guild_filter}
                    """,
                    params,
                )
            ).fetchall()
            pending = [dict(row) for row in bracket] + [dict(row) for row in swiss]

        processed = 0
        for match in pending:
            for side in ("player1", "player2"):
                player_id = str(match[f"{side}_id"])
                deck_name = str(match.get(f"{side}_deck") or "").strip()
                if not deck_name:
                    continue
                won = player_id == str(match["winner_id"])
                async with expansion_connection() as db:
                    await db.execute("BEGIN IMMEDIATE")
                    exists = await (
                        await db.execute(
                            """
                            SELECT 1 FROM processed_deck_matches
                            WHERE guild_id=? AND source_key=? AND discord_id=?
                            """,
                            (match["guild_id"], match["source_key"], player_id),
                        )
                    ).fetchone()
                    if exists:
                        await db.rollback()
                        continue
                    deck = await (
                        await db.execute(
                            """
                            SELECT id FROM player_decks
                            WHERE guild_id=? AND discord_id=?
                              AND LOWER(name)=LOWER(?)
                            ORDER BY CASE WHEN format=? THEN 0 ELSE 1 END, id
                            LIMIT 1
                            """,
                            (match["guild_id"], player_id, deck_name, match["format"]),
                        )
                    ).fetchone()
                    if deck:
                        await db.execute(
                            """
                            UPDATE player_decks
                            SET matches=matches+1, wins=wins+?, losses=losses+?, updated_at=?
                            WHERE id=?
                            """,
                            (1 if won else 0, 0 if won else 1, utcnow_iso(), int(deck["id"])),
                        )
                    await db.execute(
                        """
                        INSERT INTO processed_deck_matches(
                            guild_id, source_key, discord_id, deck_name, won, processed_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            match["guild_id"], match["source_key"], player_id,
                            deck_name, int(won), utcnow_iso(),
                        ),
                    )
                    await db.commit()
                    processed += 1
        return processed
