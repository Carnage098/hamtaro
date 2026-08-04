from __future__ import annotations

import shutil
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path.cwd().resolve()

REPLACEMENTS = (
    "bot.py",
    "config.py",
    "database.py",
    "requirements.txt",
    "railway.json",
    "Procfile",
    ".gitignore",
    ".env.example",
    "README.md",
    "UPGRADE.md",
    "AUDIT_REPORT.md",
    "services/database_maintenance.py",
    "utils/runtime_lock.py",
    "cogs/system_health.py",
    "web/static/app.js",
    "web/templates/index.html",
    "scripts/preflight.py",
    "tests/test_upgrade_static.py",
)


class UpgradeError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise UpgradeError(f"Motif introuvable pour {label}.")
    return text.replace(old, new, 1)


def patch_database_service(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    text = text.replace(
        "from config import DATABASE",
        "from config import DATABASE, SQLITE_BUSY_TIMEOUT_MS",
    )
    text = text.replace(
        "self.conn = await aiosqlite.connect(DATABASE)",
        "self.conn = await aiosqlite.connect(\n"
        "            str(DATABASE),\n"
        "            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,\n"
        "        )",
    )
    busy_timeout = (
        "        await self.conn.execute(\n"
        "            f\"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};\"\n"
        "        )\n"
        "        await self.conn.execute(\"PRAGMA temp_store = MEMORY;\")\n"
    )
    synchronous = '        await self.conn.execute("PRAGMA synchronous = NORMAL;")\n'
    if busy_timeout not in text and synchronous in text:
        text = text.replace(synchronous, synchronous + busy_timeout, 1)

    text = text.replace(
        "if max_players not in (4, 8, 16, 32, 64):",
        "if max_players not in (4, 8, 16, 32, 64, 128):",
    )
    text = text.replace(
        "Le tournoi doit contenir 4, 8, 16, 32 ou 64 joueurs.",
        "Le tournoi doit contenir 4, 8, 16, 32, 64 ou 128 joueurs.",
    )

    # Correction importante : un tournoi démarre à la ronde 1 et non à la
    # dernière ronde. Le second paramètre doit rester total_rounds.
    text = text.replace(
        """            (
                TournamentStatus.RUNNING.value,
                total_rounds,
                total_rounds,
                tournament_id,
            ),""",
        """            (
                TournamentStatus.RUNNING.value,
                1,
                total_rounds,
                tournament_id,
            ),""",
    )

    if text == original:
        return False

    path.write_text(text, encoding="utf-8")
    return True


def patch_capacity_references(root: Path) -> list[Path]:
    changed: list[Path] = []
    ignored = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "legacy",
    }

    replacements = {
        "(4, 8, 16, 32, 64)": "(4, 8, 16, 32, 64, 128)",
        "[4, 8, 16, 32, 64]": "[4, 8, 16, 32, 64, 128]",
        "{4, 8, 16, 32, 64}": "{4, 8, 16, 32, 64, 128}",
        "4, 8, 16, 32 ou 64": "4, 8, 16, 32, 64 ou 128",
    }

    for path in root.rglob("*.py"):
        if any(part in ignored for part in path.parts):
            continue
        if path.resolve() == Path(__file__).resolve():
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        new_text = text
        for old, new in replacements.items():
            new_text = new_text.replace(old, new)

        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed.append(path)

    return changed


def quarantine_legacy_files(root: Path) -> list[Path]:
    legacy_dir = root / "legacy"
    moved: list[Path] = []
    candidates = (
        root / "bot(10).py",
        root / "install_hotfix.py",
        root / "install_update.py",
    )

    for source in candidates:
        if not source.exists():
            continue
        legacy_dir.mkdir(parents=True, exist_ok=True)
        destination = legacy_dir / source.name
        if destination.exists():
            destination = legacy_dir / f"old_{source.name}"
        shutil.move(str(source), str(destination))
        moved.append(destination)

    return moved


def handle_env_file(root: Path) -> Path | None:
    source = root / ".env"
    if not source.exists():
        return None

    destination = root / ".env.local"
    if destination.exists():
        destination = root / ".env.local.backup"
    shutil.move(str(source), str(destination))
    return destination


def copy_replacements(root: Path) -> list[Path]:
    copied: list[Path] = []
    for relative in REPLACEMENTS:
        source = PACKAGE_ROOT / relative
        if not source.exists():
            raise UpgradeError(f"Fichier absent du pack : {relative}")
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination)
    return copied


def main() -> int:
    if not (PROJECT_ROOT / "services" / "database_service.py").exists():
        print(
            "ERREUR : exécute ce script depuis la racine du dépôt Hamtaro.",
            file=sys.stderr,
        )
        return 2

    backup_root = PROJECT_ROOT / "upgrade_backup"
    backup_root.mkdir(exist_ok=True)

    for relative in REPLACEMENTS:
        current = PROJECT_ROOT / relative
        if current.exists():
            destination = backup_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current, destination)

    database_service = PROJECT_ROOT / "services" / "database_service.py"
    database_service_backup = backup_root / "services" / "database_service.py"
    database_service_backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(database_service, database_service_backup)

    env_moved = handle_env_file(PROJECT_ROOT)
    legacy_moved = quarantine_legacy_files(PROJECT_ROOT)
    copied = copy_replacements(PROJECT_ROOT)
    patched_service = patch_database_service(database_service)
    capacity_files = patch_capacity_references(PROJECT_ROOT)

    print("\nMise à niveau Hamtaro terminée.")
    print(f"- Fichiers remplacés/ajoutés : {len(copied)}")
    print(f"- database_service.py corrigé : {'oui' if patched_service else 'déjà corrigé'}")
    print(f"- Références capacité 128 corrigées : {len(capacity_files)} fichier(s)")
    print(f"- Anciens fichiers déplacés : {len(legacy_moved)}")
    if env_moved:
        print(f"- .env déplacé vers : {env_moved.name}")
        print("  Retire aussi .env de l'historique Git et régénère les secrets exposés.")
    print(f"- Sauvegarde des anciens fichiers : {backup_root}")
    print("\nÉtapes suivantes :")
    print("1. python -m compileall .")
    print("2. pip install -r requirements.txt")
    print("3. git add . && git commit -m \"Production hardening Hamtaro\"")
    print("4. git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
