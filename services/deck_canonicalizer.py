from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

try:
    from discord import app_commands
except ImportError:  # tests hors runtime Discord
    app_commands = None


class DeckCanonicalizer:
    """Normalise les noms de decks sans rejeter les noms inconnus.

    Les alias connus sont fusionnés vers un nom canonique. Un nom inconnu est
    conservé tel quel après nettoyage des espaces/séparateurs.
    """

    def __init__(self, aliases_path: str | Path | None = None) -> None:
        root = Path(__file__).resolve().parent.parent
        self.aliases_path = Path(
            aliases_path or root / "web" / "data" / "deck_aliases.json"
        )
        self._alias_to_canonical: dict[str, str] | None = None
        self._canonicals: list[str] | None = None

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
        text = re.sub(r"\s*/\s*", " / ", text)
        text = re.sub(r"[^0-9A-Za-zÀ-ÿ/]+", " ", text)
        return re.sub(r"\s+", " ", text).strip().casefold()

    def _load(self) -> None:
        if self._alias_to_canonical is not None:
            return
        alias_map: dict[str, str] = {}
        canonicals: list[str] = []
        try:
            payload = json.loads(self.aliases_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            payload = {}
        raw = payload.get("canonical", {}) if isinstance(payload, dict) else {}
        for canonical, aliases in raw.items():
            canonical_name = self.normalize_text(canonical)
            if not canonical_name:
                continue
            canonicals.append(canonical_name)
            alias_map[self.key(canonical_name)] = canonical_name
            if isinstance(aliases, list):
                for alias in aliases:
                    alias_key = self.key(alias)
                    if alias_key:
                        alias_map[alias_key] = canonical_name
        self._alias_to_canonical = alias_map
        self._canonicals = sorted(set(canonicals), key=str.casefold)

    def canonicalize(self, value: Any) -> str:
        self._load()
        normalized = self.normalize_text(value)
        if not normalized:
            return ""
        assert self._alias_to_canonical is not None

        direct = self._alias_to_canonical.get(self.key(normalized))
        if direct:
            return direct

        # Décks mixtes : chaque composant est résolu séparément.
        parts = [part.strip() for part in normalized.split(" / ") if part.strip()]
        if len(parts) > 1:
            resolved: list[str] = []
            seen: set[str] = set()
            for part in parts:
                canonical = self._alias_to_canonical.get(
                    self.key(part),
                    self.normalize_text(part),
                )
                marker = canonical.casefold()
                if marker not in seen:
                    seen.add(marker)
                    resolved.append(canonical)

            # On reteste le mix complet, notamment pour Gold Pride / PUNK.
            mix = " / ".join(resolved)
            full = self._alias_to_canonical.get(self.key(mix))
            return full or mix

        return normalized

    def canonical_key(self, value: Any) -> str:
        return self.key(self.canonicalize(value))

    def known_names(self) -> list[str]:
        self._load()
        return list(self._canonicals or [])


async def deck_name_autocomplete(interaction, current: str):
    if app_commands is None:
        return []
    service = DeckCanonicalizer()
    query = service.key(current)
    names = service.known_names()
    if query:
        names = sorted(
            names,
            key=lambda name: (
                not service.key(name).startswith(query),
                query not in service.key(name),
                name.casefold(),
            ),
        )
        names = [
            name for name in names
            if query in service.key(name)
            or service.key(name).startswith(query)
        ]
    return [
        app_commands.Choice(name=name[:100], value=name[:100])
        for name in names[:25]
    ]
