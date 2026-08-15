from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

import aiohttp
from discord import app_commands

from config import DATABASE


LOGGER = logging.getLogger("hamtaro.command_sync_once")
STATE_FILE = DATABASE.parent / "command_sync_once_state.json"
API_BASE = "https://discord.com/api/v10"

EDITABLE_GUILD_FIELDS = (
    "name",
    "name_localizations",
    "description",
    "description_localizations",
    "options",
    "default_member_permissions",
    "default_permission",
    "nsfw",
)


def _load_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        LOGGER.exception("Impossible de lire l'état de synchronisation.")
        return {}


def _save_state(data: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(STATE_FILE)


def _payload(tree: app_commands.CommandTree) -> list[dict[str, Any]]:
    commands = list(tree.get_commands())
    commands.sort(key=lambda command: command.name)
    return [command.to_dict(tree) for command in commands]


def _fingerprint(payload: list[dict[str, Any]]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _command_key(command: dict[str, Any]) -> tuple[int, str]:
    return (
        int(command.get("type") or 1),
        str(command.get("name") or ""),
    )


def _edit_payload(command: dict[str, Any]) -> dict[str, Any]:
    return {
        key: command[key]
        for key in EDITABLE_GUILD_FIELDS
        if key in command
    }


def _retry_after(response: aiohttp.ClientResponse, body: Any) -> float:
    value: Any = None

    if isinstance(body, dict):
        value = body.get("retry_after")

    if value is None:
        value = response.headers.get("Retry-After")

    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _reset_after(response: aiohttp.ClientResponse) -> float:
    try:
        return max(
            0.0,
            float(response.headers.get("X-RateLimit-Reset-After") or 0.0),
        )
    except (TypeError, ValueError):
        return 0.0


def _remaining(response: aiohttp.ClientResponse) -> int | None:
    value = response.headers.get("X-RateLimit-Remaining")
    if value is None:
        return None

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _log_429(
    response: aiohttp.ClientResponse,
    body: Any,
    raw_text: str,
    *,
    label: str,
) -> None:
    LOGGER.error("━━━━━━━━ DISCORD RATE LIMIT DIAGNOSTIC ━━━━━━━━")
    LOGGER.error("Opération                : %s", label)
    LOGGER.error("HTTP status              : %s", response.status)

    for key in (
        "X-RateLimit-Scope",
        "X-RateLimit-Bucket",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "X-RateLimit-Reset-After",
        "Retry-After",
        "Date",
        "Via",
        "CF-Ray",
    ):
        LOGGER.error(
            "%-24s : %s",
            key,
            response.headers.get(key, "<absent>"),
        )

    try:
        rendered = json.dumps(
            body if body else raw_text[:2000],
            ensure_ascii=False,
            sort_keys=True,
        )
    except Exception:
        rendered = repr(body if body else raw_text[:2000])

    LOGGER.error("Discord response body    : %s", rendered[:3000])
    LOGGER.error("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


async def _request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    label: str,
    json_payload: Any = None,
    max_shared_waits: int = 2,
) -> tuple[int, Any, aiohttp.typedefs.LooseHeaders, float]:
    """Effectue une requête avec retries strictement bornés.

    - jamais de boucle infinie ;
    - uniquement les 429 scope=shared sont retentés ;
    - maximum `max_shared_waits` attentes pour une opération ;
    - le délai Discord Retry-After est respecté.
    """
    shared_waits = 0

    while True:
        kwargs: dict[str, Any] = {}
        if json_payload is not None:
            kwargs["json"] = json_payload

        async with session.request(method, url, **kwargs) as response:
            raw_text = await response.text()

            try:
                body = json.loads(raw_text) if raw_text else {}
            except json.JSONDecodeError:
                body = {}

            status = response.status
            headers = dict(response.headers)
            reset_after = _reset_after(response)

            if status != 429:
                return status, body, headers, reset_after

            _log_429(
                response,
                body,
                raw_text,
                label=label,
            )

            scope = str(response.headers.get("X-RateLimit-Scope") or "")
            retry_after = _retry_after(response, body)

            if (
                scope == "shared"
                and shared_waits < max_shared_waits
                and 0.0 < retry_after <= 900.0
            ):
                shared_waits += 1
                wait_for = retry_after + 1.0

                LOGGER.warning(
                    "429 shared sur %s : attente contrôlée %.1fs "
                    "(%s/%s), puis UNE nouvelle tentative.",
                    label,
                    wait_for,
                    shared_waits,
                    max_shared_waits,
                )

                await asyncio.sleep(wait_for)
                continue

            LOGGER.error(
                "STOP sur %s : aucun retry supplémentaire. "
                "scope=%s retry_after=%.1fs",
                label,
                scope or "<absent>",
                retry_after,
            )
            return status, body, headers, reset_after


async def _pace_from_headers(
    headers: aiohttp.typedefs.LooseHeaders,
    *,
    label: str,
) -> None:
    remaining_raw = headers.get("X-RateLimit-Remaining")
    reset_raw = headers.get("X-RateLimit-Reset-After")

    try:
        remaining = (
            int(float(remaining_raw))
            if remaining_raw is not None
            else None
        )
    except (TypeError, ValueError):
        remaining = None

    try:
        reset_after = float(reset_raw or 0.0)
    except (TypeError, ValueError):
        reset_after = 0.0

    if remaining == 0 and reset_after > 0:
        wait_for = reset_after + 0.75
        LOGGER.info(
            "Bucket épuisé après %s : pause préventive %.1fs.",
            label,
            wait_for,
        )
        await asyncio.sleep(wait_for)
    else:
        # Petit espacement pour éviter les rafales d'écritures.
        await asyncio.sleep(0.35)


async def _sync_guild_differential(
    tree: app_commands.CommandTree,
    *,
    application_id: int,
    token: str,
    guild_id: int,
    force: bool,
) -> dict[str, Any]:
    desired = _payload(tree)
    fingerprint = _fingerprint(desired)
    scope = f"guild:{guild_id}"

    state = _load_state()
    entry = state.get(scope)
    if not isinstance(entry, dict):
        entry = {}

    if (
        not force
        and entry.get("status") == "synced"
        and entry.get("fingerprint") == fingerprint
        and entry.get("mode") == "differential"
    ):
        LOGGER.info(
            "Arbre Discord inchangé et déjà synchronisé : %s. "
            "Aucune écriture envoyée.",
            scope,
        )
        return {
            "status": "unchanged",
            "scope": scope,
            "fingerprint": fingerprint,
        }

    base_url = (
        f"{API_BASE}/applications/{application_id}"
        f"/guilds/{guild_id}/commands"
    )

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (Hamtaro, differential-command-sync)",
    }

    timeout = aiohttp.ClientTimeout(total=45)

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
    ) as session:
        LOGGER.info(
            "Sync Discord DIFFÉRENTIELLE : lecture des commandes "
            "enregistrées sur %s.",
            scope,
        )

        status, existing_body, get_headers, _ = await _request(
            session,
            "GET",
            base_url + "?with_localizations=true",
            label="GET guild commands",
            max_shared_waits=1,
        )

        if status != 200 or not isinstance(existing_body, list):
            LOGGER.error(
                "Impossible de lire les commandes Discord : HTTP %s. "
                "Aucune écriture effectuée.",
                status,
            )

            state[scope] = {
                "status": "read_failed",
                "mode": "differential",
                "fingerprint": fingerprint,
                "http_status": status,
                "updated_at": time.time(),
            }
            _save_state(state)

            return {
                "status": "read_failed",
                "scope": scope,
                "http_status": status,
            }

        existing: list[dict[str, Any]] = [
            item
            for item in existing_body
            if isinstance(item, dict)
        ]

        existing_by_key = {
            _command_key(item): item
            for item in existing
        }
        desired_by_key = {
            _command_key(item): item
            for item in desired
        }

        missing_keys = [
            key
            for key in desired_by_key
            if key not in existing_by_key
        ]
        stale_keys = [
            key
            for key in existing_by_key
            if key not in desired_by_key
        ]

        LOGGER.info(
            "Discord actuellement : %s racine(s). "
            "Cible Hamtaro : %s. Existantes=%s, manquantes=%s, obsolètes=%s.",
            len(existing),
            len(desired),
            len(desired) - len(missing_keys),
            len(missing_keys),
            len(stale_keys),
        )

        # Si les anciennes commandes empêchent de rester sous la limite des
        # 100 CHAT_INPUT, on ne supprime que le strict minimum avant création.
        current_chat = sum(
            1
            for item in existing
            if int(item.get("type") or 1) == 1
        )
        missing_chat = sum(
            1
            for key in missing_keys
            if key[0] == 1
        )

        predelete_needed = max(0, current_chat + missing_chat - 100)
        predeleted_keys: set[tuple[int, str]] = set()

        if predelete_needed:
            candidates = [
                key
                for key in stale_keys
                if key[0] == 1
            ][:predelete_needed]

            LOGGER.warning(
                "%s ancienne(s) commande(s) doivent être supprimées "
                "avant les créations pour rester sous 100 racines.",
                len(candidates),
            )

            for key in candidates:
                old = existing_by_key[key]
                command_id = str(old.get("id") or "")
                if not command_id:
                    continue

                label = f"DELETE stale {key[1]}"
                delete_url = f"{base_url}/{command_id}"

                dstatus, _, dheaders, _ = await _request(
                    session,
                    "DELETE",
                    delete_url,
                    label=label,
                )

                if dstatus != 204:
                    LOGGER.error(
                        "Arrêt de la sync : suppression préalable de /%s "
                        "refusée (HTTP %s).",
                        key[1],
                        dstatus,
                    )
                    return {
                        "status": "partial",
                        "scope": scope,
                        "stage": "predelete",
                        "http_status": dstatus,
                    }

                predeleted_keys.add(key)
                await _pace_from_headers(
                    dheaders,
                    label=label,
                )

        updated = 0
        created = 0

        # On met d'abord à jour les commandes déjà existantes : PATCH ne crée
        # pas de nouvelle commande et restaure leurs sous-commandes/options.
        for desired_command in desired:
            key = _command_key(desired_command)
            existing_command = existing_by_key.get(key)

            if existing_command is None or key in predeleted_keys:
                continue

            command_id = str(existing_command.get("id") or "")
            if not command_id:
                continue

            label = f"PATCH /{key[1]}"
            patch_url = f"{base_url}/{command_id}"

            pstatus, _, pheaders, _ = await _request(
                session,
                "PATCH",
                patch_url,
                label=label,
                json_payload=_edit_payload(desired_command),
            )

            if pstatus != 200:
                LOGGER.error(
                    "Sync différentielle interrompue sur /%s : HTTP %s. "
                    "%s commande(s) déjà mise(s) à jour.",
                    key[1],
                    pstatus,
                    updated,
                )

                state[scope] = {
                    "status": "partial",
                    "mode": "differential",
                    "fingerprint": fingerprint,
                    "stage": "update",
                    "updated": updated,
                    "created": created,
                    "http_status": pstatus,
                    "updated_at": time.time(),
                }
                _save_state(state)

                return {
                    "status": "partial",
                    "scope": scope,
                    "stage": "update",
                    "updated": updated,
                    "created": created,
                    "http_status": pstatus,
                }

            updated += 1
            LOGGER.info(
                "✅ [%s/%s] commande mise à jour : /%s",
                updated,
                len(desired),
                key[1],
            )
            await _pace_from_headers(
                pheaders,
                label=label,
            )

        # Puis seulement les racines réellement absentes.
        for desired_command in desired:
            key = _command_key(desired_command)

            if (
                key in existing_by_key
                and key not in predeleted_keys
            ):
                continue

            label = f"POST /{key[1]}"

            cstatus, _, cheaders, _ = await _request(
                session,
                "POST",
                base_url,
                label=label,
                json_payload=desired_command,
            )

            if cstatus not in (200, 201):
                LOGGER.error(
                    "Création de /%s refusée (HTTP %s). "
                    "STOP : aucune boucle infinie.",
                    key[1],
                    cstatus,
                )

                state[scope] = {
                    "status": "partial",
                    "mode": "differential",
                    "fingerprint": fingerprint,
                    "stage": "create",
                    "updated": updated,
                    "created": created,
                    "http_status": cstatus,
                    "updated_at": time.time(),
                }
                _save_state(state)

                return {
                    "status": "partial",
                    "scope": scope,
                    "stage": "create",
                    "updated": updated,
                    "created": created,
                    "http_status": cstatus,
                }

            created += 1
            LOGGER.info(
                "✅ commande restaurée/créée : /%s (HTTP %s)",
                key[1],
                cstatus,
            )
            await _pace_from_headers(
                cheaders,
                label=label,
            )

        # Les 26 racines cibles existent maintenant : nettoyage des anciennes.
        deleted = len(predeleted_keys)

        for key in stale_keys:
            if key in predeleted_keys:
                continue

            old = existing_by_key[key]
            command_id = str(old.get("id") or "")
            if not command_id:
                continue

            label = f"DELETE stale /{key[1]}"
            delete_url = f"{base_url}/{command_id}"

            dstatus, _, dheaders, _ = await _request(
                session,
                "DELETE",
                delete_url,
                label=label,
            )

            if dstatus != 204:
                LOGGER.warning(
                    "Ancienne commande /%s non supprimée (HTTP %s). "
                    "Les commandes Hamtaro cibles sont déjà restaurées.",
                    key[1],
                    dstatus,
                )
                break

            deleted += 1
            await _pace_from_headers(
                dheaders,
                label=label,
            )

        # Vérification finale en lecture seule.
        vstatus, final_body, _, _ = await _request(
            session,
            "GET",
            base_url,
            label="GET final verification",
            max_shared_waits=1,
        )

        final_keys: set[tuple[int, str]] = set()

        if vstatus == 200 and isinstance(final_body, list):
            final_keys = {
                _command_key(item)
                for item in final_body
                if isinstance(item, dict)
            }

        wanted_keys = set(desired_by_key)
        missing_after = sorted(
            wanted_keys - final_keys,
            key=lambda item: item[1],
        ) if final_keys else []

        if vstatus == 200 and not missing_after:
            state[scope] = {
                "status": "synced",
                "mode": "differential",
                "fingerprint": fingerprint,
                "updated_at": time.time(),
                "command_count": len(desired),
                "updated": updated,
                "created": created,
                "deleted": deleted,
            }
            _save_state(state)

            LOGGER.info(
                "✅ SYNC DIFFÉRENTIELLE TERMINÉE : "
                "%s racines Hamtaro présentes ; updated=%s created=%s "
                "deleted=%s.",
                len(desired),
                updated,
                created,
                deleted,
            )

            return {
                "status": "synced",
                "scope": scope,
                "command_count": len(desired),
                "updated": updated,
                "created": created,
                "deleted": deleted,
            }

        LOGGER.error(
            "Vérification finale incomplète : HTTP=%s, manquantes=%s",
            vstatus,
            [name for _, name in missing_after],
        )

        return {
            "status": "partial",
            "scope": scope,
            "stage": "verification",
            "missing": [name for _, name in missing_after],
        }


