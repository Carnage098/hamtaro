from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from services.expansion_database import (
    columns_for,
    dumps,
    expansion_connection,
    loads,
    normalize_format,
    table_exists,
    utcnow_iso,
)


class TournamentExtensionsService:
    async def tournament_by_code(self, guild_id: str, code: str | None) -> dict[str, Any] | None:
        async with expansion_connection() as db:
            if code:
                row = await (
                    await db.execute(
                        """
                        SELECT * FROM tournaments
                        WHERE guild_id=? AND LOWER(code)=LOWER(?)
                        LIMIT 1
                        """,
                        (guild_id, code.strip()),
                    )
                ).fetchone()
            else:
                row = await (
                    await db.execute(
                        """
                        SELECT * FROM tournaments
                        WHERE guild_id=?
                          AND status NOT IN ('finished','cancelled','archived')
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        (guild_id,),
                    )
                ).fetchone()
            return dict(row) if row else None

    async def tournament_info(self, guild_id: str, code: str | None) -> dict[str, Any]:
        tournament = await self.tournament_by_code(guild_id, code)
        if tournament is None:
            raise ValueError("Tournoi introuvable.")
        tournament_id = int(tournament["id"])
        async with expansion_connection() as db:
            registration = await (
                await db.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN dropped=1 THEN 1 ELSE 0 END) AS dropped
                    FROM registrations WHERE tournament_id=?
                    """,
                    (tournament_id,),
                )
            ).fetchone()
            matches = await (
                await db.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN status IN ('validated','completed') THEN 1 ELSE 0 END) AS completed
                    FROM matches WHERE tournament_id=?
                    """,
                    (tournament_id,),
                )
            ).fetchone()
            swiss = await (
                await db.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed
                    FROM swiss_matches WHERE tournament_id=?
                    """,
                    (tournament_id,),
                )
            ).fetchone()
            waitlist = await (
                await db.execute(
                    """
                    SELECT COUNT(*) AS total FROM tournament_waitlist
                    WHERE tournament_id=? AND status IN ('waiting','offered')
                    """,
                    (tournament_id,),
                )
            ).fetchone()
            featured = await (
                await db.execute(
                    """
                    SELECT * FROM featured_matches
                    WHERE tournament_id=? AND status IN ('announced','live')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (tournament_id,),
                )
            ).fetchone()
        return {
            "tournament": tournament,
            "registrations": int(registration["total"] or 0),
            "dropped": int(registration["dropped"] or 0),
            "bracket_total": int(matches["total"] or 0),
            "bracket_completed": int(matches["completed"] or 0),
            "swiss_total": int(swiss["total"] or 0),
            "swiss_completed": int(swiss["completed"] or 0),
            "waitlist": int(waitlist["total"] or 0),
            "featured": dict(featured) if featured else None,
        }

    async def tournament_recap(self, guild_id: str, code: str | None) -> dict[str, Any]:
        info = await self.tournament_info(guild_id, code)
        tournament = info["tournament"]
        tournament_id = int(tournament["id"])
        async with expansion_connection() as db:
            deck_rows = await (
                await db.execute(
                    """
                    SELECT COALESCE(NULLIF(TRIM(deck),''),'Non renseigné') AS deck,
                           COUNT(*) AS players
                    FROM registrations
                    WHERE tournament_id=?
                    GROUP BY COALESCE(NULLIF(TRIM(deck),''),'Non renseigné')
                    ORDER BY players DESC, deck
                    LIMIT 10
                    """,
                    (tournament_id,),
                )
            ).fetchall()
            score_rows = await (
                await db.execute(
                    """
                    SELECT score, COUNT(*) AS total
                    FROM matches
                    WHERE tournament_id=? AND score IS NOT NULL AND TRIM(score)<>''
                    GROUP BY score ORDER BY total DESC LIMIT 5
                    """,
                    (tournament_id,),
                )
            ).fetchall()
            swiss_score_rows = await (
                await db.execute(
                    """
                    SELECT CAST(player1_score AS TEXT)||'-'||CAST(player2_score AS TEXT) AS score,
                           COUNT(*) AS total
                    FROM swiss_matches
                    WHERE tournament_id=? AND status='completed' AND COALESCE(is_bye,0)=0
                    GROUP BY player1_score, player2_score
                    ORDER BY total DESC LIMIT 5
                    """,
                    (tournament_id,),
                )
            ).fetchall()
            champion = tournament.get("winner_name") or "Non déterminé"
            final_rows = await (
                await db.execute(
                    """
                    SELECT username, final_rank
                    FROM registrations
                    WHERE tournament_id=? AND final_rank IS NOT NULL
                    ORDER BY final_rank ASC LIMIT 8
                    """,
                    (tournament_id,),
                )
            ).fetchall()
            active_players = await (
                await db.execute(
                    """
                    SELECT discord_id, username, COUNT(*) AS matches
                    FROM (
                        SELECT player1_id AS discord_id, player1_name AS username
                        FROM matches WHERE tournament_id=? AND COALESCE(is_bye,0)=0
                        UNION ALL
                        SELECT player2_id, player2_name
                        FROM matches WHERE tournament_id=? AND COALESCE(is_bye,0)=0
                        UNION ALL
                        SELECT player1_id, player1_name
                        FROM swiss_matches WHERE tournament_id=? AND COALESCE(is_bye,0)=0
                        UNION ALL
                        SELECT player2_id, player2_name
                        FROM swiss_matches WHERE tournament_id=? AND COALESCE(is_bye,0)=0
                    )
                    WHERE discord_id IS NOT NULL
                    GROUP BY discord_id, username
                    ORDER BY matches DESC LIMIT 5
                    """,
                    (tournament_id, tournament_id, tournament_id, tournament_id),
                )
            ).fetchall()
        score_counts: dict[str, int] = {}
        for row in [*score_rows, *swiss_score_rows]:
            score_counts[str(row["score"])] = score_counts.get(str(row["score"]), 0) + int(row["total"])
        common_scores = sorted(score_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        return {
            **info,
            "champion": champion,
            "decks": [dict(row) for row in deck_rows],
            "common_scores": common_scores,
            "final_ranking": [dict(row) for row in final_rows],
            "most_active": [dict(row) for row in active_players],
        }

    async def create_template(
        self,
        *,
        guild_id: str,
        name: str,
        tournament_name: str,
        format_name: str,
        tournament_type: str,
        max_players: int,
        total_rounds: int | None,
        best_of: str,
        rules: str | None,
        actor_id: str,
    ) -> int:
        if tournament_type not in {"single_elimination", "swiss"}:
            raise ValueError("Type de tournoi invalide.")
        if max_players < 4 or max_players > 128:
            raise ValueError("La capacité doit être comprise entre 4 et 128 joueurs.")
        now = utcnow_iso()
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO tournament_templates_plus(
                    guild_id, name, tournament_name, format, tournament_type,
                    max_players, total_rounds, best_of, rules,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    name.strip(),
                    tournament_name.strip(),
                    normalize_format(format_name),
                    tournament_type,
                    max_players,
                    total_rounds,
                    best_of.upper(),
                    (rules or "").strip()[:2000] or None,
                    actor_id,
                    now,
                    now,
                ),
            )
            template_id = int(cursor.lastrowid)
            await self._log_action(
                db,
                guild_id=guild_id,
                action_type="create",
                entity_type="template",
                entity_id=str(template_id),
                actor_id=actor_id,
                before=None,
                after={"id": template_id, "name": name},
                reversible=True,
            )
            await db.commit()
            return template_id

    async def templates(self, guild_id: str) -> list[dict[str, Any]]:
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT * FROM tournament_templates_plus
                    WHERE guild_id=? ORDER BY name
                    """,
                    (guild_id,),
                )
            ).fetchall()
            return [dict(row) for row in rows]

    async def create_tournament_from_template(
        self,
        *,
        guild_id: str,
        template_id: int,
        code: str,
        actor_id: str,
    ) -> dict[str, Any]:
        async with expansion_connection() as db:
            template = await (
                await db.execute(
                    """
                    SELECT * FROM tournament_templates_plus
                    WHERE id=? AND guild_id=?
                    """,
                    (template_id, guild_id),
                )
            ).fetchone()
            if template is None:
                raise ValueError("Modèle introuvable.")
            cursor = await db.execute(
                """
                INSERT INTO tournaments(
                    guild_id, code, name, format, max_players, status,
                    current_round, total_rounds, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, 'registration', 0, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    guild_id,
                    code.strip().upper(),
                    template["tournament_name"],
                    template["format"],
                    int(template["max_players"]),
                    int(template["total_rounds"] or 0),
                    actor_id,
                ),
            )
            tournament_id = int(cursor.lastrowid)
            if str(template["tournament_type"]) == "swiss":
                await db.execute(
                    """
                    INSERT INTO swiss_settings(
                        tournament_id, total_rounds, current_round, status
                    ) VALUES (?, ?, 0, 'running')
                    """,
                    (tournament_id, int(template["total_rounds"] or 5)),
                )
            await self._log_action(
                db,
                guild_id=guild_id,
                action_type="create",
                entity_type="tournament_from_template",
                entity_id=str(tournament_id),
                actor_id=actor_id,
                before=None,
                after={"template_id": template_id, "code": code},
                reversible=True,
            )
            await db.commit()
            result = dict(template)
            result["tournament_id"] = tournament_id
            result["code"] = code.strip().upper()
            return result

    async def join_waitlist(
        self,
        *,
        guild_id: str,
        tournament_id: int,
        discord_id: str,
        username: str,
        deck_name: str | None,
    ) -> int:
        async with expansion_connection() as db:
            registered = await (
                await db.execute(
                    "SELECT 1 FROM registrations WHERE tournament_id=? AND discord_id=?",
                    (tournament_id, discord_id),
                )
            ).fetchone()
            if registered:
                raise ValueError("Tu es déjà inscrit à ce tournoi.")
            row = await (
                await db.execute(
                    """
                    SELECT COALESCE(MAX(position),0)+1 AS next_position
                    FROM tournament_waitlist
                    WHERE tournament_id=? AND status IN ('waiting','offered')
                    """,
                    (tournament_id,),
                )
            ).fetchone()
            position = int(row["next_position"])
            await db.execute(
                """
                INSERT INTO tournament_waitlist(
                    guild_id, tournament_id, discord_id, username,
                    deck_name, status, position, joined_at
                ) VALUES (?, ?, ?, ?, ?, 'waiting', ?, ?)
                ON CONFLICT(tournament_id, discord_id) DO UPDATE SET
                    username=excluded.username,
                    deck_name=excluded.deck_name,
                    status='waiting',
                    position=excluded.position,
                    joined_at=excluded.joined_at,
                    offered_at=NULL,
                    offer_expires_at=NULL
                """,
                (
                    guild_id,
                    tournament_id,
                    discord_id,
                    username,
                    (deck_name or "").strip() or None,
                    position,
                    utcnow_iso(),
                ),
            )
            await db.commit()
            return position

    async def leave_waitlist(self, tournament_id: int, discord_id: str) -> None:
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                UPDATE tournament_waitlist
                SET status='cancelled'
                WHERE tournament_id=? AND discord_id=?
                  AND status IN ('waiting','offered')
                """,
                (tournament_id, discord_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Tu n'es pas dans la liste d'attente.")
            await db.commit()

    async def promote_waitlist(
        self,
        *,
        guild_id: str,
        tournament_id: int,
        actor_id: str,
    ) -> dict[str, Any]:
        async with expansion_connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            tournament = await (
                await db.execute(
                    "SELECT * FROM tournaments WHERE id=? AND guild_id=?",
                    (tournament_id, guild_id),
                )
            ).fetchone()
            if tournament is None:
                await db.rollback()
                raise ValueError("Tournoi introuvable.")
            count = await (
                await db.execute(
                    "SELECT COUNT(*) AS total FROM registrations WHERE tournament_id=?",
                    (tournament_id,),
                )
            ).fetchone()
            if int(count["total"]) >= int(tournament["max_players"]):
                await db.rollback()
                raise ValueError("Le tournoi est encore complet.")
            candidate = await (
                await db.execute(
                    """
                    SELECT * FROM tournament_waitlist
                    WHERE tournament_id=? AND status='waiting'
                    ORDER BY position, joined_at LIMIT 1
                    """,
                    (tournament_id,),
                )
            ).fetchone()
            if candidate is None:
                await db.rollback()
                raise ValueError("La liste d'attente est vide.")
            await db.execute(
                """
                INSERT INTO registrations(
                    tournament_id, discord_id, username, deck,
                    checked_in, registered_at
                ) VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                """,
                (
                    tournament_id,
                    candidate["discord_id"],
                    candidate["username"],
                    candidate["deck_name"],
                ),
            )
            await db.execute(
                """
                UPDATE tournament_waitlist
                SET status='promoted', promoted_at=?
                WHERE id=?
                """,
                (utcnow_iso(), int(candidate["id"])),
            )
            await self._log_action(
                db,
                guild_id=guild_id,
                action_type="promote",
                entity_type="waitlist",
                entity_id=str(candidate["id"]),
                actor_id=actor_id,
                before=dict(candidate),
                after={"status": "promoted", "tournament_id": tournament_id},
                reversible=True,
            )
            await db.commit()
            return dict(candidate)

    async def create_judge_call(
        self,
        *,
        guild_id: str,
        tournament_id: int | None,
        channel_id: str,
        thread_id: str | None,
        reporter_id: str,
        opponent_id: str | None,
        reason: str,
        details: str | None,
    ) -> int:
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO judge_calls(
                    guild_id, tournament_id, channel_id, thread_id,
                    reporter_id, opponent_id, reason, details,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """,
                (
                    guild_id,
                    tournament_id,
                    channel_id,
                    thread_id,
                    reporter_id,
                    opponent_id,
                    reason,
                    (details or "").strip()[:1500] or None,
                    utcnow_iso(),
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def assign_judge_call(self, guild_id: str, call_id: int, actor_id: str) -> None:
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                UPDATE judge_calls
                SET status='assigned', assigned_to=?
                WHERE id=? AND guild_id=? AND status='open'
                """,
                (actor_id, call_id, guild_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Appel introuvable ou déjà pris en charge.")
            await db.commit()

    async def resolve_judge_call(
        self,
        guild_id: str,
        call_id: int,
        actor_id: str,
        resolution: str,
    ) -> None:
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                UPDATE judge_calls
                SET status='resolved', assigned_to=COALESCE(assigned_to,?),
                    resolution=?, resolved_at=?
                WHERE id=? AND guild_id=? AND status IN ('open','assigned')
                """,
                (actor_id, resolution.strip()[:1500], utcnow_iso(), call_id, guild_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Appel introuvable ou déjà résolu.")
            await db.commit()

    async def open_judge_calls(self, guild_id: str) -> list[dict[str, Any]]:
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT * FROM judge_calls
                    WHERE guild_id=? AND status IN ('open','assigned')
                    ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, created_at
                    LIMIT 30
                    """,
                    (guild_id,),
                )
            ).fetchall()
            return [dict(row) for row in rows]

    async def create_match_issue(
        self,
        *,
        guild_id: str,
        tournament_id: int | None,
        source_kind: str | None,
        match_id: int | None,
        reporter_id: str,
        opponent_id: str | None,
        issue_type: str,
        details: str | None,
        requested_until: str | None,
    ) -> int:
        if issue_type not in {"no_response", "delay", "forfeit", "connection", "other"}:
            raise ValueError("Type de problème invalide.")
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO match_issues(
                    guild_id, tournament_id, source_kind, match_id,
                    reporter_id, opponent_id, issue_type, details,
                    status, first_contact_at, requested_until, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    guild_id,
                    tournament_id,
                    source_kind,
                    match_id,
                    reporter_id,
                    opponent_id,
                    issue_type,
                    (details or "").strip()[:1500] or None,
                    utcnow_iso(),
                    requested_until,
                    utcnow_iso(),
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def resolve_featured_match(
        self,
        *,
        guild_id: str,
        source_kind: str,
        match_id: int,
    ) -> dict[str, Any]:
        """Résout les deux joueurs d'un match sans dépendre d'un seul schéma casual."""
        source_kind = source_kind.casefold().strip()
        if source_kind not in {"bracket", "swiss", "casual"}:
            raise ValueError("Type de match invalide : bracket, swiss ou casual.")

        async with expansion_connection() as db:
            if source_kind in {"bracket", "swiss"}:
                table = "matches" if source_kind == "bracket" else "swiss_matches"
                if not await table_exists(db, table):
                    raise ValueError(f"La table {table} est introuvable.")
                row = await (
                    await db.execute(
                        f"""
                        SELECT m.*, t.guild_id AS tournament_guild_id,
                               t.name AS tournament_name, t.code AS tournament_code,
                               t.format AS tournament_format
                        FROM {table} m
                        JOIN tournaments t ON t.id=m.tournament_id
                        WHERE m.id=? AND t.guild_id=?
                        LIMIT 1
                        """,
                        (match_id, guild_id),
                    )
                ).fetchone()
                if row is None:
                    raise ValueError("Match introuvable sur ce serveur.")
                data = dict(row)
                player1_id = str(data.get("player1_id") or "")
                player2_id = str(data.get("player2_id") or "")
                if not player1_id or not player2_id:
                    raise ValueError("Ce match ne possède pas encore deux joueurs.")
                return {
                    "source_kind": source_kind,
                    "match_id": match_id,
                    "tournament_id": int(data["tournament_id"]),
                    "tournament_name": data.get("tournament_name"),
                    "tournament_code": data.get("tournament_code"),
                    "format": data.get("tournament_format") or "Général",
                    "round": data.get("round") or data.get("round_number"),
                    "player1_id": player1_id,
                    "player2_id": player2_id,
                    "player1_name": data.get("player1_name"),
                    "player2_name": data.get("player2_name"),
                }

            candidates = ("casual_matches", "casual_duels", "casual_match_sessions")
            player_pairs = (
                ("player1_id", "player2_id"),
                ("challenger_id", "opponent_id"),
                ("requester_id", "opponent_id"),
                ("creator_id", "accepted_by"),
            )
            for table in candidates:
                if not await table_exists(db, table):
                    continue
                columns = await columns_for(db, table)
                pair = next(
                    ((left, right) for left, right in player_pairs if left in columns and right in columns),
                    None,
                )
                if pair is None or "id" not in columns:
                    continue
                filters = ["id=?"]
                parameters: list[Any] = [match_id]
                if "guild_id" in columns:
                    filters.append("guild_id=?")
                    parameters.append(guild_id)
                row = await (
                    await db.execute(
                        f"SELECT * FROM {table} WHERE {' AND '.join(filters)} LIMIT 1",
                        tuple(parameters),
                    )
                ).fetchone()
                if row is None:
                    continue
                data = dict(row)
                player1_id = str(data.get(pair[0]) or "")
                player2_id = str(data.get(pair[1]) or "")
                if not player1_id or not player2_id:
                    raise ValueError("Le match casual n'a pas encore trouvé son deuxième joueur.")
                format_value = next(
                    (data.get(name) for name in ("format", "format_name", "game_format") if name in columns),
                    "Casual",
                )
                return {
                    "source_kind": source_kind,
                    "match_id": match_id,
                    "tournament_id": data.get("tournament_id"),
                    "tournament_name": None,
                    "tournament_code": None,
                    "format": format_value or "Casual",
                    "round": None,
                    "player1_id": player1_id,
                    "player2_id": player2_id,
                    "player1_name": None,
                    "player2_name": None,
                    "casual_table": table,
                }
            raise ValueError("Match casual introuvable ou structure casual non reconnue.")

    async def feature_match(
        self,
        *,
        guild_id: str,
        tournament_id: int | None,
        source_kind: str,
        match_id: int,
        channel_id: str,
        voice_channel_id: str | None,
        player1_id: str,
        player2_id: str,
        stream_url: str | None,
        commentators: str | None,
        title: str | None,
        actor_id: str,
    ) -> int:
        if source_kind not in {"bracket", "swiss", "casual"}:
            raise ValueError("Type de match invalide.")
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO featured_matches(
                    guild_id, tournament_id, source_kind, match_id,
                    channel_id, voice_channel_id, player1_id, player2_id,
                    stream_url, commentators, title,
                    status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'announced', ?, ?)
                """,
                (
                    guild_id,
                    tournament_id,
                    source_kind,
                    match_id,
                    channel_id,
                    voice_channel_id,
                    player1_id,
                    player2_id,
                    (stream_url or "").strip() or None,
                    (commentators or "").strip()[:300] or None,
                    (title or "").strip()[:200] or None,
                    actor_id,
                    utcnow_iso(),
                ),
            )
            featured_id = int(cursor.lastrowid)
            await self._log_action(
                db,
                guild_id=guild_id,
                action_type="create",
                entity_type="featured_match",
                entity_id=str(featured_id),
                actor_id=actor_id,
                before=None,
                after={
                    "source_kind": source_kind,
                    "match_id": match_id,
                    "voice_channel_id": voice_channel_id,
                    "player1_id": player1_id,
                    "player2_id": player2_id,
                },
                reversible=True,
            )
            await db.commit()
            return featured_id

    async def set_featured_message(self, featured_id: int, message_id: str) -> None:
        async with expansion_connection() as db:
            await db.execute(
                "UPDATE featured_matches SET message_id=? WHERE id=?",
                (message_id, featured_id),
            )
            await db.commit()

    async def open_featured_matches(self) -> list[dict[str, Any]]:
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT * FROM featured_matches
                    WHERE status IN ('announced','live') AND message_id IS NOT NULL
                    ORDER BY id DESC
                    """
                )
            ).fetchall()
            return [dict(row) for row in rows]

    async def featured_match_by_id(self, guild_id: str, featured_id: int) -> dict[str, Any]:
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    "SELECT * FROM featured_matches WHERE id=? AND guild_id=?",
                    (featured_id, guild_id),
                )
            ).fetchone()
            if row is None:
                raise ValueError("Match vedette introuvable.")
            return dict(row)

    async def update_featured_checkin(
        self,
        *,
        featured_id: int,
        discord_id: str,
        ready: bool | None = None,
        in_voice: bool | None = None,
        streaming: bool | None = None,
    ) -> None:
        async with expansion_connection() as db:
            existing = await (
                await db.execute(
                    "SELECT * FROM featured_match_checkins WHERE featured_match_id=? AND discord_id=?",
                    (featured_id, discord_id),
                )
            ).fetchone()
            values = dict(existing) if existing else {"ready": 0, "in_voice": 0, "streaming": 0}
            await db.execute(
                """
                INSERT INTO featured_match_checkins(
                    featured_match_id, discord_id, ready, in_voice, streaming, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(featured_match_id, discord_id) DO UPDATE SET
                    ready=excluded.ready, in_voice=excluded.in_voice,
                    streaming=excluded.streaming, updated_at=excluded.updated_at
                """,
                (
                    featured_id,
                    discord_id,
                    int(values["ready"] if ready is None else ready),
                    int(values["in_voice"] if in_voice is None else in_voice),
                    int(values["streaming"] if streaming is None else streaming),
                    utcnow_iso(),
                ),
            )
            await db.commit()

    async def featured_checkins(self, featured_id: int) -> list[dict[str, Any]]:
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    "SELECT * FROM featured_match_checkins WHERE featured_match_id=?",
                    (featured_id,),
                )
            ).fetchall()
            return [dict(row) for row in rows]

    async def schedule_tournament(
        self,
        *,
        guild_id: str,
        tournament_id: int | None,
        template_id: int | None,
        channel_id: str,
        announce_at: str | None,
        reminder_at: str | None,
        start_prompt_at: str | None,
        actor_id: str,
    ) -> int:
        if not any((announce_at, reminder_at, start_prompt_at)):
            raise ValueError("Au moins une date doit être renseignée.")
        for value in (announce_at, reminder_at, start_prompt_at):
            if value:
                self.parse_datetime(value)
        async with expansion_connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO scheduled_tournaments_plus(
                    guild_id, tournament_id, template_id, channel_id,
                    announce_at, reminder_at, start_prompt_at,
                    status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?)
                """,
                (
                    guild_id,
                    tournament_id,
                    template_id,
                    channel_id,
                    announce_at,
                    reminder_at,
                    start_prompt_at,
                    actor_id,
                    utcnow_iso(),
                ),
            )
            schedule_id = int(cursor.lastrowid)
            await self._log_action(
                db,
                guild_id=guild_id,
                action_type="create",
                entity_type="schedule",
                entity_id=str(schedule_id),
                actor_id=actor_id,
                before=None,
                after={"tournament_id": tournament_id, "template_id": template_id},
                reversible=True,
            )
            await db.commit()
            return schedule_id

    @staticmethod
    def parse_datetime(value: str) -> datetime:
        cleaned = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError as error:
            raise ValueError("Date invalide. Utilise le format 2026-09-01T20:00+02:00.") from error
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    async def schedules(self, guild_id: str) -> list[dict[str, Any]]:
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT s.*, t.name AS tournament_name, t.code,
                           tp.name AS template_name
                    FROM scheduled_tournaments_plus s
                    LEFT JOIN tournaments t ON t.id=s.tournament_id
                    LEFT JOIN tournament_templates_plus tp ON tp.id=s.template_id
                    WHERE s.guild_id=? AND s.status='scheduled'
                    ORDER BY COALESCE(s.announce_at,s.reminder_at,s.start_prompt_at)
                    """,
                    (guild_id,),
                )
            ).fetchall()
            return [dict(row) for row in rows]

    async def cancel_schedule(self, guild_id: str, schedule_id: int, actor_id: str) -> None:
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    "SELECT * FROM scheduled_tournaments_plus WHERE id=? AND guild_id=?",
                    (schedule_id, guild_id),
                )
            ).fetchone()
            if row is None or str(row["status"]) != "scheduled":
                raise ValueError("Programmation introuvable ou déjà terminée.")
            await db.execute(
                "UPDATE scheduled_tournaments_plus SET status='cancelled' WHERE id=?",
                (schedule_id,),
            )
            await self._log_action(
                db,
                guild_id=guild_id,
                action_type="cancel",
                entity_type="schedule",
                entity_id=str(schedule_id),
                actor_id=actor_id,
                before=dict(row),
                after={"status": "cancelled"},
                reversible=True,
            )
            await db.commit()

    async def save_settings(
        self,
        *,
        guild_id: str,
        announcements_channel_id: str | None,
        judge_channel_id: str | None,
        featured_channel_id: str | None,
        featured_voice_channel_id: str | None,
        staff_role_id: str | None,
        judge_role_id: str | None,
        default_format: str,
        actor_id: str,
    ) -> None:
        async with expansion_connection() as db:
            await db.execute(
                """
                INSERT INTO expansion_settings(
                    guild_id, announcements_channel_id, judge_channel_id,
                    featured_channel_id, featured_voice_channel_id,
                    staff_role_id, judge_role_id, default_format, updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    announcements_channel_id=excluded.announcements_channel_id,
                    judge_channel_id=excluded.judge_channel_id,
                    featured_channel_id=excluded.featured_channel_id,
                    featured_voice_channel_id=excluded.featured_voice_channel_id,
                    staff_role_id=excluded.staff_role_id,
                    judge_role_id=excluded.judge_role_id,
                    default_format=excluded.default_format,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at
                """,
                (
                    guild_id,
                    announcements_channel_id,
                    judge_channel_id,
                    featured_channel_id,
                    featured_voice_channel_id,
                    staff_role_id,
                    judge_role_id,
                    normalize_format(default_format),
                    actor_id,
                    utcnow_iso(),
                ),
            )
            await db.commit()

    async def settings(self, guild_id: str) -> dict[str, Any]:
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    "SELECT * FROM expansion_settings WHERE guild_id=?",
                    (guild_id,),
                )
            ).fetchone()
            return dict(row) if row else {
                "guild_id": guild_id,
                "announcements_channel_id": None,
                "judge_channel_id": None,
                "featured_channel_id": None,
                "featured_voice_channel_id": None,
                "staff_role_id": None,
                "judge_role_id": None,
                "default_format": "Général",
                "elo_enabled": 1,
                "auto_sync_enabled": 1,
            }

    async def action_history(self, guild_id: str, limit: int = 20) -> list[dict[str, Any]]:
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT * FROM extension_action_log
                    WHERE guild_id=? ORDER BY id DESC LIMIT ?
                    """,
                    (guild_id, max(1, min(limit, 100))),
                )
            ).fetchall()
            return [dict(row) for row in rows]

    async def revert_action(self, guild_id: str, action_id: int, actor_id: str) -> str:
        async with expansion_connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            action = await (
                await db.execute(
                    """
                    SELECT * FROM extension_action_log
                    WHERE id=? AND guild_id=?
                    """,
                    (action_id, guild_id),
                )
            ).fetchone()
            if action is None:
                await db.rollback()
                raise ValueError("Action introuvable.")
            if int(action["reversible"]) != 1 or action["reverted_at"]:
                await db.rollback()
                raise ValueError("Cette action n'est plus annulable.")
            entity_type = str(action["entity_type"])
            entity_id = str(action["entity_id"] or "")
            before = loads(action["before_json"], {}) or {}
            after = loads(action["after_json"], {}) or {}
            message = "Action annulée."

            if entity_type == "template" and str(action["action_type"]) == "create":
                await db.execute("DELETE FROM tournament_templates_plus WHERE id=?", (entity_id,))
                message = "Le modèle créé a été supprimé."
            elif entity_type == "tournament_from_template" and str(action["action_type"]) == "create":
                registrations = await (
                    await db.execute(
                        "SELECT COUNT(*) AS total FROM registrations WHERE tournament_id=?",
                        (entity_id,),
                    )
                ).fetchone()
                if int(registrations["total"]) > 0:
                    await db.rollback()
                    raise ValueError("Le tournoi contient déjà des inscriptions et ne peut pas être supprimé automatiquement.")
                await db.execute("DELETE FROM tournaments WHERE id=?", (entity_id,))
                message = "Le tournoi créé depuis le modèle a été supprimé."
            elif entity_type == "waitlist" and str(action["action_type"]) == "promote":
                tournament_id = int(after.get("tournament_id", 0))
                discord_id = str(before.get("discord_id", ""))
                await db.execute(
                    "DELETE FROM registrations WHERE tournament_id=? AND discord_id=?",
                    (tournament_id, discord_id),
                )
                await db.execute(
                    """
                    UPDATE tournament_waitlist
                    SET status='waiting', promoted_at=NULL
                    WHERE id=?
                    """,
                    (entity_id,),
                )
                message = "La promotion a été annulée et le joueur remis en attente."
            elif entity_type == "featured_match" and str(action["action_type"]) == "create":
                await db.execute(
                    "UPDATE featured_matches SET status='cancelled' WHERE id=?",
                    (entity_id,),
                )
                message = "Le match vedette a été annulé."
            elif entity_type == "schedule":
                if str(action["action_type"]) == "create":
                    await db.execute(
                        "UPDATE scheduled_tournaments_plus SET status='cancelled' WHERE id=?",
                        (entity_id,),
                    )
                    message = "La programmation créée a été annulée."
                elif str(action["action_type"]) == "cancel" and before:
                    await db.execute(
                        """
                        UPDATE scheduled_tournaments_plus
                        SET status='scheduled'
                        WHERE id=?
                        """,
                        (entity_id,),
                    )
                    message = "La programmation a été réactivée."
                else:
                    await db.rollback()
                    raise ValueError("Ce type d'action ne peut pas être annulé.")
            else:
                await db.rollback()
                raise ValueError("Ce type d'action ne peut pas être annulé automatiquement.")

            await db.execute(
                """
                UPDATE extension_action_log
                SET reverted_at=?, reverted_by=?
                WHERE id=?
                """,
                (utcnow_iso(), actor_id, action_id),
            )
            await db.commit()
            return message

    async def _log_action(
        self,
        db: Any,
        *,
        guild_id: str,
        action_type: str,
        entity_type: str,
        entity_id: str | None,
        actor_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reversible: bool,
    ) -> None:
        await db.execute(
            """
            INSERT INTO extension_action_log(
                guild_id, action_type, entity_type, entity_id,
                actor_id, before_json, after_json, reversible, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                action_type,
                entity_type,
                entity_id,
                actor_id,
                dumps(before) if before is not None else None,
                dumps(after) if after is not None else None,
                int(reversible),
                utcnow_iso(),
            ),
        )
