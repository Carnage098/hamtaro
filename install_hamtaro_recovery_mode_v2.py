from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "services" / "command_sync_once.py"

HELPER = '\n_MISSING_DEFAULTS: dict[str, Any] = {\n    "nsfw": False,\n    "default_permission": True,\n    "required": False,\n    "autocomplete": False,\n}\n\n\ndef _project_like(existing: Any, desired: Any) -> Any:\n    """Projette la réponse Discord sur la forme du payload désiré."""\n    if isinstance(desired, dict):\n        if not isinstance(existing, dict):\n            return existing\n\n        projected: dict[str, Any] = {}\n        for child_key, desired_value in desired.items():\n            if child_key in existing:\n                existing_value = existing[child_key]\n            elif child_key in _MISSING_DEFAULTS:\n                existing_value = _MISSING_DEFAULTS[child_key]\n            elif desired_value is None:\n                existing_value = None\n            else:\n                existing_value = object()\n\n            projected[child_key] = _project_like(\n                existing_value,\n                desired_value,\n            )\n        return projected\n\n    if isinstance(desired, list):\n        if not isinstance(existing, list):\n            return existing\n        if len(existing) != len(desired):\n            return existing\n        return [\n            _project_like(actual, wanted)\n            for actual, wanted in zip(existing, desired)\n        ]\n\n    return existing\n\n\ndef _commands_equivalent(\n    existing_command: dict[str, Any],\n    desired_edit: dict[str, Any],\n) -> bool:\n    return _project_like(existing_command, desired_edit) == desired_edit\n\n\n'
NEW_UPDATE_SECTION = '        updated = 0\n        created = 0\n\n        # Pendant une restauration partielle, priorité absolue aux commandes\n        # manquantes. Aucun PATCH n\'est envoyé pour les commandes existantes.\n        if missing_keys:\n            LOGGER.info(\n                "Mode restauration : %s racine(s) manquante(s) -> "\n                "PATCH des commandes existantes ignoré.",\n                len(missing_keys),\n            )\n        else:\n            for desired_command in desired:\n                key = _command_key(desired_command)\n                existing_command = existing_by_key.get(key)\n\n                if existing_command is None or key in predeleted_keys:\n                    continue\n\n                command_id = str(existing_command.get("id") or "")\n                if not command_id:\n                    continue\n\n                desired_edit = _edit_payload(desired_command)\n\n                if _commands_equivalent(existing_command, desired_edit):\n                    LOGGER.info(\n                        "↪ commande déjà identique : /%s (PATCH ignoré)",\n                        key[1],\n                    )\n                    continue\n\n                label = f"PATCH /{key[1]}"\n                patch_url = f"{base_url}/{command_id}"\n\n                pstatus, _, pheaders, _ = await _request(\n                    session,\n                    "PATCH",\n                    patch_url,\n                    label=label,\n                    json_payload=desired_edit,\n                )\n\n                if pstatus != 200:\n                    LOGGER.error(\n                        "Sync différentielle interrompue sur /%s : HTTP %s. "\n                        "%s commande(s) déjà mise(s) à jour.",\n                        key[1],\n                        pstatus,\n                        updated,\n                    )\n\n                    state[scope] = {\n                        "status": "partial",\n                        "mode": "differential",\n                        "fingerprint": fingerprint,\n                        "stage": "update",\n                        "updated": updated,\n                        "created": created,\n                        "http_status": pstatus,\n                        "updated_at": time.time(),\n                    }\n                    _save_state(state)\n\n                    return {\n                        "status": "partial",\n                        "scope": scope,\n                        "stage": "update",\n                        "updated": updated,\n                        "created": created,\n                        "http_status": pstatus,\n                    }\n\n                updated += 1\n                LOGGER.info(\n                    "✅ [%s/%s] commande mise à jour : /%s",\n                    updated,\n                    len(desired),\n                    key[1],\n                )\n                await _pace_from_headers(\n                    pheaders,\n                    label=label,\n                )\n\n'
OLD_SCOPE = '                scope == "shared"\n                and shared_waits < max_shared_waits\n                and 0.0 < retry_after <= 900.0\n'
NEW_SCOPE = '                scope in {"shared", "user"}\n                and shared_waits < max_shared_waits\n                and 0.0 < retry_after <= 900.0\n'
OLD_LOG = '                LOGGER.warning(\n                    "429 shared sur %s : attente contrôlée %.1fs "\n                    "(%s/%s), puis UNE nouvelle tentative.",\n                    label,\n                    wait_for,\n                    shared_waits,\n                    max_shared_waits,\n                )\n'
NEW_LOG = '                LOGGER.warning(\n                    "429 %s sur %s : attente contrôlée %.1fs "\n                    "(%s/%s), puis UNE nouvelle tentative.",\n                    scope,\n                    label,\n                    wait_for,\n                    shared_waits,\n                    max_shared_waits,\n                )\n'
OLD_RETRY = 'def _retry_after(response: aiohttp.ClientResponse, body: Any) -> float:\n    value: Any = None\n\n    if isinstance(body, dict):\n        value = body.get("retry_after")\n\n    if value is None:\n        value = response.headers.get("Retry-After")\n\n    try:\n        return max(0.0, float(value or 0.0))\n    except (TypeError, ValueError):\n        return 0.0\n'
NEW_RETRY = 'def _retry_after(response: aiohttp.ClientResponse, body: Any) -> float:\n    candidates: list[float] = []\n\n    values: list[Any] = [\n        body.get("retry_after") if isinstance(body, dict) else None,\n        response.headers.get("Retry-After"),\n        response.headers.get("X-RateLimit-Reset-After"),\n    ]\n\n    for value in values:\n        try:\n            if value is not None:\n                candidates.append(max(0.0, float(value)))\n        except (TypeError, ValueError):\n            continue\n\n    return max(candidates, default=0.0)\n'


