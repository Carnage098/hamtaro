from __future__ import annotations

import asyncio
import base64
import hashlib
import html as html_lib
import json
import math
import os
import re
import sqlite3
import struct
import time
import unicodedata
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, quote_plus, unquote

import aiohttp


YGOPRODECK_API = "https://db.ygoprodeck.com/api/v7"
YGOPRODECK_SITE = "https://ygoprodeck.com"
CARDMARKET_SEARCH = "https://www.cardmarket.com/en/YuGiOh/Products/Search?searchString="
CARDMARKET_CARD_BASE = "https://www.cardmarket.com/en/YuGiOh/Cards/"
NEURON_SEARCH = (
    "https://www.db.yugioh-card.com/yugiohdb/card_search.action?ope=1&sess=1&rp=20&stype=1&othercon=2&request_locale=fr&keyword="
)
KONAMI_BANLIST_URL = "https://www.yugioh-card.com/eu/play/forbidden-and-limited-list/"
EXTRA_TYPES = {
    "Fusion Monster",
    "Link Monster",
    "Pendulum Effect Fusion Monster",
    "Synchro Monster",
    "Synchro Pendulum Effect Monster",
    "Synchro Tuner Monster",
    "XYZ Monster",
    "XYZ Pendulum Effect Monster",
}
QUERY_STOP_WORDS = {
    "deck", "decks", "meta", "tcg", "ocg", "pure", "pur", "budget", "standard",
    "optimal", "optimale", "version", "modern", "moderne", "engine", "base", "the",
    "and", "avec", "sans",
}

FREESPOT_PROFILES = {
    "auto": {"label": "Automatique", "description": "Suit d'abord les usages observés dans ce deck."},
    "handtraps": {"label": "Handtraps", "description": "Favorise les handtraps génériques réellement observées."},
    "going_second": {"label": "Going second", "description": "Favorise board breakers et removals génériques observés."},
    "traps_control": {"label": "Pièges / contrôle", "description": "Favorise les Pièges et interactions génériques observés."},
    "spells": {"label": "Magies génériques", "description": "Favorise les Magies génériques de consistance ou d'impact observées."},
    "budget_staples": {"label": "Staples budget", "description": "Favorise les options génériques fréquentes et moins chères quand le prix est connu."},
}

FREESPOT_CATEGORY_LABELS = {
    "handtraps": "Handtraps",
    "board_breakers": "Board breakers",
    "traps": "Pièges génériques",
    "spells": "Magies génériques",
    "interactions": "Interactions génériques",
    "generic": "Autres staples / flex",
}


@dataclass(slots=True)
class DeckSample:
    title: str
    url: str
    main: list[int]
    extra: list[int]
    side: list[int]
    is_tournament: bool
    published: str | None
    placement: str | None
    weight: float
    fingerprint: str
    format_name: str = "unknown"


