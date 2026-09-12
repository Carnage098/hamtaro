from __future__ import annotations

from typing import Any, Iterable

import aiosqlite

from config import DATABASE, SQLITE_BUSY_TIMEOUT_MS


class BossArenaService:
    """Stockage isolé du système de matchs Boss V2.

    Ce service n'altère aucune table historique de Hamtaro. Il ajoute deux
    tables dédiées puis, uniquement quand cela est nécessaire, met à jour le
    statut d'un challenger dans la table Boss déjà existante.
    """

    PLATFORM_FORMATS: dict[str, tuple[str, ...]] = {
        "master_duel": ("classique", "anime", "structure_boutique"),
        "remote": ("classique", "goat", "edison"),
        "omega": ("classique", "goat", "edison"),
    }

    PLATFORM_LABELS: dict[str, str] = {
        "master_duel": "Master Duel",
        "remote": "Remote Duel",
        "omega": "YGO Omega",
    }

    FORMAT_LABELS: dict[str, str] = {
        "classique": "Format classique",
        "anime": "Format animé",
        "structure_boutique": "Deck de structure boutique",
        "goat": "GOAT",
        "edison": "Edison",
    }

    ACTIVE_STATUSES = ("creating", "active", "pending_confirmation", "disputed")

    async def _connect(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(
            str(DATABASE),
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
        )
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")
        return db

    async def ensure_schema(self) -> None:
        db = await self._connect()
        try:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS boss_arena_settings (
                    guild_id TEXT PRIMARY KEY,
                    match_channel_id TEXT,
                    configured_boss_id TEXT,
                    platform_key TEXT,
                    format_key TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS boss_arena_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    reign_number INTEGER NOT NULL,
                    boss_id TEXT NOT NULL,
                    boss_name TEXT NOT NULL,
                    challenger_id TEXT NOT NULL,
                    challenger_name TEXT NOT NULL,
                    challenger_row_id INTEGER,
                    parent_channel_id TEXT,
                    announcement_message_id TEXT,
                    thread_id TEXT,
                    platform_key TEXT NOT NULL,
                    format_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'creating',
                    reported_winner_id TEXT,
                    reported_by TEXT,
                    winner_id TEXT,
                    cancelled_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_boss_arena_thread
                    ON boss_arena_matches(guild_id, thread_id);

                CREATE INDEX IF NOT EXISTS idx_boss_arena_boss
                    ON boss_arena_matches(guild_id, boss_id, status);

                CREATE INDEX IF NOT EXISTS idx_boss_arena_challenger
                    ON boss_arena_matches(guild_id, challenger_id, status);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_boss_arena_one_active
                    ON boss_arena_matches(guild_id)
                    WHERE status IN ('creating', 'active', 'pending_confirmation', 'disputed');
                """
            )
            await db.commit()
        finally:
            await db.close()

    async def _ensure_settings(self, db: aiosqlite.Connection, guild_id: str) -> None:
        await db.execute(
            "INSERT OR IGNORE INTO boss_arena_settings(guild_id) VALUES(?)",
            (guild_id,),
        )

    async def settings(self, guild_id: str) -> dict[str, Any]:
        await self.ensure_schema()
        db = await self._connect()
        try:
            await self._ensure_settings(db, guild_id)
            await db.commit()
            cur = await db.execute(
                "SELECT * FROM boss_arena_settings WHERE guild_id = ?",
                (guild_id,),
            )
            row = await cur.fetchone()
            return dict(row) if row else {"guild_id": guild_id}
        finally:
            await db.close()

    def validate_configuration(self, platform_key: str, format_key: str) -> None:
        formats = self.PLATFORM_FORMATS.get(platform_key)
        if formats is None:
            raise ValueError("Cette plateforme n'est pas disponible pour le format Boss.")
        if format_key not in formats:
            platform = self.PLATFORM_LABELS.get(platform_key, platform_key)
            allowed = ", ".join(self.FORMAT_LABELS.get(item, item) for item in formats)
            raise ValueError(
                f"Le format choisi n'est pas disponible sur {platform}. Formats autorisés : {allowed}."
            )

    async def configure(
        self,
        guild_id: str,
        boss_id: str,
        platform_key: str,
        format_key: str,
    ) -> dict[str, Any]:
        self.validate_configuration(platform_key, format_key)
        await self.ensure_schema()
        db = await self._connect()
        try:
            await self._ensure_settings(db, guild_id)
            await db.execute(
                """
                UPDATE boss_arena_settings
                SET configured_boss_id = ?, platform_key = ?, format_key = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                (boss_id, platform_key, format_key, guild_id),
            )
            await db.commit()
        finally:
            await db.close()
        return await self.settings(guild_id)

    async def clear_configuration(self, guild_id: str) -> None:
        """Réinitialise seulement le choix du Boss, jamais le salon de matchs."""
        await self.ensure_schema()
        db = await self._connect()
        try:
            await self._ensure_settings(db, guild_id)
            await db.execute(
                """
                UPDATE boss_arena_settings
                SET configured_boss_id = NULL, platform_key = NULL, format_key = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            await db.commit()
        finally:
            await db.close()

    async def carry_configuration(
        self,
        guild_id: str,
        new_boss_id: str,
        *,
        default_platform_key: str = "master_duel",
        default_format_key: str = "classique",
    ) -> dict[str, Any]:
        """Transfère les règles au nouveau Boss sans interrompre la file.

        Les choix existants sont conservés. Pour une première activation, des
        règles simples et compatibles sont posées afin que l'arène puisse
        démarrer sans commande de configuration supplémentaire.
        """
        current = await self.settings(guild_id)
        platform_key = str(current.get("platform_key") or default_platform_key)
        format_key = str(current.get("format_key") or default_format_key)
        return await self.configure(
            guild_id,
            str(new_boss_id),
            platform_key,
            format_key,
        )

    async def set_match_channel(self, guild_id: str, channel_id: str | None) -> None:
        await self.ensure_schema()
        db = await self._connect()
        try:
            await self._ensure_settings(db, guild_id)
            await db.execute(
                """
                UPDATE boss_arena_settings
                SET match_channel_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                (channel_id, guild_id),
            )
            await db.commit()
        finally:
            await db.close()

    async def active_match(self, guild_id: str) -> dict[str, Any] | None:
        await self.ensure_schema()
        db = await self._connect()
        try:
            placeholders = ",".join("?" for _ in self.ACTIVE_STATUSES)
            cur = await db.execute(
                f"""
                SELECT * FROM boss_arena_matches
                WHERE guild_id = ? AND status IN ({placeholders})
                ORDER BY id ASC LIMIT 1
                """,
                (guild_id, *self.ACTIVE_STATUSES),
            )
            row = await cur.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def active_matches_for_boss(
        self,
        guild_id: str,
        boss_id: str,
    ) -> list[dict[str, Any]]:
        await self.ensure_schema()
        db = await self._connect()
        try:
            placeholders = ",".join("?" for _ in self.ACTIVE_STATUSES)
            cur = await db.execute(
                f"""
                SELECT * FROM boss_arena_matches
                WHERE guild_id = ? AND boss_id = ? AND status IN ({placeholders})
                ORDER BY id ASC
                """,
                (guild_id, boss_id, *self.ACTIVE_STATUSES),
            )
            return [dict(row) for row in await cur.fetchall()]
        finally:
            await db.close()

    async def match_by_thread(self, guild_id: str, thread_id: str) -> dict[str, Any] | None:
        await self.ensure_schema()
        db = await self._connect()
        try:
            cur = await db.execute(
                """
                SELECT * FROM boss_arena_matches
                WHERE guild_id = ? AND thread_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id, thread_id),
            )
            row = await cur.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def match_for_challenger(
        self,
        guild_id: str,
        challenger_id: str,
    ) -> dict[str, Any] | None:
        await self.ensure_schema()
        db = await self._connect()
        try:
            placeholders = ",".join("?" for _ in self.ACTIVE_STATUSES)
            cur = await db.execute(
                f"""
                SELECT * FROM boss_arena_matches
                WHERE guild_id = ? AND challenger_id = ?
                  AND status IN ({placeholders})
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id, challenger_id, *self.ACTIVE_STATUSES),
            )
            row = await cur.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def create_match(
        self,
        *,
        guild_id: str,
        reign_number: int,
        boss_id: str,
        boss_name: str,
        challenger_id: str,
        challenger_name: str,
        challenger_row_id: int,
        platform_key: str,
        format_key: str,
    ) -> dict[str, Any]:
        self.validate_configuration(platform_key, format_key)
        await self.ensure_schema()
        db = await self._connect()
        try:
            await db.execute("BEGIN IMMEDIATE")
            placeholders = ",".join("?" for _ in self.ACTIVE_STATUSES)
            cur = await db.execute(
                f"""
                SELECT id FROM boss_arena_matches
                WHERE guild_id = ? AND status IN ({placeholders})
                LIMIT 1
                """,
                (guild_id, *self.ACTIVE_STATUSES),
            )
            if await cur.fetchone():
                await db.rollback()
                raise ValueError("Un match Boss est déjà actif.")
            cur = await db.execute(
                """
                INSERT INTO boss_arena_matches(
                    guild_id, reign_number, boss_id, boss_name,
                    challenger_id, challenger_name, challenger_row_id,
                    platform_key, format_key, status
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'creating')
                """,
                (
                    guild_id,
                    int(reign_number),
                    boss_id,
                    boss_name,
                    challenger_id,
                    challenger_name,
                    int(challenger_row_id),
                    platform_key,
                    format_key,
                ),
            )
            match_id = int(cur.lastrowid)
            await db.execute(
                """
                UPDATE boss_challengers
                SET status = 'in_match', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND guild_id = ?
                """,
                (int(challenger_row_id), guild_id),
            )
            await db.commit()
            cur = await db.execute(
                "SELECT * FROM boss_arena_matches WHERE id = ?",
                (match_id,),
            )
            return dict(await cur.fetchone())
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass
            raise
        finally:
            await db.close()

    async def attach_discord_resources(
        self,
        match_id: int,
        *,
        parent_channel_id: str,
        announcement_message_id: str,
        thread_id: str,
    ) -> None:
        db = await self._connect()
        try:
            await db.execute(
                """
                UPDATE boss_arena_matches
                SET parent_channel_id = ?, announcement_message_id = ?, thread_id = ?,
                    status = 'active', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'creating'
                """,
                (parent_channel_id, announcement_message_id, thread_id, int(match_id)),
            )
            await db.commit()
        finally:
            await db.close()

    async def restore_challenger(self, guild_id: str, challenger_row_id: int) -> None:
        db = await self._connect()
        try:
            await db.execute(
                """
                UPDATE boss_challengers
                SET status = 'registered', updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ? AND id = ? AND status = 'in_match'
                """,
                (guild_id, int(challenger_row_id)),
            )
            await db.commit()
        finally:
            await db.close()

    async def report_result(
        self,
        match_id: int,
        *,
        winner_id: str,
        reporter_id: str,
    ) -> dict[str, Any]:
        db = await self._connect()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                "SELECT * FROM boss_arena_matches WHERE id = ?",
                (int(match_id),),
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError("Match Boss introuvable.")
            data = dict(row)
            if data["status"] not in {"active", "pending_confirmation"}:
                raise ValueError("Ce match n'accepte plus de déclaration de résultat.")
            participants = {str(data["boss_id"]), str(data["challenger_id"])}
            if str(reporter_id) not in participants:
                raise ValueError("Seuls les deux joueurs du match peuvent déclarer le résultat.")
            if str(winner_id) not in participants:
                raise ValueError("Le gagnant déclaré doit participer au match.")
            await db.execute(
                """
                UPDATE boss_arena_matches
                SET reported_winner_id = ?, reported_by = ?,
                    status = 'pending_confirmation', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (winner_id, reporter_id, int(match_id)),
            )
            await db.commit()
            data["reported_winner_id"] = winner_id
            data["reported_by"] = reporter_id
            data["status"] = "pending_confirmation"
            return data
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass
            raise
        finally:
            await db.close()

    async def mark_disputed(self, match_id: int) -> None:
        db = await self._connect()
        try:
            await db.execute(
                """
                UPDATE boss_arena_matches
                SET status = 'disputed', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending_confirmation'
                """,
                (int(match_id),),
            )
            await db.commit()
        finally:
            await db.close()

    async def complete_match(self, match_id: int, winner_id: str) -> None:
        db = await self._connect()
        try:
            await db.execute(
                """
                UPDATE boss_arena_matches
                SET status = 'completed', winner_id = ?,
                    completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (winner_id, int(match_id)),
            )
            await db.commit()
        finally:
            await db.close()

    async def cancel_match(
        self,
        match_id: int,
        *,
        reason: str,
        restore_challenger: bool = False,
    ) -> None:
        db = await self._connect()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                "SELECT * FROM boss_arena_matches WHERE id = ?",
                (int(match_id),),
            )
            row = await cur.fetchone()
            if not row:
                await db.rollback()
                return
            data = dict(row)
            await db.execute(
                """
                UPDATE boss_arena_matches
                SET status = 'cancelled', cancelled_reason = ?,
                    completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (reason[:250], int(match_id)),
            )
            if restore_challenger and data.get("challenger_row_id"):
                await db.execute(
                    """
                    UPDATE boss_challengers
                    SET status = 'registered', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND guild_id = ? AND status = 'in_match'
                    """,
                    (int(data["challenger_row_id"]), str(data["guild_id"])),
                )
            await db.commit()
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass
            raise
        finally:
            await db.close()

    async def migrate_waiting_challengers(
        self,
        guild_id: str,
        *,
        old_reign: int,
        new_reign: int,
        excluded_ids: Iterable[str] = (),
    ) -> int:
        """Conserve la file lors d'un changement immédiat de Boss.

        Les horaires sont volontairement effacés : le nouveau Boss peut choisir
        une autre plateforme ou un autre format.
        """
        excluded = {str(value) for value in excluded_ids}
        db = await self._connect()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                """
                SELECT discord_id, username, position
                FROM boss_challengers
                WHERE guild_id = ? AND week_number = ?
                  AND status IN ('registered', 'scheduled', 'in_match')
                ORDER BY position ASC, id ASC
                """,
                (guild_id, int(old_reign)),
            )
            rows = await cur.fetchall()
            position = 0
            migrated = 0
            for row in rows:
                discord_id = str(row["discord_id"])
                if discord_id in excluded:
                    continue
                position += 1
                cur_insert = await db.execute(
                    """
                    INSERT OR IGNORE INTO boss_challengers(
                        guild_id, week_number, discord_id, username,
                        position, scheduled_at, status
                    ) VALUES(?, ?, ?, ?, ?, NULL, 'registered')
                    """,
                    (
                        guild_id,
                        int(new_reign),
                        discord_id,
                        str(row["username"]),
                        position,
                    ),
                )
                if cur_insert.rowcount:
                    migrated += 1
            await db.commit()
            return migrated
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass
            raise
        finally:
            await db.close()