def fail(message: str) -> None:
    raise SystemExit(f"❌ {message}")


def main() -> None:
    if not TARGET.exists():
        fail(
            "services/command_sync_once.py est introuvable. "
            "Place ce script à la racine du dépôt Hamtaro."
        )

    original = TARGET.read_text(encoding="utf-8")
    text = original

    backup = TARGET.with_suffix(
        TARGET.suffix + ".before-recovery-mode-v2.bak"
    )
    if not backup.exists():
        shutil.copy2(TARGET, backup)

    changed = False

    if OLD_SCOPE in text:
        text = text.replace(OLD_SCOPE, NEW_SCOPE, 1)
        changed = True

    if OLD_LOG in text:
        text = text.replace(OLD_LOG, NEW_LOG, 1)
        changed = True

    if OLD_RETRY in text:
        text = text.replace(OLD_RETRY, NEW_RETRY, 1)
        changed = True

    if "_commands_equivalent(" not in text:
        marker = "def _retry_after(response: aiohttp.ClientResponse, body: Any) -> float:\n"
        if marker not in text:
            fail("Impossible de trouver _retry_after pour insérer le comparateur.")
        text = text.replace(marker, HELPER + marker, 1)
        changed = True

    start_marker = "        updated = 0\n        created = 0\n\n"
    end_marker = "        # Puis seulement les racines réellement absentes.\n"

    start = text.find(start_marker)
    end = text.find(end_marker)

    if start == -1 or end == -1 or end <= start:
        fail("Bloc de synchronisation PATCH introuvable.")

    current_section = text[start:end]
    if "Mode restauration :" not in current_section:
        text = text[:start] + NEW_UPDATE_SECTION + text[end:]
        changed = True

    if not changed:
        print("✅ Le mode restauration V2 est déjà installé.")
        return

    TARGET.write_text(text, encoding="utf-8")

    try:
        compile(
            TARGET.read_text(encoding="utf-8"),
            str(TARGET),
            "exec",
        )
    except Exception as error:
        TARGET.write_text(original, encoding="utf-8")
        fail(
            "Le fichier modifié ne compile pas ; restauration automatique. "
            f"Erreur : {error}"
        )

    print("✅ Mode restauration V2 installé.")
    print("✅ Tant qu'il manque des racines : zéro PATCH des existantes.")
    print("✅ Seules les commandes manquantes sont POSTées.")
    print("✅ Retry 429 scope=user et scope=shared pris en charge.")
    print("✅ Comparaison récursive utilisée une fois les 26 racines présentes.")
    print("✅ Les 26 racines / 144 actions restent inchangées.")
    print()
    print("Puis :")
    print("  python3 -m py_compile services/command_sync_once.py")
    print("  git add services/command_sync_once.py")
    print('  git commit -m "fix: prioritize missing Discord commands during recovery"')
    print("  git pull --rebase origin main")
    print("  git push origin main")


if __name__ == "__main__":
    main()
