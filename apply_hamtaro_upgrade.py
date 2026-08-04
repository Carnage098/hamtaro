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
    "CHANGELOG_PROFESSIONAL.md",
    "services/database_maintenance.py",
    "services/audit_service.py",
    "services/audit_compatibility.py",
    "services/integrity_service.py",
    "services/result_safety_service.py",
    "services/self_test_service.py",
    "services/staff_dashboard_service.py",
    "utils/runtime_lock.py",
    "cogs/system_health.py",
    "cogs/professional_web.py",
    "cogs/professional_tools.py",
    "web/static/app.js",
    "web/static/professional.css",
    "web/templates/index.html",
    "web/templates/staff_login.html",
    "web/templates/staff_dashboard.html",
    "scripts/preflight.py",
    "tests/test_upgrade_static.py",
    "tests/test_professional_suite.py",
    ".github/workflows/quality.yml",
)

PATCH_TARGETS = (
    "services/database_service.py",
    "cogs/hamtaro_hub.py",
    "web/templates/base.html",
)


class UpgradeError(RuntimeError):
    pass


def _backup_file(root: Path, backup_root: Path, relative: str) -> None:
    source = root / relative
    if not source.exists():
        return
    destination = backup_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def patch_database_service(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    if "SQLITE_BUSY_TIMEOUT_MS" not in text:
        text = text.replace(
            "from config import DATABASE",
            "from config import DATABASE, SQLITE_BUSY_TIMEOUT_MS",
            1,
        )
    text = text.replace(
        "self.conn = await aiosqlite.connect(DATABASE)",
        "self.conn = await aiosqlite.connect(\n"
        "            str(DATABASE),\n"
        "            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,\n"
        "        )",
    )
    synchronous = '        await self.conn.execute("PRAGMA synchronous = NORMAL;")\n'
    busy_block = (
        "        await self.conn.execute(\n"
        "            f\"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};\"\n"
        "        )\n"
        "        await self.conn.execute(\"PRAGMA temp_store = MEMORY;\")\n"
    )
    if synchronous in text and busy_block not in text:
        text = text.replace(synchronous, synchronous + busy_block, 1)

    replacements = {
        "if max_players not in (4, 8, 16, 32, 64):":
            "if max_players not in (4, 8, 16, 32, 64, 128):",
        "Le tournoi doit contenir 4, 8, 16, 32 ou 64 joueurs.":
            "Le tournoi doit contenir 4, 8, 16, 32, 64 ou 128 joueurs.",
        """            (
                TournamentStatus.RUNNING.value,
                total_rounds,
                total_rounds,
                tournament_id,
            ),""":
        """            (
                TournamentStatus.RUNNING.value,
                1,
                total_rounds,
                tournament_id,
            ),""",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    if text == original:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def patch_hamtaro_hub(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    if "async def configure_for_user(" not in text:
        anchor = """    @discord.ui.button(
        label=\"S'inscrire\","""
        method = '''    async def configure_for_user(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Active seulement les actions réellement disponibles pour le joueur."""

        defaults = {
            "register_button": "S'inscrire",
            "next_match_button": "Prochain match",
            "result_button": "Signaler résultat",
            "bracket_button": "Bracket",
            "ranking_button": "Classement",
        }
        for attribute, label in defaults.items():
            button = getattr(self, attribute, None)
            if button is not None:
                button.label = label
                button.disabled = True

        try:
            tournament = await self.cog.current_tournament(interaction)
        except ValueError:
            return

        status = self.cog.status_value(tournament)
        tournament_id = int(tournament.id)
        player_id = str(interaction.user.id)
        registration = await self.cog.db.fetchone(
            """
            SELECT dropped, disqualified
            FROM registrations
            WHERE tournament_id = ? AND discord_id = ?
            """,
            (tournament_id, player_id),
        )
        registered = registration is not None
        eligible = registered and not bool(registration[0]) and not bool(registration[1])
        match_data = None
        if eligible:
            match_data = await self.cog._find_player_match(
                tournament_id=tournament_id,
                player_id=player_id,
            )

        open_statuses = {"registration", "registrations", "open", "waiting"}
        active_statuses = {
            "active", "started", "running", "in_progress", "playing", "swiss"
        }
        finished_statuses = {"finished", "completed", "ended", "archived", "cancelled"}

        self.bracket_button.disabled = status not in (open_statuses | active_statuses | finished_statuses)
        self.ranking_button.disabled = status not in (active_statuses | finished_statuses)

        if status in open_statuses:
            self.register_button.disabled = registered
            if registered:
                self.register_button.label = "Déjà inscrit"
            return

        if status in active_statuses:
            self.register_button.disabled = True
            self.register_button.label = "Inscriptions fermées"
            self.next_match_button.disabled = match_data is None
            self.result_button.disabled = match_data is None
            if not eligible:
                self.next_match_button.label = "Non inscrit"
                self.result_button.label = "Non inscrit"
            elif match_data is None:
                self.next_match_button.label = "Aucun match"
                self.result_button.label = "Aucun résultat à envoyer"
            return

        self.register_button.disabled = True
        self.register_button.label = "Tournoi terminé"

'''
        if anchor not in text:
            raise UpgradeError("Impossible d'ajouter le menu /hamtaro intelligent : ancre absente.")
        text = text.replace(anchor, method + anchor, 1)

    old_refresh = """        await interaction.response.defer()
        embed = await self.cog.build_home_embed(interaction)
        await interaction.edit_original_response(embed=embed, view=self)"""
    new_refresh = """        await interaction.response.defer()
        await self.configure_for_user(interaction)
        embed = await self.cog.build_home_embed(interaction)
        await interaction.edit_original_response(embed=embed, view=self)"""
    if old_refresh in text:
        text = text.replace(old_refresh, new_refresh, 1)

    old_view = """        view = HamtaroHubView(
            cog=self,
            requester_id=interaction.user.id,
        )

        message = await interaction.followup.send("""
    new_view = """        view = HamtaroHubView(
            cog=self,
            requester_id=interaction.user.id,
        )
        await view.configure_for_user(interaction)

        message = await interaction.followup.send("""
    if old_view in text:
        text = text.replace(old_view, new_view, 1)

    if text == original:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def patch_base_template(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text
    line = '    <link rel="stylesheet" href="/static/professional.css">\n'
    if line not in text:
        anchor = '    <link rel="stylesheet" href="/static/style.css">\n'
        if anchor not in text:
            raise UpgradeError("Impossible d'ajouter professional.css à base.html.")
        text = text.replace(anchor, anchor + line, 1)
    if text == original:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def patch_capacity_references(root: Path) -> list[Path]:
    changed: list[Path] = []
    ignored = {".git", ".venv", "venv", "__pycache__", "legacy", "upgrade_backup"}
    replacements = {
        "(4, 8, 16, 32, 64)": "(4, 8, 16, 32, 64, 128)",
        "[4, 8, 16, 32, 64]": "[4, 8, 16, 32, 64, 128]",
        "{4, 8, 16, 32, 64}": "{4, 8, 16, 32, 64, 128}",
        "4, 8, 16, 32 ou 64": "4, 8, 16, 32, 64 ou 128",
    }
    for path in root.rglob("*.py"):
        if any(part in ignored for part in path.parts):
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
    for name in ("bot(10).py", "install_hotfix.py", "install_update.py"):
        source = root / name
        if not source.exists():
            continue
        legacy_dir.mkdir(parents=True, exist_ok=True)
        destination = legacy_dir / name
        counter = 1
        while destination.exists():
            destination = legacy_dir / f"{source.stem}_{counter}{source.suffix}"
            counter += 1
        shutil.move(str(source), str(destination))
        moved.append(destination)
    return moved


def handle_env_file(root: Path) -> Path | None:
    source = root / ".env"
    if not source.exists():
        return None
    destination = root / ".env.local"
    counter = 1
    while destination.exists():
        destination = root / f".env.local.{counter}"
        counter += 1
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
        print("ERREUR : exécute ce script depuis la racine du dépôt Hamtaro.", file=sys.stderr)
        return 2

    backup_root = PROJECT_ROOT / "upgrade_backup"
    backup_root.mkdir(exist_ok=True)
    for relative in (*REPLACEMENTS, *PATCH_TARGETS):
        _backup_file(PROJECT_ROOT, backup_root, relative)

    try:
        env_moved = handle_env_file(PROJECT_ROOT)
        legacy_moved = quarantine_legacy_files(PROJECT_ROOT)
        copied = copy_replacements(PROJECT_ROOT)
        patched_service = patch_database_service(PROJECT_ROOT / "services/database_service.py")
        patched_hub = patch_hamtaro_hub(PROJECT_ROOT / "cogs/hamtaro_hub.py")
        patched_base = patch_base_template(PROJECT_ROOT / "web/templates/base.html")
        capacity_files = patch_capacity_references(PROJECT_ROOT)
    except (OSError, UpgradeError) as error:
        print(f"ERREUR : {error}", file=sys.stderr)
        print(f"Les fichiers d'origine sont dans {backup_root}", file=sys.stderr)
        return 1

    print("\nMise à niveau professionnelle Hamtaro terminée.")
    print(f"- Fichiers remplacés/ajoutés : {len(copied)}")
    print(f"- Base et capacité 128 : {'corrigées' if patched_service else 'déjà corrigées'}")
    print(f"- Menu /hamtaro intelligent : {'ajouté' if patched_hub else 'déjà présent'}")
    print(f"- Styles du tableau staff : {'ajoutés' if patched_base else 'déjà présents'}")
    print(f"- Autres références de capacité corrigées : {len(capacity_files)}")
    print(f"- Anciens fichiers mis en quarantaine : {len(legacy_moved)}")
    if env_moved:
        print(f"- .env local déplacé vers {env_moved.name}")
        print("  Exécute aussi : git rm --cached .env")
    print(f"- Sauvegarde des anciens fichiers : {backup_root}")
    print("\nVérification recommandée :")
    print("1. python -m compileall .")
    print("2. pip install -r requirements.txt")
    print("3. python scripts/preflight.py")
    print("4. python -m pytest -q")
    print("5. git add . && git commit -m \"Hamtaro professional suite\" && git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
