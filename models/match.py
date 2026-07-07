from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.bracket_service import MatchStatus


@dataclass(slots=True)
class Match:

    id: int

    tournament_id: int

    round: int

    match_number: int

    bracket_position: int

    next_match_id: Optional[int]

    player1_id: Optional[str]

    player2_id: Optional[str]

    player1_name: Optional[str]

    player2_name: Optional[str]

    player1_score: int

    player2_score: int

    winner_id: Optional[str]

    status: MatchStatus

    @classmethod
    def from_row(cls, row):

        return cls(
            id=row["id"],
            tournament_id=row["tournament_id"],
            round=row["round"],
            match_number=row["match_number"],
            bracket_position=row["bracket_position"],
            next_match_id=row["next_match_id"],
            player1_id=row["player1_id"],
            player2_id=row["player2_id"],
            player1_name=row["player1_name"],
            player2_name=row["player2_name"],
            player1_score=row["player1_score"],
            player2_score=row["player2_score"],
            winner_id=row["winner_id"],
            status=MatchStatus(row["status"])
        )
