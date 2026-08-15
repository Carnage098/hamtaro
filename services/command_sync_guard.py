from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import discord
from discord import app_commands

LOGGER = logging.getLogger("hamtaro.command_sync")

def command_tree_fingerprint(tree: app_commands.CommandTree) -> str:
    roots = list(tree.get_commands(type=discord.AppCommandType.chat_input))
    payload: list[dict[str, Any]] = [
        command.to_dict(tree)
        for command in sorted(roots, key=lambda item: item.name)
    ]
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

class CommandSyncState:
    def __init__(self, path: Path, *, logger=None) -> None:
        self.path = Path(path)
        self.logger = logger or LOGGER

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            self.logger.exception("Impossible de lire l'état de synchronisation Discord.")
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def needs_sync(self, scope: str, fingerprint: str, *, force=False) -> bool:
        return bool(force or self._load().get(scope) != fingerprint)

    def mark_synced(self, scope: str, fingerprint: str) -> None:
        data = self._load()
        data[scope] = fingerprint
        self._save(data)
