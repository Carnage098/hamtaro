from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.competitive_service import CompetitiveService
from services.expansion_database import (
    expansion_connection,
    normalize_format,
    utcnow_iso,
)


@dataclass(slots=True)
class DashboardData:
    active_tournaments: list[dict[str, Any]]
    next_matches: list[dict[str, Any]]
    pending_results: int
    open_issues: int
    ratings: list[dict[str, Any]]
    achievements: list[dict[str, Any]]
    active_deck: dict[str, Any] | None


class PlayerExperienceService:
    def __init__(self) -> None:
        self.competitive = CompetitiveService()

    async def update_profile(
        self,
        *,
        guild_id: str,
        discord_id: str,
        favorite_formats: str,
        simulators: str,
        availability: str,
        about: str,
    ) -> None:
        async with expansion_connection() as db:
            await db.execute(
                """
                INSERT INTO player_profiles_plus(
                    guild_id, discord_id, favorite_formats,
                    simulators, availability, about, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                    favorite_formats=excluded.favorite_formats,
                    simulators=excluded.simulators,
                    availability=excluded.availability,
                    about=excluded.about,
                    updated_at=excluded.updated_at
                """,
                (
                    guild_id,
                    discord_id,
                    favorite_formats.strip(),
                    simulators.strip(),
                    availability.strip(),
                    about.strip()[:500],
                    utcnow_iso(),
                ),
            )
            await db.commit()

    async def profile(self, guild_id: str, discord_id: str) -> dict[str, Any]:
        async with expansion_connection() as db:
            profile = await (
                await db.execute(
                    """
                    SELECT * FROM player_profiles_plus
                    WHERE guild_id=? AND discord_id=?
                    """,
                    (guild_id, discord_id),
                )
            ).fetchone()
            player = await (
                await db.execute(
                    """
                    SELECT * FROM players
                    WHERE guild_id=? AND discord_id=?
                    """,
                    (guild_id, discord_id),
                )
            ).fetchone()
            tournament_stats = await (
                await db.execute(
                    """
                    SELECT COUNT(DISTINCT r.tournament_id) AS tournaments,
                           SUM(CASE WHEN r.final_rank=1 THEN 1 ELSE 0 END) AS titles,
                           SUM(CASE WHEN r.final_rank=2 THEN 1 ELSE 0 END) AS finals,
                           SUM(CASE WHEN r.final_rank BETWEEN 1 AND 4 THEN 1 ELSE 0 END) AS top4
                    FROM registrations r
                    JOIN tournaments t ON t.id=r.tournament_id
                    WHERE t.guild_id=? AND r.discord_id=?
                    """,
                    (guild_id, discord_id),
                )
            ).fetchone()
            ratings = await (
                await db.execute(
                    """
                    SELECT format, rating, peak_rating, games, wins, losses,
                           current_streak, best_streak
                    FROM competitive_ratings
                    WHERE guild_id=? AND discord_id=?
                    ORDER BY rating DESC, games DESC
                    LIMIT 8
                    """,
                    (guild_id, discord_id),
                )
            ).fetchall()
            achievements = await (
                await db.execute(
                    """
                    SELECT d.code, d.name, d.description, d.emoji, a.unlocked_at
                    FROM player_achievements a
                    JOIN achievement_definitions d ON d.code=a.achievement_code
                    WHERE a.guild_id=? AND a.discord_id=?
                    ORDER BY a.unlocked_at DESC
                    """,
                    (guild_id, discord_id),
                )
            ).fetchall()
            active_deck = await (
                await db.execute(
                    """
                    SELECT * FROM player_decks
                    WHERE guild_id=? AND discord_id=? AND is_active=1
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (guild_id, discord_id),
                )
            ).fetchone()
            return {
                "profile": dict(profile) if profile else {},
                "player": dict(player) if player else {},
                "tournament_stats": dict(tournament_stats) if tournament_stats else {},
                "ratings": [dict(row) for row in ratings],
                "achievements": [dict(row) for row in achievements],
                "active_deck": dict(active_deck) if active_deck else None,
            }

    async def add_deck(
        self,
        *,
        guild_id: str,
        discord_id: str,
        name: str,
        format_name: str,
        simulator: str | None,
        notes: str | None,
    ) -> int:
        cleaned_name = " ".join(word.capitalize() for word in name.split())
        if not cleaned_name:
            raise ValueError("Le nom du deck est vide.")
        now = utcnow_iso()
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO player_decks(
                    guild_id, discord_id, name, format, simulator,
                    notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    discord_id,
                    cleaned_name,
                    normalize_format(format_name),
                    (simulator or "").strip() or None,
                    (notes or "").strip()[:500] or None,
                    now,
                    now,
                ),
            )
            deck_id = int(cursor.lastrowid)
            count_row = await (
                await db.execute(
                    """
                    SELECT COUNT(*) AS total FROM player_decks
                    WHERE guild_id=? AND discord_id=? AND is_active=1
                    """,
                    (guild_id, discord_id),
                )
            ).fetchone()
            if int(count_row["total"]) == 0:
                await db.execute(
                    "UPDATE player_decks SET is_active=1 WHERE id=?",
                    (deck_id,),
                )
            await db.commit()
            return deck_id

    async def list_decks(self, guild_id: str, discord_id: str) -> list[dict[str, Any]]:
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT * FROM player_decks
                    WHERE guild_id=? AND discord_id=?
                    ORDER BY is_active DESC, format, name
                    """,
                    (guild_id, discord_id),
                )
            ).fetchall()
            return [dict(row) for row in rows]

    async def select_deck(self, guild_id: str, discord_id: str, deck_id: int) -> dict[str, Any]:
        async with expansion_connection() as db:
            deck = await (
                await db.execute(
                    """
                    SELECT * FROM player_decks
                    WHERE id=? AND guild_id=? AND discord_id=?
                    """,
                    (deck_id, guild_id, discord_id),
                )
            ).fetchone()
            if deck is None:
                raise ValueError("Deck introuvable.")
            await db.execute(
                "UPDATE player_decks SET is_active=0 WHERE guild_id=? AND discord_id=?",
                (guild_id, discord_id),
            )
            await db.execute(
                "UPDATE player_decks SET is_active=1, updated_at=? WHERE id=?",
                (utcnow_iso(), deck_id),
            )
            await db.commit()
            return dict(deck)

    async def delete_deck(self, guild_id: str, discord_id: str, deck_id: int) -> None:
        async with expansion_connection() as db:
            deck = await (
                await db.execute(
                    """
                    SELECT is_locked FROM player_decks
                    WHERE id=? AND guild_id=? AND discord_id=?
                    """,
                    (deck_id, guild_id, discord_id),
                )
            ).fetchone()
            if deck is None:
                raise ValueError("Deck introuvable.")
            if int(deck["is_locked"]) == 1:
                raise ValueError("Ce deck est verrouillé pendant un tournoi.")
            await db.execute("DELETE FROM player_decks WHERE id=?", (deck_id,))
            await db.commit()

    async def set_deck_lock(
        self,
        guild_id: str,
        discord_id: str,
        deck_id: int,
        locked: bool,
    ) -> None:
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                UPDATE player_decks
                SET is_locked=?, updated_at=?
                WHERE id=? AND guild_id=? AND discord_id=?
                """,
                (1 if locked else 0, utcnow_iso(), deck_id, guild_id, discord_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Deck introuvable.")
            await db.commit()

    async def achievements(self, guild_id: str, discord_id: str) -> list[dict[str, Any]]:
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT d.*, a.unlocked_at, a.progress
                    FROM achievement_definitions d
                    LEFT JOIN player_achievements a
                      ON a.achievement_code=d.code
                     AND a.guild_id=?
                     AND a.discord_id=?
                    WHERE d.secret=0 OR a.unlocked_at IS NOT NULL
                    ORDER BY a.unlocked_at IS NULL, a.unlocked_at DESC, d.name
                    """,
                    (guild_id, discord_id),
                )
            ).fetchall()
            return [dict(row) for row in rows]

    async def set_notifications(
        self,
        *,
        guild_id: str,
        discord_id: str,
        delivery_mode: str,
        next_match: bool,
        new_tournament: bool,
        result_reminder: bool,
        result_confirmation: bool,
        round_change: bool,
        ranking_change: bool,
    ) -> None:
        if delivery_mode not in {"dm", "thread", "none"}:
            raise ValueError("Mode de notification invalide.")
        async with expansion_connection() as db:
            await db.execute(
                """
                INSERT INTO notification_preferences(
                    guild_id, discord_id, next_match, new_tournament,
                    result_reminder, result_confirmation, round_change,
                    ranking_change, delivery_mode, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                    next_match=excluded.next_match,
                    new_tournament=excluded.new_tournament,
                    result_reminder=excluded.result_reminder,
                    result_confirmation=excluded.result_confirmation,
                    round_change=excluded.round_change,
                    ranking_change=excluded.ranking_change,
                    delivery_mode=excluded.delivery_mode,
                    updated_at=excluded.updated_at
                """,
                (
                    guild_id,
                    discord_id,
                    int(next_match),
                    int(new_tournament),
                    int(result_reminder),
                    int(result_confirmation),
                    int(round_change),
                    int(ranking_change),
                    delivery_mode,
                    utcnow_iso(),
                ),
            )
            await db.commit()

    async def notification_preferences(self, guild_id: str, discord_id: str) -> dict[str, Any]:
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    """
                    SELECT * FROM notification_preferences
                    WHERE guild_id=? AND discord_id=?
                    """,
                    (guild_id, discord_id),
                )
            ).fetchone()
            if row:
                return dict(row)
            return {
                "next_match": 1,
                "new_tournament": 1,
                "result_reminder": 1,
                "result_confirmation": 1,
                "round_change": 1,
                "ranking_change": 0,
                "delivery_mode": "thread",
            }

    async def dashboard(self, guild_id: str, discord_id: str) -> DashboardData:
        async with expansion_connection() as db:
            tournaments = await (
                await db.execute(
                    """
                    SELECT DISTINCT t.id, t.code, t.name, t.format, t.status,
                           t.current_round, r.deck
                    FROM registrations r
                    JOIN tournaments t ON t.id=r.tournament_id
                    WHERE t.guild_id=? AND r.discord_id=?
                      AND t.status NOT IN ('finished','cancelled','archived')
                    ORDER BY t.created_at DESC
                    LIMIT 5
                    """,
                    (guild_id, discord_id),
                )
            ).fetchall()

            bracket = await (
                await db.execute(
                    """
                    SELECT 'bracket' AS kind, m.id, m.tournament_id, m.round AS round_number,
                           m.player1_id, m.player2_id, m.player1_name, m.player2_name,
                           m.status, t.name AS tournament_name, t.code
                    FROM matches m
                    JOIN tournaments t ON t.id=m.tournament_id
                    WHERE t.guild_id=?
                      AND ? IN (m.player1_id,m.player2_id)
                      AND m.status IN ('waiting','playing','reported')
                      AND COALESCE(m.is_bye,0)=0
                    ORDER BY m.round, m.id
                    LIMIT 5
                    """,
                    (guild_id, discord_id),
                )
            ).fetchall()
            swiss = await (
                await db.execute(
                    """
                    SELECT 'swiss' AS kind, sm.id, sm.tournament_id,
                           sm.round_number, sm.player1_id, sm.player2_id,
                           sm.player1_name, sm.player2_name, sm.status,
                           t.name AS tournament_name, t.code
                    FROM swiss_matches sm
                    JOIN tournaments t ON t.id=sm.tournament_id
                    WHERE t.guild_id=?
                      AND ? IN (sm.player1_id,sm.player2_id)
                      AND sm.status='pending'
                      AND COALESCE(sm.is_bye,0)=0
                    ORDER BY sm.round_number, sm.table_number
                    LIMIT 5
                    """,
                    (guild_id, discord_id),
                )
            ).fetchall()
            pending_results = await (
                await db.execute(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM matches m JOIN tournaments t ON t.id=m.tournament_id
                       WHERE t.guild_id=? AND ? IN (m.player1_id,m.player2_id) AND m.status='reported')
                      +
                      (SELECT COUNT(*) FROM swiss_matches sm JOIN tournaments t ON t.id=sm.tournament_id
                       WHERE t.guild_id=? AND ? IN (sm.player1_id,sm.player2_id) AND sm.status='completed'
                         AND sm.reported_by IS NOT NULL AND sm.finished_at IS NULL)
                      AS total
                    """,
                    (guild_id, discord_id, guild_id, discord_id),
                )
            ).fetchone()
            issues = await (
                await db.execute(
                    """
                    SELECT COUNT(*) AS total FROM match_issues
                    WHERE guild_id=? AND reporter_id=? AND status IN ('open','reviewing')
                    """,
                    (guild_id, discord_id),
                )
            ).fetchone()
            ratings = await (
                await db.execute(
                    """
                    SELECT format, rating, games, wins, losses, current_streak
                    FROM competitive_ratings
                    WHERE guild_id=? AND discord_id=?
                    ORDER BY rating DESC LIMIT 5
                    """,
                    (guild_id, discord_id),
                )
            ).fetchall()
            achievements = await (
                await db.execute(
                    """
                    SELECT d.name, d.emoji, a.unlocked_at
                    FROM player_achievements a
                    JOIN achievement_definitions d ON d.code=a.achievement_code
                    WHERE a.guild_id=? AND a.discord_id=?
                    ORDER BY a.unlocked_at DESC LIMIT 5
                    """,
                    (guild_id, discord_id),
                )
            ).fetchall()
            active_deck = await (
                await db.execute(
                    """
                    SELECT * FROM player_decks
                    WHERE guild_id=? AND discord_id=? AND is_active=1
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (guild_id, discord_id),
                )
            ).fetchone()

        next_matches = [dict(row) for row in bracket] + [dict(row) for row in swiss]
        next_matches.sort(key=lambda item: (int(item.get("round_number") or 0), int(item.get("id") or 0)))
        return DashboardData(
            active_tournaments=[dict(row) for row in tournaments],
            next_matches=next_matches[:5],
            pending_results=int(pending_results["total"] if pending_results else 0),
            open_issues=int(issues["total"] if issues else 0),
            ratings=[dict(row) for row in ratings],
            achievements=[dict(row) for row in achievements],
            active_deck=dict(active_deck) if active_deck else None,
        )
