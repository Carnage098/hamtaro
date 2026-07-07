from dataclasses import dataclass
from typing import Optional


@dataclass
class Match:

    id: Optional[int]

    tournament_id: int

    round: int

    player1_id: str

    player2_id: str

    player1_name: str

    player2_name: str

    player1_deck: Optional[str]

    player2_deck: Optional[str]

    score: Optional[str]

    winner_id: Optional[str]

    loser_id: Optional[str]

    status: str
