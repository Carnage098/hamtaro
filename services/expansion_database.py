from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator, Iterable

import aiosqlite

from config import DATABASE


DEFAULT_RATING = 1000


def utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_format(value: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "Général").strip())
    return cleaned.title() or "Général"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


@asynccontextmanager
async def expansion_connection() -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(str(DATABASE), timeout=30)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON;")
    await db.execute("PRAGMA journal_mode = WAL;")
    await db.execute("PRAGMA synchronous = NORMAL;")
    await db.execute("PRAGMA busy_timeout = 30000;")
    try:
        yield db
    finally:
        await db.close()


async def table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    row = await (
        await db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
    ).fetchone()
    return row is not None


async def columns_for(db: aiosqlite.Connection, table_name: str) -> set[str]:
    if not await table_exists(db, table_name):
        return set()
    rows = await (await db.execute(f"PRAGMA table_info({table_name})")).fetchall()
    return {str(row[1]) for row in rows}


async def ensure_column(
    db: aiosqlite.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    """Ajoute une colonne aux installations déjà existantes, sans perdre de données."""
    if column_name not in await columns_for(db, table_name):
        await db.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )


async def fetchone(
    query: str,
    parameters: Iterable[Any] = (),
) -> aiosqlite.Row | None:
    async with expansion_connection() as db:
        return await (await db.execute(query, tuple(parameters))).fetchone()


async def fetchall(
    query: str,
    parameters: Iterable[Any] = (),
) -> list[aiosqlite.Row]:
    async with expansion_connection() as db:
        rows = await (await db.execute(query, tuple(parameters))).fetchall()
        return list(rows)


async def execute(
    query: str,
    parameters: Iterable[Any] = (),
) -> int:
    async with expansion_connection() as db:
        cursor = await db.execute(query, tuple(parameters))
        await db.commit()
        return int(cursor.lastrowid or 0)


