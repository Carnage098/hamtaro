from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class Player:
    """
    Représente un joueur inscrit.
    """

    discord_id: Optional[str]

    username: str

    deck: Optional[str] = None

    seed: Optional[int] = None

    checked_in: bool = True

    @property
    def is_bye(self) -> bool:
        return self.discord_id is None

    @classmethod
    def bye(cls) -> "Player":
        return cls(
            discord_id=None,
            username="BYE"
        )

    @classmethod
    def from_row(cls, row):
        return cls(
            discord_id=row["discord_id"],
            username=row["username"],
            deck=row["deck"] if "deck" in row.keys() else None,
            seed=row["seed"] if "seed" in row.keys() else None,
            checked_in=bool(row["checked_in"]) if "checked_in" in row.keys() else True
        )
