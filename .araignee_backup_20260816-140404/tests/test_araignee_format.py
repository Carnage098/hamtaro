from services.araignee_format_service import AraigneeFormatService


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


def test_valid_main_quota():
    service = AraigneeFormatService()
    decklist = "\n".join(
        [
            "Bébé Araignée", "Araignée Matriarche Fendeuse", "Araignée Matriarche",
            "Araignée des Cavernes", "Araignée des Ténèbres", "Araignée du Sacrifice",
            "Araignée Sniper", "Araignée Chasseuse", "Kumootoko", "Jirai Gumo",
        ]
        + [f"Carte générique {index}" for index in range(30)]
    )
    result = service.validate_text(decklist)
    assert result.main_count == 40
    assert result.spider_count == 10
    assert result.valid


def test_full_sections_are_checked():
    service = AraigneeFormatService()
    lines = (
        ["Main Deck"]
        + [
            "Bébé Araignée", "Araignée Matriarche Fendeuse", "Araignée Matriarche",
            "Araignée des Cavernes", "Araignée des Ténèbres", "Araignée du Sacrifice",
            "Araignée Sniper", "Araignée Chasseuse", "Kumootoko", "Jirai Gumo",
        ]
        + [f"Carte générique {index}" for index in range(30)]
        + ["Extra Deck"]
        + [f"Extra {index}" for index in range(15)]
        + ["Side Deck"]
        + [f"Side {index}" for index in range(3)]
    )
    result = service.validate_text("\n".join(lines))
    assert result.extra_count == 15
    assert result.side_count == 3
    assert result.checks["extra_deck_size"] is True
    assert result.checks["side_deck_size"] is True
    assert result.valid


def test_too_many_copies_is_rejected():
    service = AraigneeFormatService()
    lines = (
        ["Bébé Araignée"] * 10
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
