
from dataclasses import dataclass
from typing import Optional


@dataclass
class Registration:

    id: Optional[int]

    tournament_id: int

    discord_id: str

    username: str

    deck: Optional[str]
