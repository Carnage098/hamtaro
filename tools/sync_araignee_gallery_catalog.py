from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
BUILD_VERSION = 1

ATTRIBUTE_LABELS = {
    "DARK": "TÉNÈBRES",
    "DIVINE": "DIVIN",
    "EARTH": "TERRE",
    "FIRE": "FEU",
    "LIGHT": "LUMIÈRE",
    "WATER": "EAU",
    "WIND": "VENT",
}

RACE_LABELS = {
    "Aqua": "Aqua",
    "Beast": "Bête",
    "Beast-Warrior": "Bête-Guerrier",
    "Cyberse": "Cyberse",
    "Dinosaur": "Dinosaure",
    "Divine-Beast": "Bête Divine",
    "Dragon": "Dragon",
    "Fairy": "Elfe",
    "Fiend": "Démon",
    "Fish": "Poisson",
    "Illusion": "Illusion",
    "Insect": "Insecte",
    "Machine": "Machine",
    "Plant": "Plante",
    "Psychic": "Psychique",
    "Pyro": "Pyro",
    "Reptile": "Reptile",
    "Rock": "Rocher",
    "Sea Serpent": "Serpent de Mer",
    "Spellcaster": "Magicien",
    "Thunder": "Tonnerre",
    "Warrior": "Guerrier",
    "Winged Beast": "Bête Ailée",
    "Wyrm": "Wyrm",
    "Zombie": "Zombie",
}

SUBTYPE_LABELS = {
    "Normal": "Normale",
    "Continuous": "Continue",
    "Quick-Play": "Jeu-Rapide",
    "Field": "Terrain",
    "Equip": "Équipement",
    "Ritual": "Rituel",
    "Counter": "Contre-Piège",
}

VISUAL_FAMILY_LABELS = {
    "true_spider": "Araignée directe",
    "humanoid": "Humanoïde arachnéen",
    "mechanical": "Araignée mécanique / cyber",
    "web_support": "Toile / support arachnéen",
    "scorpion": "Scorpion / arachnide proche",
    "indirect": "Référence indirecte",
}


