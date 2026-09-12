from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from discord import app_commands


SCHEDULE_PATH = Path(__file__).resolve().parents[1] / "data" / "tournament_schedule.json"


def load_schedule() -> dict[str, Any]:
    with SCHEDULE_PATH.open("r", encoding="utf-8") as source:
        return json.load(source)


def schedule_slots() -> list[dict[str, Any]]:
    return [
        slot
        for month in load_schedule().get("months", [])
        for slot in month.get("slots", [])
    ]


def get_schedule_slot(slot_id: str | None) -> dict[str, Any] | None:
    if not slot_id:
        return None
    return next((slot for slot in schedule_slots() if slot["id"] == slot_id), None)


async def schedule_slot_autocomplete(
    _interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    query = current.casefold().strip()
    choices: list[app_commands.Choice[str]] = []
    for slot in schedule_slots():
        label = (
            f"{slot['day_label']} · {slot['start']}–{slot['end']} · "
            f"{slot['format']}"
        )
        if query and query not in label.casefold() and query not in slot["id"]:
            continue
        choices.append(app_commands.Choice(name=label[:100], value=slot["id"]))
        if len(choices) == 25:
            break
    return choices


def public_schedule(tournaments: list[dict[str, Any]]) -> dict[str, Any]:
    schedule = deepcopy(load_schedule())
    by_slot = {
        str(tournament.get("scheduled_slot_id")): tournament
        for tournament in tournaments
        if tournament.get("scheduled_slot_id")
    }
    for month in schedule.get("months", []):
        for slot in month.get("slots", []):
            slot["tournament"] = by_slot.get(slot["id"])
    return schedule
