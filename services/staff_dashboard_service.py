from __future__ import annotations

from typing import Any


class StaffDashboardService:
    """Lecture centralisée des données affichées dans le tableau de bord staff."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.db = bot.db

    async def overview(self, guild_id: str) -> dict[str, Any]:
        active_tournaments = await self.db.fetchall(
            """
            SELECT
                t.*,
                COUNT(r.id) AS participant_count
            FROM tournaments t
            LEFT JOIN registrations r ON r.tournament_id = t.id
            WHERE t.guild_id = ?
              AND t.status NOT IN ('finished', 'cancelled')
            GROUP BY t.id
            ORDER BY t.created_at DESC, t.id DESC
            LIMIT 30
            """,
            (guild_id,),
        )
        pending_results = await self.db.fetchall(
            """
            SELECT
                rr.*,
                t.code AS tournament_code,
                t.name AS tournament_name
            FROM result_requests rr
            JOIN tournaments t ON t.id = rr.tournament_id
            WHERE rr.guild_id = ?
              AND rr.status IN ('pending', 'confirmed', 'contested', 'processing')
            ORDER BY
                CASE rr.status
                    WHEN 'contested' THEN 0
                    WHEN 'confirmed' THEN 1
                    WHEN 'pending' THEN 2
                    ELSE 3
                END,
                rr.created_at ASC
            LIMIT 50
            """,
            (guild_id,),
        )
        recent_audit = await self.db.fetchall(
            """
            SELECT *
            FROM audit_logs
            WHERE guild_id = ?
            ORDER BY id DESC
            LIMIT 30
            """,
            (guild_id,),
        )
        invalid_matches = await self.db.fetchall(
            """
            SELECT
                m.id,
                m.tournament_id,
                t.code AS tournament_code,
                m.round,
                m.match_number,
                m.status,
                m.player1_name,
                m.player2_name,
                m.winner_name
            FROM matches m
            JOIN tournaments t ON t.id = m.tournament_id
            WHERE t.guild_id = ?
              AND (
                    (m.player1_id IS NOT NULL AND m.player1_id = m.player2_id)
                 OR (
                        m.status IN ('validated', 'completed')
                    AND m.is_bye = 0
                    AND m.winner_id IS NULL
                 )
                 OR (
                        m.winner_id IS NOT NULL
                    AND m.winner_id NOT IN (m.player1_id, m.player2_id)
                 )
              )
            ORDER BY m.id DESC
            LIMIT 30
            """,
            (guild_id,),
        )
        totals = {
            "active_tournaments": int(
                await self.db.fetchval(
                    """
                    SELECT COUNT(*) FROM tournaments
                    WHERE guild_id = ?
                      AND status NOT IN ('finished', 'cancelled')
                    """,
                    (guild_id,),
                )
                or 0
            ),
            "registrations": int(
                await self.db.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM registrations r
                    JOIN tournaments t ON t.id = r.tournament_id
                    WHERE t.guild_id = ?
                    """,
                    (guild_id,),
                )
                or 0
            ),
            "pending_results": len(pending_results),
            "invalid_matches": len(invalid_matches),
        }

        return {
            "totals": totals,
            "active_tournaments": [dict(row) for row in active_tournaments],
            "pending_results": [dict(row) for row in pending_results],
            "recent_audit": [dict(row) for row in recent_audit],
            "invalid_matches": [dict(row) for row in invalid_matches],
        }
