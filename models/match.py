from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from models.enums import MatchStatus


@dataclass(slots=True)
class Match:
    """
    Représente un match d'un tournoi.
    """

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

    player1_score: int = 0
    player2_score: int = 0

    winner_id: Optional[str] = None

    score: Optional[str] = None

    reported_by: Optional[str] = None
    validated_by: Optional[str] = None

    reported_at: Optional[datetime] = None
    validated_at: Optional[datetime] = None

    status: MatchStatus = MatchStatus.WAITING

    # ---------------------------------------------------------
    # PROPRIÉTÉS
    # ---------------------------------------------------------

    @property
    def is_finished(self) -> bool:
        return self.status == MatchStatus.FINISHED

    @property
    def has_bye(self) -> bool:
        return (
            self.player1_id is None
            or self.player2_id is None
        )

    @property
    def winner_known(self) -> bool:
        return self.winner_id is not None

    @property
    def players(self) -> tuple[Optional[str], Optional[str]]:
        return (
            self.player1_id,
            self.player2_id
        )

    # ---------------------------------------------------------
    # CONVERSION SQL
    # ---------------------------------------------------------

    @classmethod
    def from_row(cls, row) -> "Match":

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

            score=row["score"],

            reported_by=row["reported_by"],

            validated_by=row["validated_by"],

            reported_at=row["reported_at"],

            validated_at=row["validated_at"],

            status=MatchStatus(row["status"])
        )

    # ---------------------------------------------------------
    # EXPORT
    # ---------------------------------------------------------

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "tournament_id": self.tournament_id,

            "round": self.round,

            "match_number": self.match_number,

            "bracket_position": self.bracket_position,

            "next_match_id": self.next_match_id,

            "player1_id": self.player1_id,

            "player2_id": self.player2_id,

            "player1_name": self.player1_name,

            "player2_name": self.player2_name,

            "player1_score": self.player1_score,

            "player2_score": self.player2_score,

            "winner_id": self.winner_id,

            "score": self.score,

            "status": self.status.value
        }

    # ---------------------------------------------------------
    # AFFICHAGE
    # ---------------------------------------------------------

    def __str__(self) -> str:

        p1 = self.player1_name or "???"
        p2 = self.player2_name or "???"

        return (
            f"Match {self.match_number} "
            f"({p1} vs {p2})"
        )
