from datetime import datetime
from zoneinfo import ZoneInfo

from services.tournament_automation_service import (
    due_tournament_specs,
    scheduled_start_at,
)


PARIS = ZoneInfo("Europe/Paris")


def test_schedule_start_uses_paris_timezone():
    start = scheduled_start_at(
        {"date": "2026-09-19", "start": "18:00"},
        "Europe/Paris",
    )
    assert start == datetime(2026, 9, 19, 18, 0, tzinfo=PARIS)


def test_due_tournaments_only_include_started_slots():
    due = due_tournament_specs(datetime(2026, 9, 20, 15, 59, tzinfo=PARIS))
    assert [spec["scheduled_slot_id"] for spec in due] == [
        "2026-09-19-suisse"
    ]


def test_swiss_slots_keep_the_swiss_structure():
    due = due_tournament_specs(datetime(2026, 11, 22, 16, 0, tzinfo=PARIS))
    swiss = [spec for spec in due if spec["code"].startswith("SUI-")]
    assert len(swiss) == 2
    assert {spec["structure"] for spec in swiss} == {"swiss"}
