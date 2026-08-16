from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from services.trophy_award_service import TrophyAwardService
from services.spiderman_trophy_award_service import SpidermanTrophyAwardService


class TrophyService:
    """Catalogue public + attributions SQLite des trophées Hamtaro."""

    def __init__(self, bot: Any, catalog_path: Path | None = None) -> None:
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        self.catalog_path = catalog_path or project_root / "web" / "data" / "trophies.json"
        self.awards = TrophyAwardService(bot)
        self.spiderman_awards = SpidermanTrophyAwardService()

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

    def _load_catalog(self) -> dict[str, Any]:
        if not self.catalog_path.exists():
            raise RuntimeError(f"Catalogue des trophées introuvable : {self.catalog_path}")
        with self.catalog_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or not isinstance(payload.get("trophies"), list):
            raise RuntimeError("web/data/trophies.json doit contenir une liste 'trophies'.")
        return payload

    def _resolve_holder_name(
        self,
        discord_id: str | None,
        fallback: str | None,
    ) -> str | None:
        if not discord_id:
            return fallback
        try:
            user_id = int(discord_id)
        except (TypeError, ValueError):
            return fallback

        user = getattr(self.bot, "get_user", lambda _id: None)(user_id)
        if user is not None:
            return (
                getattr(user, "display_name", None)
                or getattr(user, "name", None)
                or fallback
            )

        for guild in list(getattr(self.bot, "guilds", []) or []):
            member = getattr(guild, "get_member", lambda _id: None)(user_id)
            if member is not None:
                return (
                    getattr(member, "display_name", None)
                    or getattr(member, "name", None)
                    or fallback
                )
        return fallback

    def _enrich(
        self,
        trophy: dict[str, Any],
        award: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = deepcopy(trophy)
        item["id"] = self.normalize_id(str(item.get("id") or ""))

        # L'attribution SQLite est la source de vérité pour le propriétaire.
        if award:
            item["holder_discord_id"] = str(award.get("discord_id") or "").strip() or None
            item["holder_name"] = award.get("holder_name")
            item["deck"] = award.get("deck")
            item["format"] = award.get("format")
            item["tournament_name"] = award.get("tournament_name")
            item["tournament_id"] = award.get("tournament_id")
            item["tournament_code"] = award.get("tournament_code") or item.get("tournament_code")
            item["awarded_at"] = award.get("awarded_at")
            item["award_guild_id"] = award.get("guild_id")

        holder_id = str(item.get("holder_discord_id") or "").strip() or None
        item["holder_discord_id"] = holder_id
        item["holder_name"] = self._resolve_holder_name(holder_id, item.get("holder_name"))
        item["is_awarded"] = bool(holder_id or item.get("holder_name"))
        item["display_holder"] = item.get("holder_name") or "À attribuer"
        item["detail_url"] = f"/trophies/{item['id'].lower()}"

        model_url = str(item.get("model_path") or "").strip()
        model_web_path = urlsplit(model_url).path
        if model_web_path.startswith("/static/"):
            project_root = Path(__file__).resolve().parent.parent
            model_file = project_root / "web" / model_web_path.lstrip("/")
            if model_file.exists():
                item["model_size_mb"] = (
                    f"{model_file.stat().st_size / (1024 * 1024):.1f}".replace(".", ",")
                )
                item["model_exists"] = True
            else:
                item["model_exists"] = False

        return item

    async def all_trophies(self) -> list[dict[str, Any]]:
        payload = self._load_catalog()
        awards = await self.awards.all_awards()
        awards.update(await self.spiderman_awards.all_awards())
        trophies = [
            self._enrich(
                item,
                awards.get(self.normalize_id(str(item.get("id") or ""))),
            )
            for item in payload["trophies"]
            if isinstance(item, dict)
        ]
        trophies.sort(key=lambda item: item.get("number", 999999))
        return trophies

    async def get_trophy(self, trophy_id: str) -> dict[str, Any] | None:
        normalized = self.normalize_id(trophy_id)
        for trophy in await self.all_trophies():
            if trophy.get("id") == normalized:
                return trophy
        return None

    async def trophies_for_player(self, discord_id: str) -> list[dict[str, Any]]:
        wanted = str(discord_id or "").strip()
        if not wanted:
            return []
        return [
            trophy
            for trophy in await self.all_trophies()
            if str(trophy.get("holder_discord_id") or "") == wanted
        ]
