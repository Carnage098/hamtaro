from __future__ import annotations

import py_compile
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BOT = ROOT / "bot.py"
CONFIG = ROOT / "config.py"
SERVICE = ROOT / "services" / "command_sync_once.py"

SERVICE_CODE = '\nfrom __future__ import annotations\n\nimport hashlib\nimport json\nimport logging\nimport time\nfrom typing import Any\n\nimport aiohttp\nfrom discord import app_commands\n\nfrom config import DATABASE\n\n\nLOGGER = logging.getLogger("hamtaro.command_sync_once")\nSTATE_FILE = DATABASE.parent / "command_sync_once_state.json"\nAPI_BASE = "https://discord.com/api/v10"\n\n\ndef _load_state() -> dict[str, Any]:\n    try:\n        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))\n        return data if isinstance(data, dict) else {}\n    except FileNotFoundError:\n        return {}\n    except Exception:\n        LOGGER.exception("Impossible de lire l\'état one-shot des commandes.")\n        return {}\n\n\ndef _save_state(data: dict[str, Any]) -> None:\n    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)\n    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")\n    tmp.write_text(\n        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),\n        encoding="utf-8",\n    )\n    tmp.replace(STATE_FILE)\n\n\ndef _payload(tree: app_commands.CommandTree) -> list[dict[str, Any]]:\n    commands = list(tree.get_commands())\n    commands.sort(key=lambda command: (int(command.type.value), command.name))\n    return [command.to_dict(tree) for command in commands]\n\n\ndef _fingerprint(payload: list[dict[str, Any]]) -> str:\n    raw = json.dumps(\n        payload,\n        sort_keys=True,\n        separators=(",", ":"),\n        ensure_ascii=False,\n    ).encode("utf-8")\n    return hashlib.sha256(raw).hexdigest()\n\n\nasync def publish_application_commands_once(\n    tree: app_commands.CommandTree,\n    *,\n    application_id: int,\n    token: str,\n    guild_id: int | None = None,\n    force: bool = False,\n) -> dict[str, Any]:\n    """Publie l\'arbre avec UNE requête HTTP maximum, sans retry automatique."""\n\n    payload = _payload(tree)\n    fingerprint = _fingerprint(payload)\n\n    scope = f"guild:{guild_id}" if guild_id else "global"\n    state = _load_state()\n    entry = state.get(scope)\n    if not isinstance(entry, dict):\n        entry = {}\n\n    now = time.time()\n    next_allowed_at = float(entry.get("next_allowed_at") or 0.0)\n\n    # FORCE ne contourne JAMAIS un cooldown 429.\n    if next_allowed_at > now:\n        remaining = max(0.0, next_allowed_at - now)\n        LOGGER.warning(\n            "Sync Discord one-shot BLOQUÉE : scope=%s, "\n            "nouvelle tentative autorisée dans %.1fs. "\n            "Aucune requête envoyée.",\n            scope,\n            remaining,\n        )\n        return {\n            "status": "cooldown",\n            "scope": scope,\n            "retry_after": remaining,\n            "fingerprint": fingerprint,\n        }\n\n    if (\n        not force\n        and entry.get("status") == "synced"\n        and entry.get("fingerprint") == fingerprint\n    ):\n        LOGGER.info(\n            "Arbre Discord inchangé et déjà publié : %s. "\n            "Aucune requête envoyée.",\n            scope,\n        )\n        return {\n            "status": "unchanged",\n            "scope": scope,\n            "fingerprint": fingerprint,\n        }\n\n    if guild_id:\n        url = (\n            f"{API_BASE}/applications/{application_id}"\n            f"/guilds/{guild_id}/commands"\n        )\n    else:\n        url = f"{API_BASE}/applications/{application_id}/commands"\n\n    headers = {\n        "Authorization": f"Bot {token}",\n        "Content-Type": "application/json",\n        "User-Agent": "DiscordBot (Hamtaro, command-sync-one-shot)",\n    }\n\n    LOGGER.info(\n        "Sync Discord ONE-SHOT : %s commande(s) racine(s) -> %s "\n        "(empreinte=%s).",\n        len(payload),\n        scope,\n        fingerprint[:12],\n    )\n\n    timeout = aiohttp.ClientTimeout(total=30)\n\n    try:\n        async with aiohttp.ClientSession(timeout=timeout) as session:\n            async with session.put(\n                url,\n                headers=headers,\n                json=payload,\n            ) as response:\n                raw_text = await response.text()\n\n                try:\n                    body = json.loads(raw_text) if raw_text else {}\n                except json.JSONDecodeError:\n                    body = {}\n\n                if response.status == 429:\n                    retry_after = 0.0\n\n                    try:\n                        retry_after = float(body.get("retry_after") or 0.0)\n                    except (TypeError, ValueError):\n                        retry_after = 0.0\n\n                    if retry_after <= 0:\n                        try:\n                            retry_after = float(\n                                response.headers.get("Retry-After") or 0.0\n                            )\n                        except (TypeError, ValueError):\n                            retry_after = 0.0\n\n                    retry_after = max(60.0, retry_after)\n                    blocked_until = time.time() + retry_after + 15.0\n\n                    state[scope] = {\n                        "status": "rate_limited",\n                        "fingerprint": fingerprint,\n                        "last_status": 429,\n                        "retry_after": retry_after,\n                        "next_allowed_at": blocked_until,\n                        "updated_at": time.time(),\n                    }\n                    _save_state(state)\n\n                    LOGGER.error(\n                        "Discord 429 : STOP. Aucun retry automatique. "\n                        "Cooldown enregistré pour %.1fs (+15s de marge).",\n                        retry_after,\n                    )\n                    return {\n                        "status": "rate_limited",\n                        "scope": scope,\n                        "retry_after": retry_after,\n                        "fingerprint": fingerprint,\n                    }\n\n                if 200 <= response.status < 300:\n                    returned_count = (\n                        len(body)\n                        if isinstance(body, list)\n                        else len(payload)\n                    )\n\n                    state[scope] = {\n                        "status": "synced",\n                        "fingerprint": fingerprint,\n                        "last_status": response.status,\n                        "next_allowed_at": 0.0,\n                        "updated_at": time.time(),\n                        "command_count": returned_count,\n                    }\n                    _save_state(state)\n\n                    LOGGER.info(\n                        "✅ Sync Discord ONE-SHOT réussie : "\n                        "%s commande(s) publiée(s) sur %s.",\n                        returned_count,\n                        scope,\n                    )\n                    return {\n                        "status": "synced",\n                        "scope": scope,\n                        "command_count": returned_count,\n                        "fingerprint": fingerprint,\n                    }\n\n                state[scope] = {\n                    "status": "failed",\n                    "fingerprint": fingerprint,\n                    "last_status": response.status,\n                    "next_allowed_at": time.time() + 900,\n                    "updated_at": time.time(),\n                    "response": raw_text[:1000],\n                }\n                _save_state(state)\n\n                LOGGER.error(\n                    "Sync Discord ONE-SHOT refusée : HTTP %s. "\n                    "STOP, aucun retry automatique. Réponse=%s",\n                    response.status,\n                    raw_text[:500],\n                )\n                return {\n                    "status": "failed",\n                    "scope": scope,\n                    "http_status": response.status,\n                    "fingerprint": fingerprint,\n                }\n\n    except Exception as error:\n        state[scope] = {\n            "status": "network_error",\n            "fingerprint": fingerprint,\n            "next_allowed_at": time.time() + 900,\n            "updated_at": time.time(),\n            "error": repr(error),\n        }\n        _save_state(state)\n\n        LOGGER.exception(\n            "Erreur réseau pendant la sync Discord ONE-SHOT. "\n            "STOP, aucun retry automatique."\n        )\n        return {\n            "status": "network_error",\n            "scope": scope,\n            "fingerprint": fingerprint,\n        }\n'
SYNC_METHOD = '    async def _sync_application_commands(self) -> None:\n        """Publie les commandes sans jamais entrer dans une boucle de retry."""\n        self._drop_retired_application_commands()\n\n        if not SYNC_GUILD_COMMANDS and not SYNC_GLOBAL_COMMANDS:\n            LOGGER.info(\n                "Synchronisation Discord désactivée. "\n                "Aucune requête de commandes ne sera envoyée."\n            )\n            return\n\n        application_id = (\n            int(self.application_id)\n            if self.application_id is not None\n            else int(self.user.id if self.user is not None else 0)\n        )\n\n        if not application_id:\n            LOGGER.error(\n                "Application ID Discord indisponible : sync one-shot annulée."\n            )\n            return\n\n        if SYNC_GUILD_COMMANDS:\n            if GUILD_ID.isdigit():\n                await publish_application_commands_once(\n                    self.tree,\n                    application_id=application_id,\n                    token=TOKEN,\n                    guild_id=int(GUILD_ID),\n                    force=FORCE_COMMAND_SYNC,\n                )\n            else:\n                LOGGER.warning(\n                    "SYNC_GUILD_COMMANDS est actif, mais GUILD_ID est invalide."\n                )\n\n        if SYNC_GLOBAL_COMMANDS:\n            await publish_application_commands_once(\n                self.tree,\n                application_id=application_id,\n                token=TOKEN,\n                guild_id=None,\n                force=FORCE_COMMAND_SYNC,\n            )\n\n'
BACKGROUND_METHOD = '    async def _sync_application_commands_after_ready(self) -> None:\n        """Attend le Gateway puis lance une seule tentative de publication."""\n        try:\n            await self.wait_until_ready()\n\n            if self.is_closed():\n                return\n\n            LOGGER.info(\n                "Hamtaro est connecté : tentative ONE-SHOT de "\n                "synchronisation des commandes."\n            )\n\n            await self._sync_application_commands()\n\n        except asyncio.CancelledError:\n            raise\n        except Exception:\n            LOGGER.exception(\n                "Échec de la tentative ONE-SHOT des commandes. "\n                "Hamtaro reste connecté."\n            )\n\n'