async def _sync_global_one_shot(
    tree: app_commands.CommandTree,
    *,
    application_id: int,
    token: str,
    force: bool,
) -> dict[str, Any]:
    """Fallback global conservateur.

    Hamtaro utilise actuellement la synchro guild. On évite ici tout mécanisme
    de retry automatique pour le scope global.
    """
    payload = _payload(tree)
    fingerprint = _fingerprint(payload)
    url = f"{API_BASE}/applications/{application_id}/commands"

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (Hamtaro, global-command-sync)",
    }

    timeout = aiohttp.ClientTimeout(total=45)

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
    ) as session:
        status, body, _, _ = await _request(
            session,
            "PUT",
            url,
            label="PUT global commands",
            json_payload=payload,
            max_shared_waits=0,
        )

    if status == 200:
        count = len(body) if isinstance(body, list) else len(payload)
        LOGGER.info(
            "✅ Sync globale réussie : %s commande(s).",
            count,
        )
        return {
            "status": "synced",
            "scope": "global",
            "command_count": count,
            "fingerprint": fingerprint,
        }

    return {
        "status": "failed",
        "scope": "global",
        "http_status": status,
        "fingerprint": fingerprint,
    }


async def publish_application_commands_once(
    tree: app_commands.CommandTree,
    *,
    application_id: int,
    token: str,
    guild_id: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Point d'entrée compatible avec bot.py.

    Guild -> synchronisation différentielle.
    Global -> one-shot conservateur.
    """
    if guild_id is not None:
        return await _sync_guild_differential(
            tree,
            application_id=application_id,
            token=token,
            guild_id=guild_id,
            force=force,
        )

    return await _sync_global_one_shot(
        tree,
        application_id=application_id,
        token=token,
        force=force,
    )
