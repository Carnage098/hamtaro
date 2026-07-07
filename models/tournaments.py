from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row

from models.enums import TournamentStatus


@dataclass(slots=True)
class Tournament:

    id: int | None

    guild_id: str

    code: str

    name: str

    format: str

    max_players: int

    status: TournamentStatus = TournamentStatus.REGISTRATION

    current_round: int = 0

    total_rounds: int = 0

    winner_id: str | None = None
    winner_name: str | None = None

    bracket_message_id: str | None = None

    created_by: str | None = None

    created_at: str | None = None
    started_at: str | None = None
    finished_at: str |None = None

    @classmethod
    def from_row(cls, row: Row | dict):

        return cls(

            id=row["id"],

            guild_id=row["guild_id"],

            code=row["code"],

            name=row["name"],

            format=row["format"],

            max_players=row["max_players"],

            status=TournamentStatus(row["status"]),

            current_round=row["current_round"],

            total_rounds=row["total_rounds"],

            winner_id=row["winner_id"],

            winner_name=row["winner_name"],

            bracket_message_id=row["bracket_message_id"],

            created_by=row["created_by"],

            created_at=row["created_at"],

            started_at=row["started_at"],

            finished_at=row["finished_at"]

        )

    def to_dict(self):

        return {

            "id": self.id,

            "guild_id": self.guild_id,

            "code": self.code,

            "name": self.name,

            "format": self.format,

            "max_players": self.max_players,

            "status": self.status.value,

            "current_round": self.current_round,

            "total_rounds": self.total_rounds,

            "winner_id": self.winner_id,

            "winner_name": self.winner_name,

            "bracket_message_id": self.bracket_message_id,

            "created_by": self.created_by,

            "created_at": self.created_at,

            "started_at": self.started_at,

            "finished_at": self.finished_at,

        }

    @property
    def is_registration(self):

        return self.status == TournamentStatus.REGISTRATION

    @property
    def is_running(self):

        return self.status == TournamentStatus.RUNNING

    @property
    def is_finished(self):

        return self.status == TournamentStatus.FINISHED
