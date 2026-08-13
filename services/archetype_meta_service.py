from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import unicodedata
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
import aiosqlite

from services.analytics_service import AnalyticsService, DeckSummary

try:
    from config import DATABASE
except ImportError:  # pragma: no cover - compat anciennes versions
    from database import DATABASE


APPROVED_STATUSES = {"approved", "validated", "completed"}
ALLOWED_IMAGE_HOSTS = {
    "images.ygoprodeck.com",
    "storage.googleapis.com",
    "cdn.discordapp.com",
    "media.discordapp.net",
    "i.imgur.com",
}


class ArchetypeMetaService:
    """Statistiques d'archétypes + gestion des artworks Hamtaro/communautaires.

    Le service ne modifie pas les tables historiques du bot. Il ajoute uniquement
    deux tables autonomes pour les artworks et lit les inscriptions/résultats
    existants pour calculer la méta.
    """

    def __init__(self, database_path: str = DATABASE) -> None:
        self.database_path = database_path
        self.analytics = AnalyticsService(database_path)
        project_root = Path(__file__).resolve().parent.parent
        self.defaults_path = project_root / "web" / "data" / "archetype_artworks.json"
        self.artwork_cache_dir = project_root / "web" / "static" / "archetype_artworks"
        self.artwork_cache_dir.mkdir(parents=True, exist_ok=True)
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()
        self._default_rules: dict[str, str] | None = None
        self._image_cache_lock = asyncio.Lock()

    @asynccontextmanager
    async def _connect(self):
        db = await aiosqlite.connect(self.database_path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
        finally:
            await db.close()

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            async with self._connect() as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS archetype_artwork_state (
                        guild_id TEXT NOT NULL,
                        deck_key TEXT NOT NULL,
                        deck_name TEXT NOT NULL,
                        default_card_name TEXT,
                        default_image_url TEXT NOT NULL,
                        active_card_name TEXT,
                        active_image_url TEXT,
                        active_proposal_id INTEGER,
                        active_submitted_by TEXT,
                        active_submitted_name TEXT,
                        updated_by TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (guild_id, deck_key)
                    )
                    """
                )
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS archetype_artwork_proposals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id TEXT NOT NULL,
                        deck_key TEXT NOT NULL,
                        deck_name TEXT NOT NULL,
                        card_name TEXT NOT NULL,
                        image_url TEXT NOT NULL,
                        submitted_by TEXT NOT NULL,
                        submitted_name TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        reviewed_by TEXT,
                        reviewed_at TIMESTAMP,
                        rejection_reason TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CHECK (status IN ('pending', 'approved', 'rejected'))
                    )
                    """
                )
                await db.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_artwork_proposals_pending
                    ON archetype_artwork_proposals(guild_id, status, created_at)
                    """
                )
                await db.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_artwork_one_pending_per_user_deck
                    ON archetype_artwork_proposals(guild_id, deck_key, submitted_by)
                    WHERE status = 'pending'
                    """
                )
                await db.commit()
            self._schema_ready = True

    @staticmethod
    def normalize_deck_name(value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        text = text.replace("—", "-").replace("–", "-")
        text = re.sub(r"\s*[/+&|]\s*", " / ", text)
        text = re.sub(r"\s+", " ", text)
        return text

    @classmethod
    def deck_key(cls, value: Any) -> str:
        return cls.normalize_deck_name(value).casefold()

    @classmethod
    def slugify(cls, value: Any) -> str:
        text = cls.normalize_deck_name(value)
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.casefold()
        text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        return text or "deck"

    @staticmethod
    def validate_image_url(url: str) -> str:
        value = str(url or "").strip()
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("L'image doit utiliser une URL HTTPS valide.")
        hostname = (parsed.hostname or "").casefold()
        allow_any = os.getenv("ARCHETYPE_ARTWORK_ALLOW_ANY_HTTPS", "0").strip() == "1"
        if not allow_any and hostname not in ALLOWED_IMAGE_HOSTS:
            raise ValueError(
                "Hôte d'image non autorisé. Utilise YGOPRODeck, Discord CDN ou Imgur."
            )
        return value

    def _load_default_rules(self) -> dict[str, str]:
        if self._default_rules is not None:
            return self._default_rules
        rules: dict[str, str] = {}
        try:
            payload = json.loads(self.defaults_path.read_text(encoding="utf-8"))
            raw_rules = payload.get("defaults", {}) if isinstance(payload, dict) else {}
            for deck_name, card_name in raw_rules.items():
                key = self.deck_key(deck_name)
                if key and str(card_name or "").strip():
                    rules[key] = str(card_name).strip()
        except (OSError, ValueError, TypeError):
            rules = {}
        self._default_rules = rules
        return rules

    @staticmethod
    def _extract_card_image(card: dict[str, Any], fallback_name: str) -> tuple[str | None, str | None]:
        images = card.get("card_images") or []
        if not images:
            return None, None
        image = images[0]
        # On privilégie l'artwork recadré, pas l'image entière de la carte.
        url = image.get("image_url_cropped") or image.get("image_url")
        if not url:
            return None, None
        return str(card.get("name") or fallback_name), str(url)

    async def _lookup_card_image(self, card_name: str) -> tuple[str | None, str | None]:
        """Résout un nom de carte via YGOPRODeck. Échec = (None, None)."""
        card_name = str(card_name or "").strip()
        if not card_name:
            return None, None
        endpoint = os.getenv(
            "YGO_CARD_API_URL",
            "https://db.ygoprodeck.com/api/v7/cardinfo.php",
        )
        timeout = aiohttp.ClientTimeout(total=8)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for params in ({"name": card_name}, {"fname": card_name}):
                    async with session.get(endpoint, params=params) as response:
                        if response.status != 200:
                            continue
                        payload = await response.json(content_type=None)
                        data = payload.get("data") if isinstance(payload, dict) else None
                        if not data:
                            continue
                        name, url = self._extract_card_image(data[0], card_name)
                        if url:
                            return name, url
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
            return None, None
        return None, None

    async def _lookup_archetype_representative(
        self, archetype_name: str
    ) -> tuple[str | None, str | None]:
        """Fallback : trouve une vraie carte appartenant à l'archétype."""
        archetype_name = str(archetype_name or "").strip()
        if not archetype_name:
            return None, None
        endpoint = os.getenv(
            "YGO_CARD_API_URL",
            "https://db.ygoprodeck.com/api/v7/cardinfo.php",
        )
        timeout = aiohttp.ClientTimeout(total=8)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(endpoint, params={"archetype": archetype_name}) as response:
                    if response.status != 200:
                        return None, None
                    payload = await response.json(content_type=None)
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if not data:
                        return None, None
                    # Priorité à une carte dont le nom contient directement le nom
                    # d'archétype, sinon on prend la première carte renvoyée.
                    needle = archetype_name.casefold()
                    card = next(
                        (c for c in data if needle in str(c.get("name") or "").casefold()),
                        data[0],
                    )
                    return self._extract_card_image(card, archetype_name)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
            return None, None

    async def _resolve_artwork_source(
        self, deck_name: str, candidate: str
    ) -> tuple[str | None, str | None]:
        """Résout d'abord la carte choisie, puis l'archétype si nécessaire."""
        resolved_name, image_url = await self._lookup_card_image(candidate)
        if image_url:
            return resolved_name, image_url

        normalized = self.normalize_deck_name(deck_name)
        components = [part.strip() for part in normalized.split(" / ") if part.strip()]
        tried: set[str] = set()
        for component in [candidate, *components]:
            key = component.casefold()
            if not component or key in tried:
                continue
            tried.add(key)
            resolved_name, image_url = await self._lookup_archetype_representative(component)
            if image_url:
                return resolved_name, image_url
        return None, None

    async def _cache_remote_image(self, image_url: str) -> str:
        """Télécharge une seule fois l'artwork et renvoie son URL statique locale."""
        image_url = str(image_url or "").strip()
        if not image_url.startswith("https://"):
            return image_url

        digest = hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:24]
        suffix = ".png" if urlparse(image_url).path.lower().endswith(".png") else ".jpg"
        filename = f"{digest}{suffix}"
        destination = self.artwork_cache_dir / filename
        public_url = f"/static/archetype_artworks/{filename}"
        if destination.exists() and destination.stat().st_size > 1024:
            return public_url

        async with self._image_cache_lock:
            if destination.exists() and destination.stat().st_size > 1024:
                return public_url
            timeout = aiohttp.ClientTimeout(total=12)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(image_url) as response:
                        if response.status != 200:
                            return image_url
                        content_type = str(response.headers.get("Content-Type") or "").lower()
                        if "image" not in content_type:
                            return image_url
                        body = await response.read()
                        if not body or len(body) > 8 * 1024 * 1024:
                            return image_url
                        temp = destination.with_suffix(destination.suffix + ".tmp")
                        temp.write_bytes(body)
                        temp.replace(destination)
                        return public_url
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                return image_url

    @classmethod
    def _automatic_card_candidate(cls, deck_name: str) -> str:
        # Pour un mix, Hamtaro prend par défaut le premier moteur nommé.
        # Le staff peut définir un choix spécifique via /artwork default.
        normalized = cls.normalize_deck_name(deck_name)
        first = normalized.split(" / ", 1)[0].strip()
        return first or normalized

    async def ensure_default_artwork(self, guild_id: str, deck_name: str) -> dict[str, Any]:
        await self.ensure_schema()
        display_name = self.normalize_deck_name(deck_name)
        key = self.deck_key(display_name)
        existing: dict[str, Any] | None = None
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM archetype_artwork_state
                WHERE guild_id = ? AND deck_key = ?
                """,
                (guild_id, key),
            )
            row = await cursor.fetchone()
            if row is not None:
                existing = dict(row)
                # La V1 pouvait mémoriser le placeholder si l'API n'avait pas
                # répondu. En V2 on réessaie automatiquement pour le réparer.
                current_default = str(existing.get("default_image_url") or "")
                if current_default and "hamtaro-pancarte-fin.png" not in current_default:
                    return existing

        rules = self._load_default_rules()
        candidate = rules.get(key) or self._automatic_card_candidate(display_name)
        resolved_name, image_url = await self._resolve_artwork_source(display_name, candidate)
        if not image_url:
            if existing is not None:
                return existing
            resolved_name = candidate or "Hamtaro"
            image_url = "/static/hamtaro-pancarte-fin.png"

        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO archetype_artwork_state(
                    guild_id, deck_key, deck_name,
                    default_card_name, default_image_url
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, deck_key) DO UPDATE SET
                    deck_name = excluded.deck_name,
                    default_card_name = excluded.default_card_name,
                    default_image_url = excluded.default_image_url,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (guild_id, key, display_name, resolved_name, image_url),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT * FROM archetype_artwork_state WHERE guild_id = ? AND deck_key = ?",
                (guild_id, key),
            )
            row = await cursor.fetchone()
            return dict(row)

    @staticmethod
    def _display_artwork(state: dict[str, Any]) -> dict[str, Any]:
        community = bool(state.get("active_image_url"))
        return {
            "card_name": (
                state.get("active_card_name")
                if community
                else state.get("default_card_name")
            ),
            "image_url": (
                state.get("active_image_url")
                if community
                else state.get("default_image_url")
            ),
            "source": "community" if community else "hamtaro",
            "submitted_by": state.get("active_submitted_by") if community else None,
            "submitted_name": state.get("active_submitted_name") if community else None,
            "proposal_id": state.get("active_proposal_id") if community else None,
        }

    async def _tournament_ids_for_format(self, guild_id: str, format_filter: str) -> list[int]:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT id FROM tournaments
                WHERE guild_id = ? AND LOWER(TRIM(format)) = LOWER(TRIM(?))
                ORDER BY id ASC
                """,
                (guild_id, format_filter),
            )
            return [int(row[0]) for row in await cursor.fetchall()]

    @staticmethod
    def _merge_summaries(summaries: list[DeckSummary]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for item in summaries:
            key = ArchetypeMetaService.deck_key(item.deck)
            row = merged.setdefault(
                key,
                {
                    "deck": ArchetypeMetaService.normalize_deck_name(item.deck),
                    "players": 0,
                    "matches": 0,
                    "wins": 0,
                    "losses": 0,
                    "double_losses": 0,
                    "top4": 0,
                    "tournament_wins": 0,
                    # tournament-specific summaries don't expose player IDs,
                    # so this is an upper bound when filtering many tournaments.
                    "_players_sum": 0,
                },
            )
            row["_players_sum"] += int(item.players)
            row["matches"] += int(item.matches)
            row["wins"] += int(item.wins)
            row["losses"] += int(item.losses)
            row["double_losses"] += int(item.double_losses)
            row["top4"] += int(item.top4)
            row["tournament_wins"] += int(item.tournament_wins)
        for row in merged.values():
            row["players"] = row.pop("_players_sum")
            row["win_rate"] = (
                row["wins"] / row["matches"] * 100.0 if row["matches"] else 0.0
            )
        return list(merged.values())

    async def _unique_player_counts_for_format(
        self, guild_id: str, format_filter: str
    ) -> dict[str, int]:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT r.deck, COUNT(DISTINCT r.discord_id) AS players
                FROM registrations r
                JOIN tournaments t ON t.id = r.tournament_id
                WHERE t.guild_id = ?
                  AND LOWER(TRIM(t.format)) = LOWER(TRIM(?))
                  AND TRIM(COALESCE(r.deck, '')) <> ''
                GROUP BY LOWER(TRIM(r.deck))
                """,
                (guild_id, format_filter),
            )
            result: dict[str, int] = {}
            for row in await cursor.fetchall():
                result[self.deck_key(row["deck"])] = int(row["players"] or 0)
            return result

    async def list_formats(self, guild_id: str) -> list[str]:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT DISTINCT TRIM(format) AS format
                FROM tournaments
                WHERE guild_id = ? AND TRIM(COALESCE(format, '')) <> ''
                ORDER BY LOWER(TRIM(format)) ASC
                """,
                (guild_id,),
            )
            return [str(row["format"]) for row in await cursor.fetchall()]

    async def list_archetypes(
        self,
        guild_id: str,
        *,
        format_filter: str | None = None,
        search: str | None = None,
        sort_by: str = "players",
    ) -> list[dict[str, Any]]:
        await self.ensure_schema()
        if format_filter:
            tournament_ids = await self._tournament_ids_for_format(guild_id, format_filter)
            summaries: list[DeckSummary] = []
            for tournament_id in tournament_ids:
                summaries.extend(
                    await self.analytics.get_deck_statistics(guild_id, tournament_id)
                )
            rows = self._merge_summaries(summaries)
            unique_counts = await self._unique_player_counts_for_format(
                guild_id, format_filter
            )
            for row in rows:
                row["players"] = unique_counts.get(self.deck_key(row["deck"]), 0)
        else:
            summaries = await self.analytics.get_deck_statistics(guild_id)
            rows = [asdict(item) for item in summaries]

        query = self.normalize_deck_name(search or "").casefold()
        if query:
            rows = [row for row in rows if query in self.deck_key(row.get("deck"))]

        # Une résolution d'artwork manquante peut nécessiter un appel API.
        # On limite la concurrence pour ne pas surcharger l'API externe.
        semaphore = asyncio.Semaphore(4)

        async def enrich(row: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                state = await self.ensure_default_artwork(guild_id, str(row["deck"]))
            result = dict(row)
            result["deck"] = self.normalize_deck_name(result["deck"])
            result["slug"] = self.slugify(result["deck"])
            artwork = self._display_artwork(state)
            remote_url = str(artwork.get("image_url") or "")
            artwork["remote_image_url"] = remote_url if remote_url.startswith("https://") else None
            artwork["image_url"] = await self._cache_remote_image(remote_url)
            result["artwork"] = artwork
            result["win_rate"] = float(result.get("win_rate") or 0.0)
            return result

        enriched = await asyncio.gather(*(enrich(row) for row in rows)) if rows else []
        sorters = {
            "win_rate": lambda row: (row["win_rate"], row.get("matches", 0), row.get("players", 0)),
            "matches": lambda row: (row.get("matches", 0), row["win_rate"], row.get("players", 0)),
            "wins": lambda row: (row.get("wins", 0), row["win_rate"], row.get("matches", 0)),
            "name": lambda row: self.deck_key(row.get("deck")),
            "players": lambda row: (row.get("players", 0), row.get("matches", 0), row["win_rate"]),
        }
        if sort_by == "name":
            enriched.sort(key=sorters["name"])
        else:
            enriched.sort(key=sorters.get(sort_by, sorters["players"]), reverse=True)
        return enriched

    async def get_archetype_by_slug(
        self, guild_id: str, slug: str, *, format_filter: str | None = None
    ) -> dict[str, Any] | None:
        rows = await self.list_archetypes(guild_id, format_filter=format_filter)
        for row in rows:
            if row["slug"] == slug:
                row["players_detail"] = await self.players_for_deck(
                    guild_id, row["deck"], format_filter=format_filter
                )
                return row
        return None

    async def players_for_deck(
        self, guild_id: str, deck_name: str, *, format_filter: str | None = None
    ) -> list[dict[str, Any]]:
        key = self.deck_key(deck_name)
        format_sql = ""
        params: list[Any] = [guild_id]
        if format_filter:
            format_sql = "AND LOWER(TRIM(t.format)) = LOWER(TRIM(?))"
            params.append(format_filter)
        async with self._connect() as db:
            cursor = await db.execute(
                f"""
                SELECT r.discord_id,
                       COALESCE(p.display_name, p.username, r.username) AS display_name,
                       p.avatar_url,
                       COUNT(DISTINCT r.tournament_id) AS tournaments
                FROM registrations r
                JOIN tournaments t ON t.id = r.tournament_id
                LEFT JOIN players p
                  ON p.guild_id = t.guild_id AND p.discord_id = r.discord_id
                WHERE t.guild_id = ?
                  {format_sql}
                  AND TRIM(COALESCE(r.deck, '')) <> ''
                GROUP BY r.discord_id
                ORDER BY LOWER(COALESCE(p.display_name, p.username, r.username)) ASC
                """,
                tuple(params),
            )
            result = []
            for row in await cursor.fetchall():
                # SQLite ne peut pas appliquer notre normalisation Python dans SQL.
                # On vérifie les inscriptions de chaque joueur ci-dessous.
                player_id = str(row["discord_id"])
                deck_cursor = await db.execute(
                    f"""
                    SELECT r.deck
                    FROM registrations r
                    JOIN tournaments t ON t.id = r.tournament_id
                    WHERE t.guild_id = ? AND r.discord_id = ? {format_sql}
                    """,
                    tuple([guild_id, player_id] + ([format_filter] if format_filter else [])),
                )
                player_decks = [self.deck_key(d["deck"]) for d in await deck_cursor.fetchall()]
                if key not in player_decks:
                    continue
                result.append(
                    {
                        "discord_id": player_id,
                        "display_name": str(row["display_name"] or player_id),
                        "avatar_url": row["avatar_url"],
                        "tournaments": int(row["tournaments"] or 0),
                    }
                )
            return result

    async def deck_exists(self, guild_id: str, deck_name: str) -> bool:
        key = self.deck_key(deck_name)
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT r.deck
                FROM registrations r
                JOIN tournaments t ON t.id = r.tournament_id
                WHERE t.guild_id = ? AND TRIM(COALESCE(r.deck, '')) <> ''
                """,
                (guild_id,),
            )
            return any(self.deck_key(row["deck"]) == key for row in await cursor.fetchall())

    async def submit_proposal(
        self,
        guild_id: str,
        deck_name: str,
        card_name: str,
        image_url: str | None,
        submitted_by: str,
        submitted_name: str,
    ) -> int:
        await self.ensure_schema()
        display_name = self.normalize_deck_name(deck_name)
        if not display_name:
            raise ValueError("Nom de deck vide.")
        if not await self.deck_exists(guild_id, display_name):
            raise ValueError("Ce deck n'existe pas encore dans les inscriptions Hamtaro.")
        card_name = str(card_name or "").strip()
        if not card_name:
            raise ValueError("Indique le nom de la carte représentée.")
        if image_url:
            image_url = self.validate_image_url(image_url)
        else:
            resolved_name, resolved_url = await self._lookup_card_image(card_name)
            if not resolved_url:
                raise ValueError(
                    "Carte introuvable automatiquement. Indique une URL HTTPS d'artwork valide."
                )
            card_name = resolved_name or card_name
            image_url = self.validate_image_url(resolved_url)
        await self.ensure_default_artwork(guild_id, display_name)
        try:
            async with self._connect() as db:
                cursor = await db.execute(
                    """
                    INSERT INTO archetype_artwork_proposals(
                        guild_id, deck_key, deck_name, card_name, image_url,
                        submitted_by, submitted_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        self.deck_key(display_name),
                        display_name,
                        card_name,
                        image_url,
                        submitted_by,
                        submitted_name,
                    ),
                )
                await db.commit()
                return int(cursor.lastrowid)
        except aiosqlite.IntegrityError as error:
            raise ValueError(
                "Tu as déjà une proposition en attente pour ce deck."
            ) from error

    async def list_pending(self, guild_id: str, limit: int = 25) -> list[dict[str, Any]]:
        await self.ensure_schema()
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM archetype_artwork_proposals
                WHERE guild_id = ? AND status = 'pending'
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (guild_id, max(1, min(int(limit), 100))),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def approve_proposal(self, guild_id: str, proposal_id: int, reviewer_id: str) -> dict[str, Any]:
        await self.ensure_schema()
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM archetype_artwork_proposals
                WHERE guild_id = ? AND id = ? AND status = 'pending'
                """,
                (guild_id, proposal_id),
            )
            proposal = await cursor.fetchone()
            if proposal is None:
                raise ValueError("Proposition introuvable ou déjà traitée.")
            p = dict(proposal)
            await db.execute(
                """
                UPDATE archetype_artwork_proposals
                SET status = 'approved', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (reviewer_id, proposal_id),
            )
            await db.execute(
                """
                UPDATE archetype_artwork_state
                SET active_card_name = ?, active_image_url = ?,
                    active_proposal_id = ?, active_submitted_by = ?,
                    active_submitted_name = ?, updated_by = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ? AND deck_key = ?
                """,
                (
                    p["card_name"],
                    p["image_url"],
                    proposal_id,
                    p["submitted_by"],
                    p["submitted_name"],
                    reviewer_id,
                    guild_id,
                    p["deck_key"],
                ),
            )
            await db.commit()
            return p

    async def reject_proposal(
        self,
        guild_id: str,
        proposal_id: int,
        reviewer_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        await self.ensure_schema()
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM archetype_artwork_proposals
                WHERE guild_id = ? AND id = ? AND status = 'pending'
                """,
                (guild_id, proposal_id),
            )
            proposal = await cursor.fetchone()
            if proposal is None:
                raise ValueError("Proposition introuvable ou déjà traitée.")
            await db.execute(
                """
                UPDATE archetype_artwork_proposals
                SET status = 'rejected', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP,
                    rejection_reason = ?
                WHERE id = ?
                """,
                (reviewer_id, str(reason or "").strip() or None, proposal_id),
            )
            await db.commit()
            return dict(proposal)

    async def set_hamtaro_default(
        self,
        guild_id: str,
        deck_name: str,
        card_name: str,
        image_url: str | None,
        reviewer_id: str,
    ) -> None:
        display_name = self.normalize_deck_name(deck_name)
        card_name = str(card_name or "").strip()
        if not card_name:
            raise ValueError("Indique le nom de la carte représentée.")
        if image_url:
            image_url = self.validate_image_url(image_url)
        else:
            resolved_name, resolved_url = await self._lookup_card_image(card_name)
            if not resolved_url:
                raise ValueError(
                    "Carte introuvable automatiquement. Indique une URL HTTPS d'artwork valide."
                )
            card_name = resolved_name or card_name
            image_url = self.validate_image_url(resolved_url)
        await self.ensure_default_artwork(guild_id, display_name)
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE archetype_artwork_state
                SET deck_name = ?, default_card_name = ?, default_image_url = ?,
                    updated_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ? AND deck_key = ?
                """,
                (
                    display_name,
                    str(card_name or "").strip(),
                    image_url,
                    reviewer_id,
                    guild_id,
                    self.deck_key(display_name),
                ),
            )
            await db.commit()

    async def reset_to_hamtaro_default(self, guild_id: str, deck_name: str, reviewer_id: str) -> None:
        display_name = self.normalize_deck_name(deck_name)
        await self.ensure_default_artwork(guild_id, display_name)
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE archetype_artwork_state
                SET active_card_name = NULL, active_image_url = NULL,
                    active_proposal_id = NULL, active_submitted_by = NULL,
                    active_submitted_name = NULL, updated_by = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ? AND deck_key = ?
                """,
                (reviewer_id, guild_id, self.deck_key(display_name)),
            )
            await db.commit()

    async def current_artwork(self, guild_id: str, deck_name: str) -> dict[str, Any]:
        state = await self.ensure_default_artwork(guild_id, deck_name)
        return self._display_artwork(state)
