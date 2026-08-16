from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ParsedDeck:
    main: list[str]
    extra: list[str]
    side: list[str]
    saw_extra: bool
    saw_side: bool
    unsupported_numeric_ids: int


@dataclass(slots=True)
class AraigneeValidation:
    valid: bool
    main_count: int
    extra_count: int
    side_count: int
    spider_count: int
    matched_cards: list[dict[str, Any]]
    suggestions: list[dict[str, str]]
    errors: list[str]
    warnings: list[str]
    checks: dict[str, bool | None]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AraigneeFormatService:
    """Source unique du Format Araignée pour Discord et le site."""

    MAX_DECKLIST_CHARS = 20_000

    def __init__(self, data_path: Path | None = None) -> None:
        root = Path(__file__).resolve().parent.parent
        self.data_path = data_path or root / "data" / "formats" / "araignee.json"
        self._data: dict[str, Any] | None = None
        self._normalized_pool: dict[str, str] | None = None

    @staticmethod
    def normalize_name(value: str) -> str:
        value = str(value or "").strip().casefold()
        value = (
            value.replace("’", "'")
            .replace("‘", "'")
            .replace("–", "-")
            .replace("—", "-")
        )
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    def _validate_config(self, data: dict[str, Any]) -> None:
        if data.get("id") != "araignee":
            raise ValueError("Le fichier de format doit avoir id='araignee'.")

        pool = data.get("spider_card_pool")
        if not isinstance(pool, list) or not pool:
            raise ValueError("Le pool Araignée est vide ou invalide.")

        normalized = [self.normalize_name(card) for card in pool]
        duplicates = [
            name for name, count in Counter(normalized).items()
            if count > 1
        ]
        if duplicates:
            raise ValueError(
                "Le pool Araignée contient des doublons après normalisation."
            )

        main = data.get("main_deck") or {}
        if int(main.get("exact_cards", 0)) <= 0:
            raise ValueError("La taille du Main Deck est invalide.")
        if int(main.get("spider_min", 0)) > int(main.get("spider_max", 0)):
            raise ValueError("spider_min ne peut pas dépasser spider_max.")

    def data(self) -> dict[str, Any]:
        if self._data is None:
            with self.data_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            self._validate_config(loaded)
            self._data = loaded
        return self._data

    def reload(self) -> dict[str, Any]:
        self._data = None
        self._normalized_pool = None
        return self.data()

    def pool(self) -> list[str]:
        return [str(card) for card in self.data().get("spider_card_pool") or []]

    def normalized_pool(self) -> dict[str, str]:
        if self._normalized_pool is None:
            self._normalized_pool = {
                self.normalize_name(card): card
                for card in self.pool()
            }
        return self._normalized_pool

    def pool_revision(self) -> str:
        payload = "\n".join(self.pool()).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:12]

    @staticmethod
    def _strip_bullet(raw: str) -> str:
        raw = re.sub(r"^\s*[-*•]\s+", "", raw)
        raw = re.sub(r"^\s*\d+[.)]\s+", "", raw)
        return raw.strip()

    @classmethod
    def _parse_quantity_and_name(cls, line: str) -> tuple[int, str] | None:
        raw = cls._strip_bullet(str(line or "").strip())
        if not raw:
            return None

        if raw.startswith("//"):
            return None

        patterns = (
            r"^\s*(\d+)\s*[xX×]\s*(.+?)\s*$",
            r"^\s*(.+?)\s*[xX×]\s*(\d+)\s*$",
            r"^\s*(\d+)\s+(.+?)\s*$",
        )

        match = re.match(patterns[0], raw)
        if match:
            return max(1, int(match.group(1))), match.group(2).strip()

        match = re.match(patterns[1], raw)
        if match:
            return max(1, int(match.group(2))), match.group(1).strip()

        match = re.match(patterns[2], raw)
        if match and int(match.group(1)) <= 3:
            return max(1, int(match.group(1))), match.group(2).strip()

        return 1, raw

    def parse_decklist(self, decklist: str) -> ParsedDeck:
        text = str(decklist or "")
        if len(text) > self.MAX_DECKLIST_CHARS:
            raise ValueError(
                f"Decklist trop longue ({len(text)} caractères). "
                f"Maximum : {self.MAX_DECKLIST_CHARS}."
            )

        sections: dict[str, list[str]] = {
            "main": [],
            "extra": [],
            "side": [],
        }
        current = "main"
        saw_extra = False
        saw_side = False
        numeric_ids = 0

        for source_line in text.splitlines():
            line = source_line.strip()
            if not line:
                continue

            # Marqueurs YDK. Les IDs numériques ne sont pas résolus sans base cartes.
            lowered = line.casefold()
            if lowered in {"#main", "main", "main deck", "deck principal"}:
                current = "main"
                continue
            if lowered in {"#extra", "extra", "extra deck"}:
                current = "extra"
                saw_extra = True
                continue
            if lowered in {"!side", "#side", "side", "side deck"}:
                current = "side"
                saw_side = True
                continue

            if line.startswith("#") or line.startswith("//"):
                continue

            parsed = self._parse_quantity_and_name(line)
            if not parsed:
                continue

            qty, name = parsed
            normalized_name = self.normalize_name(name)

            if normalized_name.isdigit():
                numeric_ids += qty
                continue

            sections[current].extend([name] * qty)

        return ParsedDeck(
            main=sections["main"],
            extra=sections["extra"],
            side=sections["side"],
            saw_extra=saw_extra,
            saw_side=saw_side,
            unsupported_numeric_ids=numeric_ids,
        )

    def _spider_suggestions(self, cards: list[str]) -> list[dict[str, str]]:
        pool = self.normalized_pool()
        pool_keys = list(pool.keys())
        suggestions: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for card in cards:
            normalized = self.normalize_name(card)
            if not normalized or normalized in pool:
                continue

            close = get_close_matches(
                normalized,
                pool_keys,
                n=1,
                cutoff=0.88,
            )
            if not close:
                continue

            official = pool[close[0]]
            key = (card, official)
            if key in seen:
                continue
            seen.add(key)
            suggestions.append({
                "entered": card,
                "suggested": official,
            })

        return suggestions[:8]

    def validate_text(self, decklist: str) -> AraigneeValidation:
        parsed = self.parse_decklist(decklist)
        data = self.data()
        main_rules = data["main_deck"]
        extra_rules = data["extra_deck"]
        side_rules = data["side_deck"]
        default_max = int((data.get("copies") or {}).get("default_max", 3))
        pool = self.normalized_pool()

        spider_names = [
            card for card in parsed.main
            if self.normalize_name(card) in pool
        ]
        spider_count = len(spider_names)

        spider_counter = Counter(
            pool[self.normalize_name(card)]
            for card in spider_names
        )
        matched = [
            {"name": name, "quantity": quantity}
            for name, quantity in sorted(
                spider_counter.items(),
                key=lambda item: self.normalize_name(item[0]),
            )
        ]

        errors: list[str] = []
        warnings: list[str] = []

        main_ok = len(parsed.main) == int(main_rules["exact_cards"])
        spider_ok = (
            int(main_rules["spider_min"])
            <= spider_count
            <= int(main_rules["spider_max"])
        )
        extra_ok = (
            len(parsed.extra) <= int(extra_rules["max_cards"])
            if parsed.saw_extra
            else None
        )
        side_ok = (
            len(parsed.side) == int(side_rules["exact_cards"])
            if parsed.saw_side
            else None
        )

        if not main_ok:
            errors.append(
                f"Le Main Deck doit contenir exactement "
                f"{main_rules['exact_cards']} cartes "
                f"(détecté : {len(parsed.main)})."
            )

        if spider_count < int(main_rules["spider_min"]):
            errors.append(
                f"Il faut au moins {main_rules['spider_min']} cartes Araignée "
                f"dans le Main Deck (détecté : {spider_count})."
            )
        elif spider_count > int(main_rules["spider_max"]):
            errors.append(
                f"Il faut au maximum {main_rules['spider_max']} cartes Araignée "
                f"dans le Main Deck (détecté : {spider_count})."
            )

        if extra_ok is False:
            errors.append(
                f"L'Extra Deck ne peut pas dépasser "
                f"{extra_rules['max_cards']} cartes "
                f"(détecté : {len(parsed.extra)})."
            )

        if side_ok is False:
            errors.append(
                f"Le Side Deck du Format Araignée doit contenir exactement "
                f"{side_rules['exact_cards']} cartes "
                f"(détecté : {len(parsed.side)})."
            )

        all_cards = parsed.main + parsed.extra + parsed.side
        copy_counts = Counter(self.normalize_name(card) for card in all_cards)
        display_names: dict[str, str] = {}
        for card in all_cards:
            display_names.setdefault(self.normalize_name(card), card)

        over_limit = [
            (display_names[key], count)
            for key, count in copy_counts.items()
            if key and count > default_max
        ]
        copies_ok = not over_limit

        for name, count in sorted(over_limit):
            errors.append(
                f"{name} apparaît {count} fois dans Main + Extra + Side "
                f"(maximum générique : {default_max})."
            )

        if parsed.unsupported_numeric_ids:
            warnings.append(
                f"{parsed.unsupported_numeric_ids} entrée(s) numérique(s) de type "
                ".ydk détectée(s) : colle un export contenant les noms des cartes "
                "pour que le pool Araignée soit reconnu."
            )

        if not parsed.saw_extra:
            warnings.append(
                "Aucune section Extra Deck fournie : sa taille n'a pas été contrôlée."
            )
        if not parsed.saw_side:
            warnings.append(
                "Aucune section Side Deck fournie : la règle des 3 cartes n'a pas été contrôlée."
            )

        warnings.append(
            "Le validateur ne peut pas encore confirmer l'identité de l'archétype "
            "secondaire, la whitelist générique ni les restrictions propres aux banlists."
        )

        suggestions = self._spider_suggestions(parsed.main)

        checks: dict[str, bool | None] = {
            "main_deck_size": main_ok,
            "spider_quota": spider_ok,
            "extra_deck_size": extra_ok,
            "side_deck_size": side_ok,
            "default_copy_limit": copies_ok,
        }

        return AraigneeValidation(
            valid=not errors,
            main_count=len(parsed.main),
            extra_count=len(parsed.extra),
            side_count=len(parsed.side),
            spider_count=spider_count,
            matched_cards=matched,
            suggestions=suggestions,
            errors=errors,
            warnings=warnings,
            checks=checks,
        )

    def public_data(self) -> dict[str, Any]:
        data = dict(self.data())
        data["pool_count"] = len(self.pool())
        data["pool_revision"] = self.pool_revision()
        return data
