from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

try:
    from config import DATABASE, SQLITE_BUSY_TIMEOUT_MS
except ImportError:  # tests / installation inspection
    DATABASE = "hamtaro.db"
    SQLITE_BUSY_TIMEOUT_MS = 5000


DEFAULT_TEAM_ELO = 1000
DEFAULT_K_FACTOR = 32
MAX_TEAM_IMAGE_BYTES = 5 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug or "equipe"


def canonical_pair(member1_id: str | int, member2_id: str | int) -> tuple[str, str, str]:
    first = str(member1_id or "").strip()
    second = str(member2_id or "").strip()
    if not first or not second or first == second:
        raise ValueError("Une équipe 2v2 doit contenir deux membres Discord différents.")
    ordered = sorted((first, second), key=lambda value: (len(value), value))
    return ordered[0], ordered[1], f"{ordered[0]}:{ordered[1]}"


def expected_score(rating_a: int, rating_b: int) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def elo_change(rating_a: int, rating_b: int, score_a: float, k_factor: int = DEFAULT_K_FACTOR) -> int:
    return int(round(k_factor * (score_a - expected_score(rating_a, rating_b))))


def detect_image_mime(data: bytes) -> str | None:
    # Refuse volontairement SVG/GIF : uniquement formats raster sûrs pour un logo d'équipe.
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(slots=True)
class TeamSourceColumns:
    table: str
    id_column: str | None
    name_column: str
    member1_column: str | None
    member2_column: str | None
    guild_column: str | None
    member1_name_column: str | None
    member2_name_column: str | None