def normalize(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("–", "-")
        .replace("—", "-")
    )
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_cards(ids: list[int], batch_size: int = 45) -> dict[int, dict[str, Any]]:
    cards: dict[int, dict[str, Any]] = {}
    unique_ids = list(dict.fromkeys(int(card_id) for card_id in ids if card_id))
    for start in range(0, len(unique_ids), batch_size):
        batch = unique_ids[start : start + batch_size]
        query = urlencode({"id": ",".join(str(card_id) for card_id in batch), "misc": "yes"})
        request = Request(
            f"{API_URL}?{query}",
            headers={
                "User-Agent": "Hamtaro-Araignee-Gallery/1.0",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=30) as response:  # noqa: S310 - URL is fixed above.
            payload = json.loads(response.read().decode("utf-8"))
        for card in payload.get("data") or []:
            try:
                card_id = int(card.get("id"))
            except (TypeError, ValueError):
                continue
            cards[card_id] = card
            for image in card.get("card_images") or []:
                try:
                    cards.setdefault(int(image.get("id")), card)
                except (TypeError, ValueError):
                    pass
        if start + batch_size < len(unique_ids):
            time.sleep(0.12)
    return cards


def type_keys(api_card: dict[str, Any] | None) -> list[str]:
    if not api_card:
        return []
    raw = str(api_card.get("type") or "").casefold()
    keys: list[str] = []
    if "spell card" in raw:
        return ["spell"]
    if "trap card" in raw:
        return ["trap"]
    if "normal" in raw:
        keys.append("normal")
    if "effect" in raw:
        keys.append("effect")
    if "ritual" in raw:
        keys.append("ritual")
    if "fusion" in raw:
        keys.append("fusion")
    if "synchro" in raw:
        keys.append("synchro")
    if "xyz" in raw:
        keys.append("xyz")
    if "link" in raw:
        keys.append("link")
    if "pendulum" in raw:
        keys.append("pendulum")
    if not keys and "monster" in raw:
        keys.append("effect")
    return list(dict.fromkeys(keys))


def zone_for(keys: list[str]) -> str:
    return "extra" if any(key in {"fusion", "synchro", "xyz", "link"} for key in keys) else "main"


def metric_for(api_card: dict[str, Any] | None, keys: list[str]) -> dict[str, Any] | None:
    if not api_card or not keys or keys[0] in {"spell", "trap"}:
        return None
    if "link" in keys:
        value = api_card.get("linkval")
        if value is not None:
            return {"kind": "link", "value": int(value), "label": f"Lien {int(value)}"}
    level = api_card.get("level")
    if level is None:
        return None
    level = int(level)
    if "xyz" in keys:
        return {"kind": "rank", "value": level, "label": f"Rang {level}"}
    return {"kind": "level", "value": level, "label": f"Niveau {level}"}


def visual_family(display_name: str, api_card: dict[str, Any] | None) -> str:
    name = normalize(display_name)
    archetype = normalize((api_card or {}).get("archetype"))
    card_type = str((api_card or {}).get("type") or "").casefold()

    if any(token in name for token in ("scorpion", "serket", "scorpio", "scorp")):
        return "scorpion"

    mechanical_tokens = (
        "karakuri", "cyber", "numerique", "digital bug", "krawler", "tindangle",
        "mechabot", "machine", "atil spia", "bm 4", "arsenal", "allie de la justice",
    )
    if any(token in name or token in archetype for token in mechanical_tokens):
        return "mechanical"

    if "spell card" in card_type or "trap card" in card_type:
        if any(token in name for token in (
            "toile", "fil", "web", "antre", "proie", "roulette", "trappe", "piege", "trap",
        )):
            return "web_support"

    if any(token in name or token in archetype for token in (
        "traptrix", "madame araignee", "tsuchigumo", "joruri p u n k madame",
    )):
        return "humanoid"

    if any(token in name for token in (
        "araignee", "spider", "gumo", "tarent", "arachn", "uru", "kumongous", "nephila",
    )):
        return "true_spider"

    return "indirect"


def deck_tags(display_name: str, api_card: dict[str, Any] | None, family: str) -> list[str]:
    name = normalize(display_name)
    archetype_raw = str((api_card or {}).get("archetype") or "").strip()
    archetype = normalize(archetype_raw)
    tags: list[str] = []

    def add(label: str) -> None:
        if label not in tags:
            tags.append(label)

    if "kaiju" in name or "kaiju" in archetype:
        add("Araignée Kaiju")
    if "uru" in name or "earthbound immortal" in archetype or "terre immortel" in name:
        add("Uru / Spider Temple")
    if "traptrix" in name or "traptrix" in archetype:
        add("SpiderWeb Traptrix")
    if "mayakashi" in name or "mayakashi" in archetype:
        add("Araignée Mayakashi")
    if "predaplant" in name or "predaplant" in archetype or "predaplante" in name:
        add("Araignée Prédaplante")
    if "p u n k" in name or "p u n k" in archetype:
        add("Araignée P.U.N.K.")
    if "tindangle" in name or "tindangle" in archetype:
        add("Araignée Tindangle")
    if "krawler" in name or "krawler" in archetype:
        add("Araignée Krawler")
    if any(token in name or token in archetype for token in ("vendread", "vendetterreur", "revendetterreur")):
        add("Araignée Vendetterreur")
    if "karakuri" in name or "karakuri" in archetype:
        add("Cyber-Araignée / Karakuri")
    if family == "mechanical":
        add("Cyber-Araignée")
    if archetype_raw:
        add(f"Engine {archetype_raw}")
    return tags


def apply_override(entry: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    if not override:
        return entry
    for key, value in override.items():
        if key == "deck_tags":
            current = list(entry.get("deck_tags") or [])
            for item in value or []:
                if item not in current:
                    current.append(str(item))
            entry["deck_tags"] = current
        else:
            entry[key] = value
    if "visual_family" in override and "visual_family_label" not in override:
        entry["visual_family_label"] = VISUAL_FAMILY_LABELS.get(str(entry.get("visual_family")), str(entry.get("visual_family")))
    return entry


def make_entry(
    display_name: str,
    manifest: dict[str, Any],
    api_card: dict[str, Any] | None,
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    keys = type_keys(api_card)
    family = visual_family(display_name, api_card)
    race = str((api_card or {}).get("race") or "").strip()
    attribute = str((api_card or {}).get("attribute") or "").strip().upper()
    subtype = race if keys and keys[0] in {"spell", "trap"} else ""
    image_status = str(manifest.get("status") or "missing")

    entry = {
        "name": display_name,
        "card_id": manifest.get("card_id"),
        "api_name": manifest.get("api_name") or (api_card or {}).get("name") or display_name,
        "metadata_ok": bool(api_card),
        "type": str((api_card or {}).get("type") or ""),
        "type_keys": keys,
        "zone": zone_for(keys) if keys else "unknown",
        "attribute": attribute,
        "attribute_label": ATTRIBUTE_LABELS.get(attribute, attribute),
        "race": race if not subtype else "",
        "race_label": RACE_LABELS.get(race, race) if not subtype else "",
        "spelltrap_subtype": subtype,
        "spelltrap_subtype_label": SUBTYPE_LABELS.get(subtype, subtype),
        "metric": metric_for(api_card, keys),
        "archetype": str((api_card or {}).get("archetype") or "").strip(),
        "visual_family": family,
        "visual_family_label": VISUAL_FAMILY_LABELS[family],
        "deck_tags": deck_tags(display_name, api_card, family),
        "image_status": image_status,
        "has_image": image_status == "ok" and bool(manifest.get("local_path")),
    }
    return apply_override(entry, override)


def build_filter_options(cards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    def counted(key: str, label_key: str | None = None) -> list[dict[str, Any]]:
        values: dict[str, dict[str, Any]] = {}
        for card in cards:
            value = card.get(key)
            if value in (None, "", [], {}):
                continue
            raw_values = value if isinstance(value, list) else [value]
            for raw in raw_values:
                raw = str(raw)
                if not raw:
                    continue
                label = str(card.get(label_key) or raw) if label_key else raw
                item = values.setdefault(raw, {"value": raw, "label": label, "count": 0})
                item["count"] += 1
        return sorted(values.values(), key=lambda item: normalize(item["label"]))

    metric_values: dict[str, dict[str, Any]] = {}
    for card in cards:
        metric = card.get("metric") or {}
        if not metric:
            continue
        key = f"{metric.get('kind')}:{metric.get('value')}"
        item = metric_values.setdefault(key, {"value": key, "label": metric.get("label") or key, "count": 0})
        item["count"] += 1

    return {
        "attribute": counted("attribute", "attribute_label"),
        "race": counted("race", "race_label"),
        "spelltrap_subtype": counted("spelltrap_subtype", "spelltrap_subtype_label"),
        "metric": sorted(metric_values.values(), key=lambda item: (item["value"].split(":")[0], int(item["value"].split(":")[1]))),
        "archetype": counted("archetype"),
        "visual_family": counted("visual_family", "visual_family_label"),
        "deck_tag": counted("deck_tags"),
    }


def sync_catalog(project_root: Path, allow_network: bool = True) -> tuple[Path, dict[str, Any]]:
    root = project_root.resolve()
    manifest_path = root / "data" / "formats" / "araignee_images.json"
    overrides_path = root / "data" / "formats" / "araignee_gallery_overrides.json"
    output_path = root / "web" / "static" / "araignee" / "araignee_catalog.json"

    manifest_data = load_json(manifest_path, {})
    cards_manifest = manifest_data.get("cards") or {}
    if not cards_manifest:
        raise RuntimeError(f"Manifest Araignée vide ou absent : {manifest_path}")

    existing_payload = load_json(output_path, {}) or {}
    existing_cards = existing_payload.get("cards") or []
    existing_by_name = {normalize(card.get("name")): card for card in existing_cards if card.get("name")}
    existing_by_id = {}
    for card in existing_cards:
        try:
            existing_by_id[int(card.get("card_id"))] = card
        except (TypeError, ValueError):
            pass

    overrides = (load_json(overrides_path, {}) or {}).get("cards") or {}
    ids = [entry.get("card_id") for entry in cards_manifest.values() if entry.get("card_id")]
    api_cards: dict[int, dict[str, Any]] = {}
    api_error = ""

    if allow_network:
        try:
            api_cards = fetch_cards([int(card_id) for card_id in ids])
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            api_error = str(error)

    by_api_name: dict[str, dict[str, Any]] = {
        normalize(card.get("name")): card
        for card in api_cards.values()
        if card.get("name")
    }

    cards: list[dict[str, Any]] = []
    missing_metadata: list[str] = []
    for display_name, manifest in cards_manifest.items():
        card_id = manifest.get("card_id")
        api_card = None
        if card_id:
            try:
                api_card = api_cards.get(int(card_id))
            except (TypeError, ValueError):
                pass
        if api_card is None:
            api_card = by_api_name.get(normalize(manifest.get("api_name")))
        if api_card is None:
            existing = existing_by_name.get(normalize(display_name))
            if existing is None and card_id:
                try:
                    existing = existing_by_id.get(int(card_id))
                except (TypeError, ValueError):
                    existing = None
            if existing and existing.get("metadata_ok"):
                entry = dict(existing)
                entry.update({
                    "name": display_name,
                    "card_id": manifest.get("card_id"),
                    "api_name": manifest.get("api_name") or entry.get("api_name") or display_name,
                    "image_status": str(manifest.get("status") or "missing"),
                    "has_image": str(manifest.get("status") or "missing") == "ok" and bool(manifest.get("local_path")),
                })
                cards.append(apply_override(entry, overrides.get(display_name)))
                continue
            missing_metadata.append(display_name)
        cards.append(make_entry(display_name, manifest, api_card, overrides.get(display_name)))

    payload = {
        "version": BUILD_VERSION,
        "source": "YGOPRODeck API v7 + araignee_gallery_overrides.json",
        "pool_count": len(cards),
        "metadata_count": sum(1 for card in cards if card.get("metadata_ok")),
        "missing_metadata_count": len(missing_metadata),
        "api_error": api_error,
        "cards": cards,
        "filters": build_filter_options(cards),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path, payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconstruit le catalogue filtrable du Format Araignée.")
    parser.add_argument("project_root", nargs="?", default=".", help="Racine du dépôt Hamtaro.")
    parser.add_argument("--no-network", action="store_true", help="Ne contacte pas YGOPRODeck ; applique seulement les heuristiques/overrides.")
    args = parser.parse_args()
    output, payload = sync_catalog(Path(args.project_root), allow_network=not args.no_network)
    print(f"Catalogue écrit : {output}")
    print(f"Cartes : {payload['pool_count']} | métadonnées : {payload['metadata_count']} | sans métadonnées : {payload['missing_metadata_count']}")
    if payload.get("api_error"):
        print(f"Avertissement API : {payload['api_error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
