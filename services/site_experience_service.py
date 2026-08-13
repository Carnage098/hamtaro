from __future__ import annotations

from collections import Counter
from typing import Any

from services.competitive_service import CompetitiveService, MIN_OFFICIAL_GAMES
from services.expansion_database import (
    columns_for,
    expansion_connection,
    normalize_format,
    table_exists,
)
from services.player_experience_service import PlayerExperienceService


ACTIVE_MATCH_STATUSES = {"waiting", "playing", "pending", "scheduled", "in_progress"}
VALIDATION_MATCH_STATUSES = {"reported", "pending_validation", "validation"}
FINISHED_MATCH_STATUSES = {"validated", "completed", "cancelled"}


def _dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


class SiteExperienceService:
    """Données publiques enrichies du site Hamtaro.

    Toutes les méthodes sont en lecture seule. Elles tolèrent les anciennes
    installations : lorsqu'une table facultative n'existe pas encore, la page
    concernée est rendue avec une section vide plutôt qu'une erreur 500.
    """

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.competitive = CompetitiveService()
        self.players = PlayerExperienceService()

    async def live_matches(
        self,
        guild_id: str,
        *,
        limit: int = 300,
    ) -> dict[str, Any]:
        """Retourne les matchs publics à jouer ou en validation.

        Les requêtes sont construites à partir des colonnes réellement
        présentes dans SQLite. Une ancienne base Railway ne doit donc plus
        provoquer une erreur 500 lorsqu'une colonne facultative manque.
        """

        matches: list[dict[str, Any]] = []
        limit = max(1, min(int(limit), 500))

        async with expansion_connection() as db:
            has_tournaments = await table_exists(db, "tournaments")
            tournament_columns = (
                await columns_for(db, "tournaments")
                if has_tournaments
                else set()
            )

            # ------------------------------------------------------
            # MATCHS À ÉLIMINATION DIRECTE
            # ------------------------------------------------------
            if has_tournaments and await table_exists(db, "matches"):
                match_columns = await columns_for(db, "matches")
                required = {
                    "id",
                    "tournament_id",
                    "player1_id",
                    "player2_id",
                }

                if required.issubset(match_columns):
                    def bracket_column(
                        name: str,
                        fallback: str = "NULL",
                    ) -> str:
                        return (
                            f"m.{name}"
                            if name in match_columns
                            else fallback
                        )

                    tournament_type_sql = (
                        "t.tournament_type"
                        if "tournament_type" in tournament_columns
                        else "'single_elimination'"
                    )
                    status_sql = bracket_column(
                        "status",
                        "'waiting'",
                    )
                    round_sql = bracket_column("round", "0")
                    match_number_sql = bracket_column(
                        "match_number",
                        "0",
                    )
                    player1_name_sql = bracket_column(
                        "player1_name",
                        "'Joueur 1'",
                    )
                    player2_name_sql = bracket_column(
                        "player2_name",
                        "'Joueur 2'",
                    )
                    player1_score_sql = bracket_column(
                        "player1_score",
                        "0",
                    )
                    player2_score_sql = bracket_column(
                        "player2_score",
                        "0",
                    )
                    score_sql = bracket_column("score")
                    reported_by_sql = bracket_column("reported_by")
                    reported_at_sql = bracket_column("reported_at")
                    created_at_sql = bracket_column(
                        "created_at",
                        "CURRENT_TIMESTAMP",
                    )

                    bye_filter = (
                        "AND COALESCE(m.is_bye, 0)=0"
                        if "is_bye" in match_columns
                        else ""
                    )
                    status_filter = (
                    """
                      AND m.status IN (
                          'waiting',
                          'playing',
                          'pending',
                          'scheduled',
                          'in_progress',
                          'reported',
                          'pending_validation',
                          'validation'
                      )
                    """
                    if "status" in match_columns
                    else ""
                )
                    order_date_sql = (
                        "COALESCE(m.reported_at, m.created_at)"
                        if {
                            "reported_at",
                            "created_at",
                        }.issubset(match_columns)
                        else (
                            "m.reported_at"
                            if "reported_at" in match_columns
                            else (
                                "m.created_at"
                                if "created_at" in match_columns
                                else "m.id"
                            )
                        )
                    )

                    rows = await (
                        await db.execute(
                            f"""
                            SELECT
                                m.id AS match_id,
                                'bracket' AS match_type,
                                {status_sql} AS status,
                                {round_sql} AS round_number,
                                {match_number_sql} AS match_number,
                                m.player1_id,
                                {player1_name_sql} AS player1_name,
                                m.player2_id,
                                {player2_name_sql} AS player2_name,
                                {player1_score_sql} AS player1_score,
                                {player2_score_sql} AS player2_score,
                                {score_sql} AS score,
                                {reported_by_sql} AS reported_by,
                                {reported_at_sql} AS reported_at,
                                {created_at_sql} AS created_at,
                                t.id AS tournament_id,
                                t.code AS tournament_code,
                                t.name AS tournament_name,
                                t.format,
                                {tournament_type_sql}
                                    AS tournament_type,
                                t.status AS tournament_status
                            FROM matches m
                            JOIN tournaments t
                              ON t.id=m.tournament_id
                            WHERE t.guild_id=?
                              {bye_filter}
                              {status_filter}
                            ORDER BY
                                CASE {status_sql}
                                    WHEN 'reported' THEN 0
                                    WHEN 'pending_validation' THEN 0
                                    WHEN 'validation' THEN 0
                                    WHEN 'playing' THEN 1
                                    ELSE 2
                                END,
                                {order_date_sql} DESC,
                                m.id DESC
                            LIMIT ?
                            """,
                            (guild_id, limit),
                        )
                    ).fetchall()

                    for row in rows:
                        item = dict(row)
                        item["reference"] = (
                            f"bracket:{item['match_id']}"
                        )
                        item["round_label"] = (
                            f"Ronde "
                            f"{item.get('round_number') or '?'}"
                        )
                        item["score_display"] = (
                            item.get("score")
                            or (
                                f"{_safe_int(item.get('player1_score'))}"
                                f"-"
                                f"{_safe_int(item.get('player2_score'))}"
                            )
                        )
                        item["stage"] = (
                            "validation"
                            if (
                                str(
                                    item.get("status") or ""
                                ).lower()
                                in VALIDATION_MATCH_STATUSES
                                or item.get("reported_at")
                            )
                            else "waiting"
                        )
                        matches.append(item)

            # ------------------------------------------------------
            # MATCHS SUISSES
            # ------------------------------------------------------
            if (
                has_tournaments
                and await table_exists(db, "swiss_matches")
            ):
                swiss_columns = await columns_for(
                    db,
                    "swiss_matches",
                )
                required = {
                    "id",
                    "tournament_id",
                    "player1_id",
                    "player2_id",
                }

                if required.issubset(swiss_columns):
                    def swiss_column(
                        name: str,
                        fallback: str = "NULL",
                    ) -> str:
                        return (
                            f"sm.{name}"
                            if name in swiss_columns
                            else fallback
                        )

                    tournament_type_sql = (
                        "t.tournament_type"
                        if "tournament_type" in tournament_columns
                        else "'swiss'"
                    )
                    status_sql = swiss_column(
                        "status",
                        "'pending'",
                    )
                    round_sql = swiss_column(
                        "round_number",
                        "0",
                    )
                    table_sql = swiss_column(
                        "table_number",
                        "0",
                    )
                    player1_name_sql = swiss_column(
                        "player1_name",
                        "'Joueur 1'",
                    )
                    player2_name_sql = swiss_column(
                        "player2_name",
                        "'Joueur 2'",
                    )
                    player1_score_sql = swiss_column(
                        "player1_score",
                        "0",
                    )
                    player2_score_sql = swiss_column(
                        "player2_score",
                        "0",
                    )
                    reported_by_sql = swiss_column(
                        "reported_by",
                    )
                    reported_at_sql = swiss_column(
                        "reported_at",
                    )
                    created_at_sql = swiss_column(
                        "created_at",
                        "CURRENT_TIMESTAMP",
                    )

                    bye_filter = (
                        "AND COALESCE(sm.is_bye, 0)=0"
                        if "is_bye" in swiss_columns
                        else ""
                    )
                    status_filter = (
                        """
                          AND sm.status NOT IN (
                              'completed',
                              'validated',
                              'cancelled'
                          )
                        """
                        if "status" in swiss_columns
                        else ""
                    )
                    order_date_sql = (
                        "COALESCE(sm.reported_at, sm.created_at)"
                        if {
                            "reported_at",
                            "created_at",
                        }.issubset(swiss_columns)
                        else (
                            "sm.reported_at"
                            if "reported_at" in swiss_columns
                            else (
                                "sm.created_at"
                                if "created_at" in swiss_columns
                                else "sm.id"
                            )
                        )
                    )

                    rows = await (
                        await db.execute(
                            f"""
                            SELECT
                                sm.id AS match_id,
                                'swiss' AS match_type,
                                {status_sql} AS status,
                                {round_sql} AS round_number,
                                {table_sql} AS match_number,
                                sm.player1_id,
                                {player1_name_sql} AS player1_name,
                                sm.player2_id,
                                {player2_name_sql} AS player2_name,
                                {player1_score_sql}
                                    AS player1_score,
                                {player2_score_sql}
                                    AS player2_score,
                                NULL AS score,
                                {reported_by_sql} AS reported_by,
                                {reported_at_sql} AS reported_at,
                                {created_at_sql} AS created_at,
                                t.id AS tournament_id,
                                t.code AS tournament_code,
                                t.name AS tournament_name,
                                t.format,
                                {tournament_type_sql}
                                    AS tournament_type,
                                t.status AS tournament_status
                            FROM swiss_matches sm
                            JOIN tournaments t
                              ON t.id=sm.tournament_id
                            WHERE t.guild_id=?
                              {bye_filter}
                              {status_filter}
                            ORDER BY
                                CASE
                                    WHEN {reported_at_sql}
                                         IS NOT NULL
                                    THEN 0
                                    ELSE 1
                                END,
                                {order_date_sql} DESC,
                                sm.id DESC
                            LIMIT ?
                            """,
                            (guild_id, limit),
                        )
                    ).fetchall()

                    for row in rows:
                        item = dict(row)
                        item["reference"] = (
                            f"swiss:{item['match_id']}"
                        )
                        item["round_label"] = (
                            f"Ronde "
                            f"{item.get('round_number') or '?'}"
                            f" · Table "
                            f"{item.get('match_number') or '?'}"
                        )
                        item["score_display"] = (
                            f"{_safe_int(item.get('player1_score'))}"
                            f"-"
                            f"{_safe_int(item.get('player2_score'))}"
                        )
                        item["stage"] = (
                            "validation"
                            if item.get("reported_at")
                            else "waiting"
                        )
                        matches.append(item)

        matches.sort(
            key=lambda item: (
                0 if item.get("stage") == "validation" else 1,
                str(
                    item.get("reported_at")
                    or item.get("created_at")
                    or ""
                ),
                _safe_int(item.get("match_id")),
            ),
            reverse=False,
        )

        waiting = [
            item
            for item in matches
            if item.get("stage") == "waiting"
        ]
        validation = [
            item
            for item in matches
            if item.get("stage") == "validation"
        ]

        tournaments: dict[int, dict[str, Any]] = {}
        for item in matches:
            tournament_id = _safe_int(
                item.get("tournament_id")
            )
            tournaments[tournament_id] = {
                "id": tournament_id,
                "name": item.get("tournament_name"),
                "code": item.get("tournament_code"),
                "format": item.get("format"),
            }

        formats = sorted(
            {
                str(item.get("format") or "Non renseigné")
                for item in matches
            },
            key=str.casefold,
        )

        return {
            "waiting": waiting,
            "validation": validation,
            "all": matches,
            "counts": {
                "waiting": len(waiting),
                "validation": len(validation),
                "total": len(matches),
            },
            "tournaments": sorted(
                tournaments.values(),
                key=lambda item: str(
                    item.get("name") or ""
                ).casefold(),
            ),
            "formats": formats,
        }

    async def competitive_dashboard(
        self,
        guild_id: str,
        selected_format: str = "Général",
    ) -> dict[str, Any]:
        selected_format = normalize_format(selected_format)
        season = await self.competitive.display_season(guild_id)
        season_id = _safe_int(season.get("id"))
        rankings = await self.competitive.ranking(
            guild_id,
            selected_format,
            limit=100,
            season_id=season_id,
            official_only=True,
        )
        provisional = await self.competitive.ranking(
            guild_id,
            selected_format,
            limit=100,
            season_id=season_id,
            official_only=False,
        )
        provisional = [
            row for row in provisional
            if _safe_int(row.get("games")) < MIN_OFFICIAL_GAMES
        ]

        formats: list[str] = []
        recent_changes: list[dict[str, Any]] = []
        async with expansion_connection() as db:
            if await table_exists(db, "competitive_ratings"):
                format_rows = await (
                    await db.execute(
                        """
                        SELECT DISTINCT format
                        FROM competitive_ratings
                        WHERE guild_id=?
                        ORDER BY format
                        """,
                        (guild_id,),
                    )
                ).fetchall()
                formats = [str(row["format"]) for row in format_rows]

            if await table_exists(db, "rating_history"):
                recent_rows = await (
                    await db.execute(
                        """
                        SELECT
                            h.discord_id,
                            COALESCE(p.display_name, p.username, h.discord_id) AS player_name,
                            h.format,
                            h.old_rating,
                            h.new_rating,
                            h.delta,
                            h.result,
                            h.created_at
                        FROM rating_history h
                        LEFT JOIN players p
                          ON p.guild_id=h.guild_id
                         AND p.discord_id=h.discord_id
                        WHERE h.guild_id=?
                          AND (?='Général' OR h.format=?)
                          AND h.season_id=?
                        ORDER BY h.id DESC
                        LIMIT 12
                        """,
                        (guild_id, selected_format, selected_format, season_id),
                    )
                ).fetchall()
                recent_changes = _dicts(recent_rows)

        if "Général" not in formats:
            formats.insert(0, "Général")
        if selected_format not in formats:
            formats.append(selected_format)

        total_games = sum(_safe_int(row.get("games")) for row in rankings)
        total_matches = total_games // 2
        average_rating = (
            round(
                sum(_safe_int(row.get("rating")) for row in rankings)
                / len(rankings)
            )
            if rankings else 1000
        )
        return {
            "season": season,
            "season_id": season_id,
            "selected_format": selected_format,
            "formats": formats,
            "rankings": rankings,
            "podium": rankings[:3],
            "provisional": provisional[:12],
            "recent_changes": recent_changes,
            "stats": {
                "official_players": len(rankings),
                "provisional_players": len(provisional),
                "matches": total_matches,
                "average_rating": average_rating,
                "minimum_games": MIN_OFFICIAL_GAMES,
            },
        }

    async def seasons_dashboard(self, guild_id: str) -> dict[str, Any]:
        seasons: list[dict[str, Any]] = []
        async with expansion_connection() as db:
            if await table_exists(db, "competitive_seasons"):
                rows = await (
                    await db.execute(
                        """
                        SELECT *
                        FROM competitive_seasons
                        WHERE guild_id=?
                        ORDER BY
                            CASE status
                                WHEN 'active' THEN 0
                                WHEN 'scheduled' THEN 1
                                WHEN 'closed' THEN 2
                                ELSE 3
                            END,
                            id DESC
                        """,
                        (guild_id,),
                    )
                ).fetchall()
                seasons = _dicts(rows)

        enriched: list[dict[str, Any]] = []
        for season in seasons:
            season_id = _safe_int(season.get("id"))
            status = str(season.get("status") or "").lower()
            try:
                summary = await self.competitive.season_summary(
                    guild_id,
                    season_id,
                )

                # Les snapshots n'existent qu'après la clôture. Pour une
                # saison active, on construit donc le podium et les champions
                # depuis les cotes actuellement enregistrées.
                if status != "closed":
                    podium = await self.competitive.season_ranking(
                        guild_id,
                        season_id,
                        "Général",
                        limit=3,
                    )
                    summary["podium"] = podium[:3]
                    summary["qualified_players"] = len(
                        await self.competitive.season_ranking(
                            guild_id,
                            season_id,
                            "Général",
                            limit=100,
                        )
                    )

                    format_champions: list[dict[str, Any]] = []
                    async with expansion_connection() as db:
                        if await table_exists(db, "competitive_ratings"):
                            format_rows = await (
                                await db.execute(
                                    """
                                    SELECT DISTINCT format
                                    FROM competitive_ratings
                                    WHERE guild_id=? AND season_id=? AND games>0
                                    ORDER BY format
                                    """,
                                    (guild_id, season_id),
                                )
                            ).fetchall()
                            for format_row in format_rows:
                                format_name = str(format_row["format"])
                                leaders = await self.competitive.season_ranking(
                                    guild_id,
                                    season_id,
                                    format_name,
                                    limit=1,
                                )
                                if leaders:
                                    champion = dict(leaders[0])
                                    champion["format"] = format_name
                                    format_champions.append(champion)
                    summary["format_champions"] = format_champions

            except (ValueError, KeyError):
                summary = {
                    "season": season,
                    "podium": [],
                    "format_champions": [],
                    "qualified_players": 0,
                    "players": 0,
                    "matches": 0,
                    "minimum_games": MIN_OFFICIAL_GAMES,
                }
            enriched.append(summary)

        return {
            "active": [
                item for item in enriched
                if str(item.get("season", {}).get("status")) == "active"
            ],
            "scheduled": [
                item for item in enriched
                if str(item.get("season", {}).get("status")) == "scheduled"
            ],
            "closed": [
                item for item in enriched
                if str(item.get("season", {}).get("status")) == "closed"
            ],
            "all": enriched,
        }

    async def enriched_profile(
        self,
        guild_id: str,
        discord_id: str,
    ) -> dict[str, Any]:
        base = await self.players.profile(guild_id, discord_id)
        player = dict(base.get("player") or {})
        profile = dict(base.get("profile") or {})
        ratings = list(base.get("ratings") or [])
        achievements = list(base.get("achievements") or [])
        active_deck = base.get("active_deck")
        tournament_stats = dict(base.get("tournament_stats") or {})

        recent_matches: list[dict[str, Any]] = []
        rating_history: list[dict[str, Any]] = []
        decks: list[dict[str, Any]] = []
        season = await self.competitive.display_season(guild_id)
        season_id = _safe_int(season.get("id"))

        async with expansion_connection() as db:
            if await table_exists(db, "competitive_ratings"):
                current_rating_rows = await (
                    await db.execute(
                        """
                        SELECT format, rating, peak_rating, games, wins, losses,
                               current_streak, best_streak, updated_at
                        FROM competitive_ratings
                        WHERE guild_id=? AND discord_id=? AND season_id=?
                        ORDER BY rating DESC, games DESC
                        LIMIT 30
                        """,
                        (guild_id, discord_id, season_id),
                    )
                ).fetchall()
                ratings = _dicts(current_rating_rows)
            if await table_exists(db, "player_decks"):
                deck_rows = await (
                    await db.execute(
                        """
                        SELECT *
                        FROM player_decks
                        WHERE guild_id=? AND discord_id=?
                        ORDER BY is_active DESC, matches DESC, updated_at DESC
                        LIMIT 20
                        """,
                        (guild_id, discord_id),
                    )
                ).fetchall()
                decks = _dicts(deck_rows)

            if await table_exists(db, "rating_history"):
                history_rows = await (
                    await db.execute(
                        """
                        SELECT *
                        FROM rating_history
                        WHERE guild_id=? AND discord_id=? AND season_id=?
                        ORDER BY id DESC
                        LIMIT 30
                        """,
                        (guild_id, discord_id, season_id),
                    )
                ).fetchall()
                rating_history = _dicts(history_rows)

            if await table_exists(db, "matches") and await table_exists(db, "tournaments"):
                bracket_rows = await (
                    await db.execute(
                        """
                        SELECT
                            m.id AS match_id,
                            'bracket' AS match_type,
                            m.player1_id,
                            m.player1_name,
                            m.player2_id,
                            m.player2_name,
                            m.winner_id,
                            m.winner_name,
                            m.score,
                            m.status,
                            COALESCE(m.validated_at, m.reported_at, m.created_at) AS played_at,
                            t.id AS tournament_id,
                            t.name AS tournament_name,
                            t.code AS tournament_code,
                            t.format
                        FROM matches m
                        JOIN tournaments t ON t.id=m.tournament_id
                        WHERE t.guild_id=?
                          AND (m.player1_id=? OR m.player2_id=?)
                          AND m.status IN ('validated','completed')
                          AND COALESCE(m.is_bye, 0)=0
                        ORDER BY COALESCE(m.validated_at, m.reported_at, m.created_at) DESC
                        LIMIT 20
                        """,
                        (guild_id, discord_id, discord_id),
                    )
                ).fetchall()
                recent_matches.extend(_dicts(bracket_rows))

            if await table_exists(db, "swiss_matches") and await table_exists(db, "tournaments"):
                swiss_columns = await columns_for(db, "swiss_matches")
                date_expr = (
                    "COALESCE(sm.finished_at, sm.reported_at, sm.created_at)"
                    if {"finished_at", "reported_at"}.issubset(swiss_columns)
                    else (
                        "COALESCE(sm.reported_at, sm.created_at)"
                        if "reported_at" in swiss_columns
                        else "sm.created_at"
                    )
                )
                swiss_rows = await (
                    await db.execute(
                        f"""
                        SELECT
                            sm.id AS match_id,
                            'swiss' AS match_type,
                            sm.player1_id,
                            sm.player1_name,
                            sm.player2_id,
                            sm.player2_name,
                            sm.winner_id,
                            sm.winner_name,
                            (CAST(sm.player1_score AS TEXT) || '-' ||
                             CAST(sm.player2_score AS TEXT)) AS score,
                            sm.status,
                            {date_expr} AS played_at,
                            t.id AS tournament_id,
                            t.name AS tournament_name,
                            t.code AS tournament_code,
                            t.format
                        FROM swiss_matches sm
                        JOIN tournaments t ON t.id=sm.tournament_id
                        WHERE t.guild_id=?
                          AND (sm.player1_id=? OR sm.player2_id=?)
                          AND sm.status='completed'
                          AND COALESCE(sm.is_bye, 0)=0
                        ORDER BY {date_expr} DESC
                        LIMIT 20
                        """,
                        (guild_id, discord_id, discord_id),
                    )
                ).fetchall()
                recent_matches.extend(_dicts(swiss_rows))

        recent_matches.sort(
            key=lambda item: str(item.get("played_at") or ""),
            reverse=True,
        )
        recent_matches = recent_matches[:20]

        form: list[str] = []
        for match in recent_matches[:8]:
            winner_id = str(match.get("winner_id") or "")
            form.append("V" if winner_id == discord_id else "D")

        total_wins = sum(_safe_int(row.get("wins")) for row in ratings)
        total_losses = sum(_safe_int(row.get("losses")) for row in ratings)
        if not ratings:
            total_wins = _safe_int(player.get("wins"))
            total_losses = _safe_int(player.get("losses"))
        total_games = total_wins + total_losses
        win_rate = round((total_wins / total_games) * 100, 1) if total_games else 0.0

        for match in recent_matches:
            if str(match.get("player1_id") or "") == discord_id:
                match["opponent_id"] = match.get("player2_id")
                match["opponent_name"] = match.get("player2_name") or "Adversaire"
            else:
                match["opponent_id"] = match.get("player1_id")
                match["opponent_name"] = match.get("player1_name") or "Adversaire"
            match["result_label"] = (
                "Victoire"
                if str(match.get("winner_id") or "") == discord_id
                else "Défaite"
            )
            match["reference"] = f"{match.get('match_type')}:{match.get('match_id')}"

        best_rating = max(
            (_safe_int(row.get("rating")) for row in ratings),
            default=1000,
        )
        peak_rating = max(
            (_safe_int(row.get("peak_rating")) for row in ratings),
            default=best_rating,
        )
        general_rating = next(
            (
                _safe_int(row.get("rating"))
                for row in ratings
                if normalize_format(str(row.get("format"))) == "Général"
            ),
            best_rating,
        )

        return {
            "discord_id": discord_id,
            "player": player,
            "profile": profile,
            "ratings": ratings,
            "achievements": achievements,
            "active_deck": active_deck,
            "decks": decks,
            "tournament_stats": tournament_stats,
            "recent_matches": recent_matches,
            "rating_history": list(reversed(rating_history)),
            "form": form,
            "season": season,
            "summary": {
                "wins": total_wins,
                "losses": total_losses,
                "games": total_games,
                "win_rate": win_rate,
                "general_rating": general_rating,
                "peak_rating": peak_rating,
                "tournaments": _safe_int(tournament_stats.get("tournaments")),
                "titles": _safe_int(tournament_stats.get("titles")),
                "finals": _safe_int(tournament_stats.get("finals")),
                "top4": _safe_int(tournament_stats.get("top4")),
            },
        }

    async def deck_metagame(
        self,
        guild_id: str,
        *,
        format_name: str | None = None,
        tournament_id: int | None = None,
        minimum_matches: int = 0,
    ) -> dict[str, Any]:
        """Construit les statistiques publiques des decks.

        Le calcul est volontairement réalisé à partir des inscriptions et des
        résultats validés. Il reste compatible avec les anciennes bases :
        les tables ou colonnes facultatives sont contrôlées avant utilisation.
        """

        selected_format = " ".join((format_name or "").split()).strip() or None
        minimum_matches = max(0, min(_safe_int(minimum_matches), 999))

        decks: list[dict[str, Any]] = []
        tournaments: list[dict[str, Any]] = []
        formats: list[str] = []
        actual_match_keys: set[str] = set()
        aggregate: dict[tuple[str, str], dict[str, Any]] = {}
        registration_deck: dict[tuple[int, str], tuple[str, str]] = {}

        def ensure_entry(
            deck_name: str,
            tournament_format: str,
        ) -> tuple[tuple[str, str], dict[str, Any]]:
            key = (
                " ".join(deck_name.split()).casefold(),
                " ".join(tournament_format.split()).casefold(),
            )
            entry = aggregate.get(key)
            if entry is None:
                entry = {
                    "_names": Counter(),
                    "_formats": Counter(),
                    "_players": set(),
                    "_tournaments": set(),
                    "appearances": 0,
                    "matches": 0,
                    "wins": 0,
                    "losses": 0,
                }
                aggregate[key] = entry

            entry["_names"][" ".join(deck_name.split())] += 1
            entry["_formats"][" ".join(tournament_format.split())] += 1
            return key, entry

        def record_result(
            source_key: str,
            tournament: int,
            player1_id: Any,
            player2_id: Any,
            winner_id: Any,
        ) -> None:
            winner = str(winner_id or "").strip()
            if not winner:
                return

            matched = False
            for raw_player_id in (player1_id, player2_id):
                player_id = str(raw_player_id or "").strip()
                if not player_id:
                    continue

                key = registration_deck.get((tournament, player_id))
                if key is None:
                    continue

                entry = aggregate.get(key)
                if entry is None:
                    continue

                entry["matches"] += 1
                if player_id == winner:
                    entry["wins"] += 1
                else:
                    entry["losses"] += 1
                matched = True

            if matched:
                actual_match_keys.add(source_key)

        async with expansion_connection() as db:
            has_registrations = await table_exists(db, "registrations")
            has_tournaments = await table_exists(db, "tournaments")

            if has_registrations and has_tournaments:
                conditions = [
                    "t.guild_id=?",
                    "r.deck IS NOT NULL",
                    "TRIM(r.deck)<>''",
                ]
                parameters: list[Any] = [guild_id]

                # Comparaison insensible à la casse : GOAT reste GOAT et ne
                # devient plus « Goat » lors du filtrage.
                if selected_format:
                    conditions.append(
                        "LOWER(TRIM(t.format))=LOWER(TRIM(?))"
                    )
                    parameters.append(selected_format)

                if tournament_id:
                    conditions.append("t.id=?")
                    parameters.append(int(tournament_id))

                registration_rows = await (
                    await db.execute(
                        f"""
                        SELECT
                            t.id AS tournament_id,
                            t.name AS tournament_name,
                            t.code AS tournament_code,
                            t.format,
                            r.discord_id,
                            TRIM(r.deck) AS deck_name
                        FROM registrations r
                        JOIN tournaments t ON t.id=r.tournament_id
                        WHERE {' AND '.join(conditions)}
                        ORDER BY t.id DESC, r.id ASC
                        """,
                        tuple(parameters),
                    )
                ).fetchall()

                for row in registration_rows:
                    item = dict(row)
                    deck_name = str(item.get("deck_name") or "").strip()
                    tournament_format = str(
                        item.get("format") or "Format non renseigné"
                    ).strip()
                    player_id = str(item.get("discord_id") or "").strip()
                    current_tournament_id = _safe_int(
                        item.get("tournament_id")
                    )

                    if not deck_name or not player_id or not current_tournament_id:
                        continue

                    key, entry = ensure_entry(
                        deck_name,
                        tournament_format,
                    )
                    entry["_players"].add(player_id)
                    entry["_tournaments"].add(current_tournament_id)
                    entry["appearances"] += 1
                    registration_deck[
                        (current_tournament_id, player_id)
                    ] = key

                tournament_rows = await (
                    await db.execute(
                        """
                        SELECT id, code, name, format, status
                        FROM tournaments
                        WHERE guild_id=?
                        ORDER BY id DESC
                        LIMIT 200
                        """,
                        (guild_id,),
                    )
                ).fetchall()
                tournaments = _dicts(tournament_rows)

                format_rows = await (
                    await db.execute(
                        """
                        SELECT DISTINCT TRIM(format) AS format
                        FROM tournaments
                        WHERE guild_id=?
                          AND format IS NOT NULL
                          AND TRIM(format)<>''
                        ORDER BY LOWER(TRIM(format))
                        """,
                        (guild_id,),
                    )
                ).fetchall()
                formats = [
                    str(row["format"])
                    for row in format_rows
                    if str(row["format"] or "").strip()
                ]

                common_conditions = ["t.guild_id=?"]
                common_parameters: list[Any] = [guild_id]
                if selected_format:
                    common_conditions.append(
                        "LOWER(TRIM(t.format))=LOWER(TRIM(?))"
                    )
                    common_parameters.append(selected_format)
                if tournament_id:
                    common_conditions.append("t.id=?")
                    common_parameters.append(int(tournament_id))

                # Matchs à élimination directe.
                if await table_exists(db, "matches"):
                    match_columns = await columns_for(db, "matches")
                    required_columns = {
                        "id",
                        "tournament_id",
                        "player1_id",
                        "player2_id",
                        "winner_id",
                    }
                    if required_columns.issubset(match_columns):
                        status_filter = (
                            "m.status IN ('validated','completed')"
                            if "status" in match_columns
                            else "1=1"
                        )
                        bye_filter = (
                            "COALESCE(m.is_bye,0)=0"
                            if "is_bye" in match_columns
                            else "1=1"
                        )
                        rows = await (
                            await db.execute(
                                f"""
                                SELECT
                                    m.id,
                                    m.tournament_id,
                                    m.player1_id,
                                    m.player2_id,
                                    m.winner_id
                                FROM matches m
                                JOIN tournaments t
                                  ON t.id=m.tournament_id
                                WHERE {' AND '.join(common_conditions)}
                                  AND {status_filter}
                                  AND {bye_filter}
                                  AND m.player1_id IS NOT NULL
                                  AND m.player2_id IS NOT NULL
                                  AND m.winner_id IS NOT NULL
                                """,
                                tuple(common_parameters),
                            )
                        ).fetchall()

                        for row in rows:
                            item = dict(row)
                            record_result(
                                f"bracket:{item.get('id')}",
                                _safe_int(item.get("tournament_id")),
                                item.get("player1_id"),
                                item.get("player2_id"),
                                item.get("winner_id"),
                            )

                # Matchs de rondes suisses.
                if await table_exists(db, "swiss_matches"):
                    swiss_columns = await columns_for(db, "swiss_matches")
                    required_columns = {
                        "id",
                        "tournament_id",
                        "player1_id",
                        "player2_id",
                        "winner_id",
                    }
                    if required_columns.issubset(swiss_columns):
                        status_filter = (
                            "sm.status IN ('completed','validated')"
                            if "status" in swiss_columns
                            else "1=1"
                        )
                        bye_filter = (
                            "COALESCE(sm.is_bye,0)=0"
                            if "is_bye" in swiss_columns
                            else "1=1"
                        )
                        double_loss_filter = (
                            "COALESCE(sm.is_double_loss,0)=0"
                            if "is_double_loss" in swiss_columns
                            else "1=1"
                        )
                        rows = await (
                            await db.execute(
                                f"""
                                SELECT
                                    sm.id,
                                    sm.tournament_id,
                                    sm.player1_id,
                                    sm.player2_id,
                                    sm.winner_id
                                FROM swiss_matches sm
                                JOIN tournaments t
                                  ON t.id=sm.tournament_id
                                WHERE {' AND '.join(common_conditions)}
                                  AND {status_filter}
                                  AND {bye_filter}
                                  AND {double_loss_filter}
                                  AND sm.player1_id IS NOT NULL
                                  AND sm.player2_id IS NOT NULL
                                  AND sm.winner_id IS NOT NULL
                                """,
                                tuple(common_parameters),
                            )
                        ).fetchall()

                        for row in rows:
                            item = dict(row)
                            record_result(
                                f"swiss:{item.get('id')}",
                                _safe_int(item.get("tournament_id")),
                                item.get("player1_id"),
                                item.get("player2_id"),
                                item.get("winner_id"),
                            )

        all_players: set[str] = set()
        total_appearances = 0

        for entry in aggregate.values():
            names: Counter[str] = entry.pop("_names")
            format_names: Counter[str] = entry.pop("_formats")
            player_ids: set[str] = entry.pop("_players")
            tournament_ids: set[int] = entry.pop("_tournaments")

            deck_name = sorted(
                names.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )[0][0]
            tournament_format = sorted(
                format_names.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )[0][0]

            matches = _safe_int(entry.get("matches"))
            wins = _safe_int(entry.get("wins"))
            losses = _safe_int(entry.get("losses"))
            appearances = _safe_int(entry.get("appearances"))

            if matches < minimum_matches:
                continue

            all_players.update(player_ids)
            total_appearances += appearances
            decks.append(
                {
                    "deck_name": deck_name,
                    "format": tournament_format,
                    "players": len(player_ids),
                    "appearances": appearances,
                    "tournaments": len(tournament_ids),
                    "matches": matches,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": (
                        round((wins / matches) * 100, 1)
                        if matches
                        else 0.0
                    ),
                    "sample_warning": matches < 5,
                }
            )

        decks.sort(
            key=lambda item: (
                -_safe_int(item.get("matches")),
                -_safe_int(item.get("appearances")),
                str(item.get("deck_name") or "").casefold(),
            )
        )

        performance_minimum = max(5, minimum_matches)
        popular = sorted(
            decks,
            key=lambda item: (
                _safe_int(item.get("appearances")),
                _safe_int(item.get("players")),
                _safe_int(item.get("matches")),
            ),
            reverse=True,
        )[:5]
        performing = sorted(
            [
                item
                for item in decks
                if _safe_int(item.get("matches")) >= performance_minimum
            ],
            key=lambda item: (
                _safe_float(item.get("win_rate")),
                _safe_int(item.get("matches")),
                _safe_int(item.get("appearances")),
            ),
            reverse=True,
        )[:5]

        selected_format_display = ""
        if selected_format:
            selected_format_display = next(
                (
                    item
                    for item in formats
                    if item.casefold() == selected_format.casefold()
                ),
                selected_format,
            )

        return {
            "decks": decks,
            "popular": popular,
            "performing": performing,
            "formats": formats,
            "tournaments": tournaments,
            "selected_format": selected_format_display,
            "selected_tournament": tournament_id,
            "minimum_matches": minimum_matches,
            "performance_minimum": performance_minimum,
            "stats": {
                "decks": len(decks),
                "players": len(all_players),
                "appearances": total_appearances,
                "matches": len(actual_match_keys),
                "deck_match_records": sum(
                    _safe_int(item.get("matches"))
                    for item in decks
                ),
            },
        }

    async def global_search(
        self,
        guild_id: str,
        query: str,
        *,
        command_catalog: dict[str, list[dict[str, Any]]] | None = None,
        limit: int = 30,
    ) -> dict[str, list[dict[str, Any]]]:
        cleaned = " ".join((query or "").split()).strip()
        if len(cleaned) < 2:
            return {
                "players": [],
                "tournaments": [],
                "decks": [],
                "commands": [],
            }
        like = f"%{cleaned}%"
        limit = max(1, min(int(limit), 50))
        players: list[dict[str, Any]] = []
        tournaments: list[dict[str, Any]] = []
        decks: list[dict[str, Any]] = []

        async with expansion_connection() as db:
            if await table_exists(db, "players"):
                rows = await (
                    await db.execute(
                        """
                        SELECT discord_id, username, display_name, avatar_url,
                               wins, losses, tournaments_played, tournaments_won
                        FROM players
                        WHERE guild_id=?
                          AND (
                              username LIKE ? COLLATE NOCASE
                              OR display_name LIKE ? COLLATE NOCASE
                              OR discord_id=?
                          )
                        ORDER BY tournaments_played DESC, wins DESC
                        LIMIT ?
                        """,
                        (guild_id, like, like, cleaned, limit),
                    )
                ).fetchall()
                players = _dicts(rows)

            if await table_exists(db, "tournaments"):
                rows = await (
                    await db.execute(
                        """
                        SELECT
                            id,
                            code,
                            name,
                            format,
                            'single_elimination' AS tournament_type,
                            status,
                            current_round,
                            total_rounds,
                            winner_name
                        FROM tournaments
                        WHERE guild_id=?
                          AND (
                              name LIKE ? COLLATE NOCASE
                              OR code LIKE ? COLLATE NOCASE
                              OR format LIKE ? COLLATE NOCASE
                          )
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (guild_id, like, like, like, limit),
                    )
                ).fetchall()
                tournaments = _dicts(rows)

            if await table_exists(db, "registrations") and await table_exists(db, "tournaments"):
                rows = await (
                    await db.execute(
                        """
                        SELECT
                            TRIM(r.deck) AS deck_name,
                            t.format,
                            COUNT(DISTINCT r.discord_id) AS players,
                            COUNT(DISTINCT r.tournament_id) AS tournaments
                        FROM registrations r
                        JOIN tournaments t ON t.id=r.tournament_id
                        WHERE t.guild_id=?
                          AND r.deck IS NOT NULL
                          AND TRIM(r.deck)<>''
                          AND r.deck LIKE ? COLLATE NOCASE
                        GROUP BY LOWER(TRIM(r.deck)), t.format
                        ORDER BY players DESC, deck_name
                        LIMIT ?
                        """,
                        (guild_id, like, limit),
                    )
                ).fetchall()
                decks = _dicts(rows)

        commands: list[dict[str, Any]] = []
        needle = cleaned.casefold()
        if command_catalog:
            for category_entries in command_catalog.values():
                for entry in category_entries:
                    haystack = str(entry.get("search_text") or "").casefold()
                    if needle in haystack:
                        commands.append(dict(entry))
                        if len(commands) >= limit:
                            break
                if len(commands) >= limit:
                    break

        return {
            "players": players,
            "tournaments": tournaments,
            "decks": decks,
            "commands": commands,
        }
