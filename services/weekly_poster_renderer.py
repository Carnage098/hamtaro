"""Mise en page déterministe des affiches, adaptée aux aperçus Discord."""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parents[1] / "web" / "static"
WIDTH, MARGIN = 1080, 44
INK, MUTED, GOLD = "#F6F3EA", "#AFBED2", "#F8CA72"
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
          "août", "septembre", "octobre", "novembre", "décembre")


@lru_cache(maxsize=48)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = f"DejaVuSans{'-Bold' if bold else ''}.ttf"
    for path in (ASSETS / "fonts" / name, Path("/usr/share/fonts/truetype/dejavu") / name):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise RuntimeError("Police DejaVuSans absente : impossible de produire une affiche lisible.")


def wrap(text: str, face: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Conserve tout le texte, y compris les codes sans espaces."""
    lines: list[str] = []
    current = ""
    for word in str(text).split():
        candidate = f"{current} {word}" if current else word
        if face.getlength(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        for char in word:
            if current and face.getlength(current + char) > width:
                lines.append(current)
                current = ""
            current += char
    if current:
        lines.append(current)
    return lines or [""]


def week_label(program: dict[str, Any]) -> str:
    try:
        first = program["monday"]
        last = program["sunday"]
        first = date.fromisoformat(first) if isinstance(first, str) else first
        last = date.fromisoformat(last) if isinstance(last, str) else last
        if first.year != last.year:
            return f"{first:%d/%m/%Y} — {last:%d/%m/%Y}"
        if first.month == last.month:
            return f"{first.day:02d} — {last.day:02d} {MONTHS[last.month-1]} {last.year}".upper()
        return f"{first.day} {MONTHS[first.month-1]} — {last.day} {MONTHS[last.month-1]} {last.year}".upper()
    except (KeyError, TypeError, ValueError, AttributeError):
        return str(program["label"])


def registration_note(slot: dict[str, Any]) -> str:
    state = slot["status_label"]
    if state == "Annulé":
        return "Tournoi annulé · aucune inscription possible"
    if state == "Terminé":
        return "Tournoi terminé · résultats sur le site Hamtaro"
    if state == "En cours":
        return "Tournoi en cours · suis les matchs sur le site"
    if state == "À venir":
        return f"Ouverture prévue le {slot['registration_opens']}"
    if state == "Inscriptions closes":
        return f"Inscriptions closes depuis le {slot['registration_closes']}"
    return f"Clôture des inscriptions le {slot['registration_closes']}"


@dataclass
class TextBlock:
    lines: list[str]
    size: int
    bold: bool = False

    @property
    def line_height(self) -> int:
        return round(self.size * 1.3)

    @property
    def height(self) -> int:
        return len(self.lines) * self.line_height

    def paint(self, draw: ImageDraw.ImageDraw, xy: tuple[int, int], color: str) -> int:
        x, y = xy
        for line in self.lines:
            draw.text((x, y), line, font=font(self.size, self.bold), fill=color, anchor="lt")
            y += self.line_height
        return y


def block(text: str, width: int, size: int, bold: bool = False) -> TextBlock:
    return TextBlock(wrap(text, font(size, bold), width), size, bold)


def card_layout(slot: dict[str, Any], rules: list[str]) -> dict[str, Any]:
    tournament = slot.get("tournament") or {}
    inner = WIDTH - MARGIN * 2 - 56
    title = block(str(tournament.get("format") or slot["format"]), inner, 55, True)
    raw_platform = str(slot.get("platform") or "À confirmer")
    platform = block("Plateforme à confirmer" if raw_platform.casefold() == "à confirmer" else raw_platform,
                     inner, 27)
    rules_block = TextBlock([line for rule in rules for line in wrap(rule, font(26), inner)], 26)
    code = block(str(tournament.get("code") or slot["code"]), 430, 30, True)
    minimum = int(slot["minimum_players"])
    capacity = int(tournament.get("max_players") or slot.get("max_players", 8))
    capacity_block = block(f"{capacity} places · min. {minimum}", 445, 30, True)
    note = block(registration_note(slot), inner-36, 24)
    # Tous les champs variables participent au calcul : aucun texte coupé.
    height = (83 + title.height + 12 + 48 + 8 + platform.height + 20 + rules_block.height
              + 24 + 32 + max(code.height, capacity_block.height) + 20 + note.height + 36)
    return dict(title=title, platform=platform, rules=rules_block, code=code, capacity=capacity_block,
                note=note, height=height)


def pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
         color: str, background: str, size: int = 21) -> int:
    x, y = xy
    width = round(font(size, True).getlength(text)) + 32
    draw.rounded_rectangle((x, y, x+width, y+42), radius=21, fill=background)
    draw.text((x+16, y+10), text, font=font(size, True), fill=color, anchor="lt")
    return width


def paint_card(canvas: Image.Image, slot: dict[str, Any], layout: dict[str, Any], y: int):
    draw = ImageDraw.Draw(canvas)
    x, right = MARGIN, WIDTH-MARGIN
    accent = GOLD if slot.get("kind") == "classic" else "#A9C9FF"
    draw.rounded_rectangle((x, y+6, right, y+layout["height"]+6), radius=26, fill="#070E1C")
    draw.rounded_rectangle((x, y, right, y+layout["height"]), radius=26, fill="#17243A", outline="#324460", width=2)
    draw.rounded_rectangle((x, y+24, x+5, y+95), radius=2, fill=accent)
    status = slot["status_label"]
    tone = {"Inscriptions ouvertes": ("#8CE8B5", "#1B423E"),
            "Annulé": ("#FFB2BC", "#492B3C"),
            "Complet": (GOLD, "#493E2C"),
            "Inscriptions closes": (GOLD, "#493E2C")}.get(status, ("#B8D2FA", "#293D5A"))
    badge_width = round(font(21, True).getlength(status.upper())) + 32
    pill(draw, (right-28-badge_width, y+24), status.upper(), *tone)
    date_text = slot["day_label"].upper()
    date_size = 25
    while font(date_size, True).getlength(date_text) > right-x-84-badge_width and date_size > 18:
        date_size -= 1
    draw.text((x+28, y+33), date_text, font=font(date_size, True), fill=accent, anchor="lt")
    cursor = layout["title"].paint(draw, (x+28, y+83), INK) + 12
    draw.text((x+28, cursor), f"{slot['start']}  →  {slot['end']}*", font=font(38, True), fill=accent, anchor="lt")
    cursor += 56
    cursor = layout["platform"].paint(draw, (x+28, cursor), MUTED) + 20
    cursor = layout["rules"].paint(draw, (x+28, cursor), INK) + 16
    draw.line((x+28, cursor, right-28, cursor), fill="#35455F", width=1)
    cursor += 16
    draw.text((x+28, cursor), "CODE DU TOURNOI", font=font(20, True), fill=MUTED, anchor="lt")
    draw.text((x+510, cursor), "PARTICIPATION", font=font(20, True), fill=MUTED, anchor="lt")
    cursor += 24
    layout["code"].paint(draw, (x+28, cursor), accent)
    layout["capacity"].paint(draw, (x+510, cursor), INK)
    cursor += max(layout["code"].height, layout["capacity"].height) + 20
    draw.rounded_rectangle((x+28, cursor-6, right-28, cursor+layout["note"].height+10), radius=12, fill="#111D30")
    layout["note"].paint(draw, (x+46, cursor+2), MUTED)


def render_poster(program: dict[str, Any], rules: list[list[str]]) -> bytes:
    slots = program["slots"]
    layouts = [card_layout(slot, rule) for slot, rule in zip(slots, rules, strict=True)]
    date_block = block(week_label(program), WIDTH-2*MARGIN-52, 35, True)
    cards_top = 330 + date_block.height + 66
    cards_height = sum(item["height"]+26 for item in layouts) if slots else 230
    footer_top = cards_top + cards_height + 12
    height = footer_top + 385
    canvas = Image.new("RGB", (WIDTH, height))
    draw = ImageDraw.Draw(canvas)
    for y in range(height):
        amount = min(1, y/750)
        draw.line((0, y, WIDTH, y), fill=tuple(round(a+(b-a)*amount) for a, b in zip((25, 24, 56), (10, 18, 32))))
    # Trames discrètes et halo de la mascotte, derrière les informations.
    draw.arc((680, -100, 1210, 420), 50, 320, fill="#3B3859", width=2)
    draw.arc((715, -65, 1175, 385), 50, 320, fill="#393750", width=1)
    pill(draw, (MARGIN, 36), "FUN ROW  /  YU-GI-OH!", GOLD, "#34304A", 22)
    draw.text((MARGIN, 102), "HAMTARO", font=font(77, True), fill=INK, anchor="lt")
    draw.text((MARGIN, 189), "CUP", font=font(76, True), fill=GOLD, anchor="lt")
    draw.text((MARGIN+205, 213), "LE RENDEZ-VOUS\nDES DUELLISTES", font=font(24, True), fill=MUTED, spacing=7)
    mascot_path = ASSETS / "weekly-poster-mascot.webp"
    if mascot_path.exists():
        with Image.open(mascot_path) as original:
            mascot = original.convert("RGBA")
            mascot.thumbnail((310, 295), Image.Resampling.LANCZOS)
            canvas.paste(mascot, (WIDTH-MARGIN-mascot.width, 9), mascot)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((MARGIN, 315, WIDTH-MARGIN, 330+date_block.height+18), radius=18, fill=GOLD)
    date_block.paint(draw, (MARGIN+26, 331), "#171D2E")
    draw.text((MARGIN, 330+date_block.height+32), "HORAIRES DE PARIS  ·  *FIN ESTIMÉE", font=font(21, True), fill=MUTED, anchor="lt")
    cursor = cards_top
    for slot, layout in zip(slots, layouts, strict=True):
        paint_card(canvas, slot, layout, cursor)
        cursor += layout["height"] + 26
    draw = ImageDraw.Draw(canvas)
    if not slots:
        draw.rounded_rectangle((MARGIN, cursor, WIDTH-MARGIN, cursor+205), radius=24, fill="#17243A")
        draw.text((MARGIN+28, cursor+38), "PAUSE CETTE SEMAINE", font=font(40, True), fill=INK, anchor="lt")
        draw.text((MARGIN+28, cursor+110), "Le prochain programme sera annoncé sur Fun Row.", font=font(27), fill=MUTED, anchor="lt")
    draw.rounded_rectangle((MARGIN, footer_top, WIDTH-MARGIN, footer_top+247), radius=24, fill="#F4E8CC")
    draw.text((MARGIN+28, footer_top+25), "PRÊT À JOUER ?", font=font(34, True), fill="#18243A", anchor="lt")
    steps = (("1", "Sur Fun Row, utilise /inscription"),
             ("2", "Renseigne le code du tournoi et ton deck."))
    for i, (number, label) in enumerate(steps):
        y = footer_top+83+i*54
        draw.ellipse((MARGIN+28, y-2, MARGIN+64, y+34), fill="#17243A")
        draw.text((MARGIN+40, y+4), number, font=font(22, True), fill=GOLD, anchor="lt")
        draw.text((MARGIN+82, y+2), label, font=font(28, True), fill="#17243A", anchor="lt")
    draw.text((MARGIN+28, footer_top+202), "Ouverture à J−7 · clôture 30 min avant · sans check-in", font=font(24), fill="#34425A", anchor="lt")
    draw.text((MARGIN, footer_top+270), "Minimum non atteint : tournoi annulé. Consulte le règlement.", font=font(23), fill=MUTED, anchor="lt")
    draw.text((MARGIN, footer_top+310), "hamtaro-production.up.railway.app", font=font(27, True), fill=GOLD, anchor="lt")
    if program.get("preview"):
        draw.text((MARGIN, footer_top+355), "APERÇU DE DÉMONSTRATION · DONNÉES D’EXEMPLE", font=font(19, True), fill=MUTED, anchor="lt")
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
