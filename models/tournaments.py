from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Tournament:

    id: Optional[int]

    guild_id: str

    code: str

    name: str

    format: str

    max_players: int

    status: str

    current_round: int = 0

    winner_id: Optional[str] = None

    created_at: Optional[datetime] = None
