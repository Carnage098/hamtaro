from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class Tournament:

    id: int

    guild_id: str

    code: str

    name: str

    format: str

    max_players: int

    status: str

    current_round: int

    total_rounds: int

    winner_id: Optional[str]

    bracket_message_id: Optional[str]

    @classmethod
    def from_row(cls, row):

        return cls(
            id=row["id"],
            guild_id=row["guild_id"],
            code=row["code"],
            name=row["name"],
            format=row["format"],
            max_players=row["max_players"],
            status=row["status"],
            current_round=row["current_round"],
            total_rounds=row["total_rounds"],
            winner_id=row["winner_id"],
            bracket_message_id=row["bracket_message_id"]
        )
