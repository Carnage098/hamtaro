"""Programme partagé par le site, l'affiche et la publication Discord."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from services.tournament_schedule_service import local_now, weekly_schedule
from services.weekly_poster_renderer import render_poster


async def init_weekly_schema(db: Any) -> None:
    await db.execute("""CREATE TABLE IF NOT EXISTS weekly_program_settings (
        guild_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL,
        weekday INTEGER NOT NULL DEFAULT 2, hour INTEGER NOT NULL DEFAULT 18,
        minute INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 0
    )""", commit=True)
    await db.execute("""CREATE TABLE IF NOT EXISTS weekly_program_publications (
        guild_id TEXT NOT NULL, week_key TEXT NOT NULL, channel_id TEXT NOT NULL,
        message_id TEXT, status TEXT NOT NULL, error TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (guild_id, week_key)
    )""", commit=True)


def publication_due(settings: dict[str, Any], now: datetime | None = None) -> bool:
    current = local_now(now)
    monday = current.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=current.weekday())
    publish_at = monday + timedelta(days=settings["weekday"], hours=settings["hour"], minutes=settings["minute"])
    # Après une panne, rattrapage seulement avant le week-end concerné.
    return bool(settings["enabled"]) and publish_at <= current < monday + timedelta(days=5)


async def get_week_program(db: Any, guild_id: str, *, now: datetime | None = None, week_offset: int = 0) -> dict[str, Any]:
    rows = await db.fetchall("""SELECT t.*, (
        SELECT COUNT(*) FROM registrations r WHERE r.tournament_id=t.id
        AND COALESCE(r.dropped, 0)=0 AND COALESCE(r.disqualified, 0)=0
    ) AS participant_count FROM tournaments t
    WHERE t.guild_id=? AND t.scheduled_slot_id IS NOT NULL""", (guild_id,))
    return weekly_schedule([dict(row) for row in rows], now=now, week_offset=week_offset)


def modalities(slot: dict[str, Any]) -> list[str]:
    fmt = str((slot.get("tournament") or {}).get("format") or slot["format"])
    if fmt.casefold() == "suisse":
        return ["Rondes suisses · 50 min par ronde", "Double Loss autorisé · BYE actif"]
    if fmt.casefold() == "boss":
        return ["BO3 · sans Side Deck", "Règles Boss à consulter avant de jouer"]
    return ["Élimination directe", "Sans limite de 50 min · sans Double Loss"]


def render_weekly_poster(program: dict[str, Any]) -> bytes:
    """Même affiche pour l’aperçu staff et l’annonce, avec les données réelles."""
    return render_poster(program, [modalities(slot) for slot in program["slots"]])


def program_description(program: dict[str, Any]) -> str:
    lines = [f"**Semaine du {program['label']} — heures de Paris**"]
    for slot in program["slots"]:
        t = slot.get("tournament") or {}
        lines.extend([
            f"\n**{slot['day_label']} à {slot['start']} — {t.get('format') or slot['format']}**",
            f"{slot['status_label']} · {slot['platform']}",
            " · ".join(modalities(slot)),
            f"Code : `{t.get('code') or slot['code']}` · minimum : {slot['minimum_players']} joueurs · clôture : {slot['registration_closes']}",
        ])
    if not program["slots"]:
        lines.append("Aucun tournoi prévu cette semaine.")
    lines.extend(["\n**Pour t’inscrire** : sur Fun Row, utilise `/inscription` avec le **code du tournoi** et ton deck. Le menu `/hamtaro` reste disponible pour le suivi.", "Ouverture à J−7, clôture 30 minutes avant. Pas de check-in. Annulation si le minimum indiqué pour le tournoi n’est pas atteint.", "Consulte le règlement du format avant de jouer. L’heure de fin est indicative."])
    return "\n".join(lines)