class TeamDirectoryService:
    """Répertoire persistant des équipes 2v2 + classement Elo indépendant."""

    OWN_TABLES = {
        "team_profiles",
        "team_elo_events",
        "team_image_history",
        "team_tournament_history",
    }

    NAME_COLUMNS = ("team_name", "name", "nom", "duo_name", "display_name")
    ID_COLUMNS = ("id", "team_id", "duo_id")
    GUILD_COLUMNS = ("guild_id", "server_id")
    MEMBER1_COLUMNS = (
        "player1_id", "player_1_id", "member1_id", "member_1_id",
        "captain_id", "leader_id", "captain_discord_id", "player1",
    )
    MEMBER2_COLUMNS = (
        "player2_id", "player_2_id", "member2_id", "member_2_id",
        "teammate_id", "partner_id", "mate_id", "player2",
    )
    MEMBER1_NAME_COLUMNS = (
        "player1_name", "player_1_name", "member1_name", "captain_name", "leader_name",
    )
    MEMBER2_NAME_COLUMNS = (
        "player2_name", "player_2_name", "member2_name", "teammate_name", "partner_name",
    )

    TEAM_A_COLUMNS = (
        "team1_id", "team_1_id", "team_a_id", "home_team_id", "duo1_id", "duo_1_id",
        "team1", "team_a", "home_team", "duo1",
    )
    TEAM_B_COLUMNS = (
        "team2_id", "team_2_id", "team_b_id", "away_team_id", "duo2_id", "duo_2_id",
        "team2", "team_b", "away_team", "duo2",
    )
    WINNER_COLUMNS = (
        "winner_team_id", "winning_team_id", "winner_id", "winner_team", "winner",
        "winning_duo_id", "winner_duo_id",
    )
    STATUS_COLUMNS = ("status", "state", "result_status")
    APPROVED_COLUMNS = ("approved", "validated", "is_approved", "is_validated")

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = str(database_path or DATABASE)
        try:
            self.busy_timeout_ms = int(SQLITE_BUSY_TIMEOUT_MS)
        except (TypeError, ValueError):
            self.busy_timeout_ms = 5000
        self._schema_ready = False

    @asynccontextmanager
    async def connection(self):
        db = await aiosqlite.connect(self.database_path)
        db.row_factory = aiosqlite.Row
        await db.execute(f"PRAGMA busy_timeout={max(1000, self.busy_timeout_ms)}")
        await db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            await db.close()

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self.connection() as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS team_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    source_table TEXT,
                    external_team_id TEXT,
                    pair_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    member1_id TEXT NOT NULL,
                    member2_id TEXT NOT NULL,
                    member1_name TEXT,
                    member2_name TEXT,
                    image_mime TEXT,
                    image_blob BLOB,
                    image_sha256 TEXT,
                    elo INTEGER NOT NULL DEFAULT 1000,
                    peak_elo INTEGER NOT NULL DEFAULT 1000,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    draws INTEGER NOT NULL DEFAULT 0,
                    matches INTEGER NOT NULL DEFAULT 0,
                    tournaments_played INTEGER NOT NULL DEFAULT 0,
                    tournaments_won INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(guild_id, source_table, external_team_id)
                );

                CREATE INDEX IF NOT EXISTS idx_team_profiles_guild_elo
                    ON team_profiles(guild_id, elo DESC, wins DESC, name COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_team_profiles_pair
                    ON team_profiles(guild_id, pair_key);
                CREATE INDEX IF NOT EXISTS idx_team_profiles_slug
                    ON team_profiles(guild_id, slug);

                CREATE TABLE IF NOT EXISTS team_elo_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    source_key TEXT NOT NULL UNIQUE,
                    team_id INTEGER NOT NULL,
                    opponent_team_id INTEGER NOT NULL,
                    result TEXT NOT NULL,
                    old_elo INTEGER NOT NULL,
                    new_elo INTEGER NOT NULL,
                    delta INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(team_id) REFERENCES team_profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(opponent_team_id) REFERENCES team_profiles(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_team_elo_events_team
                    ON team_elo_events(team_id, id DESC);

                CREATE TABLE IF NOT EXISTS team_image_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id INTEGER NOT NULL,
                    changed_by_discord_id TEXT NOT NULL,
                    old_mime TEXT,
                    old_blob BLOB,
                    old_sha256 TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(team_id) REFERENCES team_profiles(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_team_image_history_team
                    ON team_image_history(team_id, id DESC);

                CREATE TABLE IF NOT EXISTS team_tournament_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    team_id INTEGER NOT NULL,
                    tournament_ref TEXT NOT NULL,
                    tournament_name TEXT,
                    placement INTEGER,
                    champion INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(team_id, tournament_ref),
                    FOREIGN KEY(team_id) REFERENCES team_profiles(id) ON DELETE CASCADE
                );
                """
            )
            await db.commit()
        self._schema_ready = True

    @staticmethod
    def _first_existing(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
        available = set(columns)
        return next((candidate for candidate in candidates if candidate in available), None)

    async def _table_columns(self, db: aiosqlite.Connection, table: str) -> list[str]:
        safe = table.replace('"', '""')
        rows = await (await db.execute(f'PRAGMA table_info("{safe}")')).fetchall()
        return [str(row[1]) for row in rows]

    async def _legacy_tables(self, db: aiosqlite.Connection) -> list[str]:
        rows = await (
            await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ).fetchall()
        names = [str(row[0]) for row in rows]
        return [
            name for name in names
            if name not in self.OWN_TABLES
            and not name.startswith("sqlite_")
            and (name.startswith("duo_") or "2v2" in name.lower())
        ]

    async def _discover_direct_team_sources(self, db: aiosqlite.Connection) -> list[TeamSourceColumns]:
        discovered: list[TeamSourceColumns] = []
        for table in await self._legacy_tables(db):
            columns = await self._table_columns(db, table)
            name_col = self._first_existing(columns, self.NAME_COLUMNS)
            if not name_col:
                continue
            member1_col = self._first_existing(columns, self.MEMBER1_COLUMNS)
            member2_col = self._first_existing(columns, self.MEMBER2_COLUMNS)
            if not member1_col or not member2_col:
                continue
            discovered.append(
                TeamSourceColumns(
                    table=table,
                    id_column=self._first_existing(columns, self.ID_COLUMNS),
                    name_column=name_col,
                    member1_column=member1_col,
                    member2_column=member2_col,
                    guild_column=self._first_existing(columns, self.GUILD_COLUMNS),
                    member1_name_column=self._first_existing(columns, self.MEMBER1_NAME_COLUMNS),
                    member2_name_column=self._first_existing(columns, self.MEMBER2_NAME_COLUMNS),
                )
            )
        return discovered

    async def _upsert_team_in_db(
        self,
        db: aiosqlite.Connection,
        *,
        guild_id: str,
        source_table: str,
        external_team_id: str,
        name: str,
        member1_id: str,
        member2_id: str,
        member1_name: str | None = None,
        member2_name: str | None = None,
    ) -> int:
        member1_id, member2_id, pair_key = canonical_pair(member1_id, member2_id)
        clean_name = str(name or "Équipe 2v2").strip() or "Équipe 2v2"
        base_slug = slugify(clean_name)
        now = utc_now()

        existing = await (
            await db.execute(
                """
                SELECT id FROM team_profiles
                WHERE guild_id=? AND source_table=? AND external_team_id=?
                """,
                (guild_id, source_table, external_team_id),
            )
        ).fetchone()

        if existing:
            team_id = int(existing["id"])
            await db.execute(
                """
                UPDATE team_profiles
                SET pair_key=?, name=?, slug=?, member1_id=?, member2_id=?,
                    member1_name=COALESCE(NULLIF(?, ''), member1_name),
                    member2_name=COALESCE(NULLIF(?, ''), member2_name),
                    updated_at=?
                WHERE id=?
                """,
                (
                    pair_key, clean_name, f"{base_slug}-{team_id}", member1_id, member2_id,
                    member1_name or "", member2_name or "", now, team_id,
                ),
            )
            return team_id

        cursor = await db.execute(
            """
            INSERT INTO team_profiles (
                guild_id, source_table, external_team_id, pair_key, name, slug,
                member1_id, member2_id, member1_name, member2_name,
                elo, peak_elo, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id, source_table, external_team_id, pair_key, clean_name, base_slug,
                member1_id, member2_id, member1_name, member2_name,
                DEFAULT_TEAM_ELO, DEFAULT_TEAM_ELO, now, now,
            ),
        )
        team_id = int(cursor.lastrowid)
        await db.execute(
            "UPDATE team_profiles SET slug=? WHERE id=?",
            (f"{base_slug}-{team_id}", team_id),
        )
        return team_id

    async def upsert_team(
        self,
        *,
        guild_id: str | int,
        external_team_id: str | int,
        name: str,
        member1_id: str | int,
        member2_id: str | int,
        member1_name: str | None = None,
        member2_name: str | None = None,
        source_table: str = "team_2v2_service",
    ) -> int:
        await self.ensure_schema()
        async with self.connection() as db:
            team_id = await self._upsert_team_in_db(
                db,
                guild_id=str(guild_id),
                source_table=source_table,
                external_team_id=str(external_team_id),
                name=name,
                member1_id=str(member1_id),
                member2_id=str(member2_id),
                member1_name=member1_name,
                member2_name=member2_name,
            )
            await db.commit()
            return team_id

    async def sync_legacy_duo_teams(self, guild_id: str | int) -> int:
        """Importe automatiquement les équipes depuis les tables duo_* / *2v2*."""
        await self.ensure_schema()
        guild_id = str(guild_id)
        imported = 0
        async with self.connection() as db:
            sources = await self._discover_direct_team_sources(db)
            for source in sources:
                safe = source.table.replace('"', '""')
                rows = await (await db.execute(f'SELECT rowid AS __rowid__, * FROM "{safe}"')).fetchall()
                for row in rows:
                    if source.guild_column:
                        row_guild = str(row[source.guild_column] or "").strip()
                        if row_guild and row_guild != guild_id:
                            continue
                    member1 = str(row[source.member1_column] or "").strip() if source.member1_column else ""
                    member2 = str(row[source.member2_column] or "").strip() if source.member2_column else ""
                    if not member1.isdigit() or not member2.isdigit() or member1 == member2:
                        continue
                    external_id = (
                        str(row[source.id_column])
                        if source.id_column and row[source.id_column] is not None
                        else str(row["__rowid__"])
                    )
                    await self._upsert_team_in_db(
                        db,
                        guild_id=guild_id,
                        source_table=source.table,
                        external_team_id=external_id,
                        name=str(row[source.name_column] or "Équipe 2v2"),
                        member1_id=member1,
                        member2_id=member2,
                        member1_name=(str(row[source.member1_name_column] or "") if source.member1_name_column else None),
                        member2_name=(str(row[source.member2_name_column] or "") if source.member2_name_column else None),
                    )
                    imported += 1

            # Deuxième stratégie : table d'équipes + table de membres normalisée.
            tables = await self._legacy_tables(db)
            team_tables: list[tuple[str, str, str]] = []
            member_tables: list[tuple[str, str, str, str | None]] = []
            for table in tables:
                columns = await self._table_columns(db, table)
                name_col = self._first_existing(columns, self.NAME_COLUMNS)
                id_col = self._first_existing(columns, self.ID_COLUMNS)
                if name_col and id_col:
                    team_tables.append((table, id_col, name_col))
                team_fk = self._first_existing(columns, ("team_id", "duo_id"))
                member_col = self._first_existing(columns, ("discord_id", "player_id", "member_id", "user_id"))
                member_name_col = self._first_existing(columns, ("display_name", "player_name", "member_name", "username"))
                if team_fk and member_col:
                    member_tables.append((table, team_fk, member_col, member_name_col))

            for team_table, id_col, name_col in team_tables:
                for member_table, team_fk, member_col, member_name_col in member_tables:
                    if team_table == member_table:
                        continue
                    safe_team = team_table.replace('"', '""')
                    safe_member = member_table.replace('"', '""')
                    team_rows = await (await db.execute(f'SELECT * FROM "{safe_team}"')).fetchall()
                    for team_row in team_rows:
                        external_id = str(team_row[id_col])
                        member_rows = await (
                            await db.execute(
                                f'SELECT * FROM "{safe_member}" WHERE "{team_fk}"=?',
                                (team_row[id_col],),
                            )
                        ).fetchall()
                        unique: list[aiosqlite.Row] = []
                        seen: set[str] = set()
                        for member_row in member_rows:
                            discord_id = str(member_row[member_col] or "").strip()
                            if discord_id.isdigit() and discord_id not in seen:
                                unique.append(member_row)
                                seen.add(discord_id)
                        if len(unique) != 2:
                            continue
                        await self._upsert_team_in_db(
                            db,
                            guild_id=guild_id,
                            source_table=team_table,
                            external_team_id=external_id,
                            name=str(team_row[name_col] or "Équipe 2v2"),
                            member1_id=str(unique[0][member_col]),
                            member2_id=str(unique[1][member_col]),
                            member1_name=(str(unique[0][member_name_col] or "") if member_name_col else None),
                            member2_name=(str(unique[1][member_name_col] or "") if member_name_col else None),
                        )
                        imported += 1

            await db.commit()
        return imported

    async def _resolve_team_ref(self, db: aiosqlite.Connection, guild_id: str, value: Any) -> aiosqlite.Row | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        row = await (
            await db.execute(
                """
                SELECT * FROM team_profiles
                WHERE guild_id=? AND external_team_id=?
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id, raw),
            )
        ).fetchone()
        if row:
            return row
        return await (
            await db.execute(
                """
                SELECT * FROM team_profiles
                WHERE guild_id=? AND lower(name)=lower(?)
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id, raw),
            )
        ).fetchone()

    async def _record_result_in_db(
        self,
        db: aiosqlite.Connection,
        *,
        guild_id: str,
        team_a_id: int,
        team_b_id: int,
        winner_team_id: int | None,
        source_key: str,
        k_factor: int = DEFAULT_K_FACTOR,
    ) -> bool:
        already = await (
            await db.execute("SELECT 1 FROM team_elo_events WHERE source_key=? LIMIT 1", (source_key,))
        ).fetchone()
        if already:
            return False
        team_a = await (await db.execute("SELECT * FROM team_profiles WHERE id=?", (team_a_id,))).fetchone()
        team_b = await (await db.execute("SELECT * FROM team_profiles WHERE id=?", (team_b_id,))).fetchone()
        if not team_a or not team_b or team_a_id == team_b_id:
            return False

        if winner_team_id is None:
            score_a, score_b = 0.5, 0.5
            result_a, result_b = "draw", "draw"
        elif winner_team_id == team_a_id:
            score_a, score_b = 1.0, 0.0
            result_a, result_b = "win", "loss"
        elif winner_team_id == team_b_id:
            score_a, score_b = 0.0, 1.0
            result_a, result_b = "loss", "win"
        else:
            return False

        old_a = int(team_a["elo"])
        old_b = int(team_b["elo"])
        delta_a = elo_change(old_a, old_b, score_a, k_factor)
        delta_b = -delta_a
        new_a = old_a + delta_a
        new_b = old_b + delta_b
        now = utc_now()

        def counters(result: str) -> tuple[int, int, int]:
            return (1, 0, 0) if result == "win" else ((0, 1, 0) if result == "loss" else (0, 0, 1))

        aw, al, ad = counters(result_a)
        bw, bl, bd = counters(result_b)
        await db.execute(
            """
            UPDATE team_profiles
            SET elo=?, peak_elo=MAX(peak_elo, ?), wins=wins+?, losses=losses+?, draws=draws+?,
                matches=matches+1, updated_at=?
            WHERE id=?
            """,
            (new_a, new_a, aw, al, ad, now, team_a_id),
        )
        await db.execute(
            """
            UPDATE team_profiles
            SET elo=?, peak_elo=MAX(peak_elo, ?), wins=wins+?, losses=losses+?, draws=draws+?,
                matches=matches+1, updated_at=?
            WHERE id=?
            """,
            (new_b, new_b, bw, bl, bd, now, team_b_id),
        )
        await db.executemany(
            """
            INSERT INTO team_elo_events (
                guild_id, source_key, team_id, opponent_team_id, result,
                old_elo, new_elo, delta, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (guild_id, f"{source_key}:A", team_a_id, team_b_id, result_a, old_a, new_a, delta_a, now),
                (guild_id, f"{source_key}:B", team_b_id, team_a_id, result_b, old_b, new_b, delta_b, now),
            ],
        )
        return True

    async def record_result(
        self,
        *,
        guild_id: str | int,
        team_a_id: int,
        team_b_id: int,
        winner_team_id: int | None,
        source_key: str,
        k_factor: int = DEFAULT_K_FACTOR,
    ) -> bool:
        await self.ensure_schema()
        guild_id = str(guild_id)
        async with self.connection() as db:
            # Base unique parent : permet de vérifier l'idempotence avant les :A/:B.
            existing = await (
                await db.execute(
                    "SELECT 1 FROM team_elo_events WHERE source_key IN (?, ?) LIMIT 1",
                    (f"{source_key}:A", f"{source_key}:B"),
                )
            ).fetchone()
            if existing:
                return False
            changed = await self._record_result_in_db(
                db,
                guild_id=guild_id,
                team_a_id=team_a_id,
                team_b_id=team_b_id,
                winner_team_id=winner_team_id,
                source_key=source_key,
                k_factor=k_factor,
            )
            await db.commit()
            return changed

    async def sync_legacy_duo_results(self, guild_id: str | int) -> int:
        """Convertit automatiquement les résultats 2v2 validés trouvés dans les tables duo_* en Elo."""
        await self.ensure_schema()
        guild_id = str(guild_id)
        processed = 0
        finished_statuses = {
            "approved", "validated", "finished", "completed", "done", "closed",
            "termine", "terminé", "valide", "validé", "accepte", "accepté",
        }
        async with self.connection() as db:
            for table in await self._legacy_tables(db):
                lowered = table.lower()
                if not any(word in lowered for word in ("match", "result", "game")):
                    continue
                columns = await self._table_columns(db, table)
                team_a_col = self._first_existing(columns, self.TEAM_A_COLUMNS)
                team_b_col = self._first_existing(columns, self.TEAM_B_COLUMNS)
                winner_col = self._first_existing(columns, self.WINNER_COLUMNS)
                if not team_a_col or not team_b_col or not winner_col:
                    continue
                id_col = self._first_existing(columns, self.ID_COLUMNS)
                guild_col = self._first_existing(columns, self.GUILD_COLUMNS)
                status_col = self._first_existing(columns, self.STATUS_COLUMNS)
                approved_col = self._first_existing(columns, self.APPROVED_COLUMNS)
                safe = table.replace('"', '""')
                rows = await (await db.execute(f'SELECT rowid AS __rowid__, * FROM "{safe}"')).fetchall()
                for row in rows:
                    if guild_col:
                        row_guild = str(row[guild_col] or "").strip()
                        if row_guild and row_guild != guild_id:
                            continue
                    if approved_col and str(row[approved_col] or "").strip().lower() not in {"1", "true", "yes", "approved", "validated"}:
                        continue
                    if status_col:
                        status = str(row[status_col] or "").strip().lower()
                        if status and status not in finished_statuses:
                            continue
                    team_a = await self._resolve_team_ref(db, guild_id, row[team_a_col])
                    team_b = await self._resolve_team_ref(db, guild_id, row[team_b_col])
                    if not team_a or not team_b:
                        continue
                    winner_raw = str(row[winner_col] or "").strip()
                    winner = await self._resolve_team_ref(db, guild_id, winner_raw) if winner_raw else None
                    if winner_raw and not winner:
                        continue
                    source_id = str(row[id_col]) if id_col and row[id_col] is not None else str(row["__rowid__"])
                    source_key = f"legacy:{table}:{source_id}"
                    existing = await (
                        await db.execute(
                            "SELECT 1 FROM team_elo_events WHERE source_key IN (?, ?) LIMIT 1",
                            (f"{source_key}:A", f"{source_key}:B"),
                        )
                    ).fetchone()
                    if existing:
                        continue
                    changed = await self._record_result_in_db(
                        db,
                        guild_id=guild_id,
                        team_a_id=int(team_a["id"]),
                        team_b_id=int(team_b["id"]),
                        winner_team_id=int(winner["id"]) if winner else None,
                        source_key=source_key,
                    )
                    if changed:
                        processed += 1
            await db.commit()
        return processed

    async def refresh_from_2v2(self, guild_id: str | int) -> dict[str, int]:
        imported = await self.sync_legacy_duo_teams(guild_id)
        results = await self.sync_legacy_duo_results(guild_id)
        return {"teams_seen": imported, "results_imported": results}

    async def rankings(self, guild_id: str | int, limit: int = 200) -> list[dict[str, Any]]:
        await self.ensure_schema()
        async with self.connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT id, guild_id, source_table, external_team_id, pair_key, name, slug,
                           member1_id, member2_id, member1_name, member2_name,
                           image_sha256, elo, peak_elo, wins, losses, draws, matches,
                           tournaments_played, tournaments_won, created_at, updated_at
                    FROM team_profiles
                    WHERE guild_id=?
                    ORDER BY elo DESC, wins DESC, losses ASC, name COLLATE NOCASE ASC
                    LIMIT ?
                    """,
                    (str(guild_id), max(1, min(int(limit), 500))),
                )
            ).fetchall()
        result = []
        for rank, row in enumerate(rows, start=1):
            item = dict(row)
            item["rank"] = rank
            total = int(item["wins"]) + int(item["losses"]) + int(item["draws"])
            item["win_rate"] = round((int(item["wins"]) / total) * 100, 1) if total else 0.0
            item["has_image"] = bool(item.get("image_sha256"))
            result.append(item)
        return result

    async def get_team(self, guild_id: str | int, team_id: int) -> dict[str, Any] | None:
        await self.ensure_schema()
        async with self.connection() as db:
            row = await (
                await db.execute(
                    """
                    SELECT id, guild_id, source_table, external_team_id, pair_key, name, slug,
                           member1_id, member2_id, member1_name, member2_name,
                           image_mime, image_sha256, elo, peak_elo, wins, losses, draws, matches,
                           tournaments_played, tournaments_won, created_at, updated_at
                    FROM team_profiles WHERE guild_id=? AND id=?
                    """,
                    (str(guild_id), int(team_id)),
                )
            ).fetchone()
            if not row:
                return None
            events = await (
                await db.execute(
                    """
                    SELECT e.*, o.name AS opponent_name
                    FROM team_elo_events e
                    JOIN team_profiles o ON o.id=e.opponent_team_id
                    WHERE e.team_id=?
                    ORDER BY e.id DESC LIMIT 30
                    """,
                    (int(team_id),),
                )
            ).fetchall()
            tournaments = await (
                await db.execute(
                    """
                    SELECT * FROM team_tournament_history
                    WHERE team_id=? ORDER BY id DESC LIMIT 30
                    """,
                    (int(team_id),),
                )
            ).fetchall()
        item = dict(row)
        total = int(item["wins"]) + int(item["losses"]) + int(item["draws"])
        item["win_rate"] = round((int(item["wins"]) / total) * 100, 1) if total else 0.0
        item["has_image"] = bool(item.get("image_sha256"))
        item["elo_history"] = [dict(event) for event in events]
        item["tournament_history"] = [dict(t) for t in tournaments]
        return item

    async def get_image(self, team_id: int) -> tuple[str, bytes, str] | None:
        await self.ensure_schema()
        async with self.connection() as db:
            row = await (
                await db.execute(
                    "SELECT image_mime, image_blob, image_sha256 FROM team_profiles WHERE id=?",
                    (int(team_id),),
                )
            ).fetchone()
        if not row or not row["image_blob"] or not row["image_mime"]:
            return None
        return str(row["image_mime"]), bytes(row["image_blob"]), str(row["image_sha256"] or "")

    async def can_edit(self, team_id: int, discord_id: str | int) -> bool:
        await self.ensure_schema()
        raw = str(discord_id)
        async with self.connection() as db:
            row = await (
                await db.execute(
                    "SELECT member1_id, member2_id FROM team_profiles WHERE id=?",
                    (int(team_id),),
                )
            ).fetchone()
        return bool(row and raw in {str(row["member1_id"]), str(row["member2_id"])})

    async def set_team_image(self, team_id: int, changed_by_discord_id: str | int, data: bytes) -> str:
        await self.ensure_schema()
        if len(data) > MAX_TEAM_IMAGE_BYTES:
            raise ValueError("L'image dépasse la limite de 5 Mo.")
        mime = detect_image_mime(data)
        if mime is None:
            raise ValueError("Format non pris en charge. Utilise PNG, JPEG ou WebP.")
        digest = hashlib.sha256(data).hexdigest()
        now = utc_now()
        async with self.connection() as db:
            current = await (
                await db.execute(
                    "SELECT image_mime, image_blob, image_sha256 FROM team_profiles WHERE id=?",
                    (int(team_id),),
                )
            ).fetchone()
            if not current:
                raise ValueError("Équipe introuvable.")
            if current["image_blob"]:
                await db.execute(
                    """
                    INSERT INTO team_image_history (
                        team_id, changed_by_discord_id, old_mime, old_blob, old_sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(team_id), str(changed_by_discord_id), current["image_mime"],
                        current["image_blob"], current["image_sha256"], now,
                    ),
                )
            await db.execute(
                """
                UPDATE team_profiles
                SET image_mime=?, image_blob=?, image_sha256=?, updated_at=?
                WHERE id=?
                """,
                (mime, data, digest, now, int(team_id)),
            )
            # Ne conserve que les 3 versions précédentes pour éviter de gonfler SQLite.
            await db.execute(
                """
                DELETE FROM team_image_history
                WHERE team_id=? AND id NOT IN (
                    SELECT id FROM team_image_history
                    WHERE team_id=? ORDER BY id DESC LIMIT 3
                )
                """,
                (int(team_id), int(team_id)),
            )
            await db.commit()
        return digest
