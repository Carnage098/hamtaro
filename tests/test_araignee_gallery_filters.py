from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "sync_araignee_gallery_catalog.py"
spec = importlib.util.spec_from_file_location("araignee_catalog_sync", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class AraigneeGalleryFiltersTests(unittest.TestCase):
    def test_xyz_classification(self) -> None:
        card = {
            "id": 90162951,
            "name": "Number 35: Ravenous Tarantula",
            "type": "XYZ Monster",
            "race": "Insect",
            "attribute": "DARK",
            "level": 10,
        }
        entry = module.make_entry(
            "Numéro 35 : Tarentule Vorace",
            {"status": "ok", "card_id": 90162951, "local_path": "x.jpg"},
            card,
            None,
        )
        self.assertIn("xyz", entry["type_keys"])
        self.assertEqual(entry["zone"], "extra")
        self.assertEqual(entry["metric"]["kind"], "rank")
        self.assertEqual(entry["race_label"], "Insecte")
        self.assertEqual(entry["attribute_label"], "TÉNÈBRES")

    def test_spell_subtype(self) -> None:
        card = {"id": 1, "name": "Test", "type": "Spell Card", "race": "Quick-Play"}
        entry = module.make_entry("Test", {"status": "ok", "card_id": 1, "local_path": "x.jpg"}, card, None)
        self.assertEqual(entry["type_keys"], ["spell"])
        self.assertEqual(entry["spelltrap_subtype_label"], "Jeu-Rapide")
        self.assertEqual(entry["zone"], "main")

    def test_deck_tag_and_visual_family(self) -> None:
        card = {"id": 2, "name": "Traptrix Atrax", "type": "Effect Monster", "race": "Insect", "attribute": "EARTH", "level": 4, "archetype": "Traptrix"}
        entry = module.make_entry("Traptrix Atrax", {"status": "ok", "card_id": 2, "local_path": "x.jpg"}, card, None)
        self.assertEqual(entry["visual_family"], "humanoid")
        self.assertIn("SpiderWeb Traptrix", entry["deck_tags"])

    def test_offline_catalog_is_still_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "formats").mkdir(parents=True)
            (root / "web" / "static" / "araignee").mkdir(parents=True)
            manifest = {
                "cards": {
                    "Araignée Test": {
                        "status": "ok",
                        "card_id": 12345678,
                        "api_name": "Test Spider",
                        "local_path": "web/static/araignee/cards/12345678.jpg",
                    }
                }
            }
            (root / "data" / "formats" / "araignee_images.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "data" / "formats" / "araignee_gallery_overrides.json").write_text('{"cards": {}}', encoding="utf-8")
            output, payload = module.sync_catalog(root, allow_network=False)
            self.assertTrue(output.exists())
            self.assertEqual(payload["pool_count"], 1)
            self.assertEqual(payload["missing_metadata_count"], 1)
            self.assertEqual(payload["cards"][0]["visual_family"], "true_spider")


if __name__ == "__main__":
    unittest.main()
