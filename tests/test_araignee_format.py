import json

from services.araignee_format_service import AraigneeFormatService


def _ten_spiders():
    return [
        "Bébé Araignée",
        "Araignée Matriarche Fendeuse",
        "Araignée Matriarche",
        "Araignée des Cavernes",
        "Araignée des Ténèbres",
        "Araignée du Sacrifice",
        "Araignée Sniper",
        "Araignée Chasseuse",
        "Kumootoko",
        "Jirai Gumo",
    ]


def test_pool_contains_130_unique_cards():
    service = AraigneeFormatService()
    assert len(service.pool()) == 130
    assert len(service.normalized_pool()) == 130


def test_normalization_accepts_typography():
    service = AraigneeFormatService()
    assert (
        service.normalize_name("Griffe d’Arsenal")
        == service.normalize_name("Griffe d'Arsenal")
    )


def test_main_40_is_valid():
    service = AraigneeFormatService()
    decklist = "\n".join(
        _ten_spiders()
        + [f"Carte générique {index}" for index in range(30)]
    )
    result = service.validate_text(decklist)
    assert result.main_count == 40
    assert result.spider_count == 10
    assert result.valid


def test_main_60_is_valid():
    service = AraigneeFormatService()
    decklist = "\n".join(
        _ten_spiders()
        + [f"Carte générique {index}" for index in range(50)]
    )
    result = service.validate_text(decklist)
    assert result.main_count == 60
    assert result.valid


def test_main_outside_40_60_is_rejected():
    service = AraigneeFormatService()

    too_short = "\n".join(
        _ten_spiders()
        + [f"Carte {index}" for index in range(29)]
    )
    too_long = "\n".join(
        _ten_spiders()
        + [f"Carte {index}" for index in range(51)]
    )

    assert not service.validate_text(too_short).valid
    assert not service.validate_text(too_long).valid


def test_extra_max_15_is_checked_and_side_is_free():
    service = AraigneeFormatService()
    lines = (
        ["Main Deck"]
        + _ten_spiders()
        + [f"Carte générique {index}" for index in range(30)]
        + ["Extra Deck"]
        + [f"Extra {index}" for index in range(15)]
        + ["Side Deck"]
        + [f"Side libre {index}" for index in range(9)]
    )
    result = service.validate_text("\n".join(lines))
    assert result.extra_count == 15
    assert result.side_count == 9
    assert result.checks["extra_deck_size"] is True
    assert result.checks["side_deck_size"] is None
    assert result.valid


def test_extra_over_15_is_rejected():
    service = AraigneeFormatService()
    lines = (
        ["Main Deck"]
        + _ten_spiders()
        + [f"Carte générique {index}" for index in range(30)]
        + ["Extra Deck"]
        + [f"Extra {index}" for index in range(16)]
    )
    result = service.validate_text("\n".join(lines))
    assert not result.valid
    assert result.checks["extra_deck_size"] is False


def test_too_many_copies_is_rejected():
    service = AraigneeFormatService()
    lines = (
        _ten_spiders()
        + ["Même Carte"] * 4
        + [f"Carte {index}" for index in range(26)]
    )
    result = service.validate_text("\n".join(lines))
    assert result.main_count == 40
    assert result.checks["default_copy_limit"] is False
    assert not result.valid


def test_ydk_numeric_ids_warn_instead_of_counting_as_names():
    service = AraigneeFormatService()
    text = "#main\n12345678\n#extra\n87654321\n!side\n11111111"
    result = service.validate_text(text)
    assert any(".ydk" in warning for warning in result.warnings)


def test_typo_can_suggest_pool_card():
    service = AraigneeFormatService()
    lines = (
        ["Bebe Araigne"] * 10
        + [f"Carte {index}" for index in range(30)]
    )
    result = service.validate_text("\n".join(lines))
    assert any(
        item["suggested"] == "Bébé Araignée"
        for item in result.suggestions
    )


def test_each_card_has_official_search_link():
    service = AraigneeFormatService()
    entries = service.card_entries()
    assert len(entries) == 130
    assert all(entry["url"].startswith("https://www.db.yugioh-card.com/") for entry in entries)
    assert "keyword=Jirai+Gumo" in service.official_card_search_url("Jirai Gumo")



def test_banlist_is_current_tcg():
    service = AraigneeFormatService()
    assert service.data()["banlists"] == ["Banlist TCG actuelle"]


def test_card_entries_do_not_hotlink_images_without_manifest(tmp_path):
    service = AraigneeFormatService()
    service.image_manifest_path = tmp_path / "missing.json"
    entries = service.card_entries()
    assert len(entries) == 130
    assert all(entry["image_url"] is None for entry in entries)


def test_card_entries_use_only_local_static_images(tmp_path):
    service = AraigneeFormatService()
    manifest = {
        "version": 1,
        "cards": {
            "Jirai Gumo": {
                "status": "ok",
                "card_id": 94773007,
                "api_name": "Jirai Gumo",
                "local_path": "web/static/araignee/cards/94773007.jpg",
            }
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    service.image_manifest_path = path
    entry = next(item for item in service.card_entries() if item["name"] == "Jirai Gumo")
    assert entry["image_url"] == "/static/araignee/cards/94773007.jpg"
    assert "ygoprodeck" not in entry["image_url"].lower()