class DeckBuilderService:
    """Moteur autonome de la page Générateur de decks Hamtaro.

    Le service ne dépend pas des pages /decks ou /archetypes du site. Les données
    externes sont isolées derrière quelques méthodes afin de pouvoir remplacer ou
    ajouter des fournisseurs plus tard sans refaire l'interface.

    Règles importantes :
    * Main / Extra / Side sont analysés séparément ;
    * les doublons de decklists sont dédupliqués avant les statistiques ;
    * les tournois récents pèsent davantage ;
    * une quantité n'est jamais inventée au-delà de ce qui a été observé ;
    * un prix absent reste "inconnu" et n'est jamais transformé en 0 € ;
    * les listes invalides ne sont pas utilisées pour calculer des fréquences.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parent.parent
        default_cache = self.project_root / "data" / "deck_builder_cache.sqlite3"
        self.cache_path = Path(os.getenv("DECK_BUILDER_CACHE_PATH", str(default_cache)))
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.request_timeout = max(5, int(os.getenv("DECK_BUILDER_HTTP_TIMEOUT", "14")))
        self.cache_hours = max(6, int(os.getenv("DECK_BUILDER_CACHE_HOURS", "24")))
        self.search_cache_hours = max(3, int(os.getenv("DECK_BUILDER_SEARCH_CACHE_HOURS", "12")))
        self.max_decks = min(60, max(6, int(os.getenv("DECK_BUILDER_MAX_DECKS", "32"))))
        self.card_language = os.getenv("DECK_BUILDER_CARD_LANGUAGE", "fr").strip().casefold() or "fr"
        if self.card_language not in {"en", "fr", "de", "it", "pt"}:
            self.card_language = "fr"
        default_images = self.project_root / "data" / "deck_builder_images"
        self.image_cache_path = Path(os.getenv("DECK_BUILDER_IMAGE_CACHE_PATH", str(default_images)))
        self.image_cache_path.mkdir(parents=True, exist_ok=True)
        self._last_card_fetch_dates: list[str] = []
        self.cache_namespace = "v86"
        self._last_discovery_debug: dict[str, Any] = {}
        self.user_agent = os.getenv(
            "DECK_BUILDER_USER_AGENT",
            "HamtaroDeckBuilder/8.6 (+public Yu-Gi-Oh TCG deck assistant)",
        )
        self._init_db()

    # ------------------------------------------------------------------
    # SQLite cache + price snapshots
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.cache_path, timeout=8)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with closing(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS deck_builder_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'json',
                    fetched_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deck_builder_queries (
                    query_key TEXT PRIMARY KEY,
                    display_query TEXT NOT NULL,
                    last_seen_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deck_builder_price_history (
                    card_id INTEGER NOT NULL,
                    price_date TEXT NOT NULL,
                    price_eur REAL NOT NULL,
                    PRIMARY KEY(card_id, price_date)
                );
                CREATE INDEX IF NOT EXISTS idx_deck_builder_price_history_date
                    ON deck_builder_price_history(price_date);

                CREATE TABLE IF NOT EXISTS deck_builder_catalog (
                    deck_key TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'to_enrich',
                    tcg_samples INTEGER NOT NULL DEFAULT 0,
                    last_success_at INTEGER,
                    last_attempt_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_deck_builder_catalog_status
                    ON deck_builder_catalog(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS deck_builder_sample_library (
                    deck_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    learned_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL,
                    PRIMARY KEY(deck_key, fingerprint)
                );
                CREATE INDEX IF NOT EXISTS idx_deck_builder_sample_library_seen
                    ON deck_builder_sample_library(deck_key, last_seen_at DESC);
                """
            )
            # Garde le cache borné : les réponses expirées très anciennes ne servent plus,
            # tandis que 180 jours de snapshots suffisent pour les tendances affichées.
            now = int(time.time())
            db.execute("DELETE FROM deck_builder_cache WHERE expires_at < ?", (now - 7 * 86400,))
            db.execute(
                "DELETE FROM deck_builder_price_history WHERE price_date < ?",
                ((date.today() - timedelta(days=180)).isoformat(),),
            )
            db.commit()

    @staticmethod
    def _query_key(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).casefold()

    def _cache_get_sync(self, key: str) -> tuple[str, str, int] | None:
        now = int(time.time())
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT payload, content_type, fetched_at FROM deck_builder_cache "
                "WHERE cache_key = ? AND expires_at > ?",
                (key, now),
            ).fetchone()
        if not row:
            return None
        return str(row["payload"]), str(row["content_type"]), int(row["fetched_at"])

    def _cache_set_sync(self, key: str, payload: str, content_type: str, ttl: int) -> None:
        now = int(time.time())
        with closing(self._connect()) as db:
            db.execute(
                """
                INSERT INTO deck_builder_cache(cache_key, payload, content_type, fetched_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload = excluded.payload,
                    content_type = excluded.content_type,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                """,
                (key, payload, content_type, now, now + ttl),
            )
            db.commit()

    def _remember_query_sync(self, query: str) -> None:
        key = self._query_key(query)
        if not key:
            return
        with closing(self._connect()) as db:
            db.execute(
                """
                INSERT INTO deck_builder_queries(query_key, display_query, last_seen_at)
                VALUES (?, ?, ?)
                ON CONFLICT(query_key) DO UPDATE SET
                    display_query = excluded.display_query,
                    last_seen_at = excluded.last_seen_at
                """,
                (key, query.strip(), int(time.time())),
            )
            db.commit()

    def _recent_queries_sync(self, query: str, limit: int = 8) -> list[str]:
        key = self._query_key(query)
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT display_query FROM deck_builder_queries "
                "WHERE query_key LIKE ? ORDER BY last_seen_at DESC LIMIT ?",
                (f"%{key}%", limit),
            ).fetchall()
        return [str(row["display_query"]) for row in rows]


    @staticmethod
    def _deck_identity(value: str) -> str:
        """Identité tolérante à la ponctuation pour D/D, D/D/D, P.U.N.K., etc."""
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        normalized = normalized.encode("ascii", "ignore").decode("ascii").casefold()
        return re.sub(r"[^a-z0-9]+", "", normalized)

    @classmethod
    def _query_variants(cls, query: str) -> list[str]:
        clean = re.sub(r"\s+", " ", str(query or "")).strip()
        if not clean:
            return []
        identity = cls._deck_identity(clean)
        variants = [clean]
        special = {
            "dd": ["D/D", "D/D/D", "DDD"],
            "ddd": ["D/D/D", "D/D", "DDD"],
            "punk": ["P.U.N.K.", "PUNK", "P.U.N.K"],
            "blueeyes": ["Blue-Eyes", "Blue Eyes"],
            "redarchfiend": ["Red Dragon Archfiend", "RDA"],
        }
        variants.extend(special.get(identity, []))
        punctuation_light = re.sub(r"[./_\\-]+", " ", clean)
        punctuation_light = re.sub(r"\s+", " ", punctuation_light).strip()
        if punctuation_light and punctuation_light.casefold() != clean.casefold():
            variants.append(punctuation_light)
        compact = re.sub(r"[^A-Za-z0-9]+", "", clean)
        if len(compact) >= 3:
            variants.append(compact)
        result: list[str] = []
        seen: set[str] = set()
        for value in variants:
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                result.append(value)
        return result[:8]

    def _catalog_upsert_sync(
        self,
        query: str,
        *,
        canonical_name: str | None = None,
        aliases: Iterable[str] = (),
        sample_count: int | None = None,
        success: bool = False,
    ) -> None:
        canonical = re.sub(r"\s+", " ", str(canonical_name or query or "")).strip()
        if not canonical:
            return
        deck_key = self._deck_identity(canonical) or self._query_key(canonical)
        now = int(time.time())
        alias_values = {re.sub(r"\s+", " ", str(v or "")).strip() for v in aliases}
        alias_values.add(re.sub(r"\s+", " ", str(query or "")).strip())
        alias_values.discard("")
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT aliases_json, tcg_samples, last_success_at FROM deck_builder_catalog WHERE deck_key = ?",
                (deck_key,),
            ).fetchone()
            existing_aliases: set[str] = set()
            existing_count = 0
            last_success = None
            if row:
                try:
                    existing_aliases.update(json.loads(str(row["aliases_json"] or "[]")))
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
                existing_count = int(row["tcg_samples"] or 0)
                last_success = row["last_success_at"]
            existing_aliases.update(alias_values)
            count = max(existing_count, int(sample_count or 0))
            if success and count >= 5:
                status = "confirmed"
            elif success and count > 0:
                status = "partial"
            else:
                status = "to_enrich"
            db.execute(
                """
                INSERT INTO deck_builder_catalog(
                    deck_key, canonical_name, aliases_json, status, tcg_samples,
                    last_success_at, last_attempt_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deck_key) DO UPDATE SET
                    canonical_name = excluded.canonical_name,
                    aliases_json = excluded.aliases_json,
                    status = CASE
                        WHEN excluded.status = 'confirmed' THEN 'confirmed'
                        WHEN deck_builder_catalog.status = 'confirmed' THEN 'confirmed'
                        WHEN excluded.status = 'partial' THEN 'partial'
                        ELSE deck_builder_catalog.status
                    END,
                    tcg_samples = MAX(deck_builder_catalog.tcg_samples, excluded.tcg_samples),
                    last_success_at = COALESCE(excluded.last_success_at, deck_builder_catalog.last_success_at),
                    last_attempt_at = excluded.last_attempt_at,
                    updated_at = excluded.updated_at
                """,
                (
                    deck_key,
                    canonical,
                    json.dumps(sorted(existing_aliases), ensure_ascii=False),
                    status,
                    count,
                    now if success else last_success,
                    now,
                    now,
                ),
            )
            db.commit()

    def _catalog_resolve_sync(self, query: str) -> tuple[str | None, list[str]]:
        identity = self._deck_identity(query)
        key = self._query_key(query)
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT canonical_name, aliases_json FROM deck_builder_catalog ORDER BY updated_at DESC LIMIT 1000"
            ).fetchall()
        for row in rows:
            canonical = str(row["canonical_name"] or "").strip()
            aliases = []
            try:
                aliases = list(json.loads(str(row["aliases_json"] or "[]")))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            candidates = [canonical, *aliases]
            if any(self._deck_identity(value) == identity for value in candidates if value):
                return canonical, [str(value) for value in aliases if value]
            if any(self._query_key(value) == key for value in candidates if value):
                return canonical, [str(value) for value in aliases if value]
        return None, []

    def _store_samples_sync(self, query: str, samples: Iterable[DeckSample]) -> None:
        values = list(samples)
        if not values:
            return
        canonical, aliases = self._catalog_resolve_sync(query)
        canonical = canonical or re.sub(r"\s+", " ", str(query or "")).strip()
        deck_key = self._deck_identity(canonical) or self._query_key(canonical)
        now = int(time.time())
        rows = []
        for sample in values:
            payload = {
                "title": sample.title,
                "url": sample.url,
                "main": sample.main,
                "extra": sample.extra,
                "side": sample.side,
                "is_tournament": sample.is_tournament,
                "published": sample.published,
                "placement": sample.placement,
                "weight": sample.weight,
                "fingerprint": sample.fingerprint,
                "format_name": sample.format_name,
            }
            rows.append((deck_key, sample.fingerprint, json.dumps(payload, ensure_ascii=False), now, now))
        with closing(self._connect()) as db:
            db.executemany(
                """
                INSERT INTO deck_builder_sample_library(deck_key, fingerprint, payload, learned_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(deck_key, fingerprint) DO UPDATE SET
                    payload = excluded.payload,
                    last_seen_at = excluded.last_seen_at
                """,
                rows,
            )
            db.commit()
        self._catalog_upsert_sync(
            query,
            canonical_name=canonical,
            aliases=[*aliases, *self._query_variants(query)],
            sample_count=len(values),
            success=True,
        )

    def _load_samples_sync(self, query: str, limit: int = 60) -> list[DeckSample]:
        canonical, _aliases = self._catalog_resolve_sync(query)
        canonical = canonical or query
        deck_key = self._deck_identity(canonical) or self._query_key(canonical)
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT payload FROM deck_builder_sample_library WHERE deck_key = ? ORDER BY last_seen_at DESC LIMIT ?",
                (deck_key, int(limit)),
            ).fetchall()
        result: list[DeckSample] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload"]))
                result.append(DeckSample(
                    title=str(payload.get("title") or "Deck appris"),
                    url=str(payload.get("url") or ""),
                    main=[int(x) for x in payload.get("main") or []],
                    extra=[int(x) for x in payload.get("extra") or []],
                    side=[int(x) for x in payload.get("side") or []],
                    is_tournament=bool(payload.get("is_tournament")),
                    published=payload.get("published"),
                    placement=payload.get("placement"),
                    weight=float(payload.get("weight") or 1.0),
                    fingerprint=str(payload.get("fingerprint") or ""),
                    format_name=str(payload.get("format_name") or "tcg"),
                ))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    def _catalog_stats_sync(self) -> dict[str, int]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS c FROM deck_builder_catalog GROUP BY status"
            ).fetchall()
            sample_count = db.execute("SELECT COUNT(*) FROM deck_builder_sample_library").fetchone()[0]
        counts = {str(row["status"]): int(row["c"] or 0) for row in rows}
        return {
            "decks_total": sum(counts.values()),
            "confirmed": counts.get("confirmed", 0),
            "partial": counts.get("partial", 0),
            "to_enrich": counts.get("to_enrich", 0),
            "samples_saved": int(sample_count or 0),
        }

    def _catalog_suggestions_sync(self, query: str, limit: int = 12) -> list[str]:
        key = self._query_key(query)
        identity = self._deck_identity(query)
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT canonical_name, aliases_json FROM deck_builder_catalog ORDER BY updated_at DESC LIMIT 1000"
            ).fetchall()
        values: list[str] = []
        for row in rows:
            canonical = str(row["canonical_name"] or "").strip()
            aliases = []
            try:
                aliases = list(json.loads(str(row["aliases_json"] or "[]")))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            haystack = " ".join([canonical, *map(str, aliases)]).casefold()
            identities = [self._deck_identity(value) for value in [canonical, *aliases] if value]
            if not key or key in haystack or (identity and any(identity in item or item in identity for item in identities if item)):
                if canonical and canonical not in values:
                    values.append(canonical)
            if len(values) >= limit:
                break
        return values

    def _store_price_snapshots_sync(
        self, cards: Iterable[dict[str, Any]], snapshot_date: str | None = None
    ) -> None:
        today = snapshot_date or date.today().isoformat()
        rows: list[tuple[int, str, float]] = []
        for card in cards:
            price = self._price(card)
            if price is None:
                continue
            try:
                card_id = int(card.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if card_id > 0:
                rows.append((card_id, today, price))
        if not rows:
            return
        with closing(self._connect()) as db:
            db.executemany(
                """
                INSERT INTO deck_builder_price_history(card_id, price_date, price_eur)
                VALUES (?, ?, ?)
                ON CONFLICT(card_id, price_date) DO UPDATE SET price_eur = excluded.price_eur
                """,
                rows,
            )
            db.commit()

    def _price_trends_sync(self, card_ids: Iterable[int]) -> dict[int, dict[str, float | None]]:
        ids = sorted({int(value) for value in card_ids if int(value) > 0})
        if not ids:
            return {}
        today = date.today()
        targets = {7: (today - timedelta(days=7)).isoformat(), 30: (today - timedelta(days=30)).isoformat()}
        result: dict[int, dict[str, float | None]] = {card_id: {"7d": None, "30d": None} for card_id in ids}
        with closing(self._connect()) as db:
            for card_id in ids:
                for days, target in targets.items():
                    row = db.execute(
                        "SELECT price_eur FROM deck_builder_price_history "
                        "WHERE card_id = ? AND price_date <= ? ORDER BY price_date DESC LIMIT 1",
                        (card_id, target),
                    ).fetchone()
                    if row:
                        result[card_id][f"{days}d"] = float(row["price_eur"])
        return result

    async def _cache_get(self, key: str) -> tuple[str, str, int] | None:
        return await asyncio.to_thread(self._cache_get_sync, key)

    async def _cache_set(self, key: str, payload: str, content_type: str, ttl: int) -> None:
        await asyncio.to_thread(self._cache_set_sync, key, payload, content_type, ttl)

    async def remember_query(self, query: str) -> None:
        await asyncio.to_thread(self._remember_query_sync, query)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    async def _fetch_text(self, url: str, *, ttl_hours: int | None = None) -> str:
        ttl = int((ttl_hours or self.cache_hours) * 3600)
        key = f"text:{self.cache_namespace}:{url}"
        cached = await self._cache_get(key)
        if cached:
            return cached[0]
        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        headers = {"User-Agent": self.user_agent, "Accept-Language": "en-US,en;q=0.8"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                response.raise_for_status()
                text = await response.text(errors="replace")
        await self._cache_set(key, text, "text", ttl)
        return text

    async def _fetch_json(self, url: str, *, ttl_hours: int | None = None) -> Any:
        ttl = int((ttl_hours or self.cache_hours) * 3600)
        key = f"json:{url}"
        cached = await self._cache_get(key)
        if cached:
            return json.loads(cached[0])
        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        await self._cache_set(key, json.dumps(payload, ensure_ascii=False), "json", ttl)
        return payload

    async def _fetch_json_with_meta(
        self, url: str, *, ttl_hours: int | None = None
    ) -> tuple[Any, int]:
        """Comme _fetch_json, mais renvoie la vraie date de récupération de la source.

        Cela évite d'afficher "mis à jour aujourd'hui" quand on relit seulement une
        réponse conservée dans le cache local.
        """
        ttl = int((ttl_hours or self.cache_hours) * 3600)
        key = f"json:{url}"
        cached = await self._cache_get(key)
        if cached:
            return json.loads(cached[0]), int(cached[2])
        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        fetched_at = int(time.time())
        await self._cache_set(key, json.dumps(payload, ensure_ascii=False), "json", ttl)
        return payload, fetched_at

    async def card_image_path(self, card_id: int) -> Path | None:
        """Télécharge une petite image une seule fois puis la sert depuis Hamtaro."""
        try:
            card_id = int(card_id)
        except (TypeError, ValueError):
            return None
        if card_id <= 0:
            return None
        target = self.image_cache_path / f"{card_id}.jpg"
        if target.is_file() and target.stat().st_size > 500:
            return target
        url = f"https://images.ygoprodeck.com/images/cards_small/{card_id}.jpg"
        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        headers = {"User-Agent": self.user_agent, "Accept": "image/jpeg,image/*;q=0.8"}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status != 200:
                        return None
                    body = await response.read()
                    if len(body) < 500:
                        return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None
        temp = target.with_name(f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
        temp.write_bytes(body)
        try:
            temp.replace(target)
        except FileNotFoundError:
            # Une requête concurrente a peut-être déjà gagné la course.
            pass
        finally:
            if temp.exists():
                temp.unlink(missing_ok=True)
        return target

    # ------------------------------------------------------------------
    # YDKE + decklist parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_ydke_segment(segment: str) -> list[int]:
        if not segment:
            return []
        padding = "=" * ((4 - len(segment) % 4) % 4)
        raw = base64.b64decode(segment + padding)
        usable = len(raw) - (len(raw) % 4)
        if usable <= 0:
            return []
        return [value[0] for value in struct.iter_unpack("<I", raw[:usable])]

    @staticmethod
    def _encode_ydke_segment(values: Iterable[int]) -> str:
        raw = b"".join(struct.pack("<I", int(value)) for value in values)
        return base64.b64encode(raw).decode("ascii").rstrip("=")

    @classmethod
    def decode_ydke(cls, uri: str) -> tuple[list[int], list[int], list[int]]:
        value = html_lib.unescape(unquote(uri)).strip()
        if not value.startswith("ydke://"):
            raise ValueError("Lien YDKE invalide")
        parts = value[7:].split("!")
        if len(parts) < 3:
            raise ValueError("Lien YDKE incomplet")
        return (
            cls._decode_ydke_segment(parts[0]),
            cls._decode_ydke_segment(parts[1]),
            cls._decode_ydke_segment(parts[2]),
        )

    @classmethod
    def encode_ydke(cls, main: Iterable[int], extra: Iterable[int], side: Iterable[int]) -> str:
        return "ydke://{}!{}!{}!".format(
            cls._encode_ydke_segment(main),
            cls._encode_ydke_segment(extra),
            cls._encode_ydke_segment(side),
        )

    @staticmethod
    def _extract_deck_links(body: str) -> list[str]:
        decoded = html_lib.unescape(body).replace("\\/", "/")
        patterns = [
            r'href=["\'](?:https://ygoprodeck\.com)?(/deck/[a-zA-Z0-9%_./?&=+~-]+-\d+)["\']',
            r'https://ygoprodeck\.com(/deck/[a-zA-Z0-9%_./?&=+~-]+-\d+)',
        ]
        found: list[str] = []
        seen: set[str] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, decoded, flags=re.IGNORECASE):
                path = unquote(match.group(1)).split("?")[0]
                url = f"{YGOPRODECK_SITE}{path}"
                if url not in seen:
                    seen.add(url)
                    found.append(url)
        return found

    @staticmethod
    def _query_components(query: str, *, limit: int = 10) -> list[str]:
        """Découpe un nom communautaire/hybride en recherches utiles sans table dédiée.

        Exemples : ``Vanquish Soul K9`` -> ``Vanquish Soul``, ``Soul K9``,
        ``Vanquish``, ``K9``. Les variantes ponctuées (D/D, P.U.N.K.) restent
        prises en charge par :meth:`_query_variants`.
        """
        clean = re.sub(r"\s+", " ", str(query or "")).strip()
        if not clean:
            return []
        normalized = unicodedata.normalize("NFKD", clean)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        words = [w for w in re.split(r"[^A-Za-z0-9]+", normalized) if w]
        words = [w for w in words if w.casefold() not in QUERY_STOP_WORDS]
        found: list[str] = []
        seen: set[str] = set()

        def add(value: str) -> None:
            value = re.sub(r"\s+", " ", value).strip()
            key = value.casefold()
            if not value or key in seen:
                return
            # Les tokens d'une seule lettre génèrent énormément de faux positifs.
            if len(value) == 1 and not value.isdigit():
                return
            seen.add(key)
            found.append(value)

        add(clean)
        # D'abord les groupes longs : ils sont plus discriminants.
        for width in (3, 2):
            if len(words) < width:
                continue
            for i in range(0, len(words) - width + 1):
                add(" ".join(words[i:i + width]))
        for word in words:
            if len(word) >= 3 or any(ch.isdigit() for ch in word):
                add(word)
        return found[:max(1, limit)]

    @classmethod
    def _archetype_candidates_from_query(cls, query: str, names: Iterable[str], *, limit: int = 8) -> list[str]:
        """Retrouve les archétypes contenus dans un nom de deck hybride.

        Cette résolution est volontairement tolérante à la ponctuation et ne
        dépend d'aucune liste codée en dur.
        """
        qid = cls._deck_identity(query)
        components = cls._query_components(query, limit=12)
        component_ids = {cls._deck_identity(value) for value in components if value}
        scored: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for raw in names:
            name = re.sub(r"\s+", " ", str(raw or "")).strip()
            nid = cls._deck_identity(name)
            if not name or not nid or nid in seen:
                continue
            score = 0
            if nid == qid:
                score = 200
            elif nid in component_ids:
                score = 180
            elif qid and len(nid) >= 2 and nid in qid:
                score = 150 + min(25, len(nid))
            elif qid and len(qid) >= 3 and qid in nid:
                score = 120
            else:
                # Petit score par chevauchement de mots, utile pour les noms
                # communautaires sans créer un fuzzy-match trop permissif.
                ntokens = {cls._deck_identity(tok) for tok in re.split(r"[^A-Za-z0-9]+", name) if len(tok) >= 2}
                overlap = len(ntokens & component_ids)
                if overlap:
                    score = 70 + overlap * 15
            if score:
                seen.add(nid)
                scored.append((score, len(nid), name))
        scored.sort(key=lambda item: (-item[0], -item[1], item[2].casefold()))
        return [name for _score, _length, name in scored[:max(1, limit)]]

    async def _card_name_resolution(self, query: str, *, limit_cards: int = 10) -> dict[str, Any]:
        """Résout un nom libre vers des cartes/archétypes TCG.

        C'est le dernier maillon qui permet à un boss monster, un nom de moteur
        ou un nom communautaire de redevenir une recherche de deck structurée.
        """
        phrases: list[str] = []
        seen_phrases: set[str] = set()
        for value in [*self._query_variants(query), *self._query_components(query, limit=10)]:
            key = value.casefold()
            if value and key not in seen_phrases:
                seen_phrases.add(key)
                phrases.append(value)
        phrases = phrases[:6]
        payloads = await asyncio.gather(
            *(self._fetch_json(
                f"{YGOPRODECK_API}/cardinfo.php?fname={quote_plus(value)}&misc=yes&format=tcg",
                ttl_hours=self.cache_hours,
            ) for value in phrases),
            return_exceptions=True,
        )
        cards_by_id: dict[int, dict[str, Any]] = {}
        archetypes: list[str] = []
        seen_arch: set[str] = set()
        for payload in payloads:
            if isinstance(payload, Exception) or not isinstance(payload, dict):
                continue
            for card in payload.get("data") or []:
                if not isinstance(card, dict):
                    continue
                try:
                    cid = int(card.get("id") or 0)
                except (TypeError, ValueError):
                    cid = 0
                if cid > 0:
                    cards_by_id.setdefault(cid, card)
                arch = str(card.get("archetype") or "").strip()
                akey = self._deck_identity(arch)
                if arch and akey and akey not in seen_arch:
                    seen_arch.add(akey)
                    archetypes.append(arch)
        cards = list(cards_by_id.values())
        qid = self._deck_identity(query)
        cards.sort(
            key=lambda card: (
                0 if qid and qid in self._deck_identity(str(card.get("name") or "")) else 1,
                len(str(card.get("name") or "")),
            )
        )
        return {
            "phrases": phrases,
            "cards": cards[:max(1, limit_cards)],
            "archetypes": archetypes[:8],
        }

    async def _universal_discovery_urls(
        self, query: str, archetype_names: Iterable[str], *, card_limit: int = 8
    ) -> tuple[dict[str, Any], list[str]]:
        """Dernier étage de découverte, indépendant d'un archétype exact.

        Il combine décomposition d'un nom hybride, résolution par cartes TCG et
        pages d'archétypes. Toutes les URLs restent des recherches publiques
        YGOPRODeck ; les decklists sont ensuite revalidées carte-par-carte TCG.
        """
        components = self._query_components(query, limit=10)
        candidate_arch = self._archetype_candidates_from_query(query, archetype_names, limit=8)
        resolution = await self._card_name_resolution(query, limit_cards=card_limit)
        for arch in resolution.get("archetypes") or []:
            if self._deck_identity(arch) not in {self._deck_identity(v) for v in candidate_arch}:
                candidate_arch.append(arch)
        candidate_arch = candidate_arch[:10]

        urls: list[str] = []
        seen: set[str] = set()
        def add(url: str) -> None:
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        # Recherches textuelles : les deux routes sont gardées car le rendu du site
        # a déjà changé au fil du temps.
        for phrase in [*candidate_arch, *components][:12]:
            encoded = quote_plus(phrase)
            add(f"{YGOPRODECK_SITE}/deck-search.php?name={encoded}&offset=0&tournament=tier-2")
            add(f"{YGOPRODECK_SITE}/deck-search.php?name={encoded}&offset=0")
            add(f"{YGOPRODECK_SITE}/deck-search/?name={encoded}&offset=0&tournament=tier-2")
            for category_url in await self._category_urls_for_query(phrase):
                add(category_url)

        card_names: list[str] = []
        for card in resolution.get("cards") or []:
            name = str(card.get("name") or "").strip()
            if not name:
                continue
            card_names.append(name)
            encoded = quote_plus(name) + "%7C"
            add(f"{YGOPRODECK_SITE}/deck-search.php?cardcode={encoded}&offset=0&tournament=tier-2")
            add(f"{YGOPRODECK_SITE}/deck-search.php?cardcode={encoded}&offset=0")

        debug = {
            "components": components,
            "candidate_archetypes": candidate_arch,
            "resolved_card_names": card_names[:card_limit],
            "resolution_phrases": resolution.get("phrases") or [],
        }
        return debug, urls[:40]

    @staticmethod
    def _slugify_archetype(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")

    async def _category_urls_for_query(self, query: str) -> list[str]:
        """Retourne jusqu'à 3 pages d'archétypes YGOPRODeck pertinentes.

        Les pages /category/type/... sont rendues côté serveur et constituent un
        chemin de découverte plus robuste que la page de recherche dynamique.
        """
        clean = re.sub(r"\s+", " ", str(query or "")).strip()
        if not clean:
            return []
        urls: list[str] = []

        # V8.5 : YGOPRODeck encode les noms d'archétypes dans le segment de chemin
        # (ex. ``radiant%20typhoon``), il ne les slugifie pas forcément avec des
        # tirets. On tente donc toujours d'abord le nom recherché tel quel, encodé
        # pour une URL, même si l'endpoint /archetypes.php est temporairement indisponible.
        direct = quote(clean.casefold(), safe="")
        if direct:
            urls.append(f"{YGOPRODECK_SITE}/category/type/{direct}")

        try:
            payload = await self._fetch_json(f"{YGOPRODECK_API}/archetypes.php", ttl_hours=72)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return urls
        qkey = clean.casefold()
        scored: list[tuple[int, int, str]] = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("archetype_name") or "").strip()
            if not name:
                continue
            nkey = name.casefold()
            score = None
            if nkey == qkey:
                score = 100
            elif nkey in qkey:
                score = 80
            elif qkey in nkey:
                score = 60
            if score is not None:
                scored.append((score, len(name), name))
        scored.sort(reverse=True)
        for _score, _length, name in scored[:3]:
            encoded = quote(name.casefold(), safe="")
            if encoded:
                candidate = f"{YGOPRODECK_SITE}/category/type/{encoded}"
                if candidate not in urls:
                    urls.append(candidate)
            # Ancien format conservé en dernier recours pour les routes qui
            # accepteraient encore une forme slugifiée.
            slug = self._slugify_archetype(name)
            if slug:
                candidate = f"{YGOPRODECK_SITE}/category/type/{slug}"
                if candidate not in urls:
                    urls.append(candidate)
        return urls[:6]


    @staticmethod
    def _signature_card_names(cards: Iterable[dict[str, Any]], query: str, *, limit: int = 4) -> list[str]:
        """Choisit quelques cartes-signatures pour découvrir des decks mal indexés par nom.

        Le but n'est pas d'inventer un core : ces noms servent uniquement à rechercher
        des decklists contenant réellement des cartes de l'archétype demandé.
        """
        qid = DeckBuilderService._deck_identity(query)
        scored: list[tuple[int, str]] = []
        seen: set[str] = set()
        for card in cards:
            name = str(card.get("_source_name") or card.get("name") or "").strip()
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            archetype = str(card.get("archetype") or "").strip()
            nid = DeckBuilderService._deck_identity(name)
            aid = DeckBuilderService._deck_identity(archetype)
            score = 0
            if qid and aid == qid:
                score += 120
            elif qid and aid and (qid in aid or aid in qid):
                score += 95
            if qid and qid in nid:
                score += 70
            # Les monstres propres à l'archétype donnent généralement une recherche
            # plus discriminante qu'une magie/piège générique portant un mot proche.
            ctype = str(card.get("type") or "")
            if "Monster" in ctype:
                score += 15
            if "Tuner" in ctype or "Synchro" in ctype or "Xyz" in ctype or "Link" in ctype or "Fusion" in ctype:
                score += 5
            if score > 0:
                scored.append((score, name))
        scored.sort(key=lambda item: (-item[0], len(item[1]), item[1].casefold()))
        return [name for _score, name in scored[:max(1, limit)]]

    async def _signature_discovery_urls(self, query: str, *, limit: int = 4) -> tuple[list[str], list[str]]:
        """Construit des recherches YGOPRODeck par cartes-signatures.

        Ce fallback couvre les familles dont le nom de deck est mal indexé (ex.
        Rose Dragon) tout en restant universel : aucune decklist n'est codée en dur.
        """
        cards = await self.archetype_cards(query)
        if not cards:
            # Dernier secours : cartes TCG dont le nom contient la recherche.
            url = f"{YGOPRODECK_API}/cardinfo.php?fname={quote_plus(query)}&misc=yes&format=tcg"
            try:
                payload = await self._fetch_json(url, ttl_hours=self.cache_hours)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                payload = {}
            cards = list(payload.get("data") or []) if isinstance(payload, dict) else []
        names = self._signature_card_names(cards, query, limit=limit)
        urls: list[str] = []
        for name in names:
            encoded = quote_plus(name) + "%7C"
            # deck-search.php reste utile même si /deck-search/ change de rendu.
            urls.append(f"{YGOPRODECK_SITE}/deck-search.php?cardcode={encoded}&offset=0&tournament=tier-2")
            urls.append(f"{YGOPRODECK_SITE}/deck-search.php?cardcode={encoded}&offset=0")
        return names, urls

    @staticmethod
    def _extract_passcodes_from_section(section: str) -> list[int]:
        """Extrait les passcodes d'images de cartes dans une section de deck.

        YGOPRODeck utilise les passcodes dans les URLs images/cards*. On ne prend
        qu'un identifiant par balise <img> afin d'éviter les doublons src/srcset.
        """
        result: list[int] = []
        for tag_match in re.finditer(r"<img\b[^>]*>", section, flags=re.I | re.S):
            tag = html_lib.unescape(tag_match.group(0))
            match = re.search(
                r"/cards(?:_small|_cropped)?/(\d{4,10})\.(?:jpg|jpeg|png|webp)",
                tag,
                flags=re.I,
            )
            if not match:
                match = re.search(
                    r"(?:data-passcode|data-card-passcode)=[\"'](\\d{4,10})[\"']",
                    tag,
                    flags=re.I,
                )
            if match:
                try:
                    result.append(int(match.group(1)))
                except ValueError:
                    pass
        return result

    @staticmethod
    def _quantity_from_card_context(context: str) -> int:
        """Déduit prudemment la quantité d'une carte dans son bloc HTML."""
        patterns = (
            r'(?:data-(?:qty|quantity|count|copies|card-count)|(?:qty|quantity|count|copies))=["\']([1-3])["\']',
            r'class=["\'][^"\']*(?:qty|quantity|count|copies)[^"\']*["\'][^>]*>\s*[x×]?\s*([1-3])\b',
            r'\b[x×]\s*([1-3])\b',
            r'\b([1-3])\s*[x×]\b',
        )
        for pattern in patterns:
            matches = list(re.finditer(pattern, context, flags=re.I | re.S))
            if matches:
                try:
                    return max(1, min(3, int(matches[-1].group(1))))
                except (TypeError, ValueError):
                    continue
        return 1

    @classmethod
    def _extract_zone_cards_from_blocks(cls, body: str) -> tuple[list[int], list[int], list[int]] | None:
        """Essaie de lire les blocs de cartes qui portent eux-mêmes leur zone.

        Les pages YGOPRODeck récentes peuvent rendre les trois titres de zones
        avant les cartes. Dans ce cas, un simple découpage entre les titres ne
        suffit plus. Ce parseur regarde le conteneur proche de chaque image et
        cherche les classes/attributs Main, Extra ou Side.
        """
        decoded = unquote(html_lib.unescape(body)).replace("\\/", "/")
        hits: list[tuple[int, int, str, int]] = []
        image_re = re.compile(
            r'<img\b[^>]*(?:/cards(?:_small|_cropped)?/|data-(?:passcode|card-passcode)=)[^>]*>',
            flags=re.I | re.S,
        )
        for image in image_re.finditer(decoded):
            tag = image.group(0)
            card_match = re.search(
                r'/cards(?:_small|_cropped)?/(\d{4,10})\.(?:jpg|jpeg|png|webp)',
                tag,
                flags=re.I,
            ) or re.search(
                r'(?:data-passcode|data-card-passcode)=["\'](\d{4,10})["\']',
                tag,
                flags=re.I,
            )
            if not card_match:
                continue
            card_id = int(card_match.group(1))
            start = max(0, image.start() - 1400)
            before = decoded[start:image.start()]
            context = before + tag
            zone = None
            # On privilégie les marqueurs explicites proches du bloc de carte.
            zone_patterns = (
                ("side", r'(?:side[-_ ]?deck|deck[-_ ]?side|data-(?:zone|location)=["\']side["\'])'),
                ("extra", r'(?:extra[-_ ]?deck|deck[-_ ]?extra|data-(?:zone|location)=["\']extra["\'])'),
                ("main", r'(?:main[-_ ]?deck|deck[-_ ]?main|data-(?:zone|location)=["\']main["\'])'),
            )
            best: tuple[int, str] | None = None
            for candidate, pattern in zone_patterns:
                matches = list(re.finditer(pattern, context, flags=re.I))
                if matches:
                    distance = len(before) - matches[-1].end()
                    if best is None or distance < best[0]:
                        best = (distance, candidate)
            if best:
                zone = best[1]
            if not zone:
                continue
            qty = cls._quantity_from_card_context(context[-700:])
            hits.append((image.start(), card_id, zone, qty))

        if not hits:
            return None
        by_zone: dict[str, list[int]] = {"main": [], "extra": [], "side": []}
        # Plusieurs src/srcset peuvent parfois pointer vers le même passcode dans
        # le même bloc. On déduplique seulement les occurrences quasi-identiques.
        previous_key: tuple[int, str] | None = None
        previous_pos = -10_000
        for pos, card_id, zone, qty in hits:
            key = (card_id, zone)
            if key == previous_key and pos - previous_pos < 350:
                continue
            by_zone[zone].extend([card_id] * qty)
            previous_key = key
            previous_pos = pos
        if cls._valid_deck(by_zone["main"], by_zone["extra"], by_zone["side"]):
            return by_zone["main"], by_zone["extra"], by_zone["side"]
        return None

    @classmethod
    def _extract_deck_ids_from_html(cls, body: str) -> tuple[list[int], list[int], list[int]] | None:
        """Fallback pour les pages où le lien YDKE n'est plus inline.

        On découpe le HTML rendu côté serveur par les titres Main/Extra/Side puis
        on lit les passcodes contenus dans les URLs d'images de cartes.
        """
        decoded = unquote(html_lib.unescape(body))
        markers: dict[str, re.Match[str] | None] = {
            "main": re.search(r"Main\s*Deck(?:\s*\([^<]{0,80}\))?", decoded, flags=re.I),
            "extra": re.search(r"Extra\s*Deck(?:\s*\([^<]{0,80}\))?", decoded, flags=re.I),
            "side": re.search(r"Side\s*Deck(?:\s*\([^<]{0,80}\))?", decoded, flags=re.I),
            "breakdown": re.search(r"Deck\s*Breakdown|View\s*Deck\s*History|Other\s*Decks", decoded, flags=re.I),
        }
        if not markers["main"]:
            return None
        main_start = markers["main"].end()
        extra_start = markers["extra"].start() if markers["extra"] else None
        side_start = markers["side"].start() if markers["side"] else None
        end_candidates = [
            match.start() for key, match in markers.items()
            if key == "breakdown" and match is not None
        ]
        doc_end = min(end_candidates) if end_candidates else len(decoded)

        if extra_start is not None:
            main_end = extra_start
        elif side_start is not None:
            main_end = side_start
        else:
            main_end = doc_end

        if markers["extra"]:
            extra_content_start = markers["extra"].end()
            extra_end = side_start if side_start is not None else doc_end
        else:
            extra_content_start = extra_end = 0

        if markers["side"]:
            side_content_start = markers["side"].end()
            side_end = doc_end
        else:
            side_content_start = side_end = 0

        main = cls._extract_passcodes_from_section(decoded[main_start:main_end])
        extra = cls._extract_passcodes_from_section(decoded[extra_content_start:extra_end]) if extra_content_start else []
        side = cls._extract_passcodes_from_section(decoded[side_content_start:side_end]) if side_content_start else []
        if cls._valid_deck(main, extra, side):
            return main, extra, side
        return None

    @staticmethod
    def _extract_meta(body: str, property_name: str) -> str | None:
        pattern = (
            r'<meta[^>]+(?:property|name)=["\']' + re.escape(property_name) + r'["\'][^>]+content=["\']([^"\']+)["\']'
        )
        match = re.search(pattern, body, flags=re.IGNORECASE)
        if not match:
            pattern = (
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']'
                + re.escape(property_name) + r'["\']'
            )
            match = re.search(pattern, body, flags=re.IGNORECASE)
        return html_lib.unescape(match.group(1)).strip() if match else None

    @staticmethod
    def _extract_title(body: str, fallback: str) -> str:
        title = DeckBuilderService._extract_meta(body, "og:title")
        if title:
            return re.sub(r"\s+-\s+YGOPRODeck.*$", "", title, flags=re.IGNORECASE).strip()
        match = re.search(r"<h1[^>]*>(.*?)</h1>", body, flags=re.IGNORECASE | re.DOTALL)
        if match:
            clean = html_lib.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
            if clean:
                return clean
        return fallback

    @staticmethod
    def _extract_published(body: str) -> str | None:
        candidates = [
            DeckBuilderService._extract_meta(body, "article:published_time"),
            DeckBuilderService._extract_meta(body, "datePublished"),
        ]
        json_date = re.search(r'"datePublished"\s*:\s*"([^"]+)"', body)
        if json_date:
            candidates.append(json_date.group(1))
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", candidate)
                if match:
                    return match.group(0)
        return None

    @staticmethod
    def _extract_placement(body: str) -> str | None:
        text = re.sub(r"<[^>]+>", " ", html_lib.unescape(body))
        text = re.sub(r"\s+", " ", text)
        patterns = [
            r"Placement:\s*([^|]{1,40}?)(?: Read More| Toggle| Tournament:|$)",
            r"\b(Winner|Runner-Up|Top\s*(?:4|8|16|32|64)|1st Place|2nd Place|3rd Place)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _sample_weight(*, is_tournament: bool, published: str | None, placement: str | None) -> float:
        weight = 1.0
        if is_tournament:
            weight *= 1.55
        placement_key = (placement or "").casefold()
        if "winner" in placement_key or "1st" in placement_key:
            weight *= 1.22
        elif any(value in placement_key for value in ("runner", "2nd", "top 4", "3rd")):
            weight *= 1.14
        elif any(value in placement_key for value in ("top 8", "top 16", "top 32")):
            weight *= 1.07
        if published:
            try:
                age_days = max(0, (date.today() - date.fromisoformat(published)).days)
                if age_days <= 30:
                    weight *= 1.35
                elif age_days <= 90:
                    weight *= 1.22
                elif age_days <= 180:
                    weight *= 1.10
                elif age_days <= 365:
                    weight *= 0.95
                else:
                    weight *= 0.68
            except ValueError:
                pass
        return round(weight, 4)

    @staticmethod
    def _find_ydke(body: str) -> str | None:
        decoded = unquote(html_lib.unescape(body))
        match = re.search(r"ydke://[A-Za-z0-9+/=_!%-]+", decoded, flags=re.IGNORECASE)
        if match:
            return match.group(0)
        match = re.search(r"ydke:\\/\\/[A-Za-z0-9+/=_!%\\-]+", body, flags=re.IGNORECASE)
        if match:
            return match.group(0).replace("\\/", "/")
        # Le deck-tool YGOPRODeck accepte également la partie data d'un YDKE
        # dans le paramètre ?y=. Certains liens n'exposent donc pas "ydke://".
        for raw in re.findall(r"[?&]y=([^&\"'<>\\s]+)", decoded, flags=re.IGNORECASE):
            candidate = unquote(raw)
            parts = candidate.split("!")
            if len(parts) >= 3 and all(parts[:3]):
                return "ydke://{}!{}!{}!".format(parts[0], parts[1], parts[2])
        return None

    @staticmethod
    def _fingerprint(main: Iterable[int], extra: Iterable[int], side: Iterable[int]) -> str:
        def section(values: Iterable[int]) -> str:
            counts = Counter(int(value) for value in values)
            return ",".join(f"{card_id}x{count}" for card_id, count in sorted(counts.items()))
        payload = f"{section(main)}|{section(extra)}|{section(side)}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _valid_deck(main: list[int], extra: list[int], side: list[int]) -> bool:
        return 40 <= len(main) <= 60 and len(extra) <= 15 and len(side) <= 15

    @staticmethod
    def _detect_sample_format(body: str, title: str = "") -> str:
        text = f"{title} {body}".casefold()
        explicit_non_tcg = (
            ("master duel", "master_duel"),
            ("tournament meta decks ocg", "ocg"),
            ("ocg tournament", "ocg"),
            ("japan championship", "ocg"),
            ("asia championship", "ocg"),
            ("china championship", "ocg"),
            ("ocg-ae", "ocg_ae"),
            ("genesys ocg", "genesys_ocg"),
            ("genesys", "genesys"),
            ("rush duel", "rush"),
            ("speed duel", "speed"),
        )
        for marker, value in explicit_non_tcg:
            if marker in text:
                return value
        tcg_markers = (
            "tournament meta decks", "tcg", "wcq regional", "regional qualifier",
            "national championship", "ycs ", "world championship qualifier",
        )
        if any(marker in text for marker in tcg_markers):
            return "tcg"
        return "unknown"

    async def _deck_sample_from_url(self, url: str) -> DeckSample | None:
        try:
            body = await self._fetch_text(url, ttl_hours=self.cache_hours)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None
        ydke = self._find_ydke(body)
        parsed_from = "ydke"
        if ydke:
            try:
                main, extra, side = self.decode_ydke(ydke)
            except (ValueError, TypeError, base64.binascii.Error):
                main, extra, side = [], [], []
        else:
            main, extra, side = [], [], []
        if not self._valid_deck(main, extra, side):
            fallback_ids = self._extract_zone_cards_from_blocks(body)
            if fallback_ids:
                main, extra, side = fallback_ids
                parsed_from = "html-zone-blocks"
            else:
                fallback_ids = self._extract_deck_ids_from_html(body)
                if not fallback_ids:
                    return None
                main, extra, side = fallback_ids
                parsed_from = "html-card-images"
        fallback = url.rstrip("/").rsplit("/", 1)[-1].rsplit("-", 1)[0].replace("-", " ").title()
        title = self._extract_title(body, fallback)
        published = self._extract_published(body)
        placement = self._extract_placement(body)
        lowered = body.casefold()
        is_tournament = any(
            marker in lowered
            for marker in (
                "tournament meta decks", "tournament:", "placement:", "wcq regional",
                "national championship", "world championship", "regional qualifier",
            )
        )
        weight = self._sample_weight(
            is_tournament=is_tournament,
            published=published,
            placement=placement,
        )
        return DeckSample(
            title=title,
            url=url,
            main=main,
            extra=extra,
            side=side,
            is_tournament=is_tournament,
            published=published,
            placement=placement,
            weight=weight,
            fingerprint=self._fingerprint(main, extra, side),
            format_name=self._detect_sample_format(body, title),
        )

    async def search_samples(self, query: str, *, max_decks: int | None = None) -> list[DeckSample]:
        clean = re.sub(r"\s+", " ", query).strip()
        if not clean:
            return []
        await self.remember_query(clean)
        limit = min(max_decks or self.max_decks, self.max_decks)
        stored = await asyncio.to_thread(self._load_samples_sync, clean, limit)
        canonical, learned_aliases = await asyncio.to_thread(self._catalog_resolve_sync, clean)
        variants = self._query_variants(canonical or clean)
        for alias in learned_aliases:
            if alias and alias.casefold() not in {v.casefold() for v in variants}:
                variants.append(alias)
        # L'endpoint des archétypes permet de retrouver automatiquement les noms
        # officiels qui diffèrent seulement par la ponctuation (P.U.N.K., D/D/D...).
        try:
            archetypes = await self._fetch_json(f"{YGOPRODECK_API}/archetypes.php", ttl_hours=72)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            archetypes = []
        identities = {self._deck_identity(value) for value in variants if value}
        base_identity = self._deck_identity(clean)
        for item in archetypes if isinstance(archetypes, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("archetype_name") or "").strip()
            nid = self._deck_identity(name)
            if not name or not nid:
                continue
            if nid in identities or nid == base_identity or (len(base_identity) >= 3 and (base_identity in nid or nid in base_identity)):
                if name.casefold() not in {v.casefold() for v in variants}:
                    variants.append(name)
        variants = variants[:8]

        source_urls: list[str] = []
        category_urls: list[str] = []
        for value in variants:
            encoded = quote_plus(value)
            # Tournament Meta Decks = TCG sur YGOPRODeck ; les formats OCG et Genesys
            # disposent de catégories séparées. La page générale sert de secours,
            # puis les deck pages explicitement non-TCG sont rejetées plus bas.
            for url in (
                f"{YGOPRODECK_SITE}/deck-search/?name={encoded}&offset=0&tournament=tier-2",
                f"{YGOPRODECK_SITE}/deck-search/?name={encoded}&offset=0",
            ):
                if url not in source_urls:
                    source_urls.append(url)
            for url in await self._category_urls_for_query(value):
                if url not in category_urls:
                    category_urls.append(url)
        # Les pages /category/type/ sont la source la plus directe lorsqu'un
        # archétype est correctement référencé (Radiant Typhoon, P.U.N.K., etc.).
        # Elles passent avant les pages de recherche génériques afin de ne pas être
        # éliminées par la limite de sources lorsque de nombreux alias existent.
        source_urls = [*category_urls, *[url for url in source_urls if url not in category_urls]]
        source_urls = source_urls[:18]
        pages = await asyncio.gather(
            *(self._fetch_text(url, ttl_hours=self.search_cache_hours) for url in source_urls),
            return_exceptions=True,
        )
        links: list[str] = []
        seen_urls: set[str] = set()
        pages_ok = 0
        for page in pages:
            if isinstance(page, Exception):
                continue
            pages_ok += 1
            for link in self._extract_deck_links(page):
                if link not in seen_urls:
                    seen_urls.add(link)
                    links.append(link)
        links = links[: min(len(links), max(limit * 3, limit))]
        semaphore = asyncio.Semaphore(5)

        async def load(url: str) -> DeckSample | None:
            async with semaphore:
                return await self._deck_sample_from_url(url)

        loaded = await asyncio.gather(*(load(url) for url in links)) if links else []

        # V8.4 : certains decks existent bien mais sont mal indexés par leur nom.
        # Si le premier passage donne peu de pages exploitables, on repart de cartes
        # propres à l'archétype et on cherche les decklists qui les contiennent.
        primary_parsed = sum(1 for sample in loaded if sample is not None)
        signature_names: list[str] = []
        signature_urls: list[str] = []
        signature_pages_ok = 0
        signature_links_added = 0
        if primary_parsed < min(4, limit):
            signature_names, signature_urls = await self._signature_discovery_urls(clean, limit=4)
            signature_urls = [url for url in signature_urls if url not in source_urls][:8]
            signature_pages = await asyncio.gather(
                *(self._fetch_text(url, ttl_hours=self.search_cache_hours) for url in signature_urls),
                return_exceptions=True,
            )
            extra_links: list[str] = []
            for page in signature_pages:
                if isinstance(page, Exception):
                    continue
                signature_pages_ok += 1
                for link in self._extract_deck_links(page):
                    if link not in seen_urls:
                        seen_urls.add(link)
                        extra_links.append(link)
            max_extra = max(limit * 3, limit)
            extra_links = extra_links[:max_extra]
            signature_links_added = len(extra_links)
            if extra_links:
                loaded.extend(await asyncio.gather(*(load(url) for url in extra_links)))
                links.extend(extra_links)

        # V8.6 : dernier étage universel. On ne suppose plus que le terme saisi
        # est un archétype : il peut être un hybride, un moteur, un boss monster
        # ou un nom communautaire. On résout alors le nom vers des composants,
        # cartes TCG et archétypes proches, puis on relance la découverte.
        universal_debug: dict[str, Any] = {}
        universal_urls: list[str] = []
        universal_pages_ok = 0
        universal_links_added = 0
        parsed_after_signature = sum(1 for sample in loaded if sample is not None)
        if parsed_after_signature < min(4, limit):
            archetype_names = [
                str(item.get("archetype_name") or "").strip()
                for item in archetypes if isinstance(item, dict) and str(item.get("archetype_name") or "").strip()
            ] if isinstance(archetypes, list) else []
            universal_debug, universal_urls = await self._universal_discovery_urls(
                clean, archetype_names, card_limit=8
            )
            already_queried = set(source_urls) | set(signature_urls)
            universal_urls = [url for url in universal_urls if url not in already_queried][:30]
            universal_pages = await asyncio.gather(
                *(self._fetch_text(url, ttl_hours=self.search_cache_hours) for url in universal_urls),
                return_exceptions=True,
            )
            universal_links: list[str] = []
            for page in universal_pages:
                if isinstance(page, Exception):
                    continue
                universal_pages_ok += 1
                for link in self._extract_deck_links(page):
                    if link not in seen_urls:
                        seen_urls.add(link)
                        universal_links.append(link)
            universal_links = universal_links[:max(limit * 4, limit)]
            universal_links_added = len(universal_links)
            if universal_links:
                loaded.extend(await asyncio.gather(*(load(url) for url in universal_links)))
                links.extend(universal_links)

        live: list[DeckSample] = []
        explicit_non_tcg = 0
        for sample in loaded:
            if sample is None:
                continue
            if sample.format_name not in {"tcg", "unknown"}:
                explicit_non_tcg += 1
                continue
            live.append(sample)

        # Validation carte-par-carte TCG : format=tcg ne renvoie que les cartes avec
        # une date de sortie TCG et exclut notamment Speed/Rush selon la doc API.
        live_ids = [cid for sample in live for cid in [*sample.main, *sample.extra, *sample.side]]
        tcg_cards = await self.card_data_by_ids(live_ids) if live_ids else {}
        tcg_compatible: list[DeckSample] = []
        card_incompatible = 0
        for sample in live:
            sample_ids = set(sample.main + sample.extra + sample.side)
            if sample_ids and sample_ids.issubset(set(tcg_cards)):
                tcg_compatible.append(sample)
            else:
                card_incompatible += 1

        deduped: dict[str, DeckSample] = {}
        for sample in [*tcg_compatible, *stored]:
            previous = deduped.get(sample.fingerprint)
            if previous is None or sample.weight > previous.weight:
                deduped[sample.fingerprint] = sample
        valid = list(deduped.values())
        valid.sort(key=lambda item: (item.weight, item.is_tournament, item.published or ""), reverse=True)
        valid = valid[:limit]
        if tcg_compatible:
            await asyncio.to_thread(self._store_samples_sync, clean, tcg_compatible)
        else:
            await asyncio.to_thread(
                self._catalog_upsert_sync,
                clean,
                aliases=variants,
                sample_count=len(stored),
                success=bool(stored),
            )
        self._last_discovery_debug = {
            "source_pages_requested": len(source_urls),
            "source_pages_loaded": pages_ok,
            "category_pages": category_urls,
            "query_variants": variants,
            "deck_links_found": len(links),
            "deck_pages_parsed": sum(1 for sample in loaded if sample is not None),
            "signature_fallback_used": bool(signature_urls),
            "signature_cards": signature_names,
            "signature_pages_requested": len(signature_urls),
            "signature_pages_loaded": signature_pages_ok,
            "signature_deck_links_added": signature_links_added,
            "universal_fallback_used": bool(universal_urls),
            "universal_pages_requested": len(universal_urls),
            "universal_pages_loaded": universal_pages_ok,
            "universal_deck_links_added": universal_links_added,
            "universal_components": universal_debug.get("components") or [],
            "universal_candidate_archetypes": universal_debug.get("candidate_archetypes") or [],
            "universal_resolved_cards": universal_debug.get("resolved_card_names") or [],
            "explicit_non_tcg_ignored": explicit_non_tcg,
            "tcg_incompatible_ignored": card_incompatible,
            "live_tcg_decks": len(tcg_compatible),
            "stored_tcg_decks_reused": len(stored),
            "unique_decks": len(valid),
            "tcg_only": True,
        }
        return valid

    @staticmethod
    def _filter_samples(
        samples: list[DeckSample],
        *,
        tournament_only: bool = False,
        days: int | None = None,
        variant: str | None = None,
        base_query: str = "",
    ) -> list[DeckSample]:
        result = samples
        if tournament_only:
            result = [sample for sample in result if sample.is_tournament]
        if days:
            threshold = date.today() - timedelta(days=max(1, days))
            filtered: list[DeckSample] = []
            for sample in result:
                if not sample.published:
                    continue
                try:
                    if date.fromisoformat(sample.published) >= threshold:
                        filtered.append(sample)
                except ValueError:
                    continue
            result = filtered
        clean_variant = re.sub(r"\s+", " ", str(variant or "")).strip().casefold()
        if clean_variant and clean_variant != base_query.casefold():
            result = [sample for sample in result if clean_variant in sample.title.casefold()]
        return result

    # ------------------------------------------------------------------
    # Card data + prices
    # ------------------------------------------------------------------
    async def card_data_by_ids(self, card_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        ids = sorted({int(card_id) for card_id in card_ids if int(card_id) > 0})
        if not ids:
            return {}
        chunks = [ids[index:index + 50] for index in range(0, len(ids), 50)]

        async def fetch(chunk: list[int]) -> tuple[list[dict[str, Any]], int]:
            url = f"{YGOPRODECK_API}/cardinfo.php?id={','.join(map(str, chunk))}&misc=yes&format=tcg"
            try:
                payload, fetched_at = await self._fetch_json_with_meta(url, ttl_hours=self.cache_hours)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                return [], int(time.time())
            rows = list(payload.get("data") or []) if isinstance(payload, dict) else []
            return rows, fetched_at

        results = await asyncio.gather(*(fetch(chunk) for chunk in chunks))
        cards: dict[int, dict[str, Any]] = {}
        fetch_dates: list[str] = []
        for group, fetched_at in results:
            fetch_date = datetime.fromtimestamp(fetched_at).date().isoformat()
            fetch_dates.append(fetch_date)
            for card in group:
                try:
                    card_id = int(card["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                card = dict(card)
                card["_source_name"] = str(card.get("name") or "")
                cards[card_id] = card
            await asyncio.to_thread(self._store_price_snapshots_sync, group, fetch_date)

        # Les decklists utilisent les passcodes anglais, mais l'interface Hamtaro peut
        # afficher les noms officiels localisés sans perdre le nom source utilisé pour
        # les recherches Cardmarket.
        if self.card_language != "en" and cards:
            async def fetch_localized(chunk: list[int]) -> list[dict[str, Any]]:
                url = (
                    f"{YGOPRODECK_API}/cardinfo.php?id={','.join(map(str, chunk))}"
                    f"&misc=yes&format=tcg&language={quote_plus(self.card_language)}"
                )
                try:
                    payload = await self._fetch_json(url, ttl_hours=self.cache_hours)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    return []
                return list(payload.get("data") or []) if isinstance(payload, dict) else []

            localized_groups = await asyncio.gather(*(fetch_localized(chunk) for chunk in chunks))
            for group in localized_groups:
                for localized in group:
                    try:
                        card_id = int(localized["id"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if card_id not in cards:
                        continue
                    cards[card_id]["_localized_name"] = str(localized.get("name") or "").strip() or None
                    cards[card_id]["_localized_desc"] = str(localized.get("desc") or "").strip() or None

        self._last_card_fetch_dates.extend(fetch_dates)
        self._last_card_fetch_dates = self._last_card_fetch_dates[-40:]
        return cards

    async def archetype_cards(self, query: str) -> list[dict[str, Any]]:
        candidates = self._query_variants(query)
        try:
            payload_arch = await self._fetch_json(f"{YGOPRODECK_API}/archetypes.php", ttl_hours=72)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            payload_arch = []
        identity = self._deck_identity(query)
        for item in payload_arch if isinstance(payload_arch, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("archetype_name") or "").strip()
            nid = self._deck_identity(name)
            if not name or not nid:
                continue
            if nid == identity or (len(identity) >= 2 and (identity in nid or nid in identity)):
                if name.casefold() not in {value.casefold() for value in candidates}:
                    candidates.append(name)
        for candidate in candidates[:10]:
            url = f"{YGOPRODECK_API}/cardinfo.php?archetype={quote_plus(candidate)}&misc=yes&format=tcg"
            try:
                payload, fetched_at = await self._fetch_json_with_meta(url, ttl_hours=self.cache_hours)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                continue
            cards = list(payload.get("data") or []) if isinstance(payload, dict) else []
            if not cards:
                continue
            fetch_date = datetime.fromtimestamp(fetched_at).date().isoformat()
            await asyncio.to_thread(self._store_price_snapshots_sync, cards, fetch_date)
            self._last_card_fetch_dates.append(fetch_date)
            if self.card_language != "en" and cards:
                localized = await self.card_data_by_ids(
                    [int(card.get("id") or 0) for card in cards if int(card.get("id") or 0) > 0]
                )
                return [localized.get(int(card.get("id") or 0), card) for card in cards]
            return cards

        # V8.6 : si aucun archétype exact n'existe, le terme peut désigner une
        # carte-signature, un deck hybride ou un nom communautaire. On résout le
        # texte vers des cartes TCG puis, si possible, vers leurs archétypes.
        resolution = await self._card_name_resolution(query, limit_cards=24)
        resolved_cards = list(resolution.get("cards") or [])
        resolved_arch = list(resolution.get("archetypes") or [])[:4]
        combined: dict[int, dict[str, Any]] = {}
        for arch in resolved_arch:
            url = f"{YGOPRODECK_API}/cardinfo.php?archetype={quote_plus(arch)}&misc=yes&format=tcg"
            try:
                payload, fetched_at = await self._fetch_json_with_meta(url, ttl_hours=self.cache_hours)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                continue
            rows = list(payload.get("data") or []) if isinstance(payload, dict) else []
            if rows:
                fetch_date = datetime.fromtimestamp(fetched_at).date().isoformat()
                await asyncio.to_thread(self._store_price_snapshots_sync, rows, fetch_date)
                self._last_card_fetch_dates.append(fetch_date)
            for card in rows:
                try:
                    cid = int(card.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                if cid > 0:
                    combined[cid] = card
        if not combined:
            for card in resolved_cards:
                try:
                    cid = int(card.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                if cid > 0:
                    combined[cid] = card
        cards = list(combined.values())
        if cards and self.card_language != "en":
            localized = await self.card_data_by_ids([int(card.get("id") or 0) for card in cards])
            return [localized.get(int(card.get("id") or 0), card) for card in cards]
        return cards

    @staticmethod
    def _market_slug(value: str) -> str:
        """Slug prudent pour tenter la page publique Cardmarket /Cards/<slug>/Versions."""
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.replace("&", " ").replace("'", "").replace("’", "")
        text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
        return re.sub(r"-+", "-", text)

    @staticmethod
    def _plain_html(fragment: str) -> str:
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", fragment, flags=re.I | re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html_lib.unescape(text).replace("\xa0", " ")
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _parse_eur(value: str | None) -> float | None:
        raw = re.sub(r"[^0-9,.' ]", "", str(value or "")).strip().replace("'", "")
        raw = raw.replace(" ", "")
        if not raw:
            return None
        if "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):
                raw = raw.replace(".", "").replace(",", ".")
            else:
                raw = raw.replace(",", "")
        elif "," in raw:
            head, tail = raw.rsplit(",", 1)
            raw = head.replace(",", "") + ("." + tail if len(tail) <= 2 else tail)
        try:
            value_f = float(raw)
        except ValueError:
            return None
        return round(value_f, 2) if value_f >= 0 else None

    @classmethod
    def _known_rarity_from_slug(cls, product_slug: str, rarities: Iterable[str]) -> str | None:
        slug = cls._market_slug(unquote(product_slug)).casefold()
        values = sorted({str(r or "").strip() for r in rarities if str(r or "").strip()}, key=len, reverse=True)
        extras = [
            "Quarter Century Secret Rare", "Prismatic Secret Rare", "Platinum Secret Rare",
            "Collector's Rare", "Collectors Rare", "Starlight Rare", "Ghost Rare",
            "Ultimate Rare", "Secret Rare", "Ultra Rare", "Super Rare", "Premium Gold Rare",
            "Gold Rare", "Rare", "Common", "Starfoil Rare", "Shatterfoil Rare",
        ]
        for rarity in values + extras:
            if cls._market_slug(rarity).casefold() in slug:
                return rarity
        return None

    @staticmethod
    def _set_similarity(left: str, right: str) -> float:
        stop = {"the", "of", "and", "a", "an", "edition", "set", "yu", "gi", "oh"}
        def toks(value: str) -> set[str]:
            value = unicodedata.normalize("NFKD", str(value or ""))
            value = "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()
            return {tok for tok in re.findall(r"[a-z0-9]+", value) if tok not in stop and len(tok) > 1}
        a, b = toks(left), toks(right)
        if not a or not b:
            return 0.0
        return len(a & b) / max(len(a), len(b))

    async def _cardmarket_version_floors(
        self, card_name: str, known_rarities: Iterable[str]
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Lit seulement les tuiles publiques /Versions, sans login ni contournement.

        Si Cardmarket refuse la requête, on retombe proprement sur card_sets et aucun
        prix EUR par impression n'est inventé.
        """
        slug = self._market_slug(card_name)
        if not slug:
            return [], None
        candidates = [f"{CARDMARKET_CARD_BASE}{slug}/Versions", f"{CARDMARKET_CARD_BASE}{slug}"]
        body = ""
        source_url = None
        for url in candidates:
            try:
                body = await self._fetch_text(url, ttl_hours=24)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                continue
            lowered = body.casefold()
            if any(marker in lowered for marker in ("captcha", "access denied", "please verify you are a human")):
                body = ""
                continue
            if "/Products/Singles/" in body:
                source_url = url
                break
        if not body:
            return [], source_url

        host = "https://www.cardmarket.com"
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        href_re = re.compile(r"href=[\"'](?P<href>/en/YuGiOh/Products/Singles/[^\"'#?]+)[\"']", re.I)
        for match in href_re.finditer(body):
            href = html_lib.unescape(match.group("href"))
            if href in seen:
                continue
            seen.add(href)
            before = max(0, match.start() - 1100)
            after = min(len(body), match.end() + 1700)
            fragment = body[before:after]
            plain = self._plain_html(fragment)
            prices: list[float] = []
            for price_match in re.finditer(r"(?:From|À partir de|A partir de)?\s*([0-9][0-9 .,'’]*[,.][0-9]{1,2}|[0-9]+)\s*€", plain, re.I):
                price = self._parse_eur(price_match.group(1))
                if price is not None:
                    prices.append(price)
            price_eur = min(prices) if prices else None
            parts = [unquote(part) for part in href.split("/") if part]
            try:
                singles_idx = parts.index("Singles")
            except ValueError:
                continue
            if len(parts) <= singles_idx + 2:
                continue
            expansion_slug = parts[singles_idx + 1]
            product_slug = parts[singles_idx + 2]
            rarity = self._known_rarity_from_slug(product_slug, known_rarities)
            set_label = re.sub(r"-+", " ", expansion_slug).strip()
            product_label = re.sub(r"-+", " ", product_slug).strip()
            available_match = re.search(r"([0-9][0-9 .,]*)\s+Available", plain, re.I)
            available = None
            if available_match:
                try:
                    available = int(re.sub(r"\D", "", available_match.group(1)))
                except ValueError:
                    pass
            rows.append({
                "market_url": host + href,
                "expansion_slug": expansion_slug,
                "set_label": set_label,
                "product_label": product_label,
                "rarity": rarity,
                "price_eur": price_eur,
                "available": available,
            })
        return rows, source_url

    async def card_printings(self, card_id: int) -> dict[str, Any]:
        try:
            card_id = int(card_id)
        except (TypeError, ValueError):
            raise ValueError("Carte invalide.")
        if card_id <= 0:
            raise ValueError("Carte invalide.")
        cards = await self.card_data_by_ids([card_id])
        card = cards.get(card_id)
        if not card:
            raise ValueError("Carte introuvable.")
        card_name = str(card.get("_source_name") or card.get("name") or f"Card {card_id}")
        localized_name = str(card.get("_localized_name") or card.get("name") or card_name)
        card_sets = list(card.get("card_sets") or [])
        known_rarities = [str(row.get("set_rarity") or "") for row in card_sets]
        market_versions, market_source = await self._cardmarket_version_floors(card_name, known_rarities)

        unmatched = set(range(len(market_versions)))
        printings: list[dict[str, Any]] = []
        for index, set_row in enumerate(card_sets):
            set_name = str(set_row.get("set_name") or "").strip()
            set_code = str(set_row.get("set_code") or "").strip()
            rarity = str(set_row.get("set_rarity") or "Inconnue").strip() or "Inconnue"
            rarity_code = str(set_row.get("set_rarity_code") or "").strip() or None
            best_idx = None
            best_score = 0.0
            for candidate_idx in list(unmatched):
                candidate = market_versions[candidate_idx]
                candidate_rarity = str(candidate.get("rarity") or "").casefold()
                if candidate_rarity and candidate_rarity != rarity.casefold():
                    continue
                score = self._set_similarity(set_name, str(candidate.get("set_label") or ""))
                if score > best_score:
                    best_idx, best_score = candidate_idx, score
            market = None
            if best_idx is not None and best_score >= 0.45:
                market = market_versions[best_idx]
                unmatched.discard(best_idx)
            try:
                set_price_usd = float(set_row.get("set_price")) if set_row.get("set_price") not in (None, "") else None
            except (TypeError, ValueError):
                set_price_usd = None
            printings.append({
                "printing_id": f"ygp:{card_id}:{index}:{set_code or index}",
                "set_name": set_name or (market.get("set_label") if market else "Édition inconnue"),
                "set_code": set_code or None,
                "rarity": rarity,
                "rarity_code": rarity_code,
                "price_eur": market.get("price_eur") if market else None,
                "price_usd_fallback": round(set_price_usd, 2) if set_price_usd is not None else None,
                "market_url": market.get("market_url") if market else CARDMARKET_SEARCH + quote_plus(card_name),
                "market_confirmed": bool(market and market.get("price_eur") is not None),
                "price_source": "Cardmarket · plancher de cette version" if market and market.get("price_eur") is not None else "Prix d'impression YGOPRODeck (USD, secours)",
                "available": market.get("available") if market else None,
            })

        for candidate_idx in sorted(unmatched):
            market = market_versions[candidate_idx]
            printings.append({
                "printing_id": f"cm:{card_id}:{candidate_idx}",
                "set_name": str(market.get("set_label") or "Version Cardmarket"),
                "set_code": None,
                "rarity": str(market.get("rarity") or "Rareté non précisée"),
                "rarity_code": None,
                "price_eur": market.get("price_eur"),
                "price_usd_fallback": None,
                "market_url": market.get("market_url") or CARDMARKET_SEARCH + quote_plus(card_name),
                "market_confirmed": market.get("price_eur") is not None,
                "price_source": "Cardmarket · plancher de cette version",
                "available": market.get("available"),
            })

        deduped: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str, str, float | None]] = set()
        for row in printings:
            key = (str(row.get("set_name") or "").casefold(), str(row.get("set_code") or "").casefold(), str(row.get("rarity") or "").casefold(), row.get("price_eur"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(row)
        deduped.sort(key=lambda row: (0 if row.get("price_eur") is not None else 1, float(row.get("price_eur") or 10**9), str(row.get("rarity") or ""), str(row.get("set_name") or "")))
        rarities = sorted({str(row.get("rarity") or "Inconnue") for row in deduped})
        return {
            "card_id": card_id,
            "name": localized_name,
            "source_name": card_name,
            "default_cardmarket_price": self._price(card),
            "printings": deduped,
            "rarities": rarities,
            "cardmarket_versions_available": any(row.get("price_eur") is not None for row in deduped),
            "cardmarket_versions_source": market_source,
            "note": "Le prix EUR correspond au plancher public de la version Cardmarket quand Hamtaro peut l'identifier. Sinon le prix d'impression YGOPRODeck en USD reste affiché séparément ; aucun prix EUR n'est inventé.",
        }

    @staticmethod
    def _price(card: dict[str, Any]) -> float | None:
        prices = card.get("card_prices") or []
        if not prices:
            return None
        try:
            raw = prices[0].get("cardmarket_price")
            if raw in (None, ""):
                return None
            value = float(raw)
            return round(value, 2) if value >= 0 else None
        except (TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _tcg_limit(card: dict[str, Any]) -> int:
        status = str((card.get("banlist_info") or {}).get("ban_tcg") or "").casefold()
        if "banned" in status or "forbidden" in status:
            return 0
        if "semi-limited" in status or "semi limited" in status:
            return 2
        if "limited" in status:
            return 1
        return 3

    @staticmethod
    def _mode(values: list[int], default: int = 1) -> int:
        if not values:
            return default
        counter = Counter(values)
        return sorted(counter.items(), key=lambda item: (item[1], item[0]), reverse=True)[0][0]

    @staticmethod
    def _importance(frequency: float) -> str:
        if frequency >= 0.75:
            return "core"
        if frequency >= 0.45:
            return "frequent"
        if frequency >= 0.15:
            return "option"
        return "rare"

    @staticmethod
    def _importance_label(value: str) -> str:
        return {
            "core": "Core / standard",
            "frequent": "Très fréquent",
            "option": "Option / tech",
            "rare": "Choix rare",
        }.get(value, value)

    @staticmethod
    def _query_tokens(query: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", query.casefold().replace("-", " "))
            if len(token) >= 3 and token not in QUERY_STOP_WORDS
        }

    @classmethod
    def _relation(cls, card: dict[str, Any], query: str, frequency: float) -> str:
        tokens = cls._query_tokens(query)
        name_raw = str(card.get("name") or "")
        archetype_raw = str(card.get("archetype") or "")
        name = name_raw.casefold().replace("-", " ")
        archetype = archetype_raw.casefold().replace("-", " ")
        haystack = f"{name} {archetype}"
        query_identity = cls._deck_identity(query)
        archetype_identity = cls._deck_identity(archetype_raw)
        name_identity = cls._deck_identity(name_raw)
        identity_match = bool(
            query_identity
            and (
                query_identity == archetype_identity
                or query_identity == name_identity
                or (len(query_identity) >= 2 and archetype_identity and (query_identity in archetype_identity or archetype_identity in query_identity))
            )
        )
        if identity_match or (tokens and any(token in haystack for token in tokens)):
            return "archetype"
        if archetype and frequency >= 0.35:
            return "engine"
        return "generic"

    @staticmethod
    def _roles(card: dict[str, Any], zone: str) -> list[str]:
        """Rôles indicatifs : ils servent à expliquer une carte, jamais à garantir une combo."""
        card_type = str(card.get("type") or "").casefold()
        desc = str(card.get("desc") or "").casefold()
        roles: list[str] = []
        if zone == "side":
            roles.append("Tech de Side")
        if zone == "extra":
            if any(word in desc for word in ("negate", "unaffected", "cannot activate")):
                roles.append("Boss / interaction")
            if any(word in desc for word in ("destroy", "banish", "send it to the gy", "return it to the hand")):
                roles.append("Removal")
            if not roles:
                roles.append("Extra Deck")
            return roles[:3]
        if "add 1" in desc and "deck" in desc and "hand" in desc:
            roles.append("Searcher")
        if ("special summon" in desc and ("from your deck" in desc or "from the deck" in desc)) or "normal summon" in desc:
            roles.append("Starter")
        if "special summon" in desc:
            roles.append("Extender")
        if "from your hand" in desc and ("opponent" in desc or "quick effect" in desc) and any(
            word in desc for word in ("negate", "destroy", "banish", "discard this card", "send this card")
        ):
            roles.append("Hand trap")
        if "negate" in desc:
            roles.append("Négation")
        if any(word in desc for word in ("destroy", "banish", "send it to the gy", "shuffle it into the deck", "return it to the hand")):
            roles.append("Removal")
        if "draw" in desc:
            roles.append("Pioche / consistance")
        if any(phrase in desc for phrase in ("all cards your opponent controls", "all monsters your opponent controls", "tribute 1 monster your opponent controls")):
            roles.append("Board breaker")
        if any(word in desc for word in ("from your gy", "from the gy", "graveyard")) and "special summon" in desc:
            roles.append("Récursion")
        if "trap" in card_type and not roles:
            roles.append("Interaction")
        if "spell" in card_type and not roles:
            roles.append("Support")
        if not roles:
            roles.append("Moteur")
        return list(dict.fromkeys(roles))[:3]

    @classmethod
    def _role(cls, card: dict[str, Any], zone: str) -> str:
        return cls._roles(card, zone)[0]

    @staticmethod
    def _freespot_category(row: dict[str, Any]) -> str | None:
        """Classe dynamiquement les cartes génériques observées dans les freespots."""
        if str(row.get("relation") or "") != "generic":
            return None
        zone = str(row.get("zone") or "main")
        if zone not in {"main", "side"}:
            return None
        roles = {str(value) for value in (row.get("role_tags") or [row.get("role")]) if value}
        card_type = str(row.get("type") or "").casefold()
        if "Hand trap" in roles:
            return "handtraps"
        if "Board breaker" in roles:
            return "board_breakers"
        if "trap" in card_type:
            return "traps"
        if "spell" in card_type:
            return "spells"
        if roles.intersection({"Négation", "Removal", "Interaction", "Tech de Side"}):
            return "interactions"
        return "generic"

    @classmethod
    def _annotate_freespot(cls, row: dict[str, Any]) -> None:
        category = cls._freespot_category(row)
        row["freespot_category"] = category
        row["freespot_category_label"] = FREESPOT_CATEGORY_LABELS.get(category) if category else None
        row["is_freespot_candidate"] = bool(category)

    @staticmethod
    def _image_url(card: dict[str, Any]) -> str | None:
        """Renvoie toujours l'URL locale Hamtaro quand l'identifiant est connu.

        La route locale télécharge l'image une seule fois puis la sert depuis le cache
        du bot, ce qui évite de hotlinker l'hébergeur d'images à chaque affichage.
        """
        try:
            card_id = int(card.get("id") or 0)
        except (TypeError, ValueError):
            card_id = 0
        if card_id > 0:
            return f"/api/deck-builder/card-image/{card_id}.jpg"
        return None

    @staticmethod
    def _line_price(price: float | None, copies: int) -> float | None:
        if price is None:
            return None
        return round(price * copies, 2)

    def _usage_rows(
        self,
        samples: list[DeckSample],
        cards: dict[int, dict[str, Any]],
        zone: str,
        query: str,
        trends: dict[int, dict[str, float | None]],
    ) -> list[dict[str, Any]]:
        zone_values: dict[int, list[tuple[int, float]]] = defaultdict(list)
        eligible_samples = [sample for sample in samples if zone != "side" or sample.side]
        total_weight = sum(sample.weight for sample in eligible_samples)
        for sample in eligible_samples:
            counts = Counter(getattr(sample, zone))
            for card_id, copies in counts.items():
                zone_values[card_id].append((copies, sample.weight))
        rows: list[dict[str, Any]] = []
        for card_id, appearances in zone_values.items():
            card = cards.get(card_id)
            if not card:
                continue
            present_weight = sum(weight for _, weight in appearances)
            frequency = (present_weight / total_weight) if total_weight else 0.0
            copies_plain = [copies for copies, _ in appearances]
            weighted_copies_num = sum(copies * weight for copies, weight in appearances)
            weighted_copies_den = sum(weight for _, weight in appearances) or 1.0
            average_copies = weighted_copies_num / weighted_copies_den
            tcg_limit = self._tcg_limit(card)
            recommended = min(tcg_limit, max(1, self._mode(copies_plain))) if tcg_limit else 0
            max_observed = min(tcg_limit, max(copies_plain, default=0)) if tcg_limit else 0
            importance = self._importance(frequency)
            price = self._price(card)
            relation = self._relation(card, query, frequency)
            trend = trends.get(card_id, {})

            def pct_change(previous: float | None) -> float | None:
                if price is None or previous in (None, 0):
                    return None
                return round(((price - float(previous)) / float(previous)) * 100, 1)

            weighted_distribution: dict[str, float] = {}
            by_copy_weight: dict[int, float] = defaultdict(float)
            for copies, weight in appearances:
                by_copy_weight[copies] += weight
            denom = sum(by_copy_weight.values()) or 1.0
            for copies, weight in sorted(by_copy_weight.items()):
                weighted_distribution[str(copies)] = round((weight / denom) * 100, 1)

            modal_ratio_pct = max(weighted_distribution.values(), default=0.0)
            if modal_ratio_pct >= 75:
                ratio_stability = "stable"
                ratio_stability_label = "Ratio très stable"
            elif modal_ratio_pct >= 50:
                ratio_stability = "common"
                ratio_stability_label = "Ratio majoritaire"
            else:
                ratio_stability = "flexible"
                ratio_stability_label = "Ratio flexible"

            rows.append(
                {
                    "id": int(card_id),
                    "name": str(card.get("_localized_name") or card.get("name") or f"Carte {card_id}"),
                    "source_name": str(card.get("_source_name") or card.get("name") or f"Card {card_id}"),
                    "type": str(card.get("type") or ""),
                    "archetype": str(card.get("archetype") or "").strip() or None,
                    "zone": zone,
                    "frequency": round(frequency, 4),
                    "frequency_pct": round(frequency * 100, 1),
                    "sample_appearances": len(appearances),
                    "sample_denominator": len(eligible_samples),
                    "average_copies": round(average_copies, 2),
                    "recommended_copies": recommended,
                    "max_observed_copies": max_observed,
                    "copy_distribution_pct": weighted_distribution,
                    "ratio_confidence_pct": round(modal_ratio_pct, 1),
                    "ratio_stability": ratio_stability,
                    "ratio_stability_label": ratio_stability_label,
                    "importance": importance,
                    "importance_label": self._importance_label(importance),
                    "relation": relation,
                    "role": self._role(card, zone),
                    "role_tags": self._roles(card, zone),
                    "role_note": "Rôle indicatif déduit du texte/type de la carte.",
                    "why_played": (
                        f"Présente dans {round(frequency * 100, 1)} % des listes {zone.upper()} analysées, "
                        f"le plus souvent à ×{recommended}."
                    ),
                    "cardmarket_price": price,
                    "recommended_price": self._line_price(price, recommended),
                    "price_change_7d_pct": pct_change(trend.get("7d")),
                    "price_change_30d_pct": pct_change(trend.get("30d")),
                    "tcg_limit": tcg_limit,
                    "ban_tcg": (card.get("banlist_info") or {}).get("ban_tcg"),
                    "image_url": self._image_url(card),
                    "cardmarket_url": CARDMARKET_SEARCH + quote_plus(str(card.get("_source_name") or card.get("name") or "")),
                    "neuron_url": NEURON_SEARCH + quote_plus(str(card.get("_localized_name") or card.get("name") or "")),
                    "score": round(frequency * 100 + min(10.0, average_copies * 2), 3),
                }
            )
        for row in rows:
            self._annotate_freespot(row)
        rows.sort(
            key=lambda row: (row["frequency"], row["average_copies"], -(row["cardmarket_price"] or 0.0)),
            reverse=True,
        )
        return rows

    @staticmethod
    def _variant_rows(samples: list[DeckSample], query: str) -> list[dict[str, Any]]:
        normalized_query = query.casefold()
        counts: dict[str, dict[str, Any]] = {}
        for sample in samples:
            title = re.sub(r"\s+", " ", sample.title).strip()
            # Retire quelques suffixes purement éditoriaux pour regrouper les listes proches.
            display = re.sub(r"\s*[-–|]\s*(?:Top\s*\d+|Winner|Runner-Up|\d+(?:st|nd|rd|th) Place).*$", "", title, flags=re.I)
            display = display.strip() or title
            key = display.casefold()
            item = counts.setdefault(
                key,
                {"name": display, "count": 0, "tournament_count": 0, "weight": 0.0},
            )
            item["count"] += 1
            item["tournament_count"] += int(sample.is_tournament)
            item["weight"] += sample.weight
        variants = sorted(counts.values(), key=lambda item: (item["weight"], item["count"]), reverse=True)
        if variants and all(item["name"].casefold() != normalized_query for item in variants):
            variants.insert(
                0,
                {
                    "name": query,
                    "count": len(samples),
                    "tournament_count": sum(1 for sample in samples if sample.is_tournament),
                    "weight": round(sum(sample.weight for sample in samples), 3),
                    "aggregate": True,
                },
            )
        for item in variants:
            item["weight"] = round(float(item["weight"]), 3)
        return variants[:16]

    @staticmethod
    def _source_rows(samples: list[DeckSample]) -> list[dict[str, Any]]:
        return [
            {
                "title": sample.title,
                "url": sample.url,
                "tournament": sample.is_tournament,
                "published": sample.published,
                "placement": sample.placement,
                "weight": sample.weight,
                "main_count": len(sample.main),
                "extra_count": len(sample.extra),
                "side_count": len(sample.side),
            }
            for sample in samples
        ]

    @staticmethod
    def _sum_known_prices(rows: Iterable[dict[str, Any]], *, relation_only: bool = False) -> dict[str, Any]:
        total = 0.0
        unknown = 0
        lines = 0
        for row in rows:
            if relation_only and row.get("relation") == "generic":
                continue
            if row.get("importance") not in {"core", "frequent"}:
                continue
            lines += 1
            value = row.get("recommended_price")
            if value is None:
                unknown += 1
            else:
                total += float(value)
        return {"known_total": round(total, 2), "unknown_price_lines": unknown, "lines": lines}

    @staticmethod
    def _confidence(samples: list[DeckSample]) -> dict[str, Any]:
        if not samples:
            return {"score": 0, "label": "Aucune donnée", "level": "none"}
        count_score = min(55.0, len(samples) / 24.0 * 55.0)
        tournament_ratio = sum(1 for sample in samples if sample.is_tournament) / len(samples)
        tournament_score = tournament_ratio * 25.0
        dated_ratio = sum(1 for sample in samples if sample.published) / len(samples)
        date_score = dated_ratio * 10.0
        side_ratio = sum(1 for sample in samples if sample.side) / len(samples)
        completeness_score = min(10.0, 5.0 + side_ratio * 5.0)
        score = int(round(min(100.0, count_score + tournament_score + date_score + completeness_score)))
        if score >= 80:
            return {"score": score, "label": "Très fiable", "level": "high"}
        if score >= 60:
            return {"score": score, "label": "Fiable", "level": "good"}
        if score >= 35:
            return {"score": score, "label": "À confirmer", "level": "medium"}
        return {"score": score, "label": "Échantillon faible", "level": "low"}

    @staticmethod
    def _detected_engines(rows_by_zone: dict[str, list[dict[str, Any]]], query: str) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for zone, rows in rows_by_zone.items():
            for row in rows:
                archetype = str(row.get("archetype") or "").strip()
                if not archetype or row.get("relation") != "engine":
                    continue
                key = archetype.casefold()
                group = groups.setdefault(
                    key,
                    {
                        "name": archetype,
                        "cards": [],
                        "main_cards": 0,
                        "extra_cards": 0,
                        "side_cards": 0,
                        "frequency_sum": 0.0,
                    },
                )
                group["cards"].append(
                    {
                        "id": row.get("id"),
                        "name": row.get("name"),
                        "zone": zone,
                        "frequency_pct": row.get("frequency_pct"),
                        "recommended_copies": row.get("recommended_copies"),
                    }
                )
                group[f"{zone}_cards"] += 1
                group["frequency_sum"] += float(row.get("frequency") or 0.0)
        engines: list[dict[str, Any]] = []
        for group in groups.values():
            card_count = len(group["cards"])
            group["average_frequency_pct"] = round((group.pop("frequency_sum") / max(1, card_count)) * 100, 1)
            group["cards"].sort(key=lambda card: float(card.get("frequency_pct") or 0), reverse=True)
            engines.append(group)
        engines.sort(key=lambda group: (group["average_frequency_pct"], len(group["cards"])), reverse=True)
        return engines[:12]

    @staticmethod
    def _deck_profile(rows_by_zone: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        targets = {"main": 40, "extra": 15, "side": 15}
        for zone, target in targets.items():
            rows = rows_by_zone.get(zone) or []
            core_slots = sum(
                min(int(row.get("recommended_copies") or 0), int(row.get("tcg_limit") or 3))
                for row in rows
                if row.get("importance") == "core"
            )
            frequent_slots = sum(
                min(int(row.get("recommended_copies") or 0), int(row.get("tcg_limit") or 3))
                for row in rows
                if row.get("importance") == "frequent"
            )
            result[zone] = {
                "target": target,
                "core_slots": min(target, core_slots),
                "frequent_slots": min(target, frequent_slots),
                "flex_slots_estimate": max(0, target - min(target, core_slots + frequent_slots)),
                "observed_unique_cards": len(rows),
            }
        return result

    @staticmethod
    def _source_freshness(samples: list[DeckSample]) -> dict[str, Any]:
        dated: list[date] = []
        for sample in samples:
            if not sample.published:
                continue
            try:
                dated.append(date.fromisoformat(sample.published))
            except ValueError:
                continue
        if not dated:
            return {"newest": None, "oldest": None, "dated_samples": 0, "undated_samples": len(samples)}
        return {
            "newest": max(dated).isoformat(),
            "oldest": min(dated).isoformat(),
            "dated_samples": len(dated),
            "undated_samples": max(0, len(samples) - len(dated)),
        }

    @staticmethod
    def _composition_profile(rows_by_zone: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for zone in ("main", "extra", "side"):
            counter: Counter[str] = Counter()
            for row in rows_by_zone.get(zone) or []:
                if float(row.get("frequency") or 0.0) < 0.15:
                    continue
                copies = max(1, int(row.get("recommended_copies") or 1))
                for role in row.get("role_tags") or [row.get("role") or "Autre"]:
                    counter[str(role)] += copies
            total = sum(counter.values()) or 1
            result[zone] = [
                {"role": role, "slots": slots, "share_pct": round(slots / total * 100, 1)}
                for role, slots in counter.most_common(8)
            ]
        return result

    @classmethod
    def _freespot_analysis(
        cls, samples: list[DeckSample], rows_by_zone: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        """Synthétise les slots génériques observés pour le deck recherché, quel qu'il soit."""
        generic_main_ids = {
            int(row.get("id") or 0)
            for row in rows_by_zone.get("main") or []
            if row.get("is_freespot_candidate")
        }
        weighted_slots = 0.0
        total_weight = 0.0
        raw_slots: list[int] = []
        for sample in samples:
            count = sum(1 for card_id in sample.main if card_id in generic_main_ids)
            weighted_slots += count * sample.weight
            total_weight += sample.weight
            raw_slots.append(count)
        average_slots = round(weighted_slots / total_weight, 1) if total_weight else 0.0
        sorted_slots = sorted(raw_slots)
        if sorted_slots:
            middle = len(sorted_slots) // 2
            median_slots = sorted_slots[middle] if len(sorted_slots) % 2 else round((sorted_slots[middle - 1] + sorted_slots[middle]) / 2, 1)
        else:
            median_slots = 0

        category_rows: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"main": [], "side": []})
        for zone in ("main", "side"):
            for row in rows_by_zone.get(zone) or []:
                category = row.get("freespot_category")
                if not category or float(row.get("frequency") or 0.0) < 0.08:
                    continue
                category_rows[str(category)][zone].append(row)

        categories: list[dict[str, Any]] = []
        for key in FREESPOT_CATEGORY_LABELS:
            main_rows = sorted(category_rows[key]["main"], key=lambda row: (float(row.get("frequency") or 0), float(row.get("score") or 0)), reverse=True)
            side_rows = sorted(category_rows[key]["side"], key=lambda row: (float(row.get("frequency") or 0), float(row.get("score") or 0)), reverse=True)
            if not main_rows and not side_rows:
                continue
            categories.append({
                "key": key,
                "label": FREESPOT_CATEGORY_LABELS[key],
                "main_candidates": main_rows[:12],
                "side_candidates": side_rows[:12],
                "main_unique": len(main_rows),
                "side_unique": len(side_rows),
            })
        return {
            "main_generic_slots_average": average_slots,
            "main_generic_slots_median": median_slots,
            "main_generic_slots_min": min(raw_slots) if raw_slots else 0,
            "main_generic_slots_max": max(raw_slots) if raw_slots else 0,
            "samples": len(samples),
            "categories": categories,
            "profiles": [{"key": key, **value} for key, value in FREESPOT_PROFILES.items()],
            "note": "Les freespots sont déduits des cartes génériques réellement observées dans les decklists du deck recherché. Ils varient selon le deck, la période et le format.",
        }

    @staticmethod
    def _cooccurrence_packages(
        samples: list[DeckSample],
        rows_by_zone: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Détecte des micro-packages par cooccurrence pondérée.

        Ce n'est pas une preuve de combo : on cherche seulement des cartes dont la
        présence varie ensemble bien plus que ne le ferait leur popularité globale.
        Les nœuds sont zone+carte afin de ne pas confondre une tech Main et Side.
        """
        if len(samples) < 4:
            return []
        meta: dict[str, dict[str, Any]] = {}
        for zone in ("main", "extra", "side"):
            for row in rows_by_zone.get(zone) or []:
                frequency = float(row.get("frequency") or 0.0)
                if frequency < 0.12:
                    continue
                key = f"{zone}:{int(row.get('id') or 0)}"
                meta[key] = {
                    "id": int(row.get("id") or 0),
                    "name": row.get("name"),
                    "zone": zone,
                    "relation": row.get("relation"),
                    "archetype": row.get("archetype"),
                    "frequency_pct": row.get("frequency_pct"),
                    "recommended_copies": row.get("recommended_copies"),
                    "image_url": row.get("image_url"),
                }
        if len(meta) < 2:
            return []
        total_weight = sum(float(sample.weight) for sample in samples) or 1.0
        presence: defaultdict[str, float] = defaultdict(float)
        pair_weight: defaultdict[tuple[str, str], float] = defaultdict(float)
        for sample in samples:
            nodes: set[str] = set()
            for zone in ("main", "extra", "side"):
                for cid in set(getattr(sample, zone)):
                    key = f"{zone}:{cid}"
                    if key in meta:
                        nodes.add(key)
            ordered = sorted(nodes)
            for node in ordered:
                presence[node] += float(sample.weight)
            for index, left in enumerate(ordered):
                for right in ordered[index + 1:]:
                    pair_weight[(left, right)] += float(sample.weight)

        adjacency: defaultdict[str, set[str]] = defaultdict(set)
        edge_stats: dict[tuple[str, str], tuple[float, float, float]] = {}
        for (left, right), together_weight in pair_weight.items():
            pa = presence[left] / total_weight
            pb = presence[right] / total_weight
            support = together_weight / total_weight
            if pa <= 0 or pb <= 0:
                continue
            confidence = min(together_weight / presence[left], together_weight / presence[right])
            lift = support / (pa * pb)
            # Évite les faux packages où une carte universelle est simplement présente partout.
            if support < 0.14 or confidence < 0.72 or lift < 1.12:
                continue
            adjacency[left].add(right)
            adjacency[right].add(left)
            edge_stats[tuple(sorted((left, right)))] = (support, confidence, lift)

        packages: list[dict[str, Any]] = []
        visited: set[str] = set()
        for start in sorted(adjacency, key=lambda key: len(adjacency[key]), reverse=True):
            if start in visited:
                continue
            stack = [start]
            component: list[str] = []
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                component.append(node)
                stack.extend(sorted(adjacency[node] - visited))
            if len(component) < 2:
                continue
            # Les gros graphes sont tronqués aux cartes les plus représentatives.
            component.sort(key=lambda node: presence[node], reverse=True)
            component = component[:8]
            internal = []
            for i, left in enumerate(component):
                for right in component[i + 1:]:
                    stat = edge_stats.get(tuple(sorted((left, right))))
                    if stat:
                        internal.append(stat)
            if not internal:
                continue
            avg_support = sum(item[0] for item in internal) / len(internal)
            avg_confidence = sum(item[1] for item in internal) / len(internal)
            avg_lift = sum(item[2] for item in internal) / len(internal)
            cards = [meta[node] for node in component]
            archetypes = [str(card.get("archetype") or "").strip() for card in cards if card.get("archetype")]
            common_archetype = Counter(archetypes).most_common(1)[0][0] if archetypes else None
            name = f"Package {common_archetype}" if common_archetype else f"Package statistique {len(packages) + 1}"
            packages.append({
                "name": name,
                "cards": cards,
                "support_pct": round(avg_support * 100, 1),
                "cohesion_pct": round(avg_confidence * 100, 1),
                "lift": round(avg_lift, 2),
                "card_count": len(cards),
                "note": "Association statistique observée dans les decklists ; elle ne prouve pas à elle seule une combo.",
            })
        packages.sort(key=lambda item: (item["cohesion_pct"], item["support_pct"], item["card_count"]), reverse=True)
        return packages[:8]

    @staticmethod
    def _engine_comparisons(
        samples: list[DeckSample],
        rows_by_zone: dict[str, list[dict[str, Any]]],
        engines: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Compare automatiquement les listes avec/sans les principaux moteurs détectés."""
        if len(samples) < 6:
            return []
        row_lookup: dict[tuple[str, int], dict[str, Any]] = {}
        for zone in ("main", "extra", "side"):
            for row in rows_by_zone.get(zone) or []:
                row_lookup[(zone, int(row.get("id") or 0))] = row
        results: list[dict[str, Any]] = []
        for engine in engines[:5]:
            engine_ids = {int(card.get("id") or 0) for card in engine.get("cards") or [] if int(card.get("id") or 0) > 0}
            if not engine_ids:
                continue
            with_samples = [s for s in samples if engine_ids.intersection(set(s.main + s.extra))]
            without_samples = [s for s in samples if not engine_ids.intersection(set(s.main + s.extra))]
            if len(with_samples) < 2 or len(without_samples) < 2:
                continue

            def zone_freq(group: list[DeckSample], zone: str) -> dict[int, float]:
                total = sum(float(sample.weight) for sample in group) or 1.0
                present: defaultdict[int, float] = defaultdict(float)
                eligible = [sample for sample in group if zone != "side" or sample.side]
                total = sum(float(sample.weight) for sample in eligible) or 1.0
                for sample in eligible:
                    for cid in set(getattr(sample, zone)):
                        present[cid] += float(sample.weight)
                return {cid: weight / total for cid, weight in present.items()}

            signatures_with: list[dict[str, Any]] = []
            signatures_without: list[dict[str, Any]] = []
            for zone in ("main", "extra", "side"):
                fw = zone_freq(with_samples, zone)
                fwo = zone_freq(without_samples, zone)
                for cid in set(fw) | set(fwo):
                    row = row_lookup.get((zone, cid))
                    if not row:
                        continue
                    delta = fw.get(cid, 0.0) - fwo.get(cid, 0.0)
                    item = {
                        "id": cid,
                        "name": row.get("name"),
                        "zone": zone,
                        "with_pct": round(fw.get(cid, 0.0) * 100, 1),
                        "without_pct": round(fwo.get(cid, 0.0) * 100, 1),
                        "delta_pct": round(abs(delta) * 100, 1),
                    }
                    if delta >= 0.18 and cid not in engine_ids:
                        signatures_with.append(item)
                    elif delta <= -0.18:
                        signatures_without.append(item)
            signatures_with.sort(key=lambda item: item["delta_pct"], reverse=True)
            signatures_without.sort(key=lambda item: item["delta_pct"], reverse=True)
            results.append({
                "engine": engine.get("name"),
                "with_count": len(with_samples),
                "without_count": len(without_samples),
                "with_signature": signatures_with[:6],
                "without_signature": signatures_without[:6],
            })
        return results[:4]

    @staticmethod
    def _observed_configurations(
        samples: list[DeckSample],
        rows_by_zone: dict[str, list[dict[str, Any]]],
        engines: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Regroupe les decklists selon les moteurs secondaires réellement présents.

        Ce regroupement est indépendant du titre publié par l'auteur. Deux listes aux
        noms différents mais utilisant les mêmes moteurs sont donc comparées ensemble.
        """
        if len(samples) < 4:
            return []
        engine_map: list[tuple[str, set[int]]] = []
        for engine in engines[:6]:
            ids = {
                int(card.get("id") or 0)
                for card in engine.get("cards") or []
                if int(card.get("id") or 0) > 0 and str(card.get("zone") or "") != "side"
            }
            if ids:
                engine_map.append((str(engine.get("name") or "Moteur"), ids))
        if not engine_map:
            return []

        groups: dict[tuple[str, ...], list[DeckSample]] = defaultdict(list)
        for sample in samples:
            deck_ids = set(sample.main + sample.extra)
            signature = tuple(sorted(name for name, ids in engine_map if deck_ids.intersection(ids)))
            groups[signature].append(sample)

        total_weight = sum(float(sample.weight) for sample in samples) or 1.0
        row_lookup: dict[tuple[str, int], dict[str, Any]] = {}
        for zone in ("main", "extra", "side"):
            for row in rows_by_zone.get(zone) or []:
                row_lookup[(zone, int(row.get("id") or 0))] = row

        def weighted_freq(group: list[DeckSample], zone: str) -> dict[int, float]:
            eligible = [sample for sample in group if zone != "side" or sample.side]
            denom = sum(float(sample.weight) for sample in eligible) or 1.0
            present: defaultdict[int, float] = defaultdict(float)
            for sample in eligible:
                for cid in set(getattr(sample, zone)):
                    present[cid] += float(sample.weight)
            return {cid: weight / denom for cid, weight in present.items()}

        baseline = {zone: weighted_freq(samples, zone) for zone in ("main", "extra", "side")}
        results: list[dict[str, Any]] = []
        for signature, group in groups.items():
            if len(group) < 2:
                continue
            group_weight = sum(float(sample.weight) for sample in group)
            signature_cards: list[dict[str, Any]] = []
            lock_cards: list[dict[str, Any]] = []
            for zone in ("main", "extra", "side"):
                freq = weighted_freq(group, zone)
                for cid, inside in freq.items():
                    row = row_lookup.get((zone, cid))
                    if not row:
                        continue
                    outside = baseline[zone].get(cid, 0.0)
                    delta = inside - outside
                    if inside >= 0.5 and (delta >= 0.12 or row.get("relation") == "engine"):
                        signature_cards.append({
                            "id": cid,
                            "name": row.get("name"),
                            "zone": zone,
                            "inside_pct": round(inside * 100, 1),
                            "overall_pct": round(outside * 100, 1),
                            "delta_pct": round(delta * 100, 1),
                            "recommended_copies": row.get("recommended_copies"),
                            "relation": row.get("relation"),
                        })
                    if zone != "side" and inside >= 0.62 and row.get("importance") in {"core", "frequent"}:
                        lock_cards.append({
                            "id": cid,
                            "name": row.get("name"),
                            "zone": zone,
                            "copies": min(int(row.get("recommended_copies") or 1), int(row.get("tcg_limit") or 3)),
                        })
            signature_cards.sort(key=lambda item: (item["delta_pct"], item["inside_pct"]), reverse=True)
            # Évite de verrouiller 25 cartes au clic : on garde seulement les pièces
            # caractéristiques les plus stables de cette construction.
            lock_ids = {(item["zone"], item["id"]) for item in signature_cards[:10]}
            lock_cards = [item for item in lock_cards if (item["zone"], item["id"]) in lock_ids][:10]
            if signature:
                name = " + ".join(signature)
                label = f"Avec {name}"
            else:
                label = "Sans moteur secondaire détecté"
            results.append({
                "name": label,
                "engines": list(signature),
                "sample_count": len(group),
                "tournament_count": sum(1 for sample in group if sample.is_tournament),
                "share_pct": round(group_weight / total_weight * 100, 1),
                "signature_cards": signature_cards[:8],
                "lock_cards": lock_cards,
            })
        results.sort(key=lambda item: (item["share_pct"], item["sample_count"]), reverse=True)
        return results[:8]

    @staticmethod
    def _flex_choice_pairs(
        samples: list[DeckSample],
        rows_by_zone: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Repère des cartes de rôle similaire qui se remplacent souvent entre les listes.

        On ne prétend pas qu'elles sont fonctionnellement identiques : le signal dit
        seulement qu'elles occupent souvent le même type de slot sans être jouées ensemble.
        """
        if len(samples) < 6:
            return []
        choices: list[dict[str, Any]] = []
        for zone in ("main", "extra", "side"):
            eligible_samples = [sample for sample in samples if zone != "side" or sample.side]
            total_weight = sum(float(sample.weight) for sample in eligible_samples) or 1.0
            candidates = [
                row for row in rows_by_zone.get(zone) or []
                if 0.12 <= float(row.get("frequency") or 0.0) <= 0.72
                and row.get("importance") in {"frequent", "option", "rare"}
            ][:40]
            if len(candidates) < 2:
                continue
            presence: defaultdict[int, float] = defaultdict(float)
            together: defaultdict[tuple[int, int], float] = defaultdict(float)
            candidate_ids = {int(row.get("id") or 0) for row in candidates}
            for sample in eligible_samples:
                ids = sorted(candidate_ids.intersection(set(getattr(sample, zone))))
                for cid in ids:
                    presence[cid] += float(sample.weight)
                for index, left in enumerate(ids):
                    for right in ids[index + 1:]:
                        together[(left, right)] += float(sample.weight)
            pairs: list[dict[str, Any]] = []
            for index, left in enumerate(candidates):
                lid = int(left.get("id") or 0)
                left_roles = set(left.get("role_tags") or [left.get("role")])
                for right in candidates[index + 1:]:
                    rid = int(right.get("id") or 0)
                    shared_roles = sorted(role for role in left_roles.intersection(set(right.get("role_tags") or [right.get("role")])) if role)
                    if not shared_roles:
                        continue
                    pa = presence[lid] / total_weight
                    pb = presence[rid] / total_weight
                    joint = together.get(tuple(sorted((lid, rid))), 0.0) / total_weight
                    denom = min(pa, pb)
                    if denom <= 0:
                        continue
                    exclusivity = max(0.0, 1.0 - joint / denom)
                    union = pa + pb - joint
                    if exclusivity < 0.55 or union < 0.32:
                        continue
                    score = exclusivity * union * (1.0 + min(pa, pb))
                    pairs.append({
                        "zone": zone,
                        "role": shared_roles[0],
                        "exclusivity_pct": round(exclusivity * 100, 1),
                        "coverage_pct": round(union * 100, 1),
                        "score": round(score, 4),
                        "options": [
                            {
                                "id": lid, "name": left.get("name"), "frequency_pct": left.get("frequency_pct"),
                                "recommended_copies": left.get("recommended_copies"), "cardmarket_price": left.get("cardmarket_price"),
                                "image_url": left.get("image_url"), "importance": left.get("importance"),
                            },
                            {
                                "id": rid, "name": right.get("name"), "frequency_pct": right.get("frequency_pct"),
                                "recommended_copies": right.get("recommended_copies"), "cardmarket_price": right.get("cardmarket_price"),
                                "image_url": right.get("image_url"), "importance": right.get("importance"),
                            },
                        ],
                        "note": "Ces cartes de rôle proche apparaissent rarement ensemble dans l'échantillon ; elles peuvent correspondre à un choix de slot flex.",
                    })
            pairs.sort(key=lambda item: item["score"], reverse=True)
            used: set[int] = set()
            for pair in pairs:
                ids = {int(option["id"]) for option in pair["options"]}
                if ids.intersection(used):
                    continue
                choices.append(pair)
                used.update(ids)
                if len([item for item in choices if item["zone"] == zone]) >= 4:
                    break
        choices.sort(key=lambda item: item["score"], reverse=True)
        return choices[:10]

    @staticmethod
    def _coherence_diagnostics(
        selected_by_zone: dict[str, list[dict[str, Any]]],
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        """Mesure l'écart au consensus sans porter de jugement stratégique absolu."""
        selected_lookup = {
            zone: {int(row.get("id") or 0): row for row in selected_by_zone.get(zone) or []}
            for zone in ("main", "extra", "side")
        }
        weighted_score = 0.0
        weighted_total = 0.0
        ratio_mismatches: list[dict[str, Any]] = []
        flex_lines = 0
        rare_lines = 0
        for zone in ("main", "extra", "side"):
            observed = {int(row.get("id") or 0): row for row in analysis.get("zones", {}).get(zone, []) or []}
            for cid, selected in selected_lookup[zone].items():
                reference = observed.get(cid)
                if not reference:
                    continue
                freq = max(0.05, float(reference.get("frequency") or 0.0))
                wanted = max(1, int(reference.get("recommended_copies") or 1))
                have = max(0, int(selected.get("copies") or 0))
                deviation = abs(have - wanted) / wanted
                match = max(0.0, 1.0 - min(1.0, deviation))
                weighted_score += freq * match
                weighted_total += freq
                importance = str(reference.get("importance") or "rare")
                if importance in {"option", "rare"}:
                    flex_lines += 1
                if importance == "rare":
                    rare_lines += 1
                if reference.get("ratio_stability") == "stable" and have != wanted:
                    ratio_mismatches.append({
                        "zone": zone,
                        "id": cid,
                        "name": reference.get("name"),
                        "selected": have,
                        "usual": wanted,
                        "ratio_confidence_pct": reference.get("ratio_confidence_pct"),
                    })
        ratio_alignment = int(round(weighted_score / weighted_total * 100)) if weighted_total else 0

        package_health: list[dict[str, Any]] = []
        for package in analysis.get("packages") or []:
            cards = package.get("cards") or []
            if not cards:
                continue
            present = 0
            for card in cards:
                zone = str(card.get("zone") or "main")
                if int(card.get("id") or 0) in selected_lookup.get(zone, {}):
                    present += 1
            if present <= 0:
                continue
            coverage = present / len(cards)
            package_health.append({
                "name": package.get("name"),
                "present": present,
                "total": len(cards),
                "coverage_pct": round(coverage * 100, 1),
                "status": "complete" if coverage >= 0.999 else "partial",
            })
        package_health.sort(key=lambda item: (item["status"] != "partial", -item["coverage_pct"]))

        role_counts: Counter[str] = Counter()
        for row in selected_by_zone.get("main") or []:
            copies = max(0, int(row.get("copies") or 0))
            for role in row.get("role_tags") or [row.get("role") or "Autre"]:
                role_counts[str(role)] += copies
        role_summary = [{"role": role, "copies": copies} for role, copies in role_counts.most_common(8)]
        signals: list[dict[str, Any]] = []
        if ratio_mismatches:
            signals.append({
                "type": "ratio",
                "label": f"{len(ratio_mismatches)} ratio(s) stable(s) différent(s) du consensus",
                "detail": "Ce n'est pas forcément une erreur : ce sont simplement les écarts les plus nets aux ratios observés.",
            })
        partial_packages = [item for item in package_health if item["status"] == "partial"]
        if partial_packages:
            signals.append({
                "type": "package",
                "label": f"{len(partial_packages)} package(s) statistique(s) partiellement présent(s)",
                "detail": "Vérifie si les cartes manquantes sont volontairement remplacées ou si le package est incomplet.",
            })
        signals.append({
            "type": "flex",
            "label": f"{flex_lines} choix flex / optionnel(s) dans la liste",
            "detail": f"Dont {rare_lines} choix rarement observé(s) dans l'échantillon actuel.",
        })
        return {
            "ratio_alignment_score": ratio_alignment,
            "ratio_mismatches": ratio_mismatches[:12],
            "package_health": package_health[:8],
            "role_summary": role_summary,
            "flex_lines": flex_lines,
            "rare_lines": rare_lines,
            "signals": signals,
            "note": "Diagnostic descriptif fondé sur les decklists analysées ; il ne remplace pas un test réel du deck.",
        }

    @staticmethod
    def _opening_hand_stats(selected_by_zone: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        """Estimation hypergéométrique sur 5 cartes, basée sur les rôles heuristiques."""
        main = selected_by_zone.get("main") or []
        total = sum(max(0, int(row.get("copies") or 0)) for row in main)
        if total < 5:
            return {"available": False, "note": "Main Deck incomplet : estimation non calculée."}
        starter_roles = {"Starter", "Searcher"}
        interaction_roles = {"Hand trap", "Interaction", "Négation", "Removal", "Board breaker"}
        starter_copies = 0
        interaction_copies = 0
        for row in main:
            copies = max(0, int(row.get("copies") or 0))
            roles = set(row.get("role_tags") or [row.get("role")])
            if roles & starter_roles:
                starter_copies += copies
            if roles & interaction_roles:
                interaction_copies += copies

        def probability(hits: int) -> float:
            hits = max(0, min(total, hits))
            if hits <= 0:
                return 0.0
            misses = total - hits
            no_hit = (math.comb(misses, 5) / math.comb(total, 5)) if misses >= 5 else 0.0
            return round((1.0 - no_hit) * 100, 1)

        return {
            "available": True,
            "deck_size": total,
            "hand_size": 5,
            "starter_copies": starter_copies,
            "starter_open_pct": probability(starter_copies),
            "interaction_copies": interaction_copies,
            "interaction_open_pct": probability(interaction_copies),
            "note": "Estimation indicative : les rôles Starter/Interaction sont déduits automatiquement du texte des cartes et ne modélisent pas les combos exactes.",
        }

    async def synergies(
        self,
        query: str,
        card_id: int,
        zone: str,
        *,
        max_decks: int | None = None,
        tournament_only: bool = False,
        days: int | None = None,
        variant: str | None = None,
    ) -> dict[str, Any]:
        """Cartes statistiquement plus présentes quand la carte source est jouée."""
        zone = zone if zone in {"main", "extra", "side"} else "main"
        clean = re.sub(r"\s+", " ", str(query or "")).strip()
        samples = await self.search_samples(clean, max_decks=max_decks)
        samples = self._filter_samples(samples, tournament_only=tournament_only, days=days, variant=variant, base_query=clean)
        if len(samples) < 3:
            return {"query": clean, "card_id": card_id, "zone": zone, "synergies": [], "note": "Échantillon insuffisant pour mesurer les associations."}
        source_samples = [sample for sample in samples if card_id in getattr(sample, zone)]
        if len(source_samples) < 2:
            return {"query": clean, "card_id": card_id, "zone": zone, "synergies": [], "note": "La carte source apparaît trop rarement pour mesurer une association fiable."}
        baseline: defaultdict[tuple[str, int], float] = defaultdict(float)
        together: defaultdict[tuple[str, int], float] = defaultdict(float)
        source_copies: dict[tuple[str, int], list[int]] = defaultdict(list)
        total_by_zone = {
            other_zone: sum(float(sample.weight) for sample in samples if other_zone != "side" or sample.side) or 1.0
            for other_zone in ("main", "extra", "side")
        }
        source_total_by_zone = {
            other_zone: sum(float(sample.weight) for sample in source_samples if other_zone != "side" or sample.side) or 1.0
            for other_zone in ("main", "extra", "side")
        }
        for sample in samples:
            for other_zone in ("main", "extra", "side"):
                if other_zone == "side" and not sample.side:
                    continue
                counts = Counter(getattr(sample, other_zone))
                for cid in counts:
                    baseline[(other_zone, cid)] += float(sample.weight)
        for sample in source_samples:
            for other_zone in ("main", "extra", "side"):
                if other_zone == "side" and not sample.side:
                    continue
                counts = Counter(getattr(sample, other_zone))
                for cid, copies in counts.items():
                    if cid == card_id and other_zone == zone:
                        continue
                    together[(other_zone, cid)] += float(sample.weight)
                    source_copies[(other_zone, cid)].append(copies)
        ranked: list[tuple[float, str, int, float, float, float]] = []
        for (other_zone, cid), pair_weight in together.items():
            conditional = pair_weight / source_total_by_zone[other_zone]
            overall = baseline[(other_zone, cid)] / total_by_zone[other_zone]
            if conditional < 0.22 or overall <= 0:
                continue
            lift = conditional / overall
            if lift < 1.08 and conditional < 0.65:
                continue
            strength = conditional * min(2.5, lift)
            ranked.append((strength, other_zone, cid, conditional, overall, lift))
        ranked.sort(reverse=True)
        ids = [cid for _, _, cid, _, _, _ in ranked[:36]] + [card_id]
        cards = await self.card_data_by_ids(ids)
        source_card = cards.get(card_id, {})
        rows: list[dict[str, Any]] = []
        for _, other_zone, cid, conditional, overall, lift in ranked[:12]:
            card = cards.get(cid)
            if not card:
                continue
            copies = source_copies[(other_zone, cid)]
            recommended = min(self._tcg_limit(card), max(1, self._mode(copies))) if self._tcg_limit(card) else 0
            if lift >= 1.5 and conditional >= 0.5:
                strength_label = "Association forte"
            elif lift >= 1.2 or conditional >= 0.5:
                strength_label = "Association nette"
            else:
                strength_label = "Souvent ensemble"
            rows.append({
                "id": cid,
                "name": str(card.get("_localized_name") or card.get("name") or cid),
                "zone": other_zone,
                "together_pct": round(conditional * 100, 1),
                "overall_pct": round(overall * 100, 1),
                "lift": round(lift, 2),
                "strength_label": strength_label,
                "recommended_copies": recommended,
                "cardmarket_price": self._price(card),
                "image_url": self._image_url(card),
                "reason": f"Présente dans {round(conditional * 100, 1)} % des listes qui jouent la carte source, contre {round(overall * 100, 1)} % au total.",
            })
        return {
            "query": clean,
            "card_id": card_id,
            "card_name": str(source_card.get("_localized_name") or source_card.get("name") or card_id),
            "zone": zone,
            "source_samples": len(source_samples),
            "samples": len(samples),
            "synergies": rows,
            "note": "Association statistique de deckbuilding : cela indique que les cartes sont souvent jouées ensemble, pas qu'une interaction de règles a été prouvée.",
        }

    async def _official_banlist_meta(self) -> dict[str, Any]:
        meta = {"source": "Konami", "url": KONAMI_BANLIST_URL, "effective_from": None, "verified": False}
        try:
            body = await self._fetch_text(KONAMI_BANLIST_URL, ttl_hours=24)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return meta
        match = re.search(r"Effective\s+from\s+(\d{1,2})/(\d{1,2})/(\d{4})", body, flags=re.I)
        if match:
            day, month, year = map(int, match.groups())
            try:
                meta["effective_from"] = date(year, month, day).isoformat()
                meta["verified"] = True
            except ValueError:
                pass
        return meta

    @classmethod
    def parse_deck_input(cls, text: str) -> tuple[list[int], list[int], list[int]]:
        """Accepte un code YDKE ou le texte standard d'un fichier .ydk."""
        raw = str(text or "").strip()
        if not raw:
            raise ValueError("Colle un code YDKE ou le contenu d'un fichier .ydk.")
        ydke_match = re.search(r"ydke://[^\s<>'\"]+", raw, flags=re.I)
        if ydke_match:
            return cls.decode_ydke(ydke_match.group(0))
        main: list[int] = []
        extra: list[int] = []
        side: list[int] = []
        current = main
        saw_section = False
        for line in raw.splitlines():
            value = line.strip()
            if not value:
                continue
            lowered = value.casefold()
            if lowered in {"#main", "main", "main deck"}:
                current = main; saw_section = True; continue
            if lowered in {"#extra", "extra", "extra deck"}:
                current = extra; saw_section = True; continue
            if lowered in {"!side", "#side", "side", "side deck"}:
                current = side; saw_section = True; continue
            if value.startswith("#") or value.startswith("!"):
                continue
            if re.fullmatch(r"\d{5,10}", value):
                current.append(int(value))
        if not saw_section and not (main or extra or side):
            raise ValueError("Format non reconnu. Utilise un code YDKE ou le contenu d'un fichier .ydk.")
        if not main and not extra and not side:
            raise ValueError("Aucune carte n'a été trouvée dans la liste importée.")
        return main, extra, side

    @staticmethod
    def _global_legality(rows_by_zone: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        counts: Counter[int] = Counter()
        limits: dict[int, int] = {}
        names: dict[int, str] = {}
        violations: list[dict[str, Any]] = []
        for rows in rows_by_zone.values():
            for row in rows:
                cid = int(row.get("id") or 0)
                if cid <= 0:
                    continue
                counts[cid] += int(row.get("copies") or 0)
                raw_limit = row.get("tcg_limit")
                limit = int(raw_limit) if raw_limit is not None else 3
                limits[cid] = min(limits.get(cid, 3), limit)
                names[cid] = str(row.get("name") or cid)
        for cid, count in counts.items():
            limit = limits.get(cid, 3)
            if count > limit:
                violations.append({"id": cid, "name": names.get(cid, str(cid)), "count": count, "limit": limit, "type": "tcg_limit"})
        main_count = sum(int(row.get("copies") or 0) for row in rows_by_zone.get("main") or [])
        extra_count = sum(int(row.get("copies") or 0) for row in rows_by_zone.get("extra") or [])
        side_count = sum(int(row.get("copies") or 0) for row in rows_by_zone.get("side") or [])
        if main_count and not 40 <= main_count <= 60:
            violations.append({"type": "main_size", "count": main_count, "minimum": 40, "maximum": 60})
        if extra_count > 15:
            violations.append({"type": "extra_size", "count": extra_count, "maximum": 15})
        if side_count > 15:
            violations.append({"type": "side_size", "count": side_count, "maximum": 15})
        return {"legal": not violations, "violations": violations, "main_count": main_count, "extra_count": extra_count, "side_count": side_count}

    @staticmethod
    def _enforce_global_limits(rows_by_zone: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        ids = {int(row.get("id") or 0) for rows in rows_by_zone.values() for row in rows if int(row.get("id") or 0) > 0}
        for cid in ids:
            appearances: list[tuple[str, dict[str, Any]]] = []
            limit = 3
            for zone, rows in rows_by_zone.items():
                for row in rows:
                    if int(row.get("id") or 0) == cid:
                        appearances.append((zone, row))
                        raw_limit = row.get("tcg_limit")
                        limit = min(limit, int(raw_limit) if raw_limit is not None else 3)
            overflow = max(0, sum(int(row.get("copies") or 0) for _, row in appearances) - limit)
            if not overflow:
                continue
            priority = {"side": 0, "main": 1, "extra": 2}
            for zone, row in sorted(
                appearances,
                key=lambda item: (bool(item[1].get("locked")), priority.get(item[0], 9)),
            ):
                if overflow <= 0:
                    break
                current = int(row.get("copies") or 0)
                remove = min(current, overflow)
                if remove:
                    row["copies"] = current - remove
                    overflow -= remove
                    changes.append({
                        "id": cid, "name": row.get("name"), "zone": zone,
                        "removed_copies": remove, "reason": f"limite TCG globale ×{limit}",
                        "locked_conflict": bool(row.get("locked")),
                    })
            for zone in rows_by_zone:
                rows_by_zone[zone][:] = [row for row in rows_by_zone[zone] if int(row.get("copies") or 0) > 0]
        return changes

    def _upgrade_path(self, current: dict[str, list[dict[str, Any]]], target: dict[str, list[dict[str, Any]]], owned_cards: dict[int, int] | None, label: str) -> dict[str, Any]:
        current_map = {zone: {int(r.get("id") or 0): r for r in rows} for zone, rows in current.items()}
        target_map = {zone: {int(r.get("id") or 0): r for r in rows} for zone, rows in target.items()}
        changes: list[dict[str, Any]] = []
        unknown = 0
        current_purchase = target_purchase = 0.0
        for zone in ("main", "extra", "side"):
            ids = set(current_map.get(zone, {})) | set(target_map.get(zone, {}))
            for cid in ids:
                old = current_map.get(zone, {}).get(cid)
                new = target_map.get(zone, {}).get(cid)
                old_qty = int((old or {}).get("copies") or 0)
                new_qty = int((new or {}).get("copies") or 0)
                if old_qty != new_qty:
                    source = new or old or {}
                    changes.append({"zone": zone, "id": cid, "name": source.get("name"), "from": old_qty, "to": new_qty, "delta": new_qty - old_qty, "price": source.get("cardmarket_price")})
            for row in current_map.get(zone, {}).values():
                value = self._effective_line_cost(row, int(row.get("copies") or 0), owned_cards)
                if value is None: unknown += 1
                else: current_purchase += value
            for row in target_map.get(zone, {}).values():
                value = self._effective_line_cost(row, int(row.get("copies") or 0), owned_cards)
                if value is None: unknown += 1
                else: target_purchase += value
        changes.sort(key=lambda item: (item["delta"] > 0, abs(item["delta"])), reverse=True)
        return {"label": label, "changes": changes[:30], "change_count": len(changes), "additional_known_purchase": round(max(0.0, target_purchase - current_purchase), 2), "unknown_price_lines": unknown}

    async def compare_imported_deck(self, query: str, deck_input: str, *, max_decks: int | None = None, tournament_only: bool = False, days: int | None = None, variant: str | None = None) -> dict[str, Any]:
        main_ids, extra_ids, side_ids = self.parse_deck_input(deck_input)
        analysis = await self.analyze(query, max_decks=max_decks, tournament_only=tournament_only, days=days, variant=variant)
        cards = await self.card_data_by_ids(main_ids + extra_ids + side_ids)
        zone_ids = {"main": main_ids, "extra": extra_ids, "side": side_ids}
        observed_any: dict[int, set[str]] = defaultdict(set)
        for zone, rows in analysis.get("zones", {}).items():
            for row in rows:
                observed_any[int(row.get("id") or 0)].add(zone)
        comparison: dict[str, list[dict[str, Any]]] = {}
        synthetic: dict[str, list[dict[str, Any]]] = {"main": [], "extra": [], "side": []}
        missing_core: list[dict[str, Any]] = []
        for zone, ids in zone_ids.items():
            counts = Counter(ids)
            observed = {int(row.get("id") or 0): row for row in analysis.get("zones", {}).get(zone, [])}
            rows: list[dict[str, Any]] = []
            for cid, copies in counts.items():
                card = cards.get(cid, {})
                ref = observed.get(cid)
                wrong_zone = cid in observed_any and zone not in observed_any[cid]
                if ref:
                    importance = str(ref.get("importance") or "rare")
                    status = "standard" if importance in {"core", "frequent"} else "unusual"
                    name = ref.get("name")
                    tcg_limit = int(ref.get("tcg_limit") if ref.get("tcg_limit") is not None else 3)
                else:
                    status = "wrong_zone" if wrong_zone else "unseen"
                    name = card.get("_localized_name") or card.get("name") or f"Carte {cid}"
                    tcg_limit = self._tcg_limit(card) if card else 3
                item = {"id": cid, "name": str(name), "copies": copies, "status": status, "frequency_pct": ref.get("frequency_pct") if ref else None, "importance": ref.get("importance") if ref else None, "recommended_copies": ref.get("recommended_copies") if ref else None, "tcg_limit": tcg_limit, "observed_zones": sorted(observed_any.get(cid, set())), "cardmarket_price": self._price(card) if card else (ref.get("cardmarket_price") if ref else None)}
                rows.append(item)
                synthetic[zone].append(dict(item))
            comparison[zone] = rows
            for row in analysis.get("zones", {}).get(zone, []):
                if row.get("importance") != "core":
                    continue
                cid = int(row.get("id") or 0)
                have = counts.get(cid, 0)
                wanted = min(int(row.get("recommended_copies") or 1), int(row.get("tcg_limit") or 3))
                if have < wanted:
                    missing_core.append({"zone": zone, "id": cid, "name": row.get("name"), "have": have, "recommended": wanted, "missing": wanted - have, "frequency_pct": row.get("frequency_pct")})
        denominator = matched = 0
        for zone in ("main", "extra", "side"):
            imported_counts = Counter(zone_ids[zone])
            for row in analysis.get("zones", {}).get(zone, []):
                if row.get("importance") not in {"core", "frequent"}:
                    continue
                wanted = min(int(row.get("recommended_copies") or 1), int(row.get("tcg_limit") or 3))
                denominator += wanted
                matched += min(wanted, imported_counts.get(int(row.get("id") or 0), 0))
        alignment = int(round(matched / denominator * 100)) if denominator else 0
        return {"query": analysis.get("query"), "analysis": analysis, "import": {"main_count": len(main_ids), "extra_count": len(extra_ids), "side_count": len(side_ids), "alignment_score": alignment, "zones": comparison, "missing_core": sorted(missing_core, key=lambda row: (row["zone"], -(row.get("frequency_pct") or 0))), "legality": self._global_legality(synthetic), "ydke": self.encode_ydke(main_ids, extra_ids, side_ids)}}

    async def analyze(
        self,
        query: str,
        *,
        max_decks: int | None = None,
        tournament_only: bool = False,
        days: int | None = None,
        variant: str | None = None,
    ) -> dict[str, Any]:
        clean = re.sub(r"\s+", " ", str(query or "")).strip()
        self._last_card_fetch_dates = []
        if len(clean) < 2:
            raise ValueError("Entre au moins 2 caractères pour rechercher un deck.")
        all_samples, banlist_meta = await asyncio.gather(
            self.search_samples(clean, max_decks=max_decks),
            self._official_banlist_meta(),
        )
        samples = self._filter_samples(
            all_samples,
            tournament_only=tournament_only,
            days=days,
            variant=variant,
            base_query=clean,
        )
        all_ids: list[int] = []
        for sample in samples:
            all_ids.extend(sample.main)
            all_ids.extend(sample.extra)
            all_ids.extend(sample.side)
        cards = await self.card_data_by_ids(all_ids)
        trends = await asyncio.to_thread(self._price_trends_sync, cards.keys())
        rows_by_zone = {
            "main": self._usage_rows(samples, cards, "main", clean, trends),
            "extra": self._usage_rows(samples, cards, "extra", clean, trends),
            "side": self._usage_rows(samples, cards, "side", clean, trends),
        }
        fallback_cards: list[dict[str, Any]] = []
        if not samples:
            archetype = await self.archetype_cards(clean)
            for card in archetype:
                card_type = str(card.get("type") or "")
                zone = "extra" if card_type in EXTRA_TYPES else "main"
                fallback_cards.append(
                    {
                        "id": int(card.get("id") or 0),
                        "name": str(card.get("_localized_name") or card.get("name") or "Carte"),
                        "type": card_type,
                        "archetype": card.get("archetype"),
                        "zone": zone,
                        "cardmarket_price": self._price(card),
                        "tcg_limit": self._tcg_limit(card),
                        "image_url": self._image_url(card),
                        "cardmarket_url": CARDMARKET_SEARCH + quote_plus(str(card.get("_source_name") or card.get("name") or "")),
                        "neuron_url": NEURON_SEARCH + quote_plus(str(card.get("_localized_name") or card.get("name") or "")),
                    }
                )
        core_rows = rows_by_zone["main"] + rows_by_zone["extra"]
        price_core = self._sum_known_prices(core_rows, relation_only=False)
        price_base = self._sum_known_prices(core_rows, relation_only=True)
        engines = self._detected_engines(rows_by_zone, clean)
        packages = self._cooccurrence_packages(samples, rows_by_zone)
        engine_comparisons = self._engine_comparisons(samples, rows_by_zone, engines)
        configurations = self._observed_configurations(samples, rows_by_zone, engines)
        flex_choices = self._flex_choice_pairs(samples, rows_by_zone)
        freespots = self._freespot_analysis(samples, rows_by_zone)
        warnings: list[str] = []
        if tournament_only and all_samples and not samples:
            warnings.append("Aucune liste de tournoi n'a passé les filtres choisis.")
        if days and all_samples and not samples:
            warnings.append("Aucune liste assez récente n'a passé la période choisie.")
        if samples and len(samples) < 5:
            warnings.append("Échantillon faible : les pourcentages sont à interpréter avec prudence.")
        if not samples and fallback_cards:
            warnings.append("Reconstruction TCG partielle : Hamtaro a retrouvé des cartes liées mais pas assez de decklists exploitables pour calculer des pourcentages fiables.")
        elif not samples:
            warnings.append("Recherche non résolue : aucune decklist ni carte TCG suffisamment liée n'a été retrouvée. Aucun résultat n'est inventé.")
        discovery_mode = "statistical" if samples else ("reconstructed" if fallback_cards else "unresolved")
        return {
            "query": clean,
            "variant": variant or "",
            "generated_on": date.today().isoformat(),
            "price_checked_on": min(self._last_card_fetch_dates) if self._last_card_fetch_dates else date.today().isoformat(),
            "price_source": "Cardmarket via YGOPRODeck · cartes TCG uniquement",
            "price_note": "Prix indicatifs de cartes sorties en TCG ; un prix indisponible est affiché comme inconnu.",
            "ruleset": "TCG",
            "catalog": await asyncio.to_thread(self._catalog_stats_sync),
            "samples_found_before_filters": len(all_samples),
            "samples_analyzed": len(samples),
            "tournament_samples": sum(1 for sample in samples if sample.is_tournament),
            "side_samples": sum(1 for sample in samples if sample.side),
            "discovery": dict(self._last_discovery_debug),
            "discovery_mode": discovery_mode,
            "filters": {
                "tournament_only": tournament_only,
                "days": days,
                "variant": variant or "",
            },
            "variants": self._variant_rows(all_samples, clean),
            "confidence": self._confidence(samples),
            "source_freshness": self._source_freshness(samples),
            "banlist": banlist_meta,
            "source_catalog": [
                {"name": "YGOPRODeck", "use": "decklists TCG, données de cartes TCG et prix Cardmarket disponibles"},
                {"name": "Konami / Neuron", "use": "référence officielle, liens cartes et vérification de la banlist"},
            ],
            "engines": engines,
            "packages": packages,
            "engine_comparisons": engine_comparisons,
            "configurations": configurations,
            "flex_choices": flex_choices,
            "freespots": freespots,
            "deck_profile": self._deck_profile(rows_by_zone),
            "composition": self._composition_profile(rows_by_zone),
            "zones": rows_by_zone,
            "base_price": price_base,
            "core_price": price_core,
            "sources": self._source_rows(samples),
            "fallback_archetype_cards": fallback_cards,
            "degraded": not bool(samples),
            "warnings": warnings,
        }

    @staticmethod
    def _normalize_constraints(
        locked_cards: dict[str, dict[int, int]] | None,
        excluded_cards: dict[str, Iterable[int]] | None,
    ) -> tuple[dict[str, dict[int, int]], dict[str, set[int]]]:
        locked: dict[str, dict[int, int]] = {"main": {}, "extra": {}, "side": {}}
        excluded: dict[str, set[int]] = {"main": set(), "extra": set(), "side": set()}
        for zone in ("main", "extra", "side"):
            for raw_id, raw_qty in (locked_cards or {}).get(zone, {}).items():
                try:
                    cid = int(raw_id)
                    qty = max(1, min(3, int(raw_qty)))
                except (TypeError, ValueError):
                    continue
                if cid > 0:
                    locked[zone][cid] = qty
            for raw_id in (excluded_cards or {}).get(zone, []):
                try:
                    cid = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if cid > 0:
                    excluded[zone].add(cid)
            # Un verrou gagne sur une exclusion contradictoire dans la même zone.
            excluded[zone].difference_update(locked[zone])
        return locked, excluded

    @staticmethod
    def _readiness(
        selected_by_zone: dict[str, list[dict[str, Any]]],
        analysis: dict[str, Any],
        legality: dict[str, Any],
        unknown_purchase_lines: int,
    ) -> dict[str, Any]:
        targets = {"main": 40, "extra": 15, "side": 15}
        checks: list[dict[str, Any]] = []
        score = 0.0
        weights = {"main": 24, "extra": 10, "side": 6}
        for zone, target in targets.items():
            count = sum(int(r.get("copies") or 0) for r in selected_by_zone.get(zone) or [])
            ratio = min(1.0, count / target) if target else 1.0
            points = weights[zone] * ratio
            score += points
            checks.append({
                "key": f"{zone}_size",
                "label": f"{zone.title()} complet",
                "ok": count == target if zone != "main" else 40 <= count <= 60,
                "detail": f"{count}/{target}",
                "points": round(points, 1),
            })

        observed_core: dict[str, dict[int, int]] = {"main": {}, "extra": {}, "side": {}}
        for zone in targets:
            for row in analysis.get("zones", {}).get(zone, []) or []:
                if row.get("importance") == "core":
                    observed_core[zone][int(row.get("id") or 0)] = int(row.get("recommended_copies") or 0)
        needed = sum(sum(m.values()) for m in observed_core.values())
        covered = 0
        for zone in targets:
            have = {int(r.get("id") or 0): int(r.get("copies") or 0) for r in selected_by_zone.get(zone) or []}
            for cid, qty in observed_core[zone].items():
                covered += min(qty, have.get(cid, 0))
        core_ratio = covered / needed if needed else 1.0
        score += 25 * core_ratio
        checks.append({
            "key": "core_coverage",
            "label": "Core couvert",
            "ok": core_ratio >= 0.9,
            "detail": f"{round(core_ratio * 100)} %",
            "points": round(25 * core_ratio, 1),
        })

        legal = bool(legality.get("legal", False))
        score += 20 if legal else 0
        checks.append({
            "key": "legality", "label": "Légalité TCG", "ok": legal,
            "detail": "OK" if legal else f"{len(legality.get('violations') or [])} conflit(s)",
            "points": 20 if legal else 0,
        })

        price_ok = unknown_purchase_lines == 0
        score += 5 if price_ok else max(0, 5 - min(5, unknown_purchase_lines))
        checks.append({
            "key": "prices", "label": "Prix exploitables", "ok": price_ok,
            "detail": "complets" if price_ok else f"{unknown_purchase_lines} ligne(s) inconnue(s)",
            "points": 5 if price_ok else max(0, 5 - min(5, unknown_purchase_lines)),
        })

        final = int(round(min(100.0, score)))
        if final >= 90:
            label, level = "Prêt à jouer", "high"
        elif final >= 75:
            label, level = "Très proche", "good"
        elif final >= 55:
            label, level = "À compléter", "medium"
        else:
            label, level = "Brouillon", "low"
        return {"score": final, "label": label, "level": level, "checks": checks}

    def _purchase_plan(
        self,
        selected_by_zone: dict[str, list[dict[str, Any]]],
        owned_cards: dict[int, int] | None,
    ) -> list[dict[str, Any]]:
        phases = [
            ("Essentiel", lambda z, r: r.get("importance") == "core" and z != "side"),
            ("Stabiliser le deck", lambda z, r: r.get("importance") == "frequent" and z != "side"),
            ("Extra / flex / Side", lambda z, r: True),
        ]
        assigned: set[tuple[str, int]] = set()
        result: list[dict[str, Any]] = []
        for title, predicate in phases:
            cards: list[dict[str, Any]] = []
            known = 0.0
            unknown = 0
            for zone in ("main", "extra", "side"):
                for row in selected_by_zone.get(zone) or []:
                    key = (zone, int(row.get("id") or 0))
                    if key in assigned or not predicate(zone, row):
                        continue
                    qty = int(row.get("copies") or 0)
                    owned = max(0, int((owned_cards or {}).get(int(row.get("id") or 0), 0)))
                    missing = max(0, qty - owned)
                    if missing <= 0:
                        assigned.add(key)
                        continue
                    price = row.get("cardmarket_price")
                    line = None if price is None else round(float(price) * missing, 2)
                    if line is None:
                        unknown += 1
                    else:
                        known += line
                    cards.append({
                        "id": row.get("id"), "name": row.get("name"), "zone": zone,
                        "missing": missing, "importance": row.get("importance"),
                        "unit_price": price, "line_price": line,
                    })
                    assigned.add(key)
            cards.sort(key=lambda x: (x.get("line_price") is None, -(x.get("line_price") or 0), str(x.get("name") or "")))
            if cards:
                result.append({
                    "title": title, "cards": cards, "known_total": round(known, 2),
                    "unknown_price_lines": unknown, "card_lines": len(cards),
                })
        return result

    async def alternatives(
        self,
        query: str,
        card_id: int,
        zone: str,
        *,
        max_decks: int | None = None,
        tournament_only: bool = False,
        days: int | None = None,
        variant: str | None = None,
    ) -> dict[str, Any]:
        if zone not in {"main", "extra", "side"}:
            raise ValueError("Zone invalide.")
        analysis = await self.analyze(
            query, max_decks=max_decks, tournament_only=tournament_only, days=days, variant=variant
        )
        rows = analysis.get("zones", {}).get(zone, []) or []
        source = next((r for r in rows if int(r.get("id") or 0) == int(card_id)), None)
        if source is None:
            raise ValueError("Cette carte n'a pas été observée dans cette zone avec les filtres actuels.")
        source_roles = set(source.get("role_tags") or [])
        source_price = source.get("cardmarket_price")
        candidates: list[dict[str, Any]] = []
        for row in rows:
            if int(row.get("id") or 0) == int(card_id) or int(row.get("tcg_limit") or 0) <= 0:
                continue
            roles = set(row.get("role_tags") or [])
            overlap = len(source_roles & roles)
            same_relation = row.get("relation") == source.get("relation")
            if not overlap and not same_relation:
                continue
            freq = float(row.get("frequency") or 0)
            quality = freq * 60 + overlap * 18 + (8 if same_relation else 0)
            alt_price = row.get("cardmarket_price")
            saving = None
            if source_price is not None and alt_price is not None:
                saving = round(float(source_price) - float(alt_price), 2)
                if saving > 0:
                    quality += min(18, saving * 1.5)
            candidates.append({
                **row,
                "role_overlap": sorted(source_roles & roles),
                "saving_per_copy": saving,
                "alternative_score": round(quality, 2),
                "reason": (
                    ("Rôle proche" if overlap else "Même famille d'usage")
                    + (f" · économie ≈ {saving:.2f} € / copie" if saving is not None and saving > 0 else "")
                ),
            })
        candidates.sort(key=lambda r: (float(r.get("alternative_score") or 0), float(r.get("frequency") or 0)), reverse=True)
        return {
            "query": analysis.get("query"), "zone": zone, "source_card": source,
            "alternatives": candidates[:10], "samples_analyzed": analysis.get("samples_analyzed", 0),
            "note": "Alternatives observées dans la même zone, classées par rôle, fréquence et coût quand le prix est connu.",
        }

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    @staticmethod
    def _rank_for_mode(row: dict[str, Any], mode: str, zone: str, freespot_profile: str = "auto") -> float:
        score = float(row.get("score") or 0.0)
        frequency = float(row.get("frequency") or 0.0)
        price = row.get("cardmarket_price")
        price_value = float(price) if price is not None else 0.0
        importance = str(row.get("importance") or "rare")
        relation = str(row.get("relation") or "generic")
        if importance == "core":
            score += 60
        elif importance == "frequent":
            score += 26
        elif importance == "rare":
            score -= 8
        if relation == "archetype":
            score += 12
        elif relation == "engine":
            score += 6
        if mode == "budget":
            if price is None:
                score -= 3
            else:
                score -= math.log1p(price_value) * (10 if importance != "core" else 3)
        elif mode == "standard":
            score -= math.log1p(price_value) * 1.8
        elif mode == "optimal":
            score += frequency * 18
        if zone == "side":
            score += frequency * 8
        profile = freespot_profile if freespot_profile in FREESPOT_PROFILES else "auto"
        if relation == "generic" and zone in {"main", "side"} and profile != "auto":
            roles = {str(value) for value in (row.get("role_tags") or [row.get("role")]) if value}
            card_type = str(row.get("type") or "").casefold()
            category = str(row.get("freespot_category") or "")
            if profile == "handtraps":
                if category == "handtraps": score += 42
                elif roles.intersection({"Négation", "Interaction"}): score += 8
            elif profile == "going_second":
                if category == "board_breakers": score += 42
                elif "Removal" in roles: score += 22
                elif "spell" in card_type: score += 6
            elif profile == "traps_control":
                if "trap" in card_type: score += 38
                if roles.intersection({"Négation", "Interaction", "Removal"}): score += 12
            elif profile == "spells":
                if "spell" in card_type: score += 34
                if roles.intersection({"Pioche / consistance", "Board breaker", "Removal"}): score += 10
            elif profile == "budget_staples":
                if price is None:
                    score -= 4
                else:
                    score += max(0.0, 30.0 - math.log1p(price_value) * 9.0)
                score += frequency * 12
        return score

    @staticmethod
    def _effective_line_cost(row: dict[str, Any], copies: int, owned_cards: dict[int, int] | None = None) -> float | None:
        card_id = int(row.get("id") or 0)
        owned = max(0, int((owned_cards or {}).get(card_id, 0)))
        missing = max(0, int(copies) - owned)
        if missing == 0:
            return 0.0
        price = row.get("cardmarket_price")
        if price is None:
            return None
        return round(float(price) * missing, 2)

    def _select_zone(
        self,
        rows: list[dict[str, Any]],
        target: int,
        mode: str,
        owned_cards: dict[int, int] | None = None,
        locked_cards: dict[int, int] | None = None,
        excluded_cards: set[int] | None = None,
        freespot_profile: str = "auto",
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        locked_cards = locked_cards or {}
        excluded_cards = excluded_cards or set()
        candidates = [
            row for row in rows
            if int(row.get("tcg_limit") or 0) > 0 and int(row.get("id") or 0) not in excluded_cards
        ]
        def selection_rank(row: dict[str, Any]) -> float:
            score = self._rank_for_mode(row, mode, str(row.get("zone") or "main"), freespot_profile)
            if mode == "budget" and owned_cards:
                owned = max(0, int(owned_cards.get(int(row.get("id") or 0), 0)))
                price = row.get("cardmarket_price")
                recommended = max(1, int(row.get("recommended_copies") or 1))
                if owned > 0 and price is not None:
                    covered_ratio = min(1.0, owned / recommended)
                    score += math.log1p(float(price)) * 10.0 * covered_ratio
            return score

        candidates.sort(key=selection_rank, reverse=True)
        selected: list[dict[str, Any]] = []
        total_cards = 0
        by_id = {int(row.get("id") or 0): row for row in candidates}
        # Les cartes verrouillées sont placées avant le classement automatique.
        for cid, requested in locked_cards.items():
            row = by_id.get(int(cid))
            if row is None or total_cards >= target:
                continue
            maximum = min(
                int(row.get("tcg_limit") or 0),
                max(1, int(row.get("max_observed_copies") or row.get("recommended_copies") or 1)),
                target - total_cards,
            )
            qty = min(maximum, max(1, int(requested)))
            if qty <= 0:
                continue
            item = dict(row)
            item["copies"] = qty
            item["locked"] = True
            item["line_price"] = self._line_price(row.get("cardmarket_price"), qty)
            item["purchase_price"] = self._effective_line_cost(item, qty, owned_cards)
            selected.append(item)
            total_cards += qty
        locked_ids = {int(row.get("id") or 0) for row in selected}
        known_price = 0.0
        known_purchase_price = 0.0
        unknown_price_lines = 0
        unknown_purchase_lines = 0

        # Passage 1 : quantités les plus courantes.
        for row in candidates:
            if total_cards >= target:
                break
            if int(row.get("id") or 0) in locked_ids:
                continue
            desired = min(
                int(row.get("recommended_copies") or 1),
                int(row.get("tcg_limit") or 3),
                target - total_cards,
            )
            if desired <= 0:
                continue
            item = dict(row)
            item["copies"] = desired
            item["line_price"] = self._line_price(row.get("cardmarket_price"), desired)
            item["purchase_price"] = self._effective_line_cost(item, desired, owned_cards)
            selected.append(item)
            total_cards += desired

        # Passage 2 : si nécessaire, on augmente seulement jusqu'à une quantité réellement observée.
        if total_cards < target:
            for item in selected:
                if total_cards >= target:
                    break
                observed_max = min(int(item.get("max_observed_copies") or 0), int(item.get("tcg_limit") or 3))
                add = min(max(0, observed_max - int(item["copies"])), target - total_cards)
                if add <= 0:
                    continue
                item["copies"] += add
                item["line_price"] = self._line_price(item.get("cardmarket_price"), int(item["copies"]))
                item["purchase_price"] = self._effective_line_cost(item, int(item["copies"]), owned_cards)
                total_cards += add

        for item in selected:
            if item["line_price"] is None:
                unknown_price_lines += 1
            else:
                known_price += float(item["line_price"])
            if item.get("purchase_price") is None:
                unknown_purchase_lines += 1
            else:
                known_purchase_price += float(item["purchase_price"])
        return selected, {
            "count": total_cards,
            "target": target,
            "complete": total_cards == target,
            "known_price": round(known_price, 2),
            "known_purchase_price": round(known_purchase_price, 2),
            "unknown_price_lines": unknown_price_lines,
            "unknown_purchase_lines": unknown_purchase_lines,
        }

    def _rebalance_budget(
        self,
        selected_by_zone: dict[str, list[dict[str, Any]]],
        candidates_by_zone: dict[str, list[dict[str, Any]]],
        budget: float,
        owned_cards: dict[int, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Remplace des copies coûteuses non essentielles par des choix observés moins chers.

        Le moteur ne crée jamais une quantité qui n'a pas été observée et ne retire pas
        une carte Core tant qu'une substitution optionnelle/fréquente reste possible.
        """
        changes: list[dict[str, Any]] = []

        def purchase_total() -> float | None:
            total = 0.0
            for rows in selected_by_zone.values():
                for row in rows:
                    value = self._effective_line_cost(row, int(row.get("copies") or 0), owned_cards)
                    if value is None:
                        return None
                    total += value
            return round(total, 2)

        current = purchase_total()
        if current is None or current <= budget:
            return changes

        importance_rank = {"rare": 0, "option": 1, "frequent": 2, "core": 3}
        for _ in range(160):
            current = purchase_total()
            if current is None or current <= budget:
                break
            best_swap: tuple[float, str, dict[str, Any], dict[str, Any]] | None = None
            for zone, selected in selected_by_zone.items():
                selected_by_id = {int(row.get("id") or 0): row for row in selected}
                removable = sorted(
                    [row for row in selected if int(row.get("copies") or 0) > 0 and not row.get("locked")],
                    key=lambda row: (importance_rank.get(str(row.get("importance")), 1), -float(row.get("cardmarket_price") or 0)),
                )
                alternatives = candidates_by_zone.get(zone) or []
                for old in removable:
                    old_price = old.get("cardmarket_price")
                    if old_price is None:
                        continue
                    for alt in alternatives:
                        alt_id = int(alt.get("id") or 0)
                        if alt_id == int(old.get("id") or 0):
                            continue
                        alt_price = alt.get("cardmarket_price")
                        if alt_price is None or float(alt_price) >= float(old_price):
                            continue
                        max_alt = min(int(alt.get("tcg_limit") or 0), int(alt.get("max_observed_copies") or 0))
                        if max_alt <= 0:
                            continue
                        existing_alt = selected_by_id.get(alt_id)
                        if existing_alt is not None and int(existing_alt.get("copies") or 0) >= max_alt:
                            continue
                        # Évite de remplacer un Core par une tech rare sauf dernier recours.
                        if old.get("importance") == "core" and alt.get("importance") not in {"core", "frequent"}:
                            continue
                        # Garde un minimum de qualité statistique.
                        if float(alt.get("score") or 0) < float(old.get("score") or 0) * 0.45:
                            continue
                        saving = float(old_price) - float(alt_price)
                        if best_swap is None or saving > best_swap[0]:
                            best_swap = (saving, zone, old, alt)
                        break
            if best_swap is None:
                break
            saving, zone, old, alt = best_swap
            old["copies"] = int(old.get("copies") or 0) - 1
            old["line_price"] = self._line_price(old.get("cardmarket_price"), old["copies"])
            old["purchase_price"] = self._effective_line_cost(old, old["copies"], owned_cards)
            if old["copies"] <= 0:
                selected_by_zone[zone].remove(old)
            existing_alt = next(
                (row for row in selected_by_zone[zone] if int(row.get("id") or 0) == int(alt.get("id") or 0)),
                None,
            )
            if existing_alt is None:
                new_item = dict(alt)
                new_item["copies"] = 1
                new_item["line_price"] = self._line_price(new_item.get("cardmarket_price"), 1)
                new_item["purchase_price"] = self._effective_line_cost(new_item, 1, owned_cards)
                selected_by_zone[zone].append(new_item)
            else:
                existing_alt["copies"] = int(existing_alt.get("copies") or 0) + 1
                existing_alt["line_price"] = self._line_price(existing_alt.get("cardmarket_price"), existing_alt["copies"])
                existing_alt["purchase_price"] = self._effective_line_cost(existing_alt, existing_alt["copies"], owned_cards)
            changes.append(
                {
                    "zone": zone,
                    "removed": old.get("name"),
                    "added": alt.get("name"),
                    "saving_per_copy": round(saving, 2),
                }
            )
        for rows in selected_by_zone.values():
            rows.sort(key=lambda row: self._rank_for_mode(row, "budget", str(row.get("zone") or "main")), reverse=True)
        return changes

    @staticmethod
    def _expanded_ids(rows: Iterable[dict[str, Any]]) -> list[int]:
        result: list[int] = []
        for row in rows:
            result.extend([int(row["id"])] * int(row.get("copies") or 0))
        return result

    @staticmethod
    def _deck_text(main: list[dict[str, Any]], extra: list[dict[str, Any]], side: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for title, zone in (("MAIN DECK", main), ("EXTRA DECK", extra), ("SIDE DECK", side)):
            lines.append(title)
            for row in zone:
                lines.append(f"{int(row.get('copies') or 0)}x {row.get('name')}")
            lines.append("")
        return "\n".join(lines).strip()

    @classmethod
    def _deck_ydk(cls, main: list[dict[str, Any]], extra: list[dict[str, Any]], side: list[dict[str, Any]]) -> str:
        lines = ["#created by Hamtaro Deck Builder", "#main"]
        lines.extend(str(card_id) for card_id in cls._expanded_ids(main))
        lines.append("#extra")
        lines.extend(str(card_id) for card_id in cls._expanded_ids(extra))
        lines.append("!side")
        lines.extend(str(card_id) for card_id in cls._expanded_ids(side))
        return "\n".join(lines) + "\n"

    async def generate(
        self,
        query: str,
        *,
        mode: str = "standard",
        budget: float | None = None,
        max_decks: int | None = None,
        tournament_only: bool = False,
        days: int | None = None,
        variant: str | None = None,
        owned_cards: dict[int, int] | None = None,
        locked_cards: dict[str, dict[int, int]] | None = None,
        excluded_cards: dict[str, Iterable[int]] | None = None,
        freespot_profile: str = "auto",
        printing_selections: dict[int, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        mode = mode if mode in {"budget", "standard", "optimal"} else "standard"
        freespot_profile = freespot_profile if freespot_profile in FREESPOT_PROFILES else "auto"
        locked_cards, excluded_cards = self._normalize_constraints(locked_cards, excluded_cards)
        owned_cards = {
            int(card_id): max(0, min(3, int(count)))
            for card_id, count in (owned_cards or {}).items()
            if str(card_id).isdigit() and int(count) > 0
        }
        if budget is not None:
            budget = max(0.0, float(budget))
        analysis = await self.analyze(
            query,
            max_decks=max_decks,
            tournament_only=tournament_only,
            days=days,
            variant=variant,
        )
        printing_selections = {
            int(card_id): dict(item)
            for card_id, item in (printing_selections or {}).items()
            if str(card_id).isdigit() and isinstance(item, dict) and item.get("price_eur") is not None
        }
        if printing_selections:
            # Les prix d'impression sont résolus côté serveur à partir du printing_id :
            # le navigateur ne peut donc pas injecter arbitrairement un prix dans le budget.
            for zone in ("main", "extra", "side"):
                patched_rows: list[dict[str, Any]] = []
                for source_row in analysis.get("zones", {}).get(zone, []) or []:
                    row = dict(source_row)
                    selected = printing_selections.get(int(row.get("id") or 0))
                    if selected:
                        row["generic_cardmarket_price"] = row.get("cardmarket_price")
                        row["cardmarket_price"] = round(float(selected["price_eur"]), 2)
                        row["selected_printing"] = dict(selected)
                    patched_rows.append(row)
                analysis["zones"][zone] = patched_rows
        if analysis["degraded"]:
            return {
                **analysis,
                "generated_deck": None,
                "generation_error": "Pas assez de decklists exploitables pour générer une liste fiable.",
            }
        main, main_meta = self._select_zone(analysis["zones"]["main"], 40, mode, owned_cards, locked_cards["main"], excluded_cards["main"], freespot_profile)
        extra, extra_meta = self._select_zone(analysis["zones"]["extra"], 15, mode, owned_cards, locked_cards["extra"], excluded_cards["extra"], freespot_profile)
        side, side_meta = self._select_zone(analysis["zones"]["side"], 15, mode, owned_cards, locked_cards["side"], excluded_cards["side"], freespot_profile)
        selected_by_zone = {"main": main, "extra": extra, "side": side}
        legality_adjustments = self._enforce_global_limits(selected_by_zone)
        main, extra, side = selected_by_zone["main"], selected_by_zone["extra"], selected_by_zone["side"]
        budget_changes: list[dict[str, Any]] = []
        if mode == "budget" and budget is not None:
            budget_candidates = {
                zone: [row for row in analysis["zones"][zone] if int(row.get("id") or 0) not in excluded_cards[zone]]
                for zone in ("main", "extra", "side")
            }
            budget_changes = self._rebalance_budget(
                selected_by_zone,
                budget_candidates,
                budget,
                owned_cards,
            )
            legality_adjustments.extend(self._enforce_global_limits(selected_by_zone))
            main, extra, side = selected_by_zone["main"], selected_by_zone["extra"], selected_by_zone["side"]
        def final_zone_meta(rows: list[dict[str, Any]], target: int) -> dict[str, Any]:
            known = purchase = 0.0
            unknown = unknown_purchase = 0
            for row in rows:
                row["line_price"] = self._line_price(row.get("cardmarket_price"), int(row.get("copies") or 0))
                row["purchase_price"] = self._effective_line_cost(row, int(row.get("copies") or 0), owned_cards)
                if row["line_price"] is None: unknown += 1
                else: known += float(row["line_price"])
                if row["purchase_price"] is None: unknown_purchase += 1
                else: purchase += float(row["purchase_price"])
            count = sum(int(row.get("copies") or 0) for row in rows)
            return {"count": count, "target": target, "complete": count == target, "known_price": round(known, 2), "known_purchase_price": round(purchase, 2), "unknown_price_lines": unknown, "unknown_purchase_lines": unknown_purchase}
        main_meta = final_zone_meta(main, 40)
        extra_meta = final_zone_meta(extra, 15)
        side_meta = final_zone_meta(side, 15)

        known_total = round(
            float(main_meta["known_price"]) + float(extra_meta["known_price"]) + float(side_meta["known_price"]),
            2,
        )
        purchase_total = round(
            float(main_meta["known_purchase_price"]) + float(extra_meta["known_purchase_price"]) + float(side_meta["known_purchase_price"]),
            2,
        )
        unknown_lines = int(main_meta["unknown_price_lines"]) + int(extra_meta["unknown_price_lines"]) + int(side_meta["unknown_price_lines"])
        unknown_purchase_lines = int(main_meta["unknown_purchase_lines"]) + int(extra_meta["unknown_purchase_lines"]) + int(side_meta["unknown_purchase_lines"])
        within_budget = None if budget is None or unknown_purchase_lines else purchase_total <= budget
        legality = self._global_legality(selected_by_zone)
        upgrade_paths: list[dict[str, Any]] = []
        targets: list[tuple[str, str]] = []
        if mode == "budget":
            targets = [("standard", "Passer en Standard"), ("optimal", "Passer en Optimal")]
        elif mode == "standard":
            targets = [("optimal", "Passer en Optimal")]
        for target_mode, label in targets:
            target_main, _ = self._select_zone(analysis["zones"]["main"], 40, target_mode, owned_cards, locked_cards["main"], excluded_cards["main"], freespot_profile)
            target_extra, _ = self._select_zone(analysis["zones"]["extra"], 15, target_mode, owned_cards, locked_cards["extra"], excluded_cards["extra"], freespot_profile)
            target_side, _ = self._select_zone(analysis["zones"]["side"], 15, target_mode, owned_cards, locked_cards["side"], excluded_cards["side"], freespot_profile)
            target_zones = {"main": target_main, "extra": target_extra, "side": target_side}
            self._enforce_global_limits(target_zones)
            upgrade_paths.append(self._upgrade_path(selected_by_zone, target_zones, owned_cards, label))

        main_ids = self._expanded_ids(main)
        extra_ids = self._expanded_ids(extra)
        side_ids = self._expanded_ids(side)
        readiness = self._readiness(selected_by_zone, analysis, legality, unknown_purchase_lines)
        purchase_plan = self._purchase_plan(selected_by_zone, owned_cards)
        opening_hand = self._opening_hand_stats(selected_by_zone)
        diagnostics = self._coherence_diagnostics(selected_by_zone, analysis)
        constraint_issues: list[dict[str, Any]] = []
        selected_lookup = {
            zone: {int(r.get("id") or 0): int(r.get("copies") or 0) for r in selected_by_zone.get(zone) or []}
            for zone in ("main", "extra", "side")
        }
        for zone in ("main", "extra", "side"):
            observed_ids = {int(r.get("id") or 0) for r in analysis.get("zones", {}).get(zone, []) or []}
            for cid, qty in locked_cards[zone].items():
                if cid not in observed_ids:
                    constraint_issues.append({"zone": zone, "id": cid, "type": "locked_unobserved", "requested": qty})
                elif selected_lookup[zone].get(cid, 0) < qty:
                    constraint_issues.append({
                        "zone": zone, "id": cid, "type": "locked_reduced",
                        "requested": qty, "selected": selected_lookup[zone].get(cid, 0),
                    })

        generated = {
            "mode": mode,
            "freespot_profile": freespot_profile,
            "freespot_profile_label": FREESPOT_PROFILES[freespot_profile]["label"],
            "budget": budget,
            "within_budget": within_budget,
            "main": main,
            "extra": extra,
            "side": side,
            "main_count": main_meta["count"],
            "extra_count": extra_meta["count"],
            "side_count": side_meta["count"],
            "main_complete": main_meta["complete"],
            "extra_complete": extra_meta["complete"],
            "side_complete": side_meta["complete"],
            "main_price": main_meta["known_price"],
            "extra_price": extra_meta["known_price"],
            "side_price": side_meta["known_price"],
            "known_total_price": known_total,
            "known_purchase_price": purchase_total,
            "owned_savings": round(max(0.0, known_total - purchase_total), 2),
            "unknown_price_lines": unknown_lines,
            "unknown_purchase_lines": unknown_purchase_lines,
            "budget_substitutions": budget_changes,
            "legality": legality,
            "legality_adjustments": legality_adjustments,
            "upgrade_paths": upgrade_paths,
            "readiness": readiness,
            "purchase_plan": purchase_plan,
            "opening_hand": opening_hand,
            "diagnostics": diagnostics,
            "selected_printings": {str(card_id): item for card_id, item in printing_selections.items()},
            "constraints": {
                "locked": {zone: locked_cards[zone] for zone in ("main", "extra", "side")},
                "excluded": {zone: sorted(excluded_cards[zone]) for zone in ("main", "extra", "side")},
                "issues": constraint_issues,
            },
            "ydke": self.encode_ydke(main_ids, extra_ids, side_ids),
            "ydk": self._deck_ydk(main, extra, side),
            "text": self._deck_text(main, extra, side),
        }
        if budget is not None and within_budget is False:
            generated["budget_overrun"] = round(purchase_total - budget, 2)
        generation_warnings: list[str] = []
        if not main_meta["complete"]:
            generation_warnings.append("Le moteur n'a pas observé assez de quantités fiables pour atteindre 40 cartes Main sans inventer.")
        if not extra_meta["complete"]:
            generation_warnings.append("L'Extra Deck reste incomplet car moins de 15 places fiables ont été observées.")
        if not side_meta["complete"]:
            generation_warnings.append("Le Side Deck reste incomplet car moins de 15 places fiables ont été observées.")
        if unknown_lines:
            generation_warnings.append("Certaines cartes n'ont pas de prix disponible ; le total affiché est donc partiel.")
        if legality_adjustments:
            generation_warnings.append(
                f"{len(legality_adjustments)} ajustement(s) ont été appliqués pour respecter les limites TCG sur Main + Extra + Side."
            )
        if not legality.get("legal", True):
            generation_warnings.append("La liste générée présente encore un conflit de légalité à vérifier.")
        if budget_changes:
            generation_warnings.append(
                f"Mode Budget : {len(budget_changes)} substitution(s) observée(s) ont été appliquées pour réduire le coût à acheter."
            )
        if budget is not None and within_budget is False:
            generation_warnings.append(
                "Le budget demandé reste trop bas sans retirer des cartes Core ou inventer des choix non observés."
            )
        if constraint_issues:
            generation_warnings.append(
                f"{len(constraint_issues)} contrainte(s) personnelle(s) n'ont pas pu être respectée(s) exactement."
            )
        locked_legality = [item for item in legality_adjustments if item.get("locked_conflict")]
        if locked_legality:
            generation_warnings.append(
                "Une carte verrouillée a dû être réduite pour respecter une limite TCG globale."
            )
        return {
            **analysis,
            "generated_deck": generated,
            "generation_error": None,
            "generation_warnings": generation_warnings,
        }

    async def catalog_stats(self) -> dict[str, int]:
        return await asyncio.to_thread(self._catalog_stats_sync)

    async def suggestions(self, query: str) -> list[str]:
        clean = re.sub(r"\s+", " ", str(query or "")).strip()
        defaults = [
            "Blue-Eyes", "Yummy", "Sky Striker", "X-Saber", "Mitsurugi", "Cyber Dragon",
            "Branded", "Traptrix", "Fire King", "Ryzeal", "Maliss", "Primite Blue-Eyes",
            "D/D/D", "P.U.N.K.", "Rose Dragon", "Radiant Typhoon", "Vanquish Soul K9",
        ]
        if not clean:
            return defaults
        recent = await asyncio.to_thread(self._recent_queries_sync, clean, 8)
        catalog_matches = await asyncio.to_thread(self._catalog_suggestions_sync, clean, 12)
        try:
            payload = await self._fetch_json(f"{YGOPRODECK_API}/archetypes.php", ttl_hours=72)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            payload = []
        names = [str(item.get("archetype_name") or "") for item in payload if isinstance(item, dict)]
        key = clean.casefold()
        direct = [name for name in names if name.casefold().startswith(key)]
        contains = [name for name in names if key in name.casefold() and name not in direct]
        combined: list[str] = []
        for value in catalog_matches + recent + direct + contains + defaults:
            if key not in value.casefold() and value not in recent:
                continue
            if value and value not in combined:
                combined.append(value)
        return combined[:18]