def fail(message: str) -> None:
    raise SystemExit(f"❌ {message}")


def backup(path: Path, suffix: str) -> None:
    target = path.with_suffix(path.suffix + suffix)
    if not target.exists():
        shutil.copy2(path, target)


def replace_method(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
) -> str:
    start = text.find(start_marker)
    end = text.find(end_marker, start)

    if start == -1 or end == -1 or end <= start:
        fail(
            f"Impossible de remplacer {start_marker.strip()} : "
            "structure bot.py non reconnue."
        )

    return text[:start] + replacement + text[end:]


def main() -> None:
    if not BOT.exists() or not CONFIG.exists():
        fail(
            "Place ce script à la racine du dépôt Hamtaro "
            "(à côté de bot.py et config.py)."
        )

    bot_original = BOT.read_text(encoding="utf-8")
    config_original = CONFIG.read_text(encoding="utf-8")

    bot_text = bot_original
    config_text = config_original

    # 1) Config FORCE_COMMAND_SYNC
    force_line = 'FORCE_COMMAND_SYNC = env_bool("FORCE_COMMAND_SYNC", False)\n'
    if force_line not in config_text:
        anchor = 'SYNC_GUILD_COMMANDS = env_bool("SYNC_GUILD_COMMANDS", True)\n'
        if anchor not in config_text:
            fail("SYNC_GUILD_COMMANDS introuvable dans config.py.")
        config_text = config_text.replace(
            anchor,
            anchor + force_line,
            1,
        )

    # 2) Import FORCE_COMMAND_SYNC dans bot.py
    if "    FORCE_COMMAND_SYNC,\n" not in bot_text:
        anchor = "    FAIL_ON_COG_ERROR,\n"
        if anchor not in bot_text:
            fail("FAIL_ON_COG_ERROR introuvable dans les imports de bot.py.")
        bot_text = bot_text.replace(
            anchor,
            anchor + "    FORCE_COMMAND_SYNC,\n",
            1,
        )

    # 3) Import du publisher one-shot
    service_import = (
        "from services.command_sync_once import "
        "publish_application_commands_once\n"
    )
    if service_import not in bot_text:
        anchor = "from services.database_service import DatabaseService\n"
        if anchor not in bot_text:
            fail("DatabaseService introuvable dans les imports de bot.py.")
        bot_text = bot_text.replace(
            anchor,
            anchor + service_import,
            1,
        )

    # 4) setup_hook doit lancer la sync en background.
    setup_start = bot_text.find("    async def setup_hook(self) -> None:\n")
    setup_end = bot_text.find(
        "    async def _load_one_extension",
        setup_start,
    )
    if setup_start == -1 or setup_end == -1:
        fail("setup_hook introuvable dans bot.py.")

    setup_block = bot_text[setup_start:setup_end]

    background_call = (
        "        self.create_background_task(\n"
        "            self._sync_application_commands_after_ready(),\n"
        '            name="hamtaro-command-sync",\n'
        "        )\n"
    )

    if background_call not in setup_block:
        blocking = "        await self._sync_application_commands()\n"
        if blocking not in setup_block:
            fail("Appel de synchronisation introuvable dans setup_hook.")
        setup_block = setup_block.replace(
            blocking,
            background_call,
            1,
        )
        bot_text = (
            bot_text[:setup_start]
            + setup_block
            + bot_text[setup_end:]
        )

    # 5) Wrapper after-ready.
    background_marker = (
        "    async def _sync_application_commands_after_ready(self) -> None:\n"
    )
    sync_marker = "    async def _sync_application_commands(self) -> None:\n"
    database_marker = "    async def _database_backup_loop(self) -> None:\n"

    if background_marker in bot_text:
        bot_text = replace_method(
            bot_text,
            background_marker,
            sync_marker,
            BACKGROUND_METHOD,
        )
    else:
        idx = bot_text.find(sync_marker)
        if idx == -1:
            fail("_sync_application_commands introuvable.")
        bot_text = (
            bot_text[:idx]
            + BACKGROUND_METHOD
            + bot_text[idx:]
        )

    # 6) Remplacement intégral de la publication Discord.
    bot_text = replace_method(
        bot_text,
        sync_marker,
        database_marker,
        SYNC_METHOD,
    )

    sync_start = bot_text.find(sync_marker)
    sync_end = bot_text.find(database_marker, sync_start)
    sync_block = bot_text[sync_start:sync_end]

    if ".tree.sync(" in sync_block:
        fail(
            "Sécurité : tree.sync() est encore présent dans "
            "_sync_application_commands."
        )

    SERVICE.parent.mkdir(parents=True, exist_ok=True)

    backup(BOT, ".before-one-shot-sync.bak")
    backup(CONFIG, ".before-one-shot-sync.bak")

    SERVICE.write_text(SERVICE_CODE.lstrip(), encoding="utf-8")
    BOT.write_text(bot_text, encoding="utf-8")
    CONFIG.write_text(config_text, encoding="utf-8")

    try:
        py_compile.compile(str(BOT), doraise=True)
        py_compile.compile(str(CONFIG), doraise=True)
        py_compile.compile(str(SERVICE), doraise=True)
    except Exception as error:
        BOT.write_text(bot_original, encoding="utf-8")
        CONFIG.write_text(config_original, encoding="utf-8")
        if SERVICE.exists():
            SERVICE.unlink()
        fail(
            "Le patch ne compile pas. Fichiers restaurés. "
            f"Erreur : {error}"
        )

    print("✅ Mode ONE-SHOT installé.")
    print("✅ Plus aucun CommandTree.sync() pour publier les commandes.")
    print("✅ Une seule requête HTTP maximum par tentative.")
    print("✅ Un 429 = STOP immédiat, sans retry automatique.")
    print("✅ Retry-After est mémorisé sur le volume Railway.")
    print("✅ FORCE_COMMAND_SYNC ne contourne pas le cooldown 429.")
    print("✅ Hamtaro reste en ligne.")
    print()
    print("Avant de pousser :")
    print("  python3 -m py_compile bot.py config.py services/command_sync_once.py")
    print()
    print("Puis :")
    print("  git add bot.py config.py services/command_sync_once.py")
    print('  git commit -m "fix: make Discord command sync one-shot"')
    print("  git pull --rebase origin main")
    print("  git push origin main")


if __name__ == "__main__":
    main()
