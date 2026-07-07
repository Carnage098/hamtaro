from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class Player:
    """
    Représente un joueur inscrit à un tournoi.
    """

    discord_id: Optional[str]

    username: str

    deck: Optional[str] = None

    seed: Optional[int] = None

    checked_in: bool = True

    @property
    def is_bye(self) -> bool:
        """Retourne True si le joueur est un BYE."""

        return self.discord_id is None

    @classmethod
    def bye(cls) -> "Player":
        """Crée un joueur BYE."""

        return cls(
            discord_id=None,
            username="BYE"
        )
