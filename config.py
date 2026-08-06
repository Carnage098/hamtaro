from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

BASE_DIR = Path(__file__).resolve().parent

# Priorité :
# 1. DATABASE_PATH si tu veux imposer un chemin précis ;
# 2. le volume Railway monté sur le service ;
# 3. le fichier local du projet pour le développement sur ordinateur.
_database_path = os.getenv("DATABASE_PATH", "").strip()
_volume_mount_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()

if _database_path:
    DATABASE = Path(_database_path).expanduser()
elif _volume_mount_path:
    DATABASE = Path(_volume_mount_path) / "database.db"
else:
    DATABASE = BASE_DIR / "database.db"

DATABASE = DATABASE.resolve()
DATABASE.parent.mkdir(parents=True, exist_ok=True)

# Salon textuel parent utilisé pour publier les recherches casual
# et créer les fils privés des matchs.
CASUAL_MATCH_CHANNEL_ID = os.getenv(
    "CASUAL_MATCH_CHANNEL_ID",
    "",
).strip()

