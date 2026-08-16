#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FORMAT_PATH = ROOT / "data" / "formats" / "araignee.json"
MANIFEST_PATH = ROOT / "data" / "formats" / "araignee_images.json"
IMAGE_DIR = ROOT / "web" / "static" / "araignee" / "cards"
API_FR = "https://db.ygoprodeck.com/api/v7/cardinfo.php?language=fr"
API_EN = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
USER_AGENT = "Hamtaro-Araignee/4.0 (+local-image-sync)"


def normalize(value: str) -> str:
    value = str(value or "").strip().casefold()
    value = value.replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())


def best_image(card: dict[str, Any]) -> str | None:
    images = card.get("card_images") or []
    if not images:
        return None
    image = images[0] or {}
    return image.get("image_url_small") or image.get("image_url")


def build_index(cards: list[dict[str, Any]], language: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for card in cards:
        name = str(card.get("name") or "").strip()
        if not name:
            continue
        key = normalize(name)
        if not key or key in index:
            continue
        index[key] = {
            "id": int(card.get("id") or 0),
            "name": name,
            "language": language,
            "image": best_image(card),
        }
    return index


def load_format() -> dict[str, Any]:
    return json.loads(FORMAT_PATH.read_text(encoding="utf-8"))


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"version": 1, "cards": {}}
    try:
        loaded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "cards": {}}
    if not isinstance(loaded, dict):
        return {"version": 1, "cards": {}}
    loaded.setdefault("version", 1)
    loaded.setdefault("cards", {})
    return loaded


def status() -> int:
    data = load_format()
    pool = data.get("spider_card_pool") or []
    manifest = load_manifest()
    cards = manifest.get("cards") or {}
    local = 0
    for name in pool:
        item = cards.get(name) or {}
        relative = item.get("local_path")
        if relative and (ROOT / relative).exists():
            local += 1
    print(f"🕷️ Galerie Araignée : {local}/{len(pool)} image(s) locale(s)")
    unresolved = [name for name in pool if not (cards.get(name) or {}).get("local_path")]
    if unresolved:
        print(f"⚠️ Sans image : {len(unresolved)}")
        for name in unresolved[:20]:
            print(" -", name)
        if len(unresolved) > 20:
            print(f" ... et {len(unresolved)-20} autre(s)")
    return 0


def sync(force: bool = False) -> int:
    data = load_format()
    pool = [str(x) for x in data.get("spider_card_pool") or []]
    if not pool:
        print("❌ Pool Araignée vide.")
        return 1

    print("📚 Téléchargement de l'index français YGOPRODeck…")
    try:
        fr_payload = request_json(API_FR)
        print("📚 Téléchargement de l'index anglais de secours…")
        en_payload = request_json(API_EN)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"❌ Impossible de récupérer l'API YGOPRODeck : {error}")
        return 2

    fr_index = build_index(fr_payload.get("data") or [], "fr")
    en_index = build_index(en_payload.get("data") or [], "en")

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 1,
        "source": "YGOPRODeck API v7",
        "note": "Images téléchargées localement conformément au guide API ; pas de hotlink continu.",
        "cards": {},
    }

    matched = 0
    downloaded = 0
    unresolved: list[str] = []

    for index, pool_name in enumerate(pool, start=1):
        key = normalize(pool_name)
        found = fr_index.get(key) or en_index.get(key)
        if not found or not found.get("image") or not found.get("id"):
            manifest["cards"][pool_name] = {
                "status": "missing",
                "local_path": None,
            }
            unresolved.append(pool_name)
            print(f"[{index:03}/{len(pool):03}] ⚠️ {pool_name} — image non résolue")
            continue

        matched += 1
        card_id = int(found["id"])
        relative = Path("web") / "static" / "araignee" / "cards" / f"{card_id}.jpg"
        destination = ROOT / relative

        try:
            if force or not destination.exists() or destination.stat().st_size < 1000:
                download(str(found["image"]), destination)
                downloaded += 1
                # Rythme volontairement modéré pour le serveur d'images.
                time.sleep(0.12)
            manifest["cards"][pool_name] = {
                "status": "ok",
                "card_id": card_id,
                "api_name": found["name"],
                "language": found["language"],
                "local_path": str(relative).replace("\\", "/"),
            }
            print(f"[{index:03}/{len(pool):03}] ✅ {pool_name} -> {found['name']}")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            manifest["cards"][pool_name] = {
                "status": "error",
                "card_id": card_id,
                "api_name": found["name"],
                "language": found["language"],
                "local_path": None,
                "error": str(error),
            }
            unresolved.append(pool_name)
            print(f"[{index:03}/{len(pool):03}] ❌ {pool_name} — {error}")

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"✅ Correspondances : {matched}/{len(pool)}")
    print(f"✅ Images téléchargées/rafraîchies : {downloaded}")
    print(f"⚠️ Sans image : {len(unresolved)}")
    print(f"📄 Manifest : {MANIFEST_PATH.relative_to(ROOT)}")
    print(f"🖼️ Dossier : {IMAGE_DIR.relative_to(ROOT)}")
    if unresolved:
        print("\nCartes non résolues :")
        for name in unresolved:
            print(" -", name)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchroniser les images du Format Araignée.")
    sub = parser.add_subparsers(dest="command", required=True)
    sync_parser = sub.add_parser("sync", help="Télécharger les images manquantes localement.")
    sync_parser.add_argument("--force", action="store_true", help="Retélécharger les images existantes.")
    sub.add_parser("status", help="Afficher la couverture de la galerie.")
    args = parser.parse_args()
    if args.command == "sync":
        return sync(force=args.force)
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
