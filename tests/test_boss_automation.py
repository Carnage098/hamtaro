import asyncio

import services.boss_arena_service as arena_module
from services.boss_arena_service import BossArenaService


def test_carry_configuration_sets_safe_defaults_for_first_boss(tmp_path, monkeypatch):
    monkeypatch.setattr(arena_module, "DATABASE", tmp_path / "boss-defaults.db")
    service = BossArenaService()

    settings = asyncio.run(service.carry_configuration("guild-1", "boss-1"))

    assert settings["configured_boss_id"] == "boss-1"
    assert settings["platform_key"] == "master_duel"
    assert settings["format_key"] == "classique"


def test_carry_configuration_keeps_rules_and_match_channel(tmp_path, monkeypatch):
    monkeypatch.setattr(arena_module, "DATABASE", tmp_path / "boss-transfer.db")
    service = BossArenaService()

    async def scenario():
        await service.set_match_channel("guild-1", "channel-42")
        await service.configure("guild-1", "boss-1", "omega", "edison")
        return await service.carry_configuration("guild-1", "boss-2")

    settings = asyncio.run(scenario())

    assert settings["configured_boss_id"] == "boss-2"
    assert settings["platform_key"] == "omega"
    assert settings["format_key"] == "edison"
    assert settings["match_channel_id"] == "channel-42"
