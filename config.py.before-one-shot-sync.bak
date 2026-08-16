from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
        "",
    }


def env_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def env_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


BASE_DIR = Path(__file__).resolve().parent

# Discord
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
PUBLIC_GUILD_ID = os.getenv("PUBLIC_GUILD_ID", "").strip()
GUILD_ID = (os.getenv("GUILD_ID") or PUBLIC_GUILD_ID or "").strip()
ENABLE_MESSAGE_CONTENT = env_bool("ENABLE_MESSAGE_CONTENT", False)
SYNC_GLOBAL_COMMANDS = env_bool("SYNC_GLOBAL_COMMANDS", False)
SYNC_GUILD_COMMANDS = env_bool("SYNC_GUILD_COMMANDS", True)

# Identifiants facultatifs de salons.
# Les matchs vedettes sont normalement configurés via /setup_plus configure.
CASUAL_MATCH_CHANNEL_ID = os.getenv("CASUAL_MATCH_CHANNEL_ID", "").strip()

# SQLite : chemin manuel, volume Railway, puis fichier local.
_database_path = os.getenv("DATABASE_PATH", "").strip()
_volume_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()

if _database_path:
    DATABASE = Path(_database_path).expanduser()
elif _volume_path:
    DATABASE = Path(_volume_path) / "database.db"
else:
    DATABASE = BASE_DIR / "database.db"

DATABASE = DATABASE.resolve()
DATABASE.parent.mkdir(parents=True, exist_ok=True)

BACKUP_DIR = Path(
    os.getenv("DATABASE_BACKUP_DIR", str(DATABASE.parent / "backups"))
).expanduser().resolve()
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

INSTANCE_LOCK_PATH = Path(
    os.getenv("INSTANCE_LOCK_PATH", str(DATABASE.parent / "hamtaro.lock"))
).expanduser().resolve()
INSTANCE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

SQLITE_BUSY_TIMEOUT_MS = env_int(
    "SQLITE_BUSY_TIMEOUT_MS",
    30_000,
    minimum=1_000,
    maximum=120_000,
)
DATABASE_BACKUPS_ENABLED = env_bool("DATABASE_BACKUPS_ENABLED", True)
DATABASE_BACKUP_INTERVAL_HOURS = env_int(
    "DATABASE_BACKUP_INTERVAL_HOURS",
    12,
    minimum=1,
    maximum=168,
)
DATABASE_BACKUP_RETENTION = env_int(
    "DATABASE_BACKUP_RETENTION",
    14,
    minimum=2,
    maximum=100,
)

# Journaux, sécurité et surveillance.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
DEBUG_INTERACTIONS = env_bool("DEBUG_INTERACTIONS", False)
ENABLE_WATCHDOG = env_bool("ENABLE_WATCHDOG", True)
FAIL_ON_COG_ERROR = env_bool("FAIL_ON_COG_ERROR", True)
EVENT_LOOP_WATCHDOG_INTERVAL = env_float(
    "EVENT_LOOP_WATCHDOG_INTERVAL",
    1.0,
    minimum=0.5,
    maximum=60.0,
)
EVENT_LOOP_WARNING_SECONDS = env_float(
    "EVENT_LOOP_WARNING_SECONDS",
    2.0,
    minimum=1.0,
    maximum=300.0,
)

# Site public et outils professionnels.
WEBSITE_ENABLED = env_bool("WEBSITE_ENABLED", True)
WEBSITE_BASE_URL = os.getenv("WEBSITE_BASE_URL", "").strip().rstrip("/")
PROFESSIONAL_TOOLS_ENABLED = env_bool("PROFESSIONAL_TOOLS_ENABLED", True)
STAFF_DASHBOARD_ENABLED = env_bool("STAFF_DASHBOARD_ENABLED", False)
STAFF_DASHBOARD_TOKEN = os.getenv("STAFF_DASHBOARD_TOKEN", "").strip()
LIVE_SITE_REFRESH_SECONDS = env_int(
    "LIVE_SITE_REFRESH_SECONDS",
    15,
    minimum=5,
    maximum=300,
)
DOCTOR_MAX_ROWS = env_int(
    "DOCTOR_MAX_ROWS",
    100,
    minimum=10,
    maximum=1_000,
)

# Banlists et extensions.
BANLIST_SYNC_INTERVAL_SECONDS = env_int(
    "BANLIST_SYNC_INTERVAL_SECONDS",
    21_600,
    minimum=900,
    maximum=86_400,
)

# Accepte les deux noms de variable Railway. Aucune variable n'est obligatoire.
BOT_BUILD = (
    os.getenv("BOT_BUILD")
    or os.getenv("HAMTARO_BUILD")
    or "hamtaro-complete-expansion-2026-08-06"
).strip()
