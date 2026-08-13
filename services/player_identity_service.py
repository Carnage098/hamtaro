from __future__ import annotations

from collections import Counter
from typing import Any

from services.analytics_service import AnalyticsService

try:
    from services.competitive_service import CompetitiveService
except Exception:
    CompetitiveService = None  # type: ignore


class PlayerIdentityService:
    def __init__(self) -> None:
        self.analytics = AnalyticsService()
        self.competitive = CompetitiveService() if CompetitiveService else None

    @staticmethod
    def _badges(summary) -> list[dict[str, str]]:
        badges: list[dict[str, str]] = []
        if summary.tournaments_won:
            badges.append({"icon": "🏆", "label": "Champion"})
        if summary.finals:
            badges.append({"icon": "🥈", "label": "Finaliste"})
        if summary.top4:
            badges.append({"icon": "🎖️", "label": "Top 4"})
        if summary.tournaments_played >= 10:
            badges.append({"icon": "🧓", "label": "Vétéran"})
        if summary.best_streak >= 5:
            badges.append({"icon": "🔥", "label": f"Série x{summary.best_streak}"})
        if summary.most_used_deck:
            badges.append({"icon": "🎴", "label": f"Spécialiste {summary.most_used_deck}"})
        return badges[:8]

    async def build(
        self,
        guild_id: str,
        player_id: str,
        fallback_name: str = "Joueur Hamtaro",
    ) -> dict[str, Any]:
        summary, matches, decks = await self.analytics.get_player_profile(
            guild_id=guild_id,
            player_id=player_id,
            fallback_name=fallback_name,
        )
        opponent_counts: Counter[str] = Counter()
        opponent_losses: Counter[str] = Counter()
        for match in matches:
            p1 = str(match.get("player1_id") or "")
            p2 = str(match.get("player2_id") or "")
            opponent = p2 if p1 == player_id else p1
            if opponent:
                opponent_counts[opponent] += 1
                if str(match.get("winner_id") or "") not in {"", player_id}:
                    opponent_losses[opponent] += 1

        rival = opponent_counts.most_common(1)[0][0] if opponent_counts else None
        nemesis = opponent_losses.most_common(1)[0][0] if opponent_losses else None

        elo = None
        if self.competitive is not None:
            try:
                elo = await self.competitive.player_rating(
                    guild_id, player_id, "Général"
                )
            except Exception:
                elo = None

        return {
            "player_id": player_id,
            "display_name": summary.display_name,
            "avatar_url": summary.avatar_url,
            "badges": self._badges(summary),
            "title": (
                "Champion Hamtaro"
                if summary.tournaments_won else
                "Finaliste Hamtaro"
                if summary.finals else
                "Duelliste Hamtaro"
            ),
            "signature_deck": summary.most_used_deck,
            "best_deck": summary.best_deck,
            "best_deck_win_rate": summary.best_deck_win_rate,
            "matches": summary.matches,
            "wins": summary.wins,
            "losses": summary.losses,
            "win_rate": summary.win_rate,
            "tournaments": summary.tournaments_played,
            "titles": summary.tournaments_won,
            "finals": summary.finals,
            "top4": summary.top4,
            "current_streak": summary.current_streak,
            "best_streak": summary.best_streak,
            "rival_id": rival,
            "nemesis_id": nemesis,
            "elo": elo,
            "decks": [
                {
                    "deck": row.deck,
                    "matches": row.matches,
                    "wins": row.wins,
                    "win_rate": row.win_rate,
                }
                for row in decks[:8]
            ],
        }
