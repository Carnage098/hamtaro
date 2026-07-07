from __future__ import annotations

from enum import Enum


class TournamentStatus(str, Enum):
    REGISTRATION = "registration"
    CHECK_IN = "check_in"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class MatchStatus(str, Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    REPORTED = "reported"
    VALIDATED = "validated"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ResultType(str, Enum):
    PLAYER1 = "player1"
    PLAYER2 = "player2"
    DRAW = "draw"
    BYE = "bye"
