"""Programme partagé par le site, l'affiche et la publication Discord."""
from __future__ import annotations

import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from services.tournament_schedule_service import local_now, weekly_schedule


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


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    suffix = "-Bold" if bold else ""
    bundled = Path(__file__).resolve().parents[1] / "web" / "static" / "fonts" / f"DejaVuSans{suffix}.ttf"
    for path in (bundled, Path(f"/usr/share/fonts/truetype/dejavu/DejaVuSans{suffix}.ttf")):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise RuntimeError("Police DejaVuSans absente : impossible de produire une affiche lisible.")


def render_weekly_poster(program: dict[str, Any]) -> bytes:
    """Affiche de données exacte, sans API payante ni texte généré aléatoirement."""
    slots = program["slots"]
    width = 1600
    card_height = 400
    rows = max(1, (len(slots) + 1) // 2)
    height = 440 + rows * (card_height + 28) + 300
    canvas = Image.new("RGB", (width, height), "#0c1322")
    draw = ImageDraw.Draw(canvas)
    cream, muted, gold, blue = "#f4f2e9", "#b3bfd0", "#f4c66a", "#89c7fd"
    draw.rounded_rectangle((64, 64, 285, 112), radius=24, fill=gold)
    draw.text((88, 73), "FUN ROW / YGO", font=_font(22, True), fill="#151d2a")
    draw.text((64, 141), "HAMTARO CUP", font=_font(84, True), fill=cream)
    draw.text((68, 249), "Ton week-end. Tes duels.", font=_font(37), fill=muted)
    draw.text((68, 320), f"SEMAINE DU {program['label']}", font=_font(28, True), fill=gold)
    if program.get("preview"):
        draw.text((width-420, 125), "APERÇU · DÉMONSTRATION", font=_font(20), fill=muted)
    draw.text((width-420, 80), "PARIS · CET / CEST", font=_font(24), fill=muted)
    for index, slot in enumerate(slots):
        x, y = 64 + (index % 2) * 748, 420 + (index // 2) * 428
        draw.rounded_rectangle((x, y, x+720, y+card_height), radius=24, fill="#182438", outline="#33445d", width=2)
        color = gold if slot.get("kind") == "classic" else blue
        draw.rounded_rectangle((x+28, y+28, x+34, y+106), radius=3, fill=color)
        draw.text((x+56, y+28), slot["day_label"].upper(), font=_font(25, True), fill=color)
        draw.text((x+56, y+68), f"{slot['start']}  →  {slot['end']}*", font=_font(29, True), fill=cream)
        t = slot.get("tournament") or {}
        title = str(t.get("format") or slot["format"])
        size = 43
        while draw.textlength(title, font=_font(size, True)) > 650 and size > 20:
            size -= 1
        draw.text((x+28, y+134), title, font=_font(size, True), fill=cream)
        draw.text((x+28, y+195), str(slot.get("platform", "Plateforme à confirmer")), font=_font(25), fill=muted)
        for line_index, line in enumerate(modalities(slot)):
            draw.text((x+28, y+242+line_index*35), line, font=_font(23), fill=cream)
        status = slot["status_label"]
        code = str(t.get("code") or slot["code"])
        draw.text((x+28, y+330), f"{status} · {code}", font=_font(22, True), fill=color)
        draw.text((x+28, y+364), f"Minimum : {slot['minimum_players']} joueurs · clôture {slot['registration_closes']}", font=_font(20), fill=muted)
    if not slots:
        draw.text((100, 500), "Pause cette semaine", font=_font(54, True), fill=cream)
        draw.text((100, 585), "Le prochain programme sera annoncé sur Fun Row.", font=_font(30), fill=muted)
    y = 440 + rows * 428
    draw.text((64, y+12), "COMMENT PARTICIPER", font=_font(29, True), fill=gold)
    draw.text((64, y+65), "01  Sur Fun Row, ouvre /hamtaro", font=_font(27), fill=cream)
    draw.text((64, y+108), "02  Choisis le tournoi → S’inscrire → indique ton deck", font=_font(27), fill=cream)
    draw.text((64, y+157), "Ouverture à J−7 · clôture 30 min avant · sans check-in", font=_font(24), fill=muted)
    draw.text((64, y+198), "4 joueurs minimum par défaut · *heure de fin indicative", font=_font(23), fill=muted)
    draw.text((64, height-42), "PROGRAMME ET RÈGLEMENTS  /  hamtaro-production.up.railway.app", font=_font(21, True), fill=gold)
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


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
    lines.extend(["\n**Pour t’inscrire** : `/hamtaro` → choisir le tournoi → **S’inscrire**, puis renseigner ton deck.", "Ouverture à J−7, clôture 30 minutes avant. Pas de check-in. Annulation si moins de 4 joueurs (sauf seuil spécifique annoncé).", "Consulte le règlement du format avant de jouer. L’heure de fin est indicative."])
    return "\n".join(lines)
