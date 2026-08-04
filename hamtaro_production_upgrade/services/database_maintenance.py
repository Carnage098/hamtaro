from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from config import (
    BACKUP_DIR,
    DATABASE,
    DATABASE_BACKUP_RETENTION,
    DATABASE_BACKUPS_ENABLED,
    SQLITE_BUSY_TIMEOUT_MS,
)

LOGGER = logging.getLogger("hamtaro.database")


async def configure_connection(connection: aiosqlite.Connection) -> None:
    await connection.execute("PRAGMA foreign_keys = ON;")
    await connection.execute("PRAGMA journal_mode = WAL;")
    await connection.execute("PRAGMA synchronous = NORMAL;")
    await connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")
    await connection.execute("PRAGMA temp_store = MEMORY;")


async def quick_check(path: Path = DATABASE) -> tuple[bool, str]:
    if not path.exists():
        return True, "new_database"

    try:
        async with aiosqlite.connect(
            str(path),
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
        ) as connection:
            await connection.execute(
                f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};"
            )
            cursor = await connection.execute("PRAGMA quick_check;")
            rows = await cursor.fetchall()
    except Exception as error:
        return False, f"check_failed: {error}"

    messages = [str(row[0]) for row in rows]
    valid = messages == ["ok"]
    return valid, "; ".join(messages) if messages else "no_result"


def _backup_sync(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(
        str(source),
        timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
    )
    target_connection = sqlite3.connect(str(target))
    try:
        source_connection.execute(
            f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};"
        )
        source_connection.backup(target_connection)
        result = target_connection.execute("PRAGMA integrity_check;").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"Sauvegarde SQLite invalide : {result}")
        target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()


async def create_backup(
    *,
    reason: str = "automatic",
    path: Path = DATABASE,
) -> Path | None:
    if not path.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_reason = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in reason
    )[:32]
    destination = BACKUP_DIR / f"database_{timestamp}_{safe_reason}.db"

    await asyncio.to_thread(_backup_sync, path, destination)
    await prune_backups()
    LOGGER.info("Sauvegarde SQLite créée : %s", destination.name)
    return destination


async def prune_backups() -> None:
    backups = sorted(
        BACKUP_DIR.glob("database_*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for obsolete in backups[DATABASE_BACKUP_RETENTION:]:
        try:
            obsolete.unlink()
        except OSError:
            LOGGER.warning(
                "Impossible de supprimer l'ancienne sauvegarde %s.",
                obsolete,
            )


async def checkpoint_wal(connection: aiosqlite.Connection | None) -> None:
    if connection is None:
        return
    try:
        await connection.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        await connection.commit()
    except Exception:
        LOGGER.exception("Échec du checkpoint WAL.")


async def prepare_database() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    valid, message = await quick_check()
    if not valid:
        raise RuntimeError(
            "La base SQLite a échoué au contrôle d'intégrité : " + message
        )

    if DATABASE.exists() and DATABASE_BACKUPS_ENABLED:
        await create_backup(reason="pre_start")
