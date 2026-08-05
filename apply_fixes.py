#!/usr/bin/env python3
"""Applique les correctifs issus de l'audit du dépôt Hamtaro.

Usage :
    python apply_fixes.py /chemin/vers/hamtaro

Le script est volontairement prudent :
- il vérifie les fichiers attendus ;
- il crée une sauvegarde avant toute modification ;
- il s'arrête si la version du dépôt ne correspond plus aux motifs audités ;
- il peut être relancé sans dupliquer les modifications.
"""

from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


class PatchError(RuntimeError):
    pass


PACKAGE_DIR = Path(__file__).resolve().parent
BUNDLED_FILES = PACKAGE_DIR / "files"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def replace_once(
    content: str,
    old: str,
    new: str,
    *,
    label: str,
) -> tuple[str, bool]:
    if new and new in content:
        return content, False
    count = content.count(old)
    if count != 1:
        raise PatchError(
            f"{label}: motif attendu une seule fois, trouvé {count} fois. "
            "Le dépôt a probablement changé depuis l'audit."
        )
    return content.replace(old, new, 1), True


def backup_file(path: Path, root: Path, backup_root: Path) -> None:
    if not path.exists():
        return
    relative = path.relative_to(root)
    destination = backup_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(path, destination)


def patch_file(
    path: Path,
    root: Path,
    backup_root: Path,
    transformer,
) -> list[str]:
    if not path.exists():
        raise PatchError(f"Fichier indispensable introuvable : {path.relative_to(root)}")

    original = read_text(path)
    modified, changes = transformer(original)
    if modified != original:
        backup_file(path, root, backup_root)
        write_text(path, modified)
    return changes


def patch_config(content: str) -> tuple[str, list[str]]:
    changes: list[str] = []

    env_float = '''\n\ndef env_float(\n    name: str,\n    default: float,\n    *,\n    minimum: float | None = None,\n    maximum: float | None = None,\n) -> float:\n    raw = os.getenv(name, "").strip()\n    try:\n        value = float(raw) if raw else default\n    except ValueError:\n        value = default\n\n    if minimum is not None:\n        value = max(minimum, value)\n    if maximum is not None:\n        value = min(maximum, value)\n    return value\n'''
    if "def env_float(" not in content:
        marker = "    return value\n\nBASE_DIR = Path(__file__).resolve().parent"
        replacement = "    return value" + env_float + "\nBASE_DIR = Path(__file__).resolve().parent"
        content, changed = replace_once(
            content,
            marker,
            replacement,
            label="config.py / ajout env_float",
        )
        if changed:
            changes.append("config.py : lecture sûre des variables décimales")

    content, changed = replace_once(
        content,
        'ENABLE_MESSAGE_CONTENT = env_bool("ENABLE_MESSAGE_CONTENT", False)',
        'ENABLE_MEMBERS_INTENT = env_bool("ENABLE_MEMBERS_INTENT", True)\n'
        'ENABLE_MESSAGE_CONTENT = env_bool("ENABLE_MESSAGE_CONTENT", False)',
        label="config.py / intent membres",
    )
    if changed:
        changes.append("config.py : intent membres configurable")

    old_watchdog = '''EVENT_LOOP_WATCHDOG_INTERVAL = max(\n    0.5,\n    float(os.getenv("EVENT_LOOP_WATCHDOG_INTERVAL", "1.0")),\n)\nEVENT_LOOP_WARNING_SECONDS = max(\n    1.0,\n    float(os.getenv("EVENT_LOOP_WARNING_SECONDS", "2.0")),\n)'''
    new_watchdog = '''EVENT_LOOP_WATCHDOG_INTERVAL = env_float(\n    "EVENT_LOOP_WATCHDOG_INTERVAL",\n    1.0,\n    minimum=0.5,\n    maximum=60.0,\n)\nEVENT_LOOP_WARNING_SECONDS = env_float(\n    "EVENT_LOOP_WARNING_SECONDS",\n    2.0,\n    minimum=1.0,\n    maximum=300.0,\n)'''
    content, changed = replace_once(
        content,
        old_watchdog,
        new_watchdog,
        label="config.py / watchdog",
    )
    if changed:
        changes.append("config.py : une valeur Railway invalide ne bloque plus le démarrage")

    content, changed = replace_once(
        content,
        'STAFF_DASHBOARD_ENABLED = env_bool("STAFF_DASHBOARD_ENABLED", True)',
        'STAFF_DASHBOARD_ENABLED = env_bool("STAFF_DASHBOARD_ENABLED", False)',
        label="config.py / tableau staff",
    )
    if changed:
        changes.append("config.py : ancien tableau staff désactivé par défaut")

    return content, changes


