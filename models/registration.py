from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class Registration:

    id: int

    tournament_id: int

    discord_id: str

    username: str

    deck: Optional[str]

    seed: Optional[int]

    checked_in: bool

    @classmethod
    def from_row(cls, row):

        return cls(
            id=row["id"],
            tournament_id=row["tournament_id"],
            discord_id=row["discord_id"],
            username=row["username"],
            deck=row["deck"],
            seed=row["seed"],
            checked_in=bool(row["checked_in"])
        )
