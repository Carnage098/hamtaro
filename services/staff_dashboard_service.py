from __future__ import annotations

import logging
import time
from typing import Any, Sequence

LOGGER = logging.getLogger(__name__)


class StaffDashboardService:
    """Prépare les données en lecture seule du tableau de bord staff."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.db = bot.db

    async def _table_exists(self, table_name: str) -> bool:
        value = await self.db.fetchval(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            LIMIT 1
            """,
            (table_name,),
        )
        return bool(value)

    async def _safe_fetchall(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> list[dict[str, Any]]:
        try:
            rows = await self.db.fetchall(query, parameters)
            return [dict(row) for row in rows]
        except Exception:
            LOGGER.exception("Requête du tableau de bord staff impossible.")
            return []

    async def _safe_count(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> int:
        try:
            return int(await self.db.fetchval(query, parameters) or 0)
        except Exception:
            LOGGER.exception("Compteur du tableau de bord staff impossible.")
            return 0

    async def overview(self, guild_id: str) -> dict[str, Any]:
        active_tournaments = await self._safe_fetchall(
            """
            SELECT
                t.id,
                t.code,
                t.name,
                t.format,
                t.status,
                t.max_players,
                t.current_round,
                t.total_rounds,
                t.created_at,
                COUNT(r.id) AS participant_count
            FROM tournaments t
            LEFT JOIN registrations r ON r.tournament_id = t.id
            WHERE t.guild_id = ?
              AND LOWER(COALESCE(t.status, '')) NOT IN (
                  'finished', 'completed', 'ended', 'archived', 'cancelled'
              )
            GROUP BY t.id
            ORDER BY t.created_at DESC, t.id DESC
            LIMIT 30
            """,
            (guild_id,),
        )

        pending_results: list[dict[str, Any]] = []
        if await self._table_exists("result_requests"):
            pending_results = await self._safe_fetchall(
                """
                SELECT
                    rr.match_kind,
                    rr.match_id,
                    rr.tournament_id,
                    rr.player1_score,
                    rr.player2_score,
                    rr.status,
                    rr.created_at,
                    t.code AS tournament_code,
                    t.name AS tournament_name
                FROM result_requests rr
                JOIN tournaments t ON t.id = rr.tournament_id
                WHERE rr.guild_id = ?
                  AND rr.status IN (
                      'pending', 'confirmed', 'contested', 'processing'
                  )
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

        recent_audit: list[dict[str, Any]] = []
        if await self._table_exists("audit_logs"):
            recent_audit = await self._safe_fetchall(
                """
                SELECT
                    id,
                    actor_id,
                    actor_name,
                    action,
                    entity_type,
                    entity_id,
                    tournament_id,
                    details,
                    created_at
                FROM audit_logs
                WHERE guild_id = ?
                ORDER BY id DESC
                LIMIT 30
                """,
                (guild_id,),
            )

        invalid_matches = await self._safe_fetchall(
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
                    (
                        m.player1_id IS NOT NULL
                        AND m.player2_id IS NOT NULL
                        AND m.player1_id = m.player2_id
                    )
                 OR (
                        m.status IN ('validated', 'completed')
                        AND COALESCE(m.is_bye, 0) = 0
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
            "active_tournaments": len(active_tournaments),
            "registrations": await self._safe_count(
                """
                SELECT COUNT(*)
                FROM registrations r
                JOIN tournaments t ON t.id = r.tournament_id
                WHERE t.guild_id = ?
                """,
                (guild_id,),
            ),
            "pending_results": len(pending_results),
            "invalid_matches": len(invalid_matches),
        }

        return {
            "totals": totals,
            "active_tournaments": active_tournaments,
            "pending_results": pending_results,
            "recent_audit": recent_audit,
            "invalid_matches": invalid_matches,
            "generated_at": int(time.time()),
        }
