from __future__ import annotations

import ast
import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def ok(message: str) -> None:
    print(f"[OK] {message}")


def warning(message: str) -> None:
    print(f"[ATTENTION] {message}")


def failure(message: str) -> None:
    print(f"[ERREUR] {message}")


def check_python_syntax() -> bool:
    valid = True
    ignored = {".git", ".venv", "venv", "__pycache__", "upgrade_backup"}
    for path in ROOT.rglob("*.py"):
        if any(part in ignored for part in path.parts):
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as error:
            failure(f"Syntaxe invalide dans {path.relative_to(ROOT)} : {error}")
            valid = False
    if valid:
        ok("Tous les fichiers Python sont syntaxiquement valides.")
    return valid


def check_environment() -> bool:
    valid = True
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if token:
        ok("DISCORD_TOKEN est défini.")
    else:
        warning("DISCORD_TOKEN n'est pas défini dans ce terminal.")

    guild_id = (
        os.getenv("GUILD_ID")
        or os.getenv("PUBLIC_GUILD_ID")
        or ""
    ).strip()
    if guild_id.isdigit():
        ok("GUILD_ID/PUBLIC_GUILD_ID est valide.")
    else:
        warning("GUILD_ID/PUBLIC_GUILD_ID est absent ou invalide.")

    volume = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    database_path = os.getenv("DATABASE_PATH", "").strip()
    if volume or database_path:
        ok("Un chemin persistant de base est configuré.")
    elif os.getenv("RAILWAY_ENVIRONMENT"):
        failure(
            "Railway est détecté, mais aucun volume ou DATABASE_PATH n'est visible."
        )
        valid = False
    else:
        warning("Mode local : la base sera créée dans le dépôt.")

    return valid


def check_repository_hygiene() -> bool:
    valid = True
    if (ROOT / ".env").exists():
        failure("Le fichier .env est encore présent à la racine du dépôt.")
        valid = False
    else:
        ok("Aucun fichier .env n'est présent dans le pack de production.")

    legacy = [
        name
        for name in ("bot(10).py", "install_hotfix.py", "install_update.py")
        if (ROOT / name).exists()
    ]
    if legacy:
        warning("Fichiers anciens encore présents : " + ", ".join(legacy))
    else:
        ok("Aucun ancien installateur ou bot dupliqué à la racine.")
    return valid


def check_database() -> bool:
    try:
        from config import DATABASE
    except Exception as error:
        failure(f"Impossible de charger config.py : {error}")
        return False

    database = Path(DATABASE)
    database.parent.mkdir(parents=True, exist_ok=True)
    if not os.access(database.parent, os.W_OK):
        failure(f"Le dossier {database.parent} n'est pas inscriptible.")
        return False

    if not database.exists():
        ok(f"La nouvelle base pourra être créée dans {database.parent}.")
        return True

    try:
        with sqlite3.connect(str(database), timeout=30) as connection:
            result = connection.execute("PRAGMA quick_check;").fetchone()
    except sqlite3.Error as error:
        failure(f"SQLite est inaccessible : {error}")
        return False

    if result and result[0] == "ok":
        ok("Le contrôle d'intégrité SQLite est valide.")
        return True

    failure(f"Contrôle SQLite invalide : {result}")
    return False



def check_professional_configuration() -> bool:
    valid = True
    enabled = os.getenv("STAFF_DASHBOARD_ENABLED", "true").strip().lower() not in {
        "0", "false", "no", "off", "disabled", ""
    }
    token = os.getenv("STAFF_DASHBOARD_TOKEN", "").strip()
    if enabled and len(token) < 24:
        message = (
            "STAFF_DASHBOARD_TOKEN doit contenir au moins 24 caractères "
            "lorsque le tableau staff est activé."
        )
        if os.getenv("RAILWAY_ENVIRONMENT"):
            failure(message)
            valid = False
        else:
            warning(message)
    elif enabled:
        ok("Le jeton du tableau de bord staff est suffisamment long.")
    else:
        ok("Le tableau de bord staff est volontairement désactivé.")

    required = (
        "cogs/professional_web.py",
        "cogs/professional_tools.py",
        "services/integrity_service.py",
        "services/self_test_service.py",
        "services/audit_service.py",
        "web/templates/staff_dashboard.html",
        ".github/workflows/quality.yml",
    )
    missing = [name for name in required if not (ROOT / name).exists()]
    if missing:
        failure("Fichiers professionnels manquants : " + ", ".join(missing))
        valid = False
    else:
        ok("Tous les modules professionnels sont présents.")
    return valid


def main() -> int:
    print("Préflight Hamtaro\n")
    checks = (
        check_python_syntax(),
        check_environment(),
        check_repository_hygiene(),
        check_professional_configuration(),
        check_database(),
    )
    print()
    if all(checks):
        print("Hamtaro est prêt pour le déploiement.")
        return 0

    print("Hamtaro nécessite encore une correction avant le déploiement.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
