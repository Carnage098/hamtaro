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


def schedule_tournament_specs(max_players: int = 8) -> list[dict[str, Any]]:
    """Retourne les tournois officiels à créer pour le planning public."""
    return [
        {
            "scheduled_slot_id": slot["id"],
            "code": slot["code"],
            "date": slot["date"],
            "start": slot["start"],
            "name": f"{slot['format']} — {slot['day_label']}",
            "format": slot["format"],
            "max_players": max_players,
            "structure": slot.get("structure", "single_elimination"),
        }
        for slot in schedule_slots()
    ]


async def _available_code(database: Any, requested_code: str) -> str:
    """Conserve le code lisible, avec un suffixe seulement en cas de collision."""
    candidate = requested_code
    suffix = 1
    while await database.fetchone(
        "SELECT id FROM tournaments WHERE code = ? LIMIT 1",
        (candidate,),
    ) is not None:
        suffix += 1
        candidate = f"{requested_code}-{suffix}"
    return candidate


async def ensure_schedule_tournaments(
    database: Any,
    guild_id: str,
    *,
    max_players: int = 8,
) -> list[int]:
    """Crée une seule fois chaque tournoi planifié et retourne les nouveaux ID."""
    if not guild_id:
        raise ValueError("Un identifiant de serveur est requis pour créer le planning.")
    if max_players not in (4, 8, 16, 32, 64):
        raise ValueError("La capacité du planning doit être 4, 8, 16, 32 ou 64.")

    created_ids: list[int] = []
    for spec in schedule_tournament_specs(max_players):
        existing = await database.fetchone(
            "SELECT id FROM tournaments WHERE scheduled_slot_id = ? LIMIT 1",
            (spec["scheduled_slot_id"],),
        )
        if existing is not None:
            continue

        code = await _available_code(database, spec["code"])
        tournament_id = await database.insert(
            """
            INSERT INTO tournaments (
                guild_id, code, name, format, max_players, status,
                created_by, scheduled_slot_id
            )
            VALUES (?, ?, ?, ?, ?, 'registration', ?, ?)
            """,
            (
                guild_id,
                code,
                spec["name"],
                spec["format"],
                spec["max_players"],
                "planning-automatique-2026",
                spec["scheduled_slot_id"],
            ),
        )
        created_ids.append(tournament_id)

    return created_ids


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
