from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row

from models.enums import MatchStatus


@dataclass(slots=True)
class Match:

    id: int | None

    tournament_id: int

    round: int

    match_number: int

    bracket_position: int

    next_match_id: int | None = None
    next_slot: int | None = None

    player1_id: str | None = None
    player2_id: str | None = None

    player1_name: str | None = None
    player2_name: str | None = None

    player1_score: int = 0
    player2_score: int = 0

    winner_id: str | None = None
    winner_name: str | None = None

    score: str | None = None

    reported_by: str | None = None
    validated_by: str | None = None

    reported_at: str | None = None
    validated_at: str | None = None

    status: MatchStatus = MatchStatus.WAITING

    is_bye: bool = False

    notes: str | None = None

    created_at: str | None = None

    @classmethod
    def from_row(cls, row: Row | dict):

        return cls(
            id=row["id"],
            tournament_id=row["tournament_id"],
            round=row["round"],
            match_number=row["match_number"],
            bracket_position=row["bracket_position"],
            next_match_id=row["next_match_id"],
            next_slot=row["next_slot"],
            player1_id=row["player1_id"],
            player2_id=row["player2_id"],
            player1_name=row["player1_name"],
            player2_name=row["player2_name"],
            player1_score=row["player1_score"],
            player2_score=row["player2_score"],
            winner_id=row["winner_id"],
            winner_name=row["winner_name"],
            score=row["score"],
            reported_by=row["reported_by"],
            validated_by=row["validated_by"],
            reported_at=row["reported_at"],
            validated_at=row["validated_at"],
            status=MatchStatus(row["status"]),
            is_bye=bool(row["is_bye"]),
            notes=row["notes"],
            created_at=row["created_at"],
        )

    def to_dict(self):

        return {
            "id": self.id,
            "tournament_id": self.tournament_id,
            "round": self.round,
            "match_number": self.match_number,
            "bracket_position": self.bracket_position,
            "next_match_id": self.next_match_id,
            "next_slot": self.next_slot,
            "player1_id": self.player1_id,
            "player2_id": self.player2_id,
            "player1_name": self.player1_name,
            "player2_name": self.player2_name,
            "player1_score": self.player1_score,
            "player2_score": self.player2_score,
            "winner_id": self.winner_id,
            "winner_name": self.winner_name,
            "score": self.score,
            "reported_by": self.reported_by,
            "validated_by": self.validated_by,
            "reported_at": self.reported_at,
            "validated_at": self.validated_at,
            "status": self.status.value,
            "is_bye": int(self.is_bye),
            "notes": self.notes,
            "created_at": self.created_at,
        }

    @property
    def has_two_players(self) -> bool:
        return (
            self.player1_id is not None
            and self.player2_id is not None
        )

    @property
    def is_finished(self) -> bool:
        return self.status == MatchStatus.COMPLETED

    @property
    def is_waiting(self) -> bool:
        return self.status == MatchStatus.WAITING
