from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass(slots=True)
class Player:

    discord_id: str
    guild_id: str

    username: str

    display_name: str | None = None
    avatar_url: str | None = None

    wins: int = 0
    losses: int = 0

    tournaments_played: int = 0
    tournaments_won: int = 0

    joined_at: str | None = None

    @classmethod
    def from_row(cls, row: Row | dict):

        return cls(
            discord_id=row["discord_id"],
            guild_id=row["guild_id"],
            username=row["username"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            wins=row["wins"],
            losses=row["losses"],
            tournaments_played=row["tournaments_played"],
            tournaments_won=row["tournaments_won"],
            joined_at=row["joined_at"],
        )

    def to_dict(self):

        return {
            "discord_id": self.discord_id,
            "guild_id": self.guild_id,
            "username": self.username,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "wins": self.wins,
            "losses": self.losses,
            "tournaments_played": self.tournaments_played,
            "tournaments_won": self.tournaments_won,
            "joined_at": self.joined_at,
        }

    @property
    def matches_played(self):

        return self.wins + self.losses

    @property
    def winrate(self):

        total = self.matches_played

        if total == 0:
            return 0.0

        return round((self.wins / total) * 100, 2)

    def record_win(self):

        self.wins += 1

    def record_loss(self):

        self.losses += 1

    def won_tournament(self):

        self.tournaments_won += 1

    def played_tournament(self):

        self.tournaments_played += 1