async def init_expansion_schema() -> None:
    async with expansion_connection() as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS expansion_settings (
                guild_id TEXT PRIMARY KEY,
                announcements_channel_id TEXT,
                judge_channel_id TEXT,
                featured_channel_id TEXT,
                featured_voice_channel_id TEXT,
                staff_role_id TEXT,
                judge_role_id TEXT,
                default_format TEXT NOT NULL DEFAULT 'Général',
                elo_enabled INTEGER NOT NULL DEFAULT 1,
                auto_sync_enabled INTEGER NOT NULL DEFAULT 1,
                minimum_ranked_games INTEGER NOT NULL DEFAULT 5,
                updated_by TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS competitive_seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                name TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                ends_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                soft_reset_factor REAL NOT NULL DEFAULT 0.50,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                closed_at TEXT,
                final_summary_sent INTEGER NOT NULL DEFAULT 0,
                CHECK(status IN ('scheduled','active','closed','cancelled'))
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_active_season_per_guild
            ON competitive_seasons(guild_id)
            WHERE status = 'active';

            CREATE TABLE IF NOT EXISTS competitive_ratings (
                guild_id TEXT NOT NULL,
                discord_id TEXT NOT NULL,
                format TEXT NOT NULL,
                season_id INTEGER NOT NULL DEFAULT 0,
                rating INTEGER NOT NULL DEFAULT 1000,
                peak_rating INTEGER NOT NULL DEFAULT 1000,
                games INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                current_streak INTEGER NOT NULL DEFAULT 0,
                best_streak INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(guild_id, discord_id, format, season_id)
            );

            CREATE TABLE IF NOT EXISTS rating_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                discord_id TEXT NOT NULL,
                format TEXT NOT NULL,
                season_id INTEGER NOT NULL DEFAULT 0,
                source_key TEXT NOT NULL,
                opponent_id TEXT,
                old_rating INTEGER NOT NULL,
                new_rating INTEGER NOT NULL,
                delta INTEGER NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(guild_id, discord_id, format, season_id, source_key)
            );

            CREATE TABLE IF NOT EXISTS processed_competitive_matches (
                guild_id TEXT NOT NULL,
                source_key TEXT NOT NULL,
                tournament_id INTEGER,
                format TEXT NOT NULL,
                player1_id TEXT NOT NULL,
                player2_id TEXT NOT NULL,
                winner_id TEXT,
                processed_at TEXT NOT NULL,
                PRIMARY KEY(guild_id, source_key)
            );

            CREATE TABLE IF NOT EXISTS processed_deck_matches (
                guild_id TEXT NOT NULL,
                source_key TEXT NOT NULL,
                discord_id TEXT NOT NULL,
                deck_name TEXT NOT NULL,
                won INTEGER NOT NULL,
                processed_at TEXT NOT NULL,
                PRIMARY KEY(guild_id, source_key, discord_id)
            );

            CREATE TABLE IF NOT EXISTS player_profiles_plus (
                guild_id TEXT NOT NULL,
                discord_id TEXT NOT NULL,
                favorite_formats TEXT NOT NULL DEFAULT '',
                simulators TEXT NOT NULL DEFAULT '',
                availability TEXT NOT NULL DEFAULT '',
                about TEXT NOT NULL DEFAULT '',
                active_deck_id INTEGER,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(guild_id, discord_id)
            );

            CREATE TABLE IF NOT EXISTS player_decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                discord_id TEXT NOT NULL,
                name TEXT NOT NULL,
                format TEXT NOT NULL,
                simulator TEXT,
                notes TEXT,
                is_active INTEGER NOT NULL DEFAULT 0,
                is_locked INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                matches INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(guild_id, discord_id, name, format)
            );

            CREATE TABLE IF NOT EXISTS achievement_definitions (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                emoji TEXT NOT NULL,
                secret INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS player_achievements (
                guild_id TEXT NOT NULL,
                discord_id TEXT NOT NULL,
                achievement_code TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 1,
                unlocked_at TEXT NOT NULL,
                source_key TEXT,
                PRIMARY KEY(guild_id, discord_id, achievement_code),
                FOREIGN KEY(achievement_code)
                    REFERENCES achievement_definitions(code)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS casual_result_requests_plus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                casual_table TEXT NOT NULL,
                casual_match_id INTEGER NOT NULL,
                reporter_id TEXT NOT NULL,
                winner_id TEXT NOT NULL,
                loser_id TEXT NOT NULL,
                score TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                confirmed_by TEXT,
                contested_by TEXT,
                contest_reason TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                CHECK(status IN ('pending','confirmed','contested','cancelled'))
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_casual_pending_result
            ON casual_result_requests_plus(casual_table, casual_match_id)
            WHERE status='pending';

            CREATE TABLE IF NOT EXISTS notification_preferences (
                guild_id TEXT NOT NULL,
                discord_id TEXT NOT NULL,
                next_match INTEGER NOT NULL DEFAULT 1,
                new_tournament INTEGER NOT NULL DEFAULT 1,
                result_reminder INTEGER NOT NULL DEFAULT 1,
                result_confirmation INTEGER NOT NULL DEFAULT 1,
                round_change INTEGER NOT NULL DEFAULT 1,
                ranking_change INTEGER NOT NULL DEFAULT 0,
                delivery_mode TEXT NOT NULL DEFAULT 'thread',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(guild_id, discord_id),
                CHECK(delivery_mode IN ('dm','thread','none'))
            );

            CREATE TABLE IF NOT EXISTS notification_deliveries (
                guild_id TEXT NOT NULL,
                discord_id TEXT NOT NULL,
                event_key TEXT NOT NULL,
                event_type TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY(guild_id, discord_id, event_key)
            );

            CREATE TABLE IF NOT EXISTS judge_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER,
                channel_id TEXT NOT NULL,
                thread_id TEXT,
                reporter_id TEXT NOT NULL,
                opponent_id TEXT,
                reason TEXT NOT NULL,
                details TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                assigned_to TEXT,
                resolution TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                CHECK(status IN ('open','assigned','resolved','cancelled'))
            );

            CREATE TABLE IF NOT EXISTS match_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER,
                source_kind TEXT,
                match_id INTEGER,
                reporter_id TEXT NOT NULL,
                opponent_id TEXT,
                issue_type TEXT NOT NULL,
                details TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                first_contact_at TEXT,
                requested_until TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                CHECK(issue_type IN ('no_response','delay','forfeit','connection','other')),
                CHECK(status IN ('open','reviewing','resolved','cancelled'))
            );

            CREATE TABLE IF NOT EXISTS tournament_waitlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER NOT NULL,
                discord_id TEXT NOT NULL,
                username TEXT NOT NULL,
                deck_name TEXT,
                status TEXT NOT NULL DEFAULT 'waiting',
                position INTEGER NOT NULL,
                joined_at TEXT NOT NULL,
                offered_at TEXT,
                offer_expires_at TEXT,
                promoted_at TEXT,
                UNIQUE(tournament_id, discord_id),
                CHECK(status IN ('waiting','offered','promoted','expired','cancelled'))
            );

            CREATE TABLE IF NOT EXISTS tournament_templates_plus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                name TEXT NOT NULL,
                tournament_name TEXT NOT NULL,
                format TEXT NOT NULL,
                tournament_type TEXT NOT NULL,
                max_players INTEGER NOT NULL,
                total_rounds INTEGER,
                best_of TEXT NOT NULL DEFAULT 'BO3',
                rules TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(guild_id, name)
            );

            CREATE TABLE IF NOT EXISTS scheduled_tournaments_plus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER,
                template_id INTEGER,
                channel_id TEXT NOT NULL,
                announce_at TEXT,
                reminder_at TEXT,
                start_prompt_at TEXT,
                status TEXT NOT NULL DEFAULT 'scheduled',
                announcement_sent INTEGER NOT NULL DEFAULT 0,
                reminder_sent INTEGER NOT NULL DEFAULT 0,
                start_prompt_sent INTEGER NOT NULL DEFAULT 0,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                CHECK(status IN ('scheduled','completed','cancelled'))
            );

            CREATE TABLE IF NOT EXISTS featured_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER,
                source_kind TEXT NOT NULL,
                match_id INTEGER NOT NULL,
                channel_id TEXT NOT NULL,
                voice_channel_id TEXT,
                player1_id TEXT,
                player2_id TEXT,
                stream_url TEXT,
                commentators TEXT,
                title TEXT,
                status TEXT NOT NULL DEFAULT 'announced',
                message_id TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                CHECK(source_kind IN ('bracket','swiss','casual')),
                CHECK(status IN ('announced','live','finished','cancelled'))
            );

            CREATE TABLE IF NOT EXISTS season_ranking_snapshots (
                season_id INTEGER NOT NULL,
                guild_id TEXT NOT NULL,
                format TEXT NOT NULL,
                rank INTEGER NOT NULL,
                discord_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                rating INTEGER NOT NULL,
                games INTEGER NOT NULL,
                wins INTEGER NOT NULL,
                losses INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(season_id, format, rank)
            );

            CREATE TABLE IF NOT EXISTS featured_match_checkins (
                featured_match_id INTEGER NOT NULL,
                discord_id TEXT NOT NULL,
                ready INTEGER NOT NULL DEFAULT 0,
                in_voice INTEGER NOT NULL DEFAULT 0,
                streaming INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(featured_match_id, discord_id),
                FOREIGN KEY(featured_match_id)
                    REFERENCES featured_matches(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS community_polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message_id TEXT,
                question TEXT NOT NULL,
                options_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                multiple_choice INTEGER NOT NULL DEFAULT 0,
                closes_at TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                closed_at TEXT,
                CHECK(status IN ('open','closed','cancelled'))
            );

            CREATE TABLE IF NOT EXISTS community_poll_votes (
                poll_id INTEGER NOT NULL,
                discord_id TEXT NOT NULL,
                option_index INTEGER NOT NULL,
                voted_at TEXT NOT NULL,
                PRIMARY KEY(poll_id, discord_id, option_index),
                FOREIGN KEY(poll_id)
                    REFERENCES community_polls(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS pending_tournament_starts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER NOT NULL,
                tournament_type TEXT NOT NULL,
                total_rounds INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_by TEXT NOT NULL,
                channel_id TEXT,
                message_id TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                confirmed_at TEXT,
                confirmed_by TEXT,
                CHECK(tournament_type IN ('single_elimination','swiss')),
                CHECK(status IN ('pending','confirmed','cancelled'))
            );

            CREATE TABLE IF NOT EXISTS pending_tournament_players (
                pending_id INTEGER NOT NULL,
                seed INTEGER NOT NULL,
                discord_id TEXT NOT NULL,
                username TEXT NOT NULL,
                PRIMARY KEY(pending_id, discord_id),
                UNIQUE(pending_id, seed),
                FOREIGN KEY(pending_id)
                    REFERENCES pending_tournament_starts(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS pending_tournament_pairings (
                pending_id INTEGER NOT NULL,
                round_number INTEGER NOT NULL,
                table_number INTEGER NOT NULL,
                player1_id TEXT NOT NULL,
                player1_name TEXT NOT NULL,
                player2_id TEXT,
                player2_name TEXT,
                is_bye INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(pending_id, round_number, table_number),
                FOREIGN KEY(pending_id)
                    REFERENCES pending_tournament_starts(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS extension_action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                actor_id TEXT NOT NULL,
                before_json TEXT,
                after_json TEXT,
                reversible INTEGER NOT NULL DEFAULT 0,
                reverted_at TEXT,
                reverted_by TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_rating_rank
            ON competitive_ratings(guild_id, format, season_id, rating DESC);
            CREATE INDEX IF NOT EXISTS idx_rating_history_player
            ON rating_history(guild_id, discord_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_waitlist_order
            ON tournament_waitlist(tournament_id, status, position);
            CREATE INDEX IF NOT EXISTS idx_notification_deliveries_player
            ON notification_deliveries(guild_id, discord_id, sent_at DESC);
            CREATE INDEX IF NOT EXISTS idx_judge_calls_status
            ON judge_calls(guild_id, status, created_at);
            CREATE INDEX IF NOT EXISTS idx_schedules_due
            ON scheduled_tournaments_plus(status, announce_at, reminder_at, start_prompt_at);
            CREATE INDEX IF NOT EXISTS idx_polls_status
            ON community_polls(guild_id, status, closes_at);
            CREATE INDEX IF NOT EXISTS idx_season_snapshot_lookup
            ON season_ranking_snapshots(guild_id, season_id, format, rank);
            CREATE INDEX IF NOT EXISTS idx_featured_voice_status
            ON featured_match_checkins(featured_match_id, ready, in_voice, streaming);
            CREATE INDEX IF NOT EXISTS idx_pending_tournament_start
            ON pending_tournament_starts(tournament_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_pending_tournament_pairings
            ON pending_tournament_pairings(pending_id, round_number, table_number);
            """
        )

        # Migrations non destructives pour les serveurs ayant déjà installé une version antérieure.
        await ensure_column(db, "expansion_settings", "featured_voice_channel_id", "TEXT")
        await ensure_column(
            db, "expansion_settings", "minimum_ranked_games", "INTEGER NOT NULL DEFAULT 5"
        )
        await ensure_column(
            db, "competitive_seasons", "final_summary_sent", "INTEGER NOT NULL DEFAULT 0"
        )
        await ensure_column(db, "featured_matches", "voice_channel_id", "TEXT")
        await ensure_column(db, "featured_matches", "player1_id", "TEXT")
        await ensure_column(db, "featured_matches", "player2_id", "TEXT")

        definitions = [
            ("first_duel", "Premier duel", "Terminer son premier match classé.", "⚔️", 0),
            ("ten_tournaments", "Habitué du bracket", "Participer à dix tournois.", "🏟️", 0),
            ("five_streak", "Invincible", "Atteindre cinq victoires consécutives.", "🔥", 0),
            ("bo5_master", "Maître du BO5", "Remporter un match au format BO5.", "👑", 0),
            ("versatile", "Polyvalent", "Jouer dans cinq formats différents.", "🌈", 0),
            ("champion", "Champion Hamtaro", "Remporter un tournoi Hamtaro.", "🏆", 0),
            ("giant_killer", "Chasseur de géants", "Battre un adversaire avec au moins 150 points ELO de plus.", "🗡️", 0),
            ("hundred_games", "Centurion", "Terminer cent matchs classés.", "💯", 0),
        ]
        await db.executemany(
            """
            INSERT OR IGNORE INTO achievement_definitions(
                code, name, description, emoji, secret
            ) VALUES (?, ?, ?, ?, ?)
            """,
            definitions,
        )
        await db.commit()
