from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from copy import deepcopy
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from discord import app_commands


SCHEDULE_PATH = Path(__file__).resolve().parents[1] / "data" / "tournament_schedule.json"


PARIS = ZoneInfo("Europe/Paris")
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
DAYS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")


def local_now(now: datetime | None = None) -> datetime:
    if now is not None and now.tzinfo is None:
        raise ValueError("Une date avec fuseau horaire est requise.")
    return now.astimezone(PARIS) if now is not None else datetime.now(PARIS)


def slot_start(slot: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(f"{slot['date']}T{slot['start']}").replace(tzinfo=PARIS)


def registration_window(slot: dict[str, Any]) -> tuple[datetime, datetime]:
    start = slot_start(slot)
    return start - timedelta(days=7), start - timedelta(minutes=30)


def registration_error(slot_id: str | None, now: datetime | None = None) -> str | None:
    slot = next((slot for slot in schedule_slots(now) if slot["id"] == slot_id), None)
    if not slot_id:
        return None
    if slot is None or slot.get("cancelled"):
        return "Ce créneau a été retiré du planning. Contacte le staff."
    opens, closes = registration_window(slot)
    current = local_now(now)
    if current < opens:
        return f"Les inscriptions ouvrent le {opens:%d/%m à %H:%M} (heure de Paris)."
    if current >= closes:
        return "Les inscriptions sont closes : fermeture 30 minutes avant le début."
    return None


def load_schedule(now: datetime | None = None) -> dict[str, Any]:
    with SCHEDULE_PATH.open("r", encoding="utf-8") as source:
        schedule = json.load(source)
    rolling = schedule.get("rolling", {})
    if not rolling.get("enabled"):
        return schedule
    anchor = date.fromisoformat(rolling["start_date"])
    horizon = local_now(now).date() + timedelta(weeks=int(rolling.get("weeks_ahead", 12)))
    rotation = rolling["rotation"]
    if not rotation:
        raise ValueError("La rotation doit contenir au moins un format.")
    by_month = {month["key"]: month for month in schedule["months"]}
    occupied = {slot["date"] for month in schedule["months"] for slot in month["slots"]}
    exceptions = schedule.get("exceptions", {})
    monday = anchor - timedelta(days=anchor.weekday())
    while monday <= horizon:
        week = (monday - anchor).days // 7
        special = "Halloween" if (monday + timedelta(days=5)).month == 10 else rotation[week % len(rotation)]
        for weekday in (5, 6):
            day = monday + timedelta(days=weekday)
            if day < anchor or day.isoformat() in occupied:
                continue
            classic = (weekday == 5) == (week % 2 == 0)
            fmt = "Classique" if classic else special
            slot = {
                "id": f"auto-{day.isoformat()}", "code": f"H-{day:%y%m%d}",
                "date": day.isoformat(),
                "day_label": f"{DAYS[weekday]} {day.day} {MONTHS[day.month - 1]}",
                "start": "18:00" if weekday == 5 and not classic else "16:00",
                "end": ("21:30" if classic else "22:30") if weekday == 5 else ("19:30" if fmt in {"Suisse", "Boss"} else "18:30"),
                "format": fmt, "kind": "classic" if classic else "special",
                "platform": rolling.get("platform", "YGO Omega"),
                "structure": "swiss" if fmt == "Suisse" else "single_elimination",
                "emoji": "🏆" if classic else "✦",
            }
            override = exceptions.get(day.isoformat(), {})
            slot.update(override)
            # Un changement de format doit changer sa structure, sauf choix explicite.
            if "format" in override and "structure" not in override:
                slot["structure"] = "swiss" if slot["format"] == "Suisse" else "single_elimination"
            key = day.strftime("%Y-%m")
            by_month.setdefault(key, {"key": key, "label": f"{MONTHS[day.month-1].capitalize()} {day.year}", "emoji": "", "slots": []})["slots"].append(slot)
        monday += timedelta(days=7)
    schedule["months"] = sorted(by_month.values(), key=lambda month: month["key"])
    for month in schedule["months"]:
        for slot in month["slots"]:
            slot.update(exceptions.get(slot["date"], {}))
    return schedule


def schedule_slots(now: datetime | None = None) -> list[dict[str, Any]]:
    return [
        slot
        for month in load_schedule(now).get("months", [])
        for slot in month.get("slots", [])
    ]


def get_schedule_slot(slot_id: str | None) -> dict[str, Any] | None:
    if not slot_id:
        return None
    return next((slot for slot in schedule_slots() if slot["id"] == slot_id), None)


def schedule_tournament_specs(max_players: int = 8, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Retourne les tournois officiels à créer pour le planning public."""
    return [
        {
            "scheduled_slot_id": slot["id"],
            "code": slot["code"],
            "date": slot["date"],
            "start": slot["start"],
            "name": f"{slot['format']} — {slot['day_label']}",
            "format": slot["format"],
            "max_players": int(slot.get("max_players", max_players)),
            "structure": slot.get("structure", "single_elimination"),
        }
        for slot in schedule_slots(now)
        if not slot.get("cancelled")
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
    now: datetime | None = None,
) -> list[int]:
    """Crée une seule fois chaque tournoi planifié et retourne les nouveaux ID."""
    if not guild_id:
        raise ValueError("Un identifiant de serveur est requis pour créer le planning.")
    if max_players not in (4, 8, 16, 32, 64, 128):
        raise ValueError("La capacité du planning doit être 4, 8, 16, 32, 64 ou 128.")

    created_ids: list[int] = []
    current = local_now(now)
    for spec in schedule_tournament_specs(max_players, now=current):
        if spec["max_players"] not in (4, 8, 16, 32, 64, 128):
            raise ValueError(f"Capacité invalide : {spec['scheduled_slot_id']}")
        opens, closes = registration_window(spec)
        if not opens <= current < closes:
            continue
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
                "planning-automatique",
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
        if slot.get("cancelled") or slot_start(slot) <= local_now():
            continue
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


def public_schedule(tournaments: list[dict[str, Any]], *, now: datetime | None = None, upcoming_only: bool = False) -> dict[str, Any]:
    schedule = deepcopy(load_schedule(now))
    by_slot = {
        str(tournament.get("scheduled_slot_id")): tournament
        for tournament in tournaments
        if tournament.get("scheduled_slot_id")
    }
    for month in schedule.get("months", []):
        for slot in month.get("slots", []):
            slot["tournament"] = by_slot.get(slot["id"])
            tournament = slot["tournament"] or {}
            try:
                minimum = max(2, int(slot.get("min_players", os.getenv("HAMTARO_AUTO_START_MIN_PLAYERS", "4"))))
            except (TypeError, ValueError):
                minimum = 4
            slot["minimum_players"] = min(minimum, tournament.get("max_players") or slot.get("max_players", 8))
            opens, closes = registration_window(slot)
            current = local_now(now)
            status = str(tournament.get("status", ""))
            slot["registration_opens"] = opens.strftime("%d/%m à %H:%M")
            slot["registration_closes"] = closes.strftime("%d/%m à %H:%M")
            slot["status_label"] = (
                "Annulé" if slot.get("cancelled") or status == "cancelled" else
                "Terminé" if status in {"finished", "completed", "ended", "closed", "archived"} else
                "En cours" if status and status not in {"registration", "check_in"} else
                "Inscriptions closes" if current >= closes else
                "À venir" if current < opens or not tournament else
                "Complet" if tournament.get("participant_count", 0) >= tournament.get("max_players", 8) else
                "Inscriptions ouvertes"
            )
        if upcoming_only:
            month["slots"] = [slot for slot in month["slots"] if slot["date"] >= local_now(now).date().isoformat()]
    if upcoming_only:
        schedule["months"] = [month for month in schedule["months"] if month["slots"]]
    return schedule


def weekly_schedule(tournaments: list[dict[str, Any]], now: datetime | None = None, week_offset: int = 0) -> dict[str, Any]:
    current = local_now(now)
    monday = current.date() - timedelta(days=current.weekday()) + timedelta(weeks=week_offset)
    sunday = monday + timedelta(days=6)
    schedule = public_schedule(tournaments, now=current)
    slots = [slot for month in schedule["months"] for slot in month["slots"] if monday.isoformat() <= slot["date"] <= sunday.isoformat()]
    return {"key": monday.isoformat(), "label": f"{monday:%d/%m} — {sunday:%d/%m/%Y}", "slots": slots, "monday": monday, "sunday": sunday}
