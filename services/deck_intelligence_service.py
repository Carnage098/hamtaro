from __future__ import annotations

import difflib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

try:
    from discord import app_commands
except ImportError:  # permet les tests/outils hors runtime Discord
    app_commands = None


class DeckIntelligenceService:
    """Normalisation canonique des decks et alias communautaires.

    Le service conserve les noms inconnus au lieu de les rejeter. Cela évite
    de bloquer une inscription tout en empêchant les variantes connues de
    fragmenter les statistiques du Meta Center.
    """

    def __init__(self, aliases_path: str | Path | None = None) -> None:
        root = Path(__file__).resolve().parent.parent
        self.aliases_path = Path(aliases_path or root / "web/data/deck_aliases.json")
        self._base_aliases: dict[str, str] | None = None

    @staticmethod
    def normalize_text(value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        text = text.replace("—", "-").replace("–", "-")
        text = re.sub(r"\s*[/+&|]\s*", " / ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @classmethod
    def key(cls, value: Any) -> str:
        text = cls.normalize_text(value)
        text = text.replace(".", "")
        text = re.sub(r"[^0-9a-zA-ZÀ-ÿ]+", " ", text)
        return re.sub(r"\s+", " ", text).strip().casefold()

    def _load_base(self) -> dict[str, str]:
        if self._base_aliases is not None:
            return self._base_aliases
        aliases: dict[str, str] = {}
        try:
            payload = json.loads(self.aliases_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            payload = {}
        canonical = payload.get("canonical", {}) if isinstance(payload, dict) else {}
        for display, raw_aliases in canonical.items():
            canonical_name = self.normalize_text(display)
            aliases[self.key(canonical_name)] = canonical_name
            if isinstance(raw_aliases, list):
                for alias in raw_aliases:
                    aliases[self.key(alias)] = canonical_name
        self._base_aliases = aliases
        return aliases

    @staticmethod
    async def ensure_schema(db) -> None:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS deck_aliases (
                guild_id TEXT NOT NULL,
                alias_key TEXT NOT NULL,
                alias_name TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, alias_key)
            )
            """,
            commit=True,
        )

    async def _guild_aliases(self, db, guild_id: str) -> dict[str, str]:
        await self.ensure_schema(db)
        rows = await db.fetchall(
            """
            SELECT alias_key, canonical_name
            FROM deck_aliases
            WHERE guild_id = ?
            """,
            (str(guild_id),),
        )
        return {
            str(row["alias_key"]): self.normalize_text(row["canonical_name"])
            for row in rows
        }

    async def canonicalize(self, db, guild_id: str, raw_name: str | None) -> str | None:
        if raw_name is None:
            return None
        display = self.normalize_text(raw_name)
        if not display:
            return None

        base = dict(self._load_base())
        base.update(await self._guild_aliases(db, guild_id))

        # Reconnaissance directe d'un deck entier.
        direct = base.get(self.key(display))
        if direct:
            return direct

        # Reconnaissance des decks mixtes moteur / moteur.
        parts = [part.strip() for part in display.split(" / ") if part.strip()]
        if len(parts) > 1:
            canonical_parts: list[str] = []
            seen: set[str] = set()
            for part in parts:
                resolved = base.get(self.key(part), self._pretty_unknown(part))
                marker = resolved.casefold()
                if marker not in seen:
                    seen.add(marker)
                    canonical_parts.append(resolved)
            return " / ".join(canonical_parts)

        return self._pretty_unknown(display)

    @staticmethod
    def _pretty_unknown(value: str) -> str:
        # On ne force pas tout en Title Case : les acronymes déjà saisis restent
        # en majuscules et les ponctuations Yu-Gi-Oh! sont conservées.
        words = []
        for word in value.split():
            if word.isupper() and len(word) <= 8:
                words.append(word)
            elif any(ch in word for ch in ".-'"):
                words.append(word)
            else:
                words.append(word[:1].upper() + word[1:])
        return " ".join(words)

    async def add_alias(
        self,
        db,
        guild_id: str,
        alias: str,
        canonical: str,
        created_by: str,
    ) -> str:
        await self.ensure_schema(db)
        alias_name = self.normalize_text(alias)
        canonical_name = self.normalize_text(canonical)
        if not alias_name or not canonical_name:
            raise ValueError("L'alias et le nom canonique doivent être renseignés.")
        await db.execute(
            """
            INSERT INTO deck_aliases(
                guild_id, alias_key, alias_name, canonical_name, created_by
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, alias_key)
            DO UPDATE SET
                alias_name = excluded.alias_name,
                canonical_name = excluded.canonical_name,
                created_by = excluded.created_by,
                created_at = CURRENT_TIMESTAMP
            """,
            (
                str(guild_id),
                self.key(alias_name),
                alias_name,
                canonical_name,
                str(created_by),
            ),
            commit=True,
        )
        return canonical_name

    async def known_names(self, db, guild_id: str) -> list[str]:
        names = set(self._load_base().values())
        for row in await db.fetchall(
            "SELECT DISTINCT deck FROM registrations WHERE TRIM(COALESCE(deck, '')) <> ''"
        ):
            value = self.normalize_text(row["deck"])
            if value:
                names.add(value)
        names.update((await self._guild_aliases(db, guild_id)).values())
        return sorted(names, key=str.casefold)

    async def suggestions(
        self,
        db,
        guild_id: str,
        query: str,
        limit: int = 12,
    ) -> list[str]:
        names = await self.known_names(db, guild_id)
        q = self.normalize_text(query)
        if not q:
            return names[:limit]
        q_key = self.key(q)
        prefix = [name for name in names if self.key(name).startswith(q_key)]
        contains = [
            name for name in names
            if q_key in self.key(name) and name not in prefix
        ]
        fuzzy = [
            name for name in difflib.get_close_matches(
                q, names, n=limit, cutoff=0.35
            )
            if name not in prefix and name not in contains
        ]
        return (prefix + contains + fuzzy)[:limit]


async def deck_name_autocomplete(
    interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    db = getattr(bot, "db", None)
    if db is None or interaction.guild is None:
        return []
    service = DeckIntelligenceService()
    try:
        names = await service.suggestions(
            db,
            str(interaction.guild.id),
            current,
            limit=25,
        )
    except Exception:
        return []
    if app_commands is None:
        return []
    return [
        app_commands.Choice(name=name[:100], value=name[:100])
        for name in names
    ]
