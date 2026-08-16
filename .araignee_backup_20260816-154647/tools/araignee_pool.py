#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "formats" / "araignee.json"


def normalize(value: str) -> str:
    value = str(value or "").strip().casefold()
    value = value.replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def load() -> dict:
    with DATA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save(data: dict) -> None:
    DATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Gérer le pool du Format Araignée.")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Ajouter une carte")
    add.add_argument("name")

    remove = sub.add_parser("remove", help="Retirer une carte")
    remove.add_argument("name")

    sub.add_parser("list", help="Afficher le pool")
    sub.add_parser("check", help="Vérifier les doublons")

    args = parser.parse_args()
    data = load()
    pool = list(data.get("spider_card_pool") or [])

    if args.command == "list":
        for index, card in enumerate(pool, start=1):
            print(f"{index}. {card}")
        print(f"\nTotal : {len(pool)}")
        return 0

    normalized = {normalize(card): card for card in pool}

    if args.command == "check":
        if len(normalized) != len(pool):
            print("❌ Doublons détectés après normalisation.")
            return 1
        print(f"✅ Pool valide : {len(pool)} cartes uniques.")
        return 0

    target = normalize(args.name)

    if args.command == "add":
        if target in normalized:
            print(f"↪ Déjà présent : {normalized[target]}")
            return 0
        pool.append(args.name.strip())
        data["spider_card_pool"] = pool
        data["pool_version"] = int(data.get("pool_version", 0)) + 1
        save(data)
        print(f"✅ Ajouté : {args.name.strip()}")
        print(f"Pool : {len(pool)} cartes · version {data['pool_version']}")
        return 0

    if args.command == "remove":
        if target not in normalized:
            print("❌ Carte introuvable.")
            return 1
        official = normalized[target]
        data["spider_card_pool"] = [
            card for card in pool if normalize(card) != target
        ]
        data["pool_version"] = int(data.get("pool_version", 0)) + 1
        save(data)
        print(f"✅ Retiré : {official}")
        print(f"Pool : {len(data['spider_card_pool'])} cartes · version {data['pool_version']}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