def patch_bot(content: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    content, changed = replace_once(
        content,
        "    ENABLE_MESSAGE_CONTENT,\n    ENABLE_WATCHDOG,",
        "    ENABLE_MEMBERS_INTENT,\n    ENABLE_MESSAGE_CONTENT,\n    ENABLE_WATCHDOG,",
        label="bot.py / import intent membres",
    )
    if changed:
        changes.append("bot.py : import de ENABLE_MEMBERS_INTENT")

    content, changed = replace_once(
        content,
        "        intents.members = True",
        "        intents.members = ENABLE_MEMBERS_INTENT",
        label="bot.py / intent membres",
    )
    if changed:
        changes.append("bot.py : l'intent privilégié Members respecte la configuration")
    return content, changes


def patch_database(content: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    content, changed = replace_once(
        content,
        "DB_VERSION = 9",
        "DB_VERSION = 10",
        label="database.py / version",
    )
    if changed:
        changes.append("database.py : version du schéma passée à 10")

    content, changed = replace_once(
        content,
        '    await ensure_column(db, "players", "tournaments_won", "INTEGER NOT NULL DEFAULT 0")',
        '    await ensure_column(db, "players", "tournaments_won", "INTEGER NOT NULL DEFAULT 0")\n'
        '    await ensure_column(db, "players", "updated_at", "TIMESTAMP")',
        label="database.py / migration updated_at",
    )
    if changed:
        changes.append("database.py : migration de players.updated_at")

    content, changed = replace_once(
        content,
        "            tournaments_won INTEGER NOT NULL DEFAULT 0,\n            PRIMARY KEY (",
        "            tournaments_won INTEGER NOT NULL DEFAULT 0,\n"
        "            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
        "            PRIMARY KEY (",
        label="database.py / schéma players",
    )
    if changed:
        changes.append("database.py : colonne updated_at ajoutée aux nouvelles bases")
    return content, changes


def patch_database_service(content: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    content, changed = replace_once(
        content,
        "from config import DATABASE",
        "from config import DATABASE, SQLITE_BUSY_TIMEOUT_MS",
        label="database_service.py / import timeout",
    )
    if changed:
        changes.append("database_service.py : import du délai SQLite")

    content, changed = replace_once(
        content,
        "        self.conn = await aiosqlite.connect(DATABASE)",
        "        self.conn = await aiosqlite.connect(\n"
        "            DATABASE,\n"
        "            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,\n"
        "        )",
        label="database_service.py / connexion",
    )
    if changed:
        changes.append("database_service.py : timeout appliqué à la connexion SQLite")

    content, changed = replace_once(
        content,
        '        await self.conn.execute("PRAGMA synchronous = NORMAL;")',
        '        await self.conn.execute("PRAGMA synchronous = NORMAL;")\n'
        '        await self.conn.execute(\n'
        '            f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};"\n'
        '        )\n'
        '        await self.conn.execute("PRAGMA temp_store = MEMORY;")',
        label="database_service.py / pragmas",
    )
    if changed:
        changes.append("database_service.py : busy_timeout SQLite réellement activé")

    content, changed = replace_once(
        content,
        "                username = excluded.username,\n"
        "                display_name = excluded.display_name,\n"
        "                avatar_url = excluded.avatar_url",
        "                username = excluded.username,\n"
        "                display_name = excluded.display_name,\n"
        "                avatar_url = excluded.avatar_url,\n"
        "                updated_at = CURRENT_TIMESTAMP",
        label="database_service.py / date de profil",
    )
    if changed:
        changes.append("database_service.py : date de mise à jour actualisée lors d'un upsert")

    content, changed = replace_once(
        content,
        "        if max_players not in (4, 8, 16, 32, 64):\n"
        "            raise ValueError(\n"
        '                "Le tournoi doit contenir 4, 8, 16, 32 ou 64 joueurs."\n'
        "            )",
        "        if max_players not in (4, 8, 16, 32, 64, 128):\n"
        "            raise ValueError(\n"
        '                "Le tournoi doit contenir 4, 8, 16, 32, 64 ou 128 joueurs."\n'
        "            )",
        label="database_service.py / capacité 128",
    )
    if changed:
        changes.append("database_service.py : création de tournois à 128 joueurs autorisée")

    return content, changes


def patch_professional_tools(content: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    if "staff_dashboard" not in content:
        return content, changes

    content, changed = replace_once(
        content,
        "import os\n",
        "",
        label="professional_tools.py / import os",
    )
    if changed:
        changes.append("professional_tools.py : import devenu inutile retiré")

    obsolete_command = '''    @app_commands.command(\n        name="staff_dashboard",\n        description="Afficher l'adresse du tableau de bord staff protégé",\n    )\n    @staff_only()\n    async def staff_dashboard(self, interaction: discord.Interaction) -> None:\n        base_url = os.getenv("WEBSITE_BASE_URL", "").strip().rstrip("/")\n        if not base_url.startswith(("http://", "https://")):\n            await interaction.response.send_message(\n                "❌ WEBSITE_BASE_URL n'est pas correctement configurée.",\n                ephemeral=True,\n            )\n            return\n        embed = discord.Embed(\n            title="🛡️ Tableau de bord staff Hamtaro",\n            description=(\n                "Le tableau de bord est protégé par le jeton Railway "\n                "`STAFF_DASHBOARD_TOKEN`. Ne partage jamais ce jeton dans un salon."\n            ),\n            url=f"{base_url}/staff",\n            colour=discord.Colour.dark_gold(),\n        )\n        view = discord.ui.View(timeout=120)\n        view.add_item(\n            discord.ui.Button(\n                label="Ouvrir le tableau de bord",\n                emoji="🛡️",\n                style=discord.ButtonStyle.link,\n                url=f"{base_url}/staff",\n            )\n        )\n        await interaction.response.send_message(\n            embed=embed,\n            view=view,\n            ephemeral=True,\n        )\n\n'''
    content, changed = replace_once(
        content,
        obsolete_command,
        "",
        label="professional_tools.py / commande staff_dashboard",
    )
    if changed:
        changes.append("professional_tools.py : commande /staff_dashboard supprimée")
    return content, changes


def patch_readme(content: str) -> tuple[str, list[str]]:
    changes: list[str] = []

    replacements = [
        (
            "- tableau de bord staff protégé sur `/staff` ;\n",
            "",
            "README.md : ancienne page /staff retirée des fonctions",
        ),
        (
            "python /chemin/vers/hamtaro_professional_suite/apply_hamtaro_upgrade.py\n"
            "python -m compileall .\n"
            "pip install -r requirements.txt\n"
            "python scripts/preflight.py\n"
            "python -m pytest -q",
            "pip install -r requirements.txt\n"
            "pip install -r requirements-dev.txt\n"
            "python -m compileall -q .\n"
            "python scripts/preflight.py\n"
            "python -m pytest -q",
            "README.md : procédure d'installation rendue autonome",
        ),
        (
            "STAFF_DASHBOARD_ENABLED=true\n"
            "STAFF_DASHBOARD_TOKEN=une-valeur-aleatoire-tres-longue\n",
            "",
            "README.md : variables de l'ancienne page staff retirées",
        ),
        (
            "### `/staff_dashboard`\n\n"
            "Donne au staff le lien vers `/staff`. Le tableau de bord est protégé par un jeton Railway, une session `HttpOnly`, un contrôle des tentatives et des en-têtes de sécurité. Les validations sensibles restent volontairement dans Discord afin de conserver l'identité du modérateur et les confirmations existantes.\n",
            "",
            "README.md : documentation de /staff_dashboard retirée",
        ),
        (
            "5. Vérifie `/staff`, `/tournaments` et `/health`.",
            "5. Vérifie `/tournaments` et `/health`.",
            "README.md : vérification de la route inexistante retirée",
        ),
    ]

    for old, new, label in replacements:
        if not new and old not in content:
            continue
        content, changed = replace_once(content, old, new, label=label)
        if changed:
            changes.append(label)
    return content, changes


def install_bundled_file(
    relative: Path,
    root: Path,
    backup_root: Path,
) -> str | None:
    source = BUNDLED_FILES / relative
    destination = root / relative
    if not source.exists():
        raise PatchError(f"Fichier embarqué introuvable : {relative}")

    source_content = source.read_bytes()
    if destination.exists() and destination.read_bytes() == source_content:
        return None

    backup_file(destination, root, backup_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return f"{relative.as_posix()} : fichier installé ou actualisé"


def remove_obsolete(path: Path, root: Path, backup_root: Path) -> str | None:
    if not path.exists():
        return None
    backup_file(path, root, backup_root)
    path.unlink()
    return f"{path.relative_to(root).as_posix()} : ancien fichier staff retiré"


def verify_python_syntax(root: Path) -> None:
    checked = [
        root / "bot.py",
        root / "config.py",
        root / "database.py",
        root / "services" / "database_service.py",
        root / "cogs" / "professional_tools.py",
    ]
    for path in checked:
        try:
            ast.parse(read_text(path), filename=str(path))
        except SyntaxError as error:
            raise PatchError(f"Erreur de syntaxe après modification dans {path}: {error}") from error


def git_untrack_generated_files(root: Path) -> list[str]:
    """Retire de l'index les secrets/fichiers générés sans effacer le disque."""
    if not (root / ".git").exists() or shutil.which("git") is None:
        return [
            "Git non disponible : exécute manuellement `git rm --cached .env` "
            "si .env est encore suivi."
        ]

    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        return ["Impossible de lire l'index Git pour retirer les fichiers générés."]

    tracked = [
        item.decode("utf-8", errors="surrogateescape")
        for item in listed.stdout.split(b"\0")
        if item
    ]

    def should_untrack(name: str) -> bool:
        path = Path(name)
        parts = set(path.parts)
        suffix = path.suffix.lower()
        return (
            name in {".env", "gitignore"}
            or "__pycache__" in parts
            or suffix in {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3"}
            or name.endswith((".db-shm", ".db-wal"))
        )

    generated = [name for name in tracked if should_untrack(name)]
    messages: list[str] = []
    for index in range(0, len(generated), 100):
        batch = generated[index : index + 100]
        result = subprocess.run(
            ["git", "rm", "--cached", "--ignore-unmatch", "--", *batch],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            messages.append(
                "Certains fichiers générés n'ont pas pu être retirés de l'index : "
                + result.stderr.strip()
            )
    if generated and not messages:
        messages.append(
            f"{len(generated)} fichier(s) secret(s) ou généré(s) retiré(s) de l'index Git "
            "sans suppression locale."
        )
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Appliquer les correctifs Hamtaro")
    parser.add_argument(
        "repository",
        nargs="?",
        default=".",
        help="Chemin vers la racine du dépôt Hamtaro (défaut : dossier courant)",
    )
    args = parser.parse_args()

    root = Path(args.repository).expanduser().resolve()
    required = [
        root / "bot.py",
        root / "config.py",
        root / "database.py",
        root / "services" / "database_service.py",
        root / "cogs" / "professional_tools.py",
        root / "README.md",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        print("Ce dossier ne ressemble pas au dépôt Hamtaro :", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        return 2

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = root / f"audit_backup_{timestamp}"
    all_changes: list[str] = []

    try:
        all_changes.extend(
            patch_file(root / "config.py", root, backup_root, patch_config)
        )
        all_changes.extend(patch_file(root / "bot.py", root, backup_root, patch_bot))
        all_changes.extend(
            patch_file(root / "database.py", root, backup_root, patch_database)
        )
        all_changes.extend(
            patch_file(
                root / "services" / "database_service.py",
                root,
                backup_root,
                patch_database_service,
            )
        )
        all_changes.extend(
            patch_file(
                root / "cogs" / "professional_tools.py",
                root,
                backup_root,
                patch_professional_tools,
            )
        )
        all_changes.extend(
            patch_file(root / "README.md", root, backup_root, patch_readme)
        )

        for relative in (
            Path(".gitignore"),
            Path(".env.example"),
            Path("requirements-dev.txt"),
            Path(".github/workflows/tests.yml"),
            Path("tests/test_professional_suite.py"),
            Path("tests/test_upgrade_static.py"),
        ):
            message = install_bundled_file(relative, root, backup_root)
            if message:
                all_changes.append(message)

        obsolete_paths = [
            root / "gitignore",
            root / "apply_hamtaro_upgrade.py",
            root / "apply_integrated_staff_dashboard.py",
            root / "install_staff_dashboard_fix.py",
            root / "installer_staff_hamtaro.py",
            root / "cogs" / "professional_web.py",
            root / "services" / "staff_dashboard_routes.py",
            root / "services" / "staff_dashboard_service.py",
            root / "web" / "templates" / "staff_dashboard.html",
            root / "web" / "templates" / "staff_login.html",
            root / "web" / "static" / "staff_dashboard.js",
        ]
        for path in obsolete_paths:
            message = remove_obsolete(path, root, backup_root)
            if message:
                all_changes.append(message)

        verify_python_syntax(root)
        git_messages = git_untrack_generated_files(root)
    except PatchError as error:
        print(f"ERREUR : {error}", file=sys.stderr)
        if backup_root.exists():
            print(f"Sauvegardes disponibles dans : {backup_root}", file=sys.stderr)
        return 1

    print("\nCorrectifs Hamtaro appliqués avec succès.\n")
    if all_changes:
        for change in all_changes:
            print(f"  ✓ {change}")
    else:
        print("  Aucun changement : les correctifs semblent déjà présents.")

    for message in git_messages:
        print(f"  ! {message}")

    if backup_root.exists() and any(backup_root.rglob("*")):
        print(f"\nSauvegardes : {backup_root}")
    print("\nVérifications conseillées :")
    print("  python -m compileall -q .")
    print("  python scripts/preflight.py")
    print("  python -m pytest -q")
    print("  git status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
