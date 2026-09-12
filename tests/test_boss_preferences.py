import pytest

from services.boss_service import BossService


def test_boss_preferences_accept_supported_combinations():
    assert BossService._validate_preferences(
        "master_duel", "anime", "samedi 18 h"
    ) == ("master_duel", "anime", "samedi 18 h")
    assert BossService._validate_preferences(
        "omega", "edison", None
    ) == ("omega", "edison", None)


def test_boss_preferences_reject_incompatible_format():
    with pytest.raises(ValueError):
        BossService._validate_preferences("master_duel", "goat", None)


def test_boss_preferences_require_both_choices():
    with pytest.raises(ValueError):
        BossService._validate_preferences("omega", None, None)
