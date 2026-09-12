from __future__ import annotations

import asyncio
from types import SimpleNamespace

from utils.tournament_resolver import active_tournament_code_autocomplete


class FakeDatabase:
    def __init__(self, tournaments):
        self.tournaments = tournaments

    async def list_active_tournaments(self, guild_id: str):
        assert guild_id == "42"
        return self.tournaments


def tournament(identifier: int, code: str, slot: str | None, name: str = "Tournoi"):
    return SimpleNamespace(
        id=identifier,
        code=code,
        name=name,
        scheduled_slot_id=slot,
    )


def test_registration_choices_show_manual_then_planning_in_chronological_order() -> None:
    tournaments = [
        tournament(30, "GEN-1110", "2026-10-11-genesys"),
        tournament(10, "SUI-1909", "2026-09-19-suisse"),
        tournament(20, "TCG-2009", "2026-09-20-classique"),
        tournament(99, "LIBRE-01", None, "Tournoi libre"),
    ]
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=42),
        client=SimpleNamespace(db=FakeDatabase(tournaments)),
    )

    choices = asyncio.run(active_tournament_code_autocomplete(interaction, ""))

    assert [choice.value for choice in choices] == [
        "LIBRE-01", "SUI-1909", "TCG-2009", "GEN-1110",
    ]
    assert "Samedi 19 septembre" in choices[1].name


def test_registration_choices_filters_on_an_exact_code() -> None:
    tournaments = [
        tournament(index, f"CODE-{index:02d}", None)
        for index in range(40)
    ]
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=42),
        client=SimpleNamespace(db=FakeDatabase(tournaments)),
    )

    choices = asyncio.run(active_tournament_code_autocomplete(interaction, "CODE-03"))

    assert [choice.value for choice in choices] == ["CODE-03"]
