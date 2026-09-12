from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from services.tournament_schedule_service import load_schedule, schedule_tournament_specs
from services.tournament_start_service import TournamentStartService


AUTO_ACTOR_ID = "hamtaro-auto"
LOGGER = logging.getLogger(__name__)


def scheduled_start_at(spec: dict[str, Any], timezone_name: str) -> datetime:
    return datetime.fromisoformat(
        f"{spec['date']}T{spec['start']}"
    ).replace(tzinfo=ZoneInfo(timezone_name))


def due_tournament_specs(now: datetime | None = None) -> list[dict[str, Any]]:
    schedule = load_schedule()
    timezone_name = str(schedule.get("timezone") or "Europe/Paris")
    timezone = ZoneInfo(timezone_name)
    current = now.astimezone(timezone) if now is not None else datetime.now(timezone)
    return [
        spec
        for spec in schedule_tournament_specs()
        if scheduled_start_at(spec, timezone_name) <= current
    ]


class TournamentAutomationService:
    """Lance une seule fois les tournois arrivés à leur horaire officiel."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.db = bot.db
        self.start_service = TournamentStartService(bot)

    async def start_due_tournaments(
        self,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for spec in due_tournament_specs(now):
            row = await self.db.fetchone(
                """
                SELECT id, guild_id, code
                FROM tournaments
                WHERE scheduled_slot_id = ?
                  AND status IN ('registration', 'check_in')
                  AND auto_start_attempted_at IS NULL
                LIMIT 1
                """,
                (spec["scheduled_slot_id"],),
            )
            if row is None:
                continue

            tournament_id = int(row["id"])
            guild_id = str(row["guild_id"])
            player_count = 0
            result = "error"
            try:
                player_count = await self.db.count_registrations(tournament_id)

                if player_count == 0:
                    await self.db.update(
                        """
                        UPDATE tournaments
                        SET auto_start_attempted_at = CURRENT_TIMESTAMP,
                            auto_start_result = 'skipped_no_players'
                        WHERE id = ? AND auto_start_attempted_at IS NULL
                        """,
                        (tournament_id,),
                    )
                    result = "skipped_no_players"
                elif player_count == 1:
                    await self.db.finish_single_player_tournament_by_bye(
                        tournament_id,
                        guild_id,
                        spec["structure"],
                    )
                    result = "finished_single_player_bye"
                else:
                    tournament = await self.db.get_tournament(tournament_id)
                    if tournament is None:
                        continue
                    payload = tournament.to_dict()
                    payload["tournament_type"] = spec["structure"]
                    preview = await self.start_service.create_preview(
                        guild_id=guild_id,
                        tournament=payload,
                        total_rounds=None,
                        actor_id=AUTO_ACTOR_ID,
                        channel_id=None,
                    )
                    await self.start_service.confirm_preview(
                        int(preview["id"]),
                        AUTO_ACTOR_ID,
                    )
                    await self.db.update(
                        """
                        UPDATE tournaments
                        SET auto_start_attempted_at = CURRENT_TIMESTAMP,
                            auto_start_result = 'started'
                        WHERE id = ?
                        """,
                        (tournament_id,),
                    )
                    result = "started"
            except Exception:
                LOGGER.exception(
                    "Échec du démarrage automatique du tournoi %s",
                    tournament_id,
                )

            results.append(
                {
                    "tournament_id": tournament_id,
                    "scheduled_slot_id": spec["scheduled_slot_id"],
                    "code": str(row["code"]),
                    "players": player_count,
                    "result": result,
                }
            )
        return results
