from __future__ import annotations

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


def _load_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        LOGGER.exception("Impossible de lire l'état one-shot des commandes.")
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


def _rate_limit_diagnostics(response, body, raw_text: str) -> dict[str, object]:
    header_names = (
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "X-RateLimit-Reset-After",
        "X-RateLimit-Bucket",
        "X-RateLimit-Scope",
        "Retry-After",
        "Date",
        "Via",
        "CF-Ray",
    )

    headers = {
        name: response.headers.get(name)
        for name in header_names
        if response.headers.get(name) is not None
    }

    return {
        "status": response.status,
        "headers": headers,
        "body": body if body else raw_text[:2000],
    }


def _log_rate_limit_diagnostics(response, body, raw_text: str) -> None:
    import json as _json

    diagnostics = _rate_limit_diagnostics(
        response,
        body,
        raw_text,
    )

    LOGGER.error("━━━━━━━━ DISCORD RATE LIMIT DIAGNOSTIC ━━━━━━━━")
    LOGGER.error("HTTP status              : %s", diagnostics["status"])

    headers = diagnostics["headers"]

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
            headers.get(key, "<absent>"),
        )

    try:
        body_text = _json.dumps(
            diagnostics["body"],
            ensure_ascii=False,
            sort_keys=True,
        )
    except Exception:
        body_text = repr(diagnostics["body"])

    LOGGER.error(
        "Discord response body    : %s",
        body_text[:3000],
    )
    LOGGER.error("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


async def publish_application_commands_once(
    tree: app_commands.CommandTree,
    *,
    application_id: int,
    token: str,
    guild_id: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Publie l'arbre avec UNE requête HTTP maximum, sans retry automatique."""

    payload = _payload(tree)
    fingerprint = _fingerprint(payload)

    scope = f"guild:{guild_id}" if guild_id else "global"
    state = _load_state()
    entry = state.get(scope)
    if not isinstance(entry, dict):
        entry = {}

    now = time.time()
    next_allowed_at = float(entry.get("next_allowed_at") or 0.0)

    # FORCE ne contourne JAMAIS un cooldown 429.
    if next_allowed_at > now:
        remaining = max(0.0, next_allowed_at - now)
        LOGGER.warning(
            "Sync Discord one-shot BLOQUÉE : scope=%s, "
            "nouvelle tentative autorisée dans %.1fs. "
            "Aucune requête envoyée.",
            scope,
            remaining,
        )
        return {
            "status": "cooldown",
            "scope": scope,
            "retry_after": remaining,
            "fingerprint": fingerprint,
        }

    if (
        not force
        and entry.get("status") == "synced"
        and entry.get("fingerprint") == fingerprint
    ):
        LOGGER.info(
            "Arbre Discord inchangé et déjà publié : %s. "
            "Aucune requête envoyée.",
            scope,
        )
        return {
            "status": "unchanged",
            "scope": scope,
            "fingerprint": fingerprint,
        }

    if guild_id:
        url = (
            f"{API_BASE}/applications/{application_id}"
            f"/guilds/{guild_id}/commands"
        )
    else:
        url = f"{API_BASE}/applications/{application_id}/commands"

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (Hamtaro, command-sync-one-shot)",
    }

    LOGGER.info(
        "Sync Discord ONE-SHOT : %s commande(s) racine(s) -> %s "
        "(empreinte=%s).",
        len(payload),
        scope,
        fingerprint[:12],
    )

    timeout = aiohttp.ClientTimeout(total=30)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.put(
                url,
                headers=headers,
                json=payload,
            ) as response:
                raw_text = await response.text()

                try:
                    body = json.loads(raw_text) if raw_text else {}
                except json.JSONDecodeError:
                    body = {}

                if response.status == 429:
                    _log_rate_limit_diagnostics(
                        response,
                        body,
                        raw_text,
                    )

                    retry_after = 0.0

                    try:
                        retry_after = float(body.get("retry_after") or 0.0)
                    except (TypeError, ValueError):
                        retry_after = 0.0

                    if retry_after <= 0:
                        try:
                            retry_after = float(
                                response.headers.get("Retry-After") or 0.0
                            )
                        except (TypeError, ValueError):
                            retry_after = 0.0

                    retry_after = max(60.0, retry_after)
                    blocked_until = time.time() + retry_after + 15.0

                    state[scope] = {
                        "status": "rate_limited",
                        "fingerprint": fingerprint,
                        "last_status": 429,
                        "retry_after": retry_after,
                        "next_allowed_at": blocked_until,
                        "updated_at": time.time(),
                    }
                    _save_state(state)

                    LOGGER.error(
                        "Discord 429 : STOP. Aucun retry automatique. "
                        "Cooldown enregistré pour %.1fs (+15s de marge).",
                        retry_after,
                    )
                    return {
                        "status": "rate_limited",
                        "scope": scope,
                        "retry_after": retry_after,
                        "fingerprint": fingerprint,
                    }

                if 200 <= response.status < 300:
                    returned_count = (
                        len(body)
                        if isinstance(body, list)
                        else len(payload)
                    )

                    state[scope] = {
                        "status": "synced",
                        "fingerprint": fingerprint,
                        "last_status": response.status,
                        "next_allowed_at": 0.0,
                        "updated_at": time.time(),
                        "command_count": returned_count,
                    }
                    _save_state(state)

                    LOGGER.info(
                        "✅ Sync Discord ONE-SHOT réussie : "
                        "%s commande(s) publiée(s) sur %s.",
                        returned_count,
                        scope,
                    )
                    return {
                        "status": "synced",
                        "scope": scope,
                        "command_count": returned_count,
                        "fingerprint": fingerprint,
                    }

                state[scope] = {
                    "status": "failed",
                    "fingerprint": fingerprint,
                    "last_status": response.status,
                    "next_allowed_at": time.time() + 900,
                    "updated_at": time.time(),
                    "response": raw_text[:1000],
                }
                _save_state(state)

                LOGGER.error(
                    "Sync Discord ONE-SHOT refusée : HTTP %s. "
                    "STOP, aucun retry automatique. Réponse=%s",
                    response.status,
                    raw_text[:500],
                )
                return {
                    "status": "failed",
                    "scope": scope,
                    "http_status": response.status,
                    "fingerprint": fingerprint,
                }

    except Exception as error:
        state[scope] = {
            "status": "network_error",
            "fingerprint": fingerprint,
            "next_allowed_at": time.time() + 900,
            "updated_at": time.time(),
            "error": repr(error),
        }
        _save_state(state)

        LOGGER.exception(
            "Erreur réseau pendant la sync Discord ONE-SHOT. "
            "STOP, aucun retry automatique."
        )
        return {
            "status": "network_error",
            "scope": scope,
            "fingerprint": fingerprint,
        }
