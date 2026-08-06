from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout


LOGGER = logging.getLogger(__name__)

YAML_YUGI_BASE_URL = (
    "https://dawnbrandbots.github.io/"
    "yaml-yugi-limit-regulation"
)
YAML_YUGI_RAW_BASE_URL = (
    "https://raw.githubusercontent.com/"
    "DawnbrandBots/yaml-yugi-limit-regulation/master/data"
)
DEFAULT_SYNC_INTERVAL_SECONDS = 6 * 60 * 60
MINIMUM_SYNC_INTERVAL_SECONDS = 15 * 60
MAXIMUM_SYNC_INTERVAL_SECONDS = 24 * 60 * 60


class BanlistDataError(RuntimeError):
    """Erreur de lecture ou de validation du catalogue des banlists."""


class BanlistSyncError(RuntimeError):
    """Erreur de synchronisation d'une source distante."""


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _format_french_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return str(value or "")

    months = (
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    )
    return f"{parsed.day} {months[parsed.month - 1]} {parsed.year}"


def _format_french_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return str(value or "")

    parsed = parsed.astimezone(UTC)
    return (
        f"{_format_french_date(parsed.strftime('%Y-%m-%d'))} "
        f"à {parsed.strftime('%H:%M')} UTC"
    )


def _read_sync_interval() -> int:
    raw = os.getenv(
        "BANLIST_SYNC_INTERVAL_SECONDS",
        str(DEFAULT_SYNC_INTERVAL_SECONDS),
    )
    try:
        interval = int(raw)
    except (TypeError, ValueError):
        interval = DEFAULT_SYNC_INTERVAL_SECONDS

    return max(
        MINIMUM_SYNC_INTERVAL_SECONDS,
        min(MAXIMUM_SYNC_INTERVAL_SECONDS, interval),
    )


