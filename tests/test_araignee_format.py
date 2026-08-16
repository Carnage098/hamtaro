import json

from services.araignee_format_service import AraigneeFormatService
from tools.araignee_images import load_aliases, resolve_card, build_index


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


def test_pool_contains_120_unique_cards():
    service = AraigneeFormatService()
    assert len(service.pool()) == 134
    assert len(service.normalized_pool()) == 134


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
    assert len(entries) == 134
    assert all(entry["url"].startswith("https://www.db.yugioh-card.com/") for entry in entries)
    assert "keyword=Jirai+Gumo" in service.official_card_search_url("Jirai Gumo")



def test_banlist_is_current_tcg():
    service = AraigneeFormatService()
    assert service.data()["banlists"] == ["Banlist TCG actuelle"]


def test_card_entries_do_not_hotlink_images_without_manifest(tmp_path):
    service = AraigneeFormatService()
    service.image_manifest_path = tmp_path / "missing.json"
    entries = service.card_entries()
    assert len(entries) == 134
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


def test_black_scorpions_removed_from_pool():
    service = AraigneeFormatService()
    removed = [
        "Scorpion Noir – Meute de la Vallée",
        "Scorpion Noir – Cimeterre",
        "Scorpion Noir – Gorgone",
        "Scorpion Noir – Pilleur",
        "Scorpion Noir – Maître des Ténèbres",
        "Scorpion Noir – Grand Maître",
        "Scorpion Noir – Sorcier",
        "Scorpion Noir – Aigle de la Vallée",
    ]
    names = set(service.pool())
    for card in removed:
        assert card not in names


def test_image_alias_file_contains_known_aliases():
    aliases = load_aliases()
    assert aliases["Bébé Araignée"] == "Baby Spider"
    assert aliases["Traptrix Trappelutea"] == "Traptrix Holeutea"


def test_resolve_card_uses_alias_when_exact_name_fails():
    fr_cards = []
    en_cards = [
        {
            "id": 123456,
            "name": "Baby Spider",
            "card_images": [{"image_url_small": "https://example.com/baby.jpg"}],
        }
    ]
    fr_index = build_index(fr_cards, "fr")
    en_index = build_index(en_cards, "en")
    aliases = {"Bébé Araignée": "Baby Spider"}

    found, alias_used, resolution = resolve_card("Bébé Araignée", fr_index, en_index, aliases)
    assert found is not None
    assert found["name"] == "Baby Spider"
    assert alias_used == "Baby Spider"
    assert resolution == "alias"


def test_ombre_spectrale_and_dragon_de_lave_removed():
    service = AraigneeFormatService()
    names = set(service.pool())
    assert "Ombre Spectrale" not in names
    assert "Dragon de Lave" not in names


def test_glass_spider_removed_from_pool():
    service = AraigneeFormatService()
    assert "Araignée de Verre" not in set(service.pool())


def test_v45_cards_added_to_pool():
    service = AraigneeFormatService()
    names = set(service.pool())
    added = [
        "Toile d'Araignée",
        "Larves d'Araignées",
        "Insecte des Ténèbres",
        "Épine Krawler",
        "Qualiarche X-Krawler",
        "Neurogos X-Krawler",
        "Krawler Croisédia",
        "Dendrite Krawler",
        "Deus X-Krawler",
        "Soma Krawler",
        "Récepteur Krawler",
        "Gliale Krawler",
        "Axone Krawler",
        "Ranvier Krawler",
        "Tragoedia",
    ]
    for card in added:
        assert card in names


def test_v45_new_cards_follow_positions_120_to_134():
    service = AraigneeFormatService()
    tail = service.pool()[-15:]
    assert tail[0] == "Toile d'Araignée"
    assert tail[-1] == "Tragoedia"
    assert len(tail) == 15
