from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class CasualMatchStatus(str, Enum):
    SEARCHING = "searching"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(slots=True, frozen=True)
class CasualMatch:
    id: int
    guild_id: str
    channel_id: str
    requester_id: str
    requester_name: str
    format_name: str
    simulator: str
    best_of: int
    status: CasualMatchStatus

    message_id: str | None = None
    thread_id: str | None = None
    opponent_id: str | None = None
    opponent_name: str | None = None

    player1_score: int | None = None
    player2_score: int | None = None
    winner_id: str | None = None
    reported_by: str | None = None

    created_at: str | None = None
    accepted_at: str | None = None
    completed_at: str | None = None
    cancelled_at: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CasualMatch":
        data = dict(row)
        return cls(
            id=int(data["id"]),
            guild_id=str(data["guild_id"]),
            channel_id=str(data["channel_id"]),
            requester_id=str(data["requester_id"]),
            requester_name=str(data["requester_name"]),
            format_name=str(data["format_name"]),
            simulator=str(data["simulator"]),
            best_of=int(data["best_of"]),
            status=CasualMatchStatus(str(data["status"])),
            message_id=_optional_str(data.get("message_id")),
            thread_id=_optional_str(data.get("thread_id")),
            opponent_id=_optional_str(data.get("opponent_id")),
            opponent_name=_optional_str(data.get("opponent_name")),
            player1_score=_optional_int(data.get("player1_score")),
            player2_score=_optional_int(data.get("player2_score")),
            winner_id=_optional_str(data.get("winner_id")),
            reported_by=_optional_str(data.get("reported_by")),
            created_at=_optional_str(data.get("created_at")),
            accepted_at=_optional_str(data.get("accepted_at")),
            completed_at=_optional_str(data.get("completed_at")),
            cancelled_at=_optional_str(data.get("cancelled_at")),
        )

    @property
    def required_wins(self) -> int:
        return (self.best_of // 2) + 1

    @property
    def participant_ids(self) -> tuple[str, ...]:
        if self.opponent_id is None:
            return (self.requester_id,)
        return (self.requester_id, self.opponent_id)

    def contains_player(self, user_id: str | int) -> bool:
        return str(user_id) in self.participant_ids


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
