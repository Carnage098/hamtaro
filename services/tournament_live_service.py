from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from config import DATABASE
except ImportError:
    from database import DATABASE

import aiosqlite


class BroadcastHub:
    """Hub de signalisation WebRTC en mémoire.

    Les médias ne transitent pas dans Python : le serveur ne transporte que
    les offres/réponses/ICE nécessaires à la connexion navigateur-à-navigateur.
    """

    def __init__(self) -> None:
        self.publishers: dict[str, Any] = {}
        self.watchers: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def stream_key(kind: str, match_id: int, slot: int) -> str:
        return f"{kind}:{int(match_id)}:{int(slot)}"

    async def add_publisher(self, key: str, ws) -> None:
        async with self._lock:
            old = self.publishers.get(key)
            if old is not None and old is not ws and not old.closed:
                await old.close(code=4001, message=b"publisher replaced")
            self.publishers[key] = ws
            watchers = list(self.watchers.get(key, {}).keys())
        for watcher_id in watchers:
            await ws.send_json({"type": "viewer_join", "viewer_id": watcher_id})

    async def remove_publisher(self, key: str, ws) -> None:
        async with self._lock:
            if self.publishers.get(key) is ws:
                self.publishers.pop(key, None)

    async def add_watcher(self, key: str, watcher_id: str, ws) -> bool:
        async with self._lock:
            self.watchers.setdefault(key, {})[watcher_id] = ws
            publisher = self.publishers.get(key)
        if publisher is not None and not publisher.closed:
            await publisher.send_json({"type": "viewer_join", "viewer_id": watcher_id})
            return True
        return False

    async def remove_watcher(self, key: str, watcher_id: str) -> None:
        async with self._lock:
            group = self.watchers.get(key)
            if group:
                group.pop(watcher_id, None)
                if not group:
                    self.watchers.pop(key, None)
            publisher = self.publishers.get(key)
        if publisher is not None and not publisher.closed:
            await publisher.send_json({"type": "viewer_leave", "viewer_id": watcher_id})

    async def to_watcher(self, key: str, watcher_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            ws = self.watchers.get(key, {}).get(watcher_id)
        if ws is not None and not ws.closed:
            await ws.send_json(payload)

    async def to_publisher(self, key: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            ws = self.publishers.get(key)
        if ws is not None and not ws.closed:
            await ws.send_json(payload)

    async def is_live(self, key: str) -> bool:
        async with self._lock:
            ws = self.publishers.get(key)
            return bool(ws is not None and not ws.closed)


class TournamentLiveService:
    def __init__(self, database_path: str = DATABASE) -> None:
        self.database_path = database_path
        self.hub = BroadcastHub()
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    async def _connect(self):
        db = await aiosqlite.connect(self.database_path)
        db.row_factory = aiosqlite.Row
        return db

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            db = await self._connect()
            try:
                await db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS tournament_competitive_settings (
                        tournament_id INTEGER PRIMARY KEY,
                        structure TEXT NOT NULL DEFAULT 'elimination',
                        best_of INTEGER NOT NULL DEFAULT 3,
                        public_decks INTEGER NOT NULL DEFAULT 1,
                        live_enabled INTEGER NOT NULL DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS live_featured_match (
                        tournament_id INTEGER PRIMARY KEY,
                        match_kind TEXT NOT NULL,
                        match_id INTEGER NOT NULL,
                        updated_by TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS live_publish_tokens (
                        token_hash TEXT PRIMARY KEY,
                        tournament_id INTEGER NOT NULL,
                        match_kind TEXT NOT NULL,
                        match_id INTEGER NOT NULL,
                        player_id TEXT NOT NULL,
                        slot INTEGER NOT NULL,
                        expires_at TIMESTAMP NOT NULL,
                        used_at TIMESTAMP,
                        revoked INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE INDEX IF NOT EXISTS idx_live_tokens_match
                    ON live_publish_tokens(match_kind, match_id, player_id);
                    """
                )
                await db.commit()
            finally:
                await db.close()
            self._schema_ready = True

    async def save_settings(
        self,
        tournament_id: int,
        *,
        structure: str,
        best_of: int,
        public_decks: bool = True,
        live_enabled: bool = True,
    ) -> None:
        await self.ensure_schema()
        db = await self._connect()
        try:
            await db.execute(
                """
                INSERT INTO tournament_competitive_settings(
                    tournament_id, structure, best_of, public_decks, live_enabled
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tournament_id)
                DO UPDATE SET
                    structure=excluded.structure,
                    best_of=excluded.best_of,
                    public_decks=excluded.public_decks,
                    live_enabled=excluded.live_enabled,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    int(tournament_id), structure, int(best_of),
                    int(public_decks), int(live_enabled),
                ),
            )
            await db.commit()
        finally:
            await db.close()

    async def tournament(self, tournament_id: int) -> dict[str, Any] | None:
        await self.ensure_schema()
        db = await self._connect()
        try:
            row = await (
                await db.execute(
                    """
                    SELECT t.*, s.structure, s.best_of, s.public_decks, s.live_enabled
                    FROM tournaments t
                    LEFT JOIN tournament_competitive_settings s ON s.tournament_id=t.id
                    WHERE t.id=?
                    """,
                    (int(tournament_id),),
                )
            ).fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def match(self, kind: str, match_id: int) -> dict[str, Any] | None:
        table = "swiss_matches" if kind == "swiss" else "matches"
        db = await self._connect()
        try:
            exists = await (
                await db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
            ).fetchone()
            if not exists:
                return None
            row = await (
                await db.execute(
                    f"""
                    SELECT m.*, t.name tournament_name, t.code tournament_code,
                           t.format tournament_format,
                           r1.deck player1_deck, r2.deck player2_deck,
                           p1.avatar_url player1_avatar, p2.avatar_url player2_avatar
                    FROM {table} m
                    JOIN tournaments t ON t.id=m.tournament_id
                    LEFT JOIN registrations r1
                      ON r1.tournament_id=m.tournament_id
                     AND r1.discord_id=m.player1_id
                    LEFT JOIN registrations r2
                      ON r2.tournament_id=m.tournament_id
                     AND r2.discord_id=m.player2_id
                    LEFT JOIN players p1
                      ON p1.guild_id=t.guild_id AND p1.discord_id=m.player1_id
                    LEFT JOIN players p2
                      ON p2.guild_id=t.guild_id AND p2.discord_id=m.player2_id
                    WHERE m.id=?
                    """,
                    (int(match_id),),
                )
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["kind"] = kind
            return result
        finally:
            await db.close()

    async def _table_columns(self, db, table: str) -> set[str]:
        rows = await (await db.execute(f"PRAGMA table_info({table})")).fetchall()
        return {str(row[1]) for row in rows}

    async def tournament_matches(self, tournament_id: int) -> list[dict[str, Any]]:
        db = await self._connect()
        results: list[dict[str, Any]] = []
        try:
            for kind, table in (("bracket", "matches"), ("swiss", "swiss_matches")):
                exists = await (
                    await db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    )
                ).fetchone()
                if not exists:
                    continue
                cols = await self._table_columns(db, table)
                round_col = "round_number" if "round_number" in cols else "round"
                table_col = "table_number" if "table_number" in cols else "match_number"
                rows = await (
                    await db.execute(
                        f"""
                        SELECT m.id, m.tournament_id, m.player1_id, m.player2_id,
                               m.player1_name, m.player2_name,
                               m.player1_score, m.player2_score,
                               m.winner_id, m.status,
                               m.{round_col} round_number,
                               m.{table_col} table_number,
                               r1.deck player1_deck, r2.deck player2_deck
                        FROM {table} m
                        LEFT JOIN registrations r1
                          ON r1.tournament_id=m.tournament_id
                         AND r1.discord_id=m.player1_id
                        LEFT JOIN registrations r2
                          ON r2.tournament_id=m.tournament_id
                         AND r2.discord_id=m.player2_id
                        WHERE m.tournament_id=?
                        ORDER BY m.{round_col} DESC, m.{table_col} ASC, m.id ASC
                        """,
                        (int(tournament_id),),
                    )
                ).fetchall()
                for row in rows:
                    item = dict(row)
                    item["kind"] = kind
                    item["slot1_live"] = await self.hub.is_live(
                        self.hub.stream_key(kind, int(item["id"]), 1)
                    )
                    item["slot2_live"] = await self.hub.is_live(
                        self.hub.stream_key(kind, int(item["id"]), 2)
                    )
                    item["is_live"] = bool(item["slot1_live"] or item["slot2_live"])
                    results.append(item)
            return results
        finally:
            await db.close()

    async def set_featured(
        self,
        tournament_id: int,
        kind: str,
        match_id: int,
        updated_by: str,
    ) -> None:
        await self.ensure_schema()
        match = await self.match(kind, match_id)
        if not match or int(match["tournament_id"]) != int(tournament_id):
            raise ValueError("Ce match n'appartient pas au tournoi indiqué.")
        db = await self._connect()
        try:
            await db.execute(
                """
                INSERT INTO live_featured_match(
                    tournament_id, match_kind, match_id, updated_by
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(tournament_id)
                DO UPDATE SET
                    match_kind=excluded.match_kind,
                    match_id=excluded.match_id,
                    updated_by=excluded.updated_by,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (int(tournament_id), kind, int(match_id), str(updated_by)),
            )
            await db.commit()
        finally:
            await db.close()

    async def featured(self, tournament_id: int) -> dict[str, Any] | None:
        await self.ensure_schema()
        db = await self._connect()
        try:
            row = await (
                await db.execute(
                    "SELECT * FROM live_featured_match WHERE tournament_id=?",
                    (int(tournament_id),),
                )
            ).fetchone()
        finally:
            await db.close()
        if row is None:
            return None
        payload = dict(row)
        match = await self.match(str(payload["match_kind"]), int(payload["match_id"]))
        if match:
            payload["match"] = match
        return payload

    async def live_center(self, tournament_id: int) -> dict[str, Any]:
        tournament = await self.tournament(tournament_id)
        if tournament is None:
            raise ValueError("Tournoi introuvable.")
        matches = await self.tournament_matches(tournament_id)
        total = len(matches)
        completed = sum(
            str(m.get("status") or "").lower() in {"approved","validated","completed"}
            for m in matches
        )
        pending = sum(
            str(m.get("status") or "").lower() in {"reported","pending","validation"}
            for m in matches
        )
        live = [m for m in matches if m["is_live"]]
        current_round = max(
            [int(m.get("round_number") or 0) for m in matches] or
            [int(tournament.get("current_round") or 0)]
        )
        featured = await self.featured(tournament_id)
        return {
            "tournament": tournament,
            "matches": matches,
            "live_matches": live,
            "featured": featured,
            "progress": {
                "total": total,
                "completed": completed,
                "pending": pending,
                "remaining": max(0, total - completed),
                "percent": round(completed / total * 100, 1) if total else 0.0,
                "round": current_round,
            },
        }

    async def create_publish_token(
        self,
        *,
        tournament_id: int,
        kind: str,
        match_id: int,
        player_id: str,
        ttl_minutes: int = 180,
    ) -> str:
        await self.ensure_schema()
        match = await self.match(kind, match_id)
        if not match or int(match["tournament_id"]) != int(tournament_id):
            raise ValueError("Match introuvable.")
        p1 = str(match.get("player1_id") or "")
        p2 = str(match.get("player2_id") or "")
        if str(player_id) not in {p1, p2}:
            raise ValueError("Ce joueur ne participe pas à ce match.")
        slot = 1 if str(player_id) == p1 else 2
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires = datetime.now(timezone.utc) + timedelta(minutes=max(15, ttl_minutes))
        db = await self._connect()
        try:
            await db.execute(
                """
                INSERT INTO live_publish_tokens(
                    token_hash, tournament_id, match_kind, match_id,
                    player_id, slot, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_hash, int(tournament_id), kind, int(match_id),
                    str(player_id), slot, expires.isoformat(),
                ),
            )
            await db.commit()
        finally:
            await db.close()
        return token

    async def validate_publish_token(self, token: str) -> dict[str, Any] | None:
        await self.ensure_schema()
        token_hash = hashlib.sha256(str(token).encode()).hexdigest()
        db = await self._connect()
        try:
            row = await (
                await db.execute(
                    """
                    SELECT * FROM live_publish_tokens
                    WHERE token_hash=? AND revoked=0
                    """,
                    (token_hash,),
                )
            ).fetchone()
            if row is None:
                return None
            payload = dict(row)
            try:
                expiry = datetime.fromisoformat(str(payload["expires_at"]))
            except ValueError:
                return None
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry < datetime.now(timezone.utc):
                return None
            return payload
        finally:
            await db.close()

    async def revoke_match_tokens(self, kind: str, match_id: int) -> None:
        await self.ensure_schema()
        db = await self._connect()
        try:
            await db.execute(
                """
                UPDATE live_publish_tokens SET revoked=1
                WHERE match_kind=? AND match_id=?
                """,
                (kind, int(match_id)),
            )
            await db.commit()
        finally:
            await db.close()
