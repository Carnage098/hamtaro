from services.tournament_schedule_service import (
    get_schedule_slot,
    public_schedule,
    schedule_tournament_specs,
    schedule_slots,
)


def test_schedule_contains_all_announced_slots():
    slots = schedule_slots()
    assert len(slots) == 22
    assert slots[0]["id"] == "2026-09-19-suisse"
    assert slots[-1]["id"] == "2026-11-29-classique"
    assert len({slot["id"] for slot in slots}) == len(slots)


def test_public_schedule_links_real_tournament_details():
    tournament = {
        "id": 42,
        "code": "TCG-4242",
        "name": "Hamtaro Suisse",
        "status": "registration",
        "max_players": 16,
        "participant_count": 7,
        "scheduled_slot_id": "2026-09-19-suisse",
    }
    schedule = public_schedule([tournament])
    first_slot = schedule["months"][0]["slots"][0]
    assert first_slot["tournament"] == tournament
    assert get_schedule_slot("inconnu") is None


def test_unlinked_slot_stays_visible():
    schedule = public_schedule([])
    assert schedule["months"][0]["slots"][0]["tournament"] is None


def test_all_schedule_tournaments_have_unique_codes_and_eight_places():
    specs = schedule_tournament_specs()
    assert len(specs) == 22
    assert len({spec["code"] for spec in specs}) == 22
    assert {spec["max_players"] for spec in specs} == {8}
    assert specs[0]["code"] == "SUI-1909"
    assert specs[3]["code"] == "SPE-2709"
