from __future__ import annotations

import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

try:
    from config import DATABASE
except ImportError:
    from database import DATABASE

from services.deck_canonicalizer import DeckCanonicalizer


class ArchetypeRepairService:
    """Diagnostic et réparation persistante des anciens noms de decks."""

    def __init__(
        self,
        database_path: str = DATABASE,
        canonicalizer: DeckCanonicalizer | None = None,
    ) -> None:
        self.database_path = database_path
        self.canonicalizer = canonicalizer or DeckCanonicalizer()

    async def preview(self, guild_id: str) -> dict[str, Any]:
        db = await aiosqlite.connect(self.database_path)
        db.row_factory = aiosqlite.Row
        try:
            rows = await (
                await db.execute(
                    """
                    SELECT r.id, r.tournament_id, r.discord_id, r.deck,
                           t.name AS tournament_name, t.code AS tournament_code
                    FROM registrations r
                    JOIN tournaments t ON t.id=r.tournament_id
                    WHERE t.guild_id=?
                      AND TRIM(COALESCE(r.deck,'')) <> ''
                    ORDER BY r.id ASC
                    """,
                    (guild_id,),
                )
            ).fetchall()
        finally:
            await db.close()

        changes: list[dict[str, Any]] = []
        canonical_counts: Counter[str] = Counter()
        raw_counts: Counter[str] = Counter()

        for row in rows:
            raw = self.canonicalizer.normalize_text(row["deck"])
            canonical = self.canonicalizer.canonicalize(raw)
            raw_counts[raw] += 1
            canonical_counts[canonical] += 1
            if raw != canonical:
                changes.append(
                    {
                        "registration_id": int(row["id"]),
                        "tournament_id": int(row["tournament_id"]),
                        "tournament": str(
                            row["tournament_name"]
                            or row["tournament_code"]
                            or row["tournament_id"]
                        ),
                        "player_id": str(row["discord_id"]),
                        "before": raw,
                        "after": canonical,
                    }
                )

        groups = []
        for canonical, count in canonical_counts.most_common():
            aliases = sorted(
                [
                    raw
                    for raw in raw_counts
                    if self.canonicalizer.canonicalize(raw) == canonical
                ],
                key=str.casefold,
            )
            if len(aliases) > 1:
                groups.append(
                    {
                        "canonical": canonical,
                        "aliases": aliases,
                        "registrations": int(count),
                    }
                )

        return {
            "registrations": len(rows),
            "changes": changes,
            "change_count": len(changes),
            "merged_groups": groups,
            "merged_group_count": len(groups),
        }

    def _backup(self) -> str:
        source = Path(self.database_path)
        if not source.exists():
            raise FileNotFoundError(f"Base SQLite introuvable : {source}")
        backup_dir = source.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = backup_dir / f"{source.stem}_{stamp}_archetype_repair{source.suffix}"
        shutil.copy2(source, destination)
        return str(destination)

    async def _merge_artwork_state(
        self,
        db: aiosqlite.Connection,
        guild_id: str,
    ) -> int:
        exists = await (
            await db.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='archetype_artwork_state'
                """
            )
        ).fetchone()
        if not exists:
            return 0

        rows = await (
            await db.execute(
                """
                SELECT *
                FROM archetype_artwork_state
                WHERE guild_id=?
                ORDER BY updated_at DESC
                """,
                (guild_id,),
            )
        ).fetchall()

        merged = 0
        for row in rows:
            current_key = str(row["deck_key"])
            current_name = str(row["deck_name"])
            canonical_name = self.canonicalizer.canonicalize(current_name)
            canonical_key = self.canonicalizer.canonical_key(canonical_name)
            if current_key == canonical_key and current_name == canonical_name:
                continue

            target = await (
                await db.execute(
                    """
                    SELECT * FROM archetype_artwork_state
                    WHERE guild_id=? AND deck_key=?
                    """,
                    (guild_id, canonical_key),
                )
            ).fetchone()

            if target is None:
                await db.execute(
                    """
                    UPDATE archetype_artwork_state
                    SET deck_key=?, deck_name=?, updated_at=CURRENT_TIMESTAMP
                    WHERE guild_id=? AND deck_key=?
                    """,
                    (canonical_key, canonical_name, guild_id, current_key),
                )
                merged += 1
                continue

            # Si la cible n'a pas d'artwork communautaire actif, on conserve
            # celui de l'alias fusionné plutôt que de le perdre.
            target_active = str(target["active_image_url"] or "")
            source_active = str(row["active_image_url"] or "")
            if not target_active and source_active:
                await db.execute(
                    """
                    UPDATE archetype_artwork_state
                    SET active_card_name=?,
                        active_image_url=?,
                        active_proposal_id=?,
                        active_submitted_by=?,
                        active_submitted_name=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE guild_id=? AND deck_key=?
                    """,
                    (
                        row["active_card_name"],
                        row["active_image_url"],
                        row["active_proposal_id"],
                        row["active_submitted_by"],
                        row["active_submitted_name"],
                        guild_id,
                        canonical_key,
                    ),
                )
            await db.execute(
                """
                DELETE FROM archetype_artwork_state
                WHERE guild_id=? AND deck_key=?
                """,
                (guild_id, current_key),
            )
            merged += 1
        return merged

    async def _merge_proposals(
        self,
        db: aiosqlite.Connection,
        guild_id: str,
    ) -> int:
        exists = await (
            await db.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='archetype_artwork_proposals'
                """
            )
        ).fetchone()
        if not exists:
            return 0

        rows = await (
            await db.execute(
                """
                SELECT *
                FROM archetype_artwork_proposals
                WHERE guild_id=?
                ORDER BY id ASC
                """,
                (guild_id,),
            )
        ).fetchall()

        changed = 0
        for row in rows:
            current_name = str(row["deck_name"])
            canonical_name = self.canonicalizer.canonicalize(current_name)
            canonical_key = self.canonicalizer.canonical_key(canonical_name)
            if (
                str(row["deck_key"]) == canonical_key
                and current_name == canonical_name
            ):
                continue

            # L'index unique interdit 2 propositions pending du même auteur
            # pour le même deck. Si la fusion crée ce cas, l'ancienne est
            # rejetée proprement avant le renommage.
            if str(row["status"]) == "pending":
                duplicate = await (
                    await db.execute(
                        """
                        SELECT id
                        FROM archetype_artwork_proposals
                        WHERE guild_id=? AND deck_key=? AND submitted_by=?
                          AND status='pending' AND id<>?
                        LIMIT 1
                        """,
                        (
                            guild_id,
                            canonical_key,
                            str(row["submitted_by"]),
                            int(row["id"]),
                        ),
                    )
                ).fetchone()
                if duplicate is not None:
                    await db.execute(
                        """
                        UPDATE archetype_artwork_proposals
                        SET status='rejected',
                            rejection_reason='Fusion automatique d''un alias de deck',
                            reviewed_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (int(row["id"]),),
                    )

            await db.execute(
                """
                UPDATE archetype_artwork_proposals
                SET deck_key=?, deck_name=?
                WHERE id=?
                """,
                (canonical_key, canonical_name, int(row["id"])),
            )
            changed += 1
        return changed

    async def apply(self, guild_id: str) -> dict[str, Any]:
        preview = await self.preview(guild_id)
        backup_path = self._backup()

        db = await aiosqlite.connect(self.database_path)
        db.row_factory = aiosqlite.Row
        try:
            await db.execute("BEGIN IMMEDIATE")
            for change in preview["changes"]:
                await db.execute(
                    """
                    UPDATE registrations
                    SET deck=?
                    WHERE id=?
                    """,
                    (
                        change["after"],
                        int(change["registration_id"]),
                    ),
                )

            artwork_changes = await self._merge_artwork_state(db, guild_id)
            proposal_changes = await self._merge_proposals(db, guild_id)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()

        return {
            **preview,
            "backup_path": backup_path,
            "artwork_changes": artwork_changes,
            "proposal_changes": proposal_changes,
        }
