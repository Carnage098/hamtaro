from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOT = ROOT / "bot.py"
CONFIG = ROOT / "config.py"
SERVICES = ROOT / "services"
PACK = ROOT / "hamtaro_command_refactor_files"
PACK_SERVICES = PACK / "services"
SYNC_FRAGMENT = PACK / "sync_method_fragment.txt"

def fail(message: str) -> None:
    raise SystemExit(f"❌ {message}")

def backup(path: Path) -> None:
    target = path.with_suffix(path.suffix + ".before-command-refactor.bak")
    if not target.exists():
        shutil.copy2(path, target)

def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        fail(f"Patch introuvable : {label}. Le dépôt a probablement évolué.")
    return text.replace(old, new, 1)

def main() -> None:
    if not BOT.exists() or not CONFIG.exists() or not SERVICES.exists():
        fail("Place ce script à la racine du dépôt Hamtaro.")
    if not PACK_SERVICES.exists() or not SYNC_FRAGMENT.exists():
        fail("Le dossier hamtaro_command_refactor_files est incomplet.")

    bot_original = BOT.read_text(encoding="utf-8")
    config_original = CONFIG.read_text(encoding="utf-8")
    bot = bot_original
    config = config_original

    bot = replace_once(
        bot,
        "from services.database_service import DatabaseService\n",
        "from services.database_service import DatabaseService\n"
        "from services.command_compactor import compact_command_tree, log_command_tree_summary\n"
        "from services.command_sync_guard import CommandSyncState, command_tree_fingerprint\n",
        "imports services",
    )

    bot = replace_once(
        bot,
        "    DATABASE_BACKUPS_ENABLED,\n",
        "    DATABASE_BACKUPS_ENABLED,\n    DATABASE,\n",
        "import DATABASE",
    )

    bot = replace_once(
        bot,
        "    FAIL_ON_COG_ERROR,\n    GUILD_ID,\n",
        "    FAIL_ON_COG_ERROR,\n    FORCE_COMMAND_SYNC,\n    GUILD_ID,\n",
        "import FORCE_COMMAND_SYNC",
    )

    bot = replace_once(
        bot,
        "        await self._load_extensions()\n        await self._sync_application_commands()\n",
        "        await self._load_extensions()\n"
        "        self._drop_retired_application_commands()\n"
        "        compact_command_tree(self.tree, logger=LOGGER)\n"
        "        log_command_tree_summary(self.tree, logger=LOGGER)\n"
        "        await self._sync_application_commands()\n",
        "setup_hook",
    )

    start_marker = "    async def _sync_application_commands(self) -> None:\n"
    end_marker = "    async def _database_backup_loop(self) -> None:\n"
    start = bot.find(start_marker)
    end = bot.find(end_marker)
    if start < 0 or end < 0 or end <= start:
        fail("Impossible de localiser la méthode de synchronisation dans bot.py.")

    fragment = SYNC_FRAGMENT.read_text(encoding="utf-8")
    bot = bot[:start] + fragment + bot[end:]

    config = replace_once(
        config,
        'SYNC_GUILD_COMMANDS = env_bool("SYNC_GUILD_COMMANDS", True)\n',
        'SYNC_GUILD_COMMANDS = env_bool("SYNC_GUILD_COMMANDS", True)\n'
        'FORCE_COMMAND_SYNC = env_bool("FORCE_COMMAND_SYNC", False)\n',
        "FORCE_COMMAND_SYNC",
    )

    # Validation syntaxique du résultat AVANT toute écriture dans le dépôt.
    try:
        ast.parse(bot, filename="bot.py")
        ast.parse(config, filename="config.py")
    except SyntaxError as error:
        fail(f"Le patch généré est invalide : {error}")

    # Rien n'est écrit avant que tous les patchs aient été validés.
    backup(BOT)
    backup(CONFIG)

    for src in PACK_SERVICES.glob("*.py"):
        shutil.copy2(src, SERVICES / src.name)

    BOT.write_text(bot, encoding="utf-8")
    CONFIG.write_text(config, encoding="utf-8")

    print("✅ Refactor commandes installé.")
    print("✅ Sauvegardes .before-command-refactor.bak créées.")
    print("✅ Compaction automatique activée.")
    print("✅ Sync par empreinte activée.")
    print()
    print("Puis lance :")
    print("python -m compileall bot.py config.py services")
    print("git add .")
    print('git commit -m "refactor: compact slash command tree"')
    print("git push origin main")

if __name__ == "__main__":
    main()