class BanlistService:
    """
    Charge le catalogue local et fusionne les données synchronisées.

    Les formats évolutifs utilisent l'API JSON YAML Yugi. La dernière copie
    valide est conservée dans ``web/data/banlists_runtime_cache.json`` afin que
    le site reste disponible lorsqu'une source distante est temporairement
    inaccessible.
    """

    def __init__(self, project_root: Path) -> None:
        self.data_path = project_root / "web" / "data" / "banlists.json"
        self.runtime_cache_path = (
            project_root
            / "web"
            / "data"
            / "banlists_runtime_cache.json"
        )
        self.sync_interval_seconds = _read_sync_interval()

        self._cached_signature: tuple[int, int] | None = None
        self._cached_payload: dict[str, Any] | None = None
        self._runtime_cache = self._load_runtime_cache()
        self._sync_lock = asyncio.Lock()
        self._sync_in_progress = False

    # ==========================================================
    # CHARGEMENT LOCAL ET FUSION
    # ==========================================================

    def _load_runtime_cache(self) -> dict[str, Any]:
        empty = {
            "schema_version": 1,
            "revision": "local",
            "last_attempt_at": "",
            "last_success_at": "",
            "errors": {},
            "formats": {},
        }
        if not self.runtime_cache_path.exists():
            return empty

        try:
            raw = json.loads(
                self.runtime_cache_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            LOGGER.warning(
                "Cache des banlists illisible : %s",
                self.runtime_cache_path,
            )
            return empty

        if not isinstance(raw, dict):
            return empty

        formats = raw.get("formats")
        if not isinstance(formats, dict):
            formats = {}

        errors = raw.get("errors")
        if not isinstance(errors, dict):
            errors = {}

        return {
            "schema_version": int(raw.get("schema_version") or 1),
            "revision": str(raw.get("revision") or "local"),
            "last_attempt_at": str(raw.get("last_attempt_at") or ""),
            "last_success_at": str(raw.get("last_success_at") or ""),
            "errors": errors,
            "formats": formats,
        }

    def _file_signature(self) -> tuple[int, int]:
        try:
            local_mtime = self.data_path.stat().st_mtime_ns
        except OSError as error:
            raise BanlistDataError(
                "Impossible de lire les informations du fichier des banlists."
            ) from error

        try:
            cache_mtime = self.runtime_cache_path.stat().st_mtime_ns
        except OSError:
            cache_mtime = 0

        return local_mtime, cache_mtime

    def load(self) -> dict[str, Any]:
        if not self.data_path.exists():
            raise BanlistDataError(
                f"Le fichier des banlists est introuvable : {self.data_path}"
            )

        signature = self._file_signature()
        if (
            self._cached_payload is not None
            and self._cached_signature == signature
        ):
            payload = deepcopy(self._cached_payload)
            payload["sync"]["in_progress"] = self._sync_in_progress
            return payload

        try:
            raw = json.loads(self.data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BanlistDataError(
                "Le fichier web/data/banlists.json est invalide."
            ) from error

        payload = self._validate(raw)
        self._runtime_cache = self._load_runtime_cache()
        payload = self._merge_runtime_data(payload)
        self._cached_payload = payload
        self._cached_signature = self._file_signature()

        result = deepcopy(payload)
        result["sync"]["in_progress"] = self._sync_in_progress
        return result

    def _merge_runtime_data(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        runtime_formats = self._runtime_cache.get("formats") or {}
        errors = self._runtime_cache.get("errors") or {}

        for item in payload["formats"]:
            provider = item.get("provider") or {}
            if provider.get("type") != "yaml_yugi":
                item["sync_state"] = "static"
                item["sync_state_label"] = "Liste historique ou manuelle"
                continue

            cached = runtime_formats.get(item["slug"])
            if isinstance(cached, dict) and cached.get("sections"):
                item["sections"] = deepcopy(cached["sections"])
                item["effective_date"] = str(
                    cached.get("effective_date")
                    or item.get("effective_date")
                    or ""
                )
                item["source_date"] = str(cached.get("source_date") or "")
                item["synced_at"] = str(cached.get("synced_at") or "")
                item["synced_at_label"] = _format_french_datetime(
                    item["synced_at"]
                )
                item["embedded_entry_count"] = int(
                    cached.get("entry_count") or 0
                )
                item["completeness_label"] = (
                    "Liste complète synchronisée automatiquement"
                )
                if item["slug"] in errors:
                    item["sync_state"] = "stale"
                    item["sync_state_label"] = (
                        "Dernière copie valide conservée"
                    )
                    item["sync_error"] = str(errors[item["slug"]])
                else:
                    item["sync_state"] = "ready"
                    item["sync_state_label"] = "Synchronisée automatiquement"
            else:
                item["sync_state"] = "pending"
                item["sync_state_label"] = "Synchronisation initiale en cours"
                if item["slug"] in errors:
                    item["sync_state"] = "error"
                    item["sync_state_label"] = "Source momentanément indisponible"
                    item["sync_error"] = str(errors[item["slug"]])

        # Les objets catégories conservent les mêmes instances de formats que
        # la liste principale. On les reconstruit après la fusion pour éviter
        # qu'une copie antérieure reste affichée dans le template.
        category_by_slug = {
            category["slug"]: {
                **category,
                "formats": [],
                "format_count": 0,
            }
            for category in payload["categories"]
        }
        for item in payload["formats"]:
            category = category_by_slug.get(item["family"])
            if category is not None:
                category["formats"].append(item)
                category["format_count"] += 1
        payload["categories"] = list(category_by_slug.values())

        last_success_at = str(
            self._runtime_cache.get("last_success_at") or ""
        )
        last_attempt_at = str(
            self._runtime_cache.get("last_attempt_at") or ""
        )
        error_count = len(errors)
        synced_count = len(runtime_formats)

        if synced_count and not error_count:
            status = "ready"
            status_label = "À jour"
        elif synced_count:
            status = "partial"
            status_label = "À jour avec une source en attente"
        elif error_count:
            status = "error"
            status_label = "Synchronisation indisponible"
        else:
            status = "pending"
            status_label = "Première synchronisation en attente"

        payload["revision"] = str(
            self._runtime_cache.get("revision") or "local"
        )
        payload["sync"] = {
            "status": status,
            "status_label": status_label,
            "in_progress": self._sync_in_progress,
            "interval_seconds": self.sync_interval_seconds,
            "interval_minutes": self.sync_interval_seconds // 60,
            "last_attempt_at": last_attempt_at,
            "last_attempt_at_label": _format_french_datetime(last_attempt_at),
            "last_success_at": last_success_at,
            "last_success_at_label": _format_french_datetime(last_success_at),
            "error_count": error_count,
            "errors": deepcopy(errors),
            "synced_format_count": synced_count,
        }
        return payload

    @staticmethod
    def _normalize_categories(raw: dict[str, Any]) -> list[dict[str, Any]]:
        configured = raw.get("categories")
        if configured is None:
            configured = []
        if not isinstance(configured, list):
            raise BanlistDataError("La clé 'categories' doit contenir une liste.")

        categories: list[dict[str, Any]] = []
        seen: set[str] = set()

        for index, entry in enumerate(configured):
            if not isinstance(entry, dict):
                raise BanlistDataError(
                    f"La catégorie n°{index + 1} doit être un objet."
                )

            slug = str(entry.get("slug") or "").strip().lower()
            name = str(entry.get("name") or "").strip()
            if not slug or not name:
                raise BanlistDataError(
                    f"La catégorie n°{index + 1} doit avoir un slug et un nom."
                )
            if slug in seen:
                raise BanlistDataError(f"Slug de catégorie dupliqué : {slug}")
            seen.add(slug)

            category = dict(entry)
            category["slug"] = slug
            category["name"] = name
            category.setdefault("short_name", name)
            category.setdefault("icon", "📚")
            category.setdefault("description", "")
            category.setdefault("order", (index + 1) * 10)
            category["formats"] = []
            category["format_count"] = 0
            categories.append(category)

        categories.sort(
            key=lambda item: (int(item.get("order") or 0), item["name"])
        )
        return categories

    @classmethod
    def _validate(cls, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise BanlistDataError("La racine de banlists.json doit être un objet.")

        formats = raw.get("formats")
        if not isinstance(formats, list):
            raise BanlistDataError("La clé 'formats' doit contenir une liste.")

        categories = cls._normalize_categories(raw)
        category_by_slug = {
            category["slug"]: category for category in categories
        }

        normalized: list[dict[str, Any]] = []
        seen_slugs: set[str] = set()

        for index, entry in enumerate(formats):
            if not isinstance(entry, dict):
                raise BanlistDataError(
                    f"Le format n°{index + 1} doit être un objet."
                )

            slug = str(entry.get("slug") or "").strip().lower()
            name = str(entry.get("name") or "").strip()

            if not slug or not name:
                raise BanlistDataError(
                    f"Le format n°{index + 1} doit avoir un slug et un nom."
                )

            if slug in seen_slugs:
                raise BanlistDataError(f"Slug de format dupliqué : {slug}")
            seen_slugs.add(slug)

            item = dict(entry)
            item["slug"] = slug
            item["name"] = name
            item["family"] = str(
                item.get("family") or "other"
            ).strip().lower()
            item.setdefault("authority", "reference")
            item.setdefault("kind", "banlist")
            item.setdefault("effective_date", "")
            item.setdefault("summary", "")
            item.setdefault("notice", "")
            item.setdefault("source_label", "Consulter la source")
            item.setdefault("source_url", "")
            item.setdefault("sections", [])
            item.setdefault("rules", [])
            item.setdefault("provider", None)

            sections = item.get("sections")
            if not isinstance(sections, list):
                raise BanlistDataError(
                    f"Les sections du format '{slug}' doivent former une liste."
                )

            total_entries = 0
            for section in sections:
                if not isinstance(section, dict):
                    continue
                entries = section.get("entries") or []
                if isinstance(entries, list):
                    total_entries += len(entries)

            item["embedded_entry_count"] = total_entries
            normalized.append(item)

            family = item["family"]
            category = category_by_slug.get(family)
            if category is None:
                category = {
                    "slug": family,
                    "name": str(
                        item.get("category_label") or family.title()
                    ),
                    "short_name": str(
                        item.get("category_label") or family.title()
                    ),
                    "icon": "📚",
                    "description": "Autres formats référencés par Hamtaro.",
                    "order": 999,
                    "formats": [],
                    "format_count": 0,
                }
                categories.append(category)
                category_by_slug[family] = category

            category["formats"].append(item)

        populated_categories: list[dict[str, Any]] = []
        for category in categories:
            category["format_count"] = len(category["formats"])
            if category["format_count"]:
                populated_categories.append(category)

        populated_categories.sort(
            key=lambda item: (int(item.get("order") or 0), item["name"])
        )

        return {
            "schema_version": int(raw.get("schema_version") or 1),
            "updated_at": str(raw.get("updated_at") or ""),
            "disclaimer": str(raw.get("disclaimer") or ""),
            "formats": normalized,
            "categories": populated_categories,
            "format_count": len(normalized),
            "category_count": len(populated_categories),
        }

    # ==========================================================
    # SYNCHRONISATION DISTANTE
    # ==========================================================

    async def periodic_sync(self) -> None:
        """Synchronise immédiatement, puis selon l'intervalle configuré."""

        while True:
            try:
                await self.synchronize()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "Erreur inattendue pendant la synchronisation des banlists."
                )

            await asyncio.sleep(self.sync_interval_seconds)

    async def synchronize(self) -> dict[str, Any]:
        if self._sync_lock.locked():
            return self.version_payload()

        async with self._sync_lock:
            self._sync_in_progress = True
            attempted_at = _utc_now_iso()
            try:
                catalog = self._validate(
                    json.loads(self.data_path.read_text(encoding="utf-8"))
                )
                providers = [
                    item
                    for item in catalog["formats"]
                    if (item.get("provider") or {}).get("type")
                    == "yaml_yugi"
                ]

                timeout = ClientTimeout(total=45, connect=15)
                headers = {
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                    "User-Agent": "Hamtaro-Banlists/2.0",
                }
                async with ClientSession(
                    timeout=timeout,
                    headers=headers,
                ) as session:
                    results = await asyncio.gather(
                        *(
                            self._synchronize_format(session, item)
                            for item in providers
                        ),
                        return_exceptions=True,
                    )

                current_formats = deepcopy(
                    self._runtime_cache.get("formats") or {}
                )
                errors: dict[str, str] = {}
                successes = 0

                for item, result in zip(providers, results, strict=True):
                    slug = item["slug"]
                    if isinstance(result, Exception):
                        errors[slug] = str(result)
                        LOGGER.warning(
                            "Synchronisation impossible pour %s : %s",
                            slug,
                            result,
                        )
                        continue

                    current_formats[slug] = result
                    successes += 1

                revision = self._calculate_revision(current_formats)
                cache = {
                    "schema_version": 1,
                    "revision": revision,
                    "last_attempt_at": attempted_at,
                    "last_success_at": (
                        attempted_at
                        if successes
                        else str(
                            self._runtime_cache.get("last_success_at") or ""
                        )
                    ),
                    "errors": errors,
                    "formats": current_formats,
                }
                self._runtime_cache = cache
                self._write_runtime_cache(cache)
                self._cached_payload = None
                self._cached_signature = None

                LOGGER.info(
                    "Banlists synchronisées : %s réussite(s), %s erreur(s), "
                    "prochaine vérification dans %s minute(s).",
                    successes,
                    len(errors),
                    self.sync_interval_seconds // 60,
                )
                return self.version_payload()
            finally:
                self._sync_in_progress = False

    async def _synchronize_format(
        self,
        session: ClientSession,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        provider = item.get("provider") or {}
        dataset = str(provider.get("dataset") or "").strip()
        mode = str(provider.get("mode") or "limit").strip().lower()
        if not dataset:
            raise BanlistSyncError(
                f"Le fournisseur du format {item['slug']} ne précise pas dataset."
            )

        vector_url = f"{YAML_YUGI_BASE_URL}/{dataset}/current.vector.json"
        vector = await self._fetch_json(session, vector_url)
        source_date = str(vector.get("date") or "").strip()
        if not source_date:
            raise BanlistSyncError(
                f"La source {dataset} ne fournit aucune date."
            )

        name_url = (
            f"{YAML_YUGI_BASE_URL}/{dataset}/{source_date}.name.json"
        )
        try:
            named = await self._fetch_json(session, name_url)
        except BanlistSyncError:
            fallback_url = (
                f"{YAML_YUGI_RAW_BASE_URL}/{dataset}/"
                f"{source_date}.name.json"
            )
            named = await self._fetch_json(session, fallback_url)
            name_url = fallback_url

        regulation = self._extract_regulation(named)
        if not regulation:
            raise BanlistSyncError(
                f"La liste {dataset} du {source_date} est vide."
            )

        if mode == "points":
            sections = self._build_points_sections(regulation)
        else:
            sections = self._build_limit_sections(regulation)

        entry_count = sum(
            len(section.get("entries") or []) for section in sections
        )
        return {
            "source_date": source_date,
            "effective_date": _format_french_date(source_date),
            "synced_at": _utc_now_iso(),
            "entry_count": entry_count,
            "sections": sections,
            "provider_url": name_url,
            "provider_name": "YAML Yugi Limit Regulation API",
        }

    @staticmethod
    async def _fetch_json(
        session: ClientSession,
        url: str,
    ) -> dict[str, Any]:
        separator = "&" if "?" in url else "?"
        request_url = f"{url}{separator}hamtaro={int(datetime.now(UTC).timestamp())}"
        try:
            async with session.get(request_url) as response:
                if response.status != 200:
                    raise BanlistSyncError(
                        f"HTTP {response.status} pour {url}"
                    )
                raw = await response.json(content_type=None)
        except BanlistSyncError:
            raise
        except Exception as error:
            raise BanlistSyncError(
                f"Impossible de joindre {url} : {error}"
            ) from error

        if not isinstance(raw, dict):
            raise BanlistSyncError(
                f"Réponse JSON inattendue pour {url}."
            )
        return raw

    @staticmethod
    def _extract_regulation(raw: dict[str, Any]) -> dict[str, int]:
        candidate = raw.get("regulation", raw)
        if not isinstance(candidate, dict):
            return {}

        result: dict[str, int] = {}
        for name, value in candidate.items():
            try:
                numeric_value = int(value)
            except (TypeError, ValueError):
                continue
            clean_name = str(name or "").strip()
            if clean_name:
                result[clean_name] = numeric_value
        return result

    @staticmethod
    def _build_limit_sections(
        regulation: dict[str, int],
    ) -> list[dict[str, Any]]:
        definitions = (
            (0, "Interdites"),
            (1, "Limitées"),
            (2, "Semi-limitées"),
        )
        sections: list[dict[str, Any]] = []

        for value, label in definitions:
            names = sorted(
                (
                    name
                    for name, current_value in regulation.items()
                    if current_value == value
                ),
                key=str.casefold,
            )
            if names:
                sections.append(
                    {
                        "label": label,
                        "entries": [{"name": name} for name in names],
                    }
                )

        other = sorted(
            (
                (name, value)
                for name, value in regulation.items()
                if value not in {0, 1, 2}
            ),
            key=lambda pair: (pair[1], pair[0].casefold()),
        )
        if other:
            sections.append(
                {
                    "label": "Autres restrictions",
                    "entries": [
                        {"name": name, "value": str(value)}
                        for name, value in other
                    ],
                }
            )
        return sections

    @staticmethod
    def _build_points_sections(
        regulation: dict[str, int],
    ) -> list[dict[str, Any]]:
        entries = [
            {
                "name": name,
                "value": f"{value} pt" if value == 1 else f"{value} pts",
                "points": value,
            }
            for name, value in regulation.items()
            if value > 0
        ]
        entries.sort(
            key=lambda entry: (
                -int(entry["points"]),
                str(entry["name"]).casefold(),
            )
        )
        for entry in entries:
            entry.pop("points", None)

        return [
            {
                "label": "Cartes avec points",
                "entries": entries,
            }
        ] if entries else []

    @staticmethod
    def _calculate_revision(formats: dict[str, Any]) -> str:
        serializable = {
            slug: {
                "source_date": item.get("source_date"),
                "sections": item.get("sections"),
            }
            for slug, item in sorted(formats.items())
            if isinstance(item, dict)
        }
        encoded = json.dumps(
            serializable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:20]

    def _write_runtime_cache(self, cache: dict[str, Any]) -> None:
        try:
            self.runtime_cache_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            temporary = self.runtime_cache_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(
                    cache,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.runtime_cache_path)
        except OSError:
            LOGGER.exception(
                "Impossible d'enregistrer le cache des banlists. "
                "La copie en mémoire reste utilisable jusqu'au redémarrage."
            )

    def version_payload(self) -> dict[str, Any]:
        return {
            "ok": True,
            "revision": str(
                self._runtime_cache.get("revision") or "local"
            ),
            "last_attempt_at": str(
                self._runtime_cache.get("last_attempt_at") or ""
            ),
            "last_success_at": str(
                self._runtime_cache.get("last_success_at") or ""
            ),
            "sync_in_progress": self._sync_in_progress,
            "interval_seconds": self.sync_interval_seconds,
            "error_count": len(
                self._runtime_cache.get("errors") or {}
            ),
        }
