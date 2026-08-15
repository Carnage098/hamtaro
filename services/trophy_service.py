from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class TrophyService:
    """Catalogue public des trophées Hamtaro."""

    def __init__(self, bot: Any, catalog_path: Path | None = None) -> None:
        self.bot = bot
        self.project_root = Path(__file__).resolve().parent.parent
        self.catalog_path = catalog_path or self.project_root / "web" / "data" / "trophies.json"
        self.model_directory = self.project_root / "web" / "static" / "models" / "trophies"

    @staticmethod
    def normalize_id(value: str) -> str:
        raw = str(value or "").strip().upper().replace("_", "-")
        if raw.isdigit():
            return f"HT-{int(raw):03d}"
        if raw.startswith("HT") and not raw.startswith("HT-"):
            suffix = raw[2:].lstrip("-")
            if suffix.isdigit():
                return f"HT-{int(suffix):03d}"
        if raw.startswith("HT-"):
            suffix = raw[3:]
            if suffix.isdigit():
                return f"HT-{int(suffix):03d}"
        return raw

    @staticmethod
    def _format_mib(path: Path) -> str:
        return f"{path.stat().st_size / (1024 * 1024):.1f}".replace(".", ",")

    def _load_catalog(self) -> dict[str, Any]:
        if not self.catalog_path.exists():
            raise RuntimeError(f"Catalogue des trophées introuvable : {self.catalog_path}")
        with self.catalog_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or not isinstance(payload.get("trophies"), list):
            raise RuntimeError("web/data/trophies.json doit contenir une liste 'trophies'.")
        return payload

    def _resolve_holder_name(self, discord_id: str | None, fallback: str | None) -> str | None:
        if not discord_id:
            return fallback
        try:
            user_id = int(discord_id)
        except (TypeError, ValueError):
            return fallback

        user = getattr(self.bot, "get_user", lambda _id: None)(user_id)
        if user is not None:
            return getattr(user, "display_name", None) or getattr(user, "name", None) or fallback

        for guild in list(getattr(self.bot, "guilds", []) or []):
            member = getattr(guild, "get_member", lambda _id: None)(user_id)
            if member is not None:
                return getattr(member, "display_name", None) or getattr(member, "name", None) or fallback
        return fallback

    def _resolve_model_file(self, model_url: str) -> Path | None:
        model_web_path = urlsplit(model_url).path
        if model_web_path.startswith("/media/trophies/"):
            filename = Path(model_web_path).name
            return self.model_directory / filename
        if model_web_path.startswith("/static/"):
            return self.project_root / "web" / model_web_path.lstrip("/")
        return None

    def _enrich(self, trophy: dict[str, Any]) -> dict[str, Any]:
        item = deepcopy(trophy)
        item["id"] = self.normalize_id(str(item.get("id") or ""))
        holder_id = str(item.get("holder_discord_id") or "").strip() or None
        item["holder_discord_id"] = holder_id
        item["holder_name"] = self._resolve_holder_name(holder_id, item.get("holder_name"))
        item["is_awarded"] = bool(holder_id or item.get("holder_name"))
        item["display_holder"] = item.get("holder_name") or "À attribuer"
        item["detail_url"] = f"/trophies/{item['id'].lower()}"

        model_url = str(item.get("model_path") or "").strip()
        model_file = self._resolve_model_file(model_url)
        item["model_exists"] = bool(model_file and model_file.exists())
        item["model_size_mb"] = None
        item["transfer_size_mb"] = None
        item["has_precompressed_model"] = False

        if model_file and model_file.exists():
            item["model_size_mb"] = self._format_mib(model_file)
            gzip_file = Path(str(model_file) + ".gz")
            if gzip_file.exists():
                item["transfer_size_mb"] = self._format_mib(gzip_file)
                item["has_precompressed_model"] = True
            else:
                item["transfer_size_mb"] = item["model_size_mb"]

        return item

    def all_trophies(self) -> list[dict[str, Any]]:
        payload = self._load_catalog()
        trophies = [self._enrich(item) for item in payload["trophies"] if isinstance(item, dict)]
        trophies.sort(key=lambda item: item.get("number", 999999))
        return trophies

    def get_trophy(self, trophy_id: str) -> dict[str, Any] | None:
        normalized = self.normalize_id(trophy_id)
        for trophy in self.all_trophies():
            if trophy.get("id") == normalized:
                return trophy
        return None

    def trophies_for_player(self, discord_id: str) -> list[dict[str, Any]]:
        wanted = str(discord_id or "").strip()
        if not wanted:
            return []
        return [
            trophy
            for trophy in self.all_trophies()
            if str(trophy.get("holder_discord_id") or "") == wanted
        ]
