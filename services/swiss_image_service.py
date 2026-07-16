from __future__ import annotations

import asyncio
import io
import math
from dataclasses import dataclass
from typing import Any

import aiohttp
from PIL import Image, ImageDraw

from graphics.swiss_theme import HamtaroSwissTheme
from services.bracket_image_service import BracketImageService


@dataclass(slots=True)
class SwissStandingVisual:
    rank: int
    discord_id: str
    username: str
    points: int
    wins: int
    losses: int
    double_losses: int
    byes: int
    played: int


@dataclass(slots=True)
class SwissMatchVisual:
    table_number: int
    player1_id: str
    player1_name: str
    player2_id: str | None
    player2_name: str | None
    status: str
    winner_id: str | None
    winner_name: str | None
    is_bye: bool
    is_double_loss: bool


class SwissImageService(BracketImageService):
    """
    Renderer graphique des rondes suisses Hamtaro.

    Modes disponibles :
    - ronde en cours ;
    - classement actuel ;
    - classement final.

    Aucun deck et aucun Top Cut ne sont affichés.
    """

    def __init__(self, db: Any, theme: HamtaroSwissTheme | None = None) -> None:
        super().__init__(db, theme or HamtaroSwissTheme())
        self.theme: HamtaroSwissTheme

    # ==========================================================
    # DONNÉES
    # ==========================================================

    async def _settings(self, tournament_id: int):
        settings = await self.db.get_swiss_settings(tournament_id)
        if settings is None:
            raise ValueError("Les rondes suisses ne sont pas lancées pour ce tournoi.")
        return settings

    async def _standings(self, tournament_id: int) -> list[SwissStandingVisual]:
        rows = await self.db.get_swiss_standings(tournament_id)
        result: list[SwissStandingVisual] = []

        for rank, row in enumerate(rows, start=1):
            result.append(
                SwissStandingVisual(
                    rank=rank,
                    discord_id=str(row["discord_id"]),
                    username=str(row["username"]),
                    points=int(row["points"] or 0),
                    wins=int(row["wins"] or 0),
                    losses=int(row["losses"] or 0),
                    double_losses=int(row["double_losses"] or 0),
                    byes=int(row["byes"] or 0),
                    played=int(row["played"] or 0),
                )
            )

        if not result:
            raise ValueError("Aucun joueur actif n'est disponible dans le classement suisse.")

        return result

    async def _matches(
        self,
        tournament_id: int,
        round_number: int,
    ) -> list[SwissMatchVisual]:
        rows = await self.db.list_swiss_matches(
            tournament_id=tournament_id,
            round_number=round_number,
        )

        result: list[SwissMatchVisual] = []
        for row in rows:
            is_draw = int(row["is_draw"] or 0) == 1
            raw_result = str(row["result"] or "none").lower()
            result.append(
                SwissMatchVisual(
                    table_number=int(row["table_number"]),
                    player1_id=str(row["player1_id"]),
                    player1_name=str(row["player1_name"]),
                    player2_id=(str(row["player2_id"]) if row["player2_id"] is not None else None),
                    player2_name=(str(row["player2_name"]) if row["player2_name"] is not None else None),
                    status=str(row["status"] or "pending").lower(),
                    winner_id=(str(row["winner_id"]) if row["winner_id"] is not None else None),
                    winner_name=(str(row["winner_name"]) if row["winner_name"] is not None else None),
                    is_bye=int(row["is_bye"] or 0) == 1,
                    is_double_loss=(
                        int(row["is_double_loss"] or 0) == 1
                        or is_draw
                        or raw_result in {"double_loss", "draw"}
                    ),
                )
            )

        return result

    async def _avatar_urls(self, tournament: Any) -> dict[str, str]:
        rows = await self.db.fetchall(
            """
            SELECT
                registrations.discord_id,
                players.avatar_url
            FROM registrations
            LEFT JOIN players
                ON players.discord_id = registrations.discord_id
                AND players.guild_id = ?
            WHERE registrations.tournament_id = ?
            """,
            (
                str(getattr(tournament, "guild_id", "")),
                int(getattr(tournament, "id")),
            ),
        )

        urls: dict[str, str] = {}
        for row in rows:
            if row["avatar_url"]:
                urls[str(row["discord_id"])] = str(row["avatar_url"])
        return urls

    async def _resolve_swiss_avatars(
        self,
        standings: list[SwissStandingVisual],
        matches: list[SwissMatchVisual],
        urls: dict[str, str],
    ) -> dict[str, Image.Image]:
        identities: dict[str, str] = {
            standing.discord_id: standing.username
            for standing in standings
        }

        for match in matches:
            identities.setdefault(match.player1_id, match.player1_name)
            if match.player2_id is not None:
                identities.setdefault(match.player2_id, match.player2_name or "Joueur inconnu")

        timeout = aiohttp.ClientTimeout(total=12, connect=5)
        connector = aiohttp.TCPConnector(limit=12)

        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            tasks = [
                self._download_avatar_with_session(
                    session,
                    urls.get(discord_id),
                    f"swiss:{discord_id}",
                    username,
                )
                for discord_id, username in identities.items()
            ]
            images = await asyncio.gather(*tasks)

        return {
            discord_id: image
            for discord_id, image in zip(identities.keys(), images)
        }

    # ==========================================================
    # CANVAS COMMUN
    # ==========================================================

    def _new_canvas(self, tournament: Any) -> tuple[Image.Image, ImageDraw.ImageDraw, int, int]:
        width = int(self.theme.swiss_width)
        height = int(self.theme.swiss_height)
        image = Image.new("RGBA", (width, height), (*self.BG, 255))

        self._draw_optional_background(image)
        header_height = self._effective_header_height(canvas_height=height)
        footer_height = self._effective_footer_height(canvas_height=height)
        self._draw_background_effects(
            image,
            header_height,
            footer_height,
            getattr(tournament, "id", "?"),
        )
        return image, ImageDraw.Draw(image), header_height, footer_height

    def _draw_swiss_header(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        tournament: Any,
        player_count: int,
        current_round: int,
        total_rounds: int,
        *,
        final_mode: bool,
    ) -> None:
        # Réutilise exactement la structure V18, puis remplace uniquement
        # la ligne "ELIMINATION DIRECTE" par les informations suisses.
        super()._draw_header(image, draw, tournament, max(2, player_count))

        width = image.width
        header_height = self._effective_header_height(canvas_height=image.height)
        display_scale = self._display_scale(width)
        mascot_width = max(
            62,
            round(int(getattr(self.theme, "header_mascot_width", 92)) * 0.80 * display_scale),
        )
        mascot_x = int(getattr(self.theme, "header_mascot_x", 22))
        title_x = max(
            mascot_x + mascot_width + 18,
            int(getattr(self.theme, "header_title_with_mascot_x", 132)),
        )
        logo_width = max(
            int(238 * display_scale),
            int(getattr(self.theme, "header_logo_maximum_width", 220)),
        )
        logo_left = width // 2 - logo_width // 2
        available = max(260, logo_left - title_x - 28)
        subtitle_size = max(
            int(22 * display_scale),
            int(getattr(self.theme, "subtitle_font_size", 20)),
            22,
        )
        subtitle_font = self._font(subtitle_size, bold=True)
        metadata_y = min(
            header_height - subtitle_size - 14,
            max(
                86,
                int(getattr(self.theme, "header_metadata_y", 104)) - 4,
            ),
        )

        draw.rectangle(
            (
                title_x - 2,
                metadata_y - 4,
                logo_left - 12,
                metadata_y + subtitle_size + 8,
            ),
            fill=(*getattr(self.theme, "header_background", self.BG), 255),
        )

        tournament_format = str(getattr(tournament, "format", "FORMAT INCONNU")).upper()
        state_label = "CLASSEMENT FINAL" if final_mode else f"RONDE {current_round}/{total_rounds}"
        metadata = (
            f"FORMAT : {tournament_format}   |   RONDES SUISSES   |   "
            f"{state_label}   |   {player_count} JOUEURS"
        )
        metadata = self._fit_text(draw, metadata, subtitle_font, available)
        draw.text((title_x, metadata_y), metadata, font=subtitle_font, fill=self.MUTED)

    def _draw_dynamic_footer(self, image: Image.Image, text: str) -> None:
        previous = self.theme.footer_center_text
        try:
            self.theme.footer_center_text = text
            self._draw_footer(image, True)
        finally:
            self.theme.footer_center_text = previous

    def _export(self, image: Image.Image) -> io.BytesIO:
        output = io.BytesIO()
        image.convert("RGB").save(
            output,
            format="PNG",
            optimize=True,
            compress_level=7,
        )
        output.seek(0)
        return output

    # ==========================================================
    # HELPERS DE DESSIN
    # ==========================================================

    def _rank_color(self, rank: int):
        if rank == 1:
            return self.theme.swiss_rank_gold
        if rank == 2:
            return self.theme.swiss_rank_silver
        if rank == 3:
            return self.theme.swiss_rank_bronze
        return self.LINE

    def _draw_panel(
        self,
        draw: ImageDraw.ImageDraw,
        bounds: tuple[int, int, int, int],
        title: str,
        subtitle: str,
        accent,
    ) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = bounds
        radius = int(self.theme.swiss_panel_radius)
        draw.rounded_rectangle(
            bounds,
            radius=radius,
            fill=(*self.PANEL, 244),
            outline=accent,
            width=int(self.theme.swiss_panel_border_width),
        )
        header_h = int(self.theme.swiss_panel_header_height)
        draw.rounded_rectangle(
            (x1, y1, x2, y1 + header_h),
            radius=radius,
            fill=(*self._blend_color(self.PANEL_ALT, accent, 0.14), 255),
        )
        draw.rectangle(
            (x1, y1 + header_h - radius, x2, y1 + header_h),
            fill=(*self._blend_color(self.PANEL_ALT, accent, 0.14), 255),
        )
        draw.rectangle((x1, y1, x1 + 6, y1 + header_h), fill=accent)

        title_font = self._font(self.theme.swiss_section_title_font_size, bold=True, italic=True)
        subtitle_font = self._font(self.theme.swiss_section_subtitle_font_size, bold=True)
        draw.text((x1 + 20, y1 + 11), title, font=title_font, fill=self.TEXT, anchor="la")
        if subtitle:
            draw.text((x2 - 18, y1 + header_h // 2), subtitle, font=subtitle_font, fill=self.MUTED, anchor="rm")
        return x1 + 12, y1 + header_h + 12, x2 - 12, y2 - 12

    def _avatar(
        self,
        image: Image.Image,
        avatars: dict[str, Image.Image],
        discord_id: str,
        username: str,
        x: int,
        y: int,
        size: int,
        border,
    ) -> None:
        avatar = avatars.get(discord_id) or self._create_fallback_avatar(username)
        self._paste_avatar(image, avatar, x, y, size, border, 2)

    def _draw_standing_row(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        standing: SwissStandingVisual,
        avatars: dict[str, Image.Image],
        bounds: tuple[int, int, int, int],
        *,
        compact: bool = False,
    ) -> None:
        x1, y1, x2, y2 = bounds
        accent = self._rank_color(standing.rank)
        draw.rounded_rectangle(
            bounds,
            radius=6,
            fill=(*self._blend_color(self.PANEL_ALT, accent, 0.07), 245),
            outline=accent,
            width=2 if standing.rank <= 3 else 1,
        )

        rank_font = self._font(20 if compact else 23, bold=True, italic=True)
        name_font = self._font(17 if compact else self.theme.swiss_standing_name_font_size, bold=True)
        stats_font = self._font(12 if compact else self.theme.swiss_standing_stats_font_size, bold=True)
        points_font = self._font(18 if compact else self.theme.swiss_standing_points_font_size, bold=True, italic=True)

        center_y = (y1 + y2) // 2
        draw.text((x1 + 18, center_y), f"#{standing.rank}", font=rank_font, fill=accent, anchor="lm")

        avatar_size = min(y2 - y1 - 12, 30 if compact else self.theme.swiss_standing_avatar_size)
        avatar_x = x1 + (58 if compact else 66)
        avatar_y = center_y - avatar_size // 2
        self._avatar(
            image,
            avatars,
            standing.discord_id,
            standing.username,
            avatar_x,
            avatar_y,
            avatar_size,
            accent,
        )

        name_x = avatar_x + avatar_size + 12
        points_space = 92 if compact else 110
        max_name_width = max(80, x2 - name_x - points_space)
        display_name = self._fit_text(draw, standing.username, name_font, max_name_width)
        draw.text((name_x, center_y - (8 if compact else 10)), display_name, font=name_font, fill=self.TEXT, anchor="lm")
        stats = (
            f"{standing.wins}V  {standing.losses}D  "
            f"{standing.double_losses}DL  {standing.byes}BYE"
        )
        draw.text((name_x, center_y + (11 if compact else 14)), stats, font=stats_font, fill=self.MUTED, anchor="lm")
        draw.text((x2 - 14, center_y - 1), f"{standing.points} PTS", font=points_font, fill=accent, anchor="rm")

    def _match_state(self, match: SwissMatchVisual) -> tuple[str, Any]:
        if match.is_bye:
            return "BYE VALIDE", self.theme.swiss_bye
        if match.status != "completed":
            return "EN ATTENTE", self.theme.swiss_pending
        if match.is_double_loss:
            return "DOUBLE LOSS", self.theme.swiss_double_loss
        return f"VICTOIRE : {match.winner_name or 'INCONNUE'}", self.theme.swiss_completed

    def _draw_match_card(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        match: SwissMatchVisual,
        avatars: dict[str, Image.Image],
        points: dict[str, int],
        bounds: tuple[int, int, int, int],
    ) -> None:
        x1, y1, x2, y2 = bounds
        state_text, state_color = self._match_state(match)
        draw.rounded_rectangle(
            bounds,
            radius=7,
            fill=(*self.PANEL_ALT, 248),
            outline=state_color,
            width=2,
        )

        table_font = self._font(self.theme.swiss_match_table_font_size, bold=True, italic=True)
        status_font = self._font(self.theme.swiss_match_status_font_size, bold=True)
        name_font = self._font(self.theme.swiss_match_name_font_size, bold=True)
        points_font = self._font(self.theme.swiss_match_points_font_size, bold=True)
        vs_font = self._font(17, bold=True, italic=True)

        draw.text((x1 + 12, y1 + 10), f"TABLE {match.table_number}", font=table_font, fill=self.TEXT, anchor="la")
        state_display = self._fit_text(draw, state_text, status_font, max(120, x2 - x1 - 145))
        draw.text((x2 - 12, y1 + 12), state_display, font=status_font, fill=state_color, anchor="ra")

        body_top = y1 + 34
        center_y = (body_top + y2) // 2 + 2
        avatar_size = min(self.theme.swiss_match_avatar_size, y2 - body_top - 14)

        p1_avatar_x = x1 + 12
        p1_avatar_y = center_y - avatar_size // 2
        self._avatar(image, avatars, match.player1_id, match.player1_name, p1_avatar_x, p1_avatar_y, avatar_size, self.RED)

        p2_name = match.player2_name or "BYE"
        p2_id = match.player2_id or "bye"
        p2_avatar_x = x2 - 12 - avatar_size
        p2_avatar_y = center_y - avatar_size // 2
        if not match.is_bye:
            self._avatar(image, avatars, p2_id, p2_name, p2_avatar_x, p2_avatar_y, avatar_size, self.BLUE)

        left_text_x = p1_avatar_x + avatar_size + 10
        right_text_x = p2_avatar_x - 10
        center_x = (x1 + x2) // 2
        side_width = max(70, center_x - left_text_x - 30)

        p1_name = self._fit_text(draw, match.player1_name, name_font, side_width)
        draw.text((left_text_x, center_y - 8), p1_name, font=name_font, fill=self.TEXT, anchor="lm")
        draw.text(
            (left_text_x, center_y + 13),
            f"{points.get(match.player1_id, 0)} PTS",
            font=points_font,
            fill=self.MUTED,
            anchor="lm",
        )

        draw.text((center_x, center_y), "VS" if not match.is_bye else "BYE", font=vs_font, fill=state_color, anchor="mm")

        if not match.is_bye:
            p2_display = self._fit_text(draw, p2_name, name_font, side_width)
            draw.text((right_text_x, center_y - 8), p2_display, font=name_font, fill=self.TEXT, anchor="rm")
            draw.text(
                (right_text_x, center_y + 13),
                f"{points.get(p2_id, 0)} PTS",
                font=points_font,
                fill=self.MUTED,
                anchor="rm",
            )

    def _draw_progress_panel(
        self,
        draw: ImageDraw.ImageDraw,
        bounds: tuple[int, int, int, int],
        current_round: int,
        total_rounds: int,
        matches: list[SwissMatchVisual],
        player_count: int,
    ) -> None:
        x1, y1, x2, y2 = self._draw_panel(
            draw,
            bounds,
            "PROGRESSION",
            f"RONDE {current_round}/{total_rounds}",
            self.BLUE,
        )

        row_h = int(self.theme.swiss_progress_row_height)
        font = self._font(self.theme.swiss_progress_font_size, bold=True)
        small = self._font(15, bold=True)
        cursor_y = y1

        max_round_rows = min(total_rounds, 10)
        for round_number in range(1, max_round_rows + 1):
            if round_number < current_round:
                label, color = "TERMINEE", self.GREEN
            elif round_number == current_round:
                label, color = "EN COURS", self.BLUE
            else:
                label, color = "A VENIR", self.MUTED

            draw.rounded_rectangle(
                (x1, cursor_y, x2, cursor_y + row_h - 6),
                radius=6,
                fill=(*self.PANEL_ALT, 240),
                outline=color,
                width=1,
            )
            draw.text((x1 + 14, cursor_y + (row_h - 6) // 2), f"RONDE {round_number}", font=font, fill=self.TEXT, anchor="lm")
            draw.text((x2 - 14, cursor_y + (row_h - 6) // 2), label, font=small, fill=color, anchor="rm")
            cursor_y += row_h

        completed = sum(1 for match in matches if match.status == "completed")
        pending = sum(1 for match in matches if match.status != "completed")
        double_losses = sum(1 for match in matches if match.is_double_loss)
        byes = sum(1 for match in matches if match.is_bye)

        stat_top = max(cursor_y + 12, y2 - 270)
        stat_gap = 10
        stat_w = (x2 - x1 - stat_gap) // 2
        stat_h = 112
        stats = [
            (str(player_count), "JOUEURS", self.TEXT),
            (str(total_rounds), "RONDES", self.BLUE),
            (str(completed), "MATCHS TERMINES", self.GREEN),
            (str(pending), "EN ATTENTE", self.theme.swiss_pending),
            (str(double_losses), "DOUBLE LOSSES", self.theme.swiss_double_loss),
            (str(byes), "BYE", self.theme.swiss_bye),
        ]

        for index, (value, label, color) in enumerate(stats):
            column = index % 2
            row = index // 2
            sx1 = x1 + column * (stat_w + stat_gap)
            sy1 = stat_top + row * (stat_h + stat_gap)
            sy2 = min(y2, sy1 + stat_h)
            if sy1 >= y2:
                break
            draw.rounded_rectangle(
                (sx1, sy1, sx1 + stat_w, sy2),
                radius=7,
                fill=(*self.PANEL_ALT, 245),
                outline=color,
                width=1,
            )
            draw.text(
                (sx1 + stat_w // 2, sy1 + 34),
                value,
                font=self._font(self.theme.swiss_stat_value_font_size, bold=True, italic=True),
                fill=color,
                anchor="mm",
            )
            draw.text(
                (sx1 + stat_w // 2, sy2 - 25),
                label,
                font=self._font(self.theme.swiss_stat_label_font_size, bold=True),
                fill=self.MUTED,
                anchor="mm",
            )

    # ==========================================================
    # RENDU RONDE EN COURS
    # ==========================================================

    async def render_round(self, tournament: Any, round_number: int | None = None) -> io.BytesIO:
        settings = await self._settings(int(tournament.id))
        current_round = int(settings["current_round"])
        total_rounds = int(settings["total_rounds"])
        selected_round = round_number or current_round

        standings = await self._standings(int(tournament.id))
        matches = await self._matches(int(tournament.id), selected_round)
        if not matches:
            raise ValueError(f"Aucun match trouvé pour la ronde {selected_round}.")

        urls = await self._avatar_urls(tournament)
        avatars = await self._resolve_swiss_avatars(standings, matches, urls)
        points = {standing.discord_id: standing.points for standing in standings}

        image, draw, header_h, footer_h = self._new_canvas(tournament)
        self._draw_swiss_header(
            image,
            draw,
            tournament,
            len(standings),
            selected_round,
            total_rounds,
            final_mode=False,
        )

        margin = int(self.theme.swiss_outer_margin)
        gap = int(self.theme.swiss_panel_gap)
        top = header_h + int(self.theme.swiss_content_top_gap)
        bottom = image.height - footer_h - int(self.theme.swiss_content_bottom_gap)

        left_w = int(self.theme.swiss_left_panel_width)
        right_w = int(self.theme.swiss_right_panel_width)
        left_bounds = (margin, top, margin + left_w, bottom)
        right_bounds = (image.width - margin - right_w, top, image.width - margin, bottom)
        center_bounds = (left_bounds[2] + gap, top, right_bounds[0] - gap, bottom)

        # Classement condensé.
        lx1, ly1, lx2, ly2 = self._draw_panel(
            draw,
            left_bounds,
            "CLASSEMENT",
            "TOP ACTUEL",
            self.RED,
        )
        row_gap = 8
        row_h = int(self.theme.swiss_standing_row_height)
        max_rows = max(1, (ly2 - ly1 + row_gap) // (row_h + row_gap))
        visible = standings[:max_rows]
        for index, standing in enumerate(visible):
            y = ly1 + index * (row_h + row_gap)
            self._draw_standing_row(
                image,
                draw,
                standing,
                avatars,
                (lx1, y, lx2, y + row_h),
            )
        hidden = len(standings) - len(visible)
        if hidden > 0:
            draw.text(
                ((lx1 + lx2) // 2, ly2 - 3),
                f"+ {hidden} AUTRES JOUEURS",
                font=self._font(16, bold=True, italic=True),
                fill=self.MUTED,
                anchor="mb",
            )

        # Appariements complets de la ronde.
        cx1, cy1, cx2, cy2 = self._draw_panel(
            draw,
            center_bounds,
            f"RONDE {selected_round}",
            f"{len(matches)} TABLES",
            self.BLUE,
        )
        count = len(matches)
        columns = 1 if count <= 8 else 2 if count <= 16 else 3 if count <= 24 else 4
        rows = math.ceil(count / columns)
        card_gap = int(self.theme.swiss_match_card_gap)
        card_w = (cx2 - cx1 - card_gap * (columns - 1)) // columns
        card_h = min(
            int(self.theme.swiss_match_card_height),
            max(82, (cy2 - cy1 - card_gap * (rows - 1)) // max(1, rows)),
        )

        for index, match in enumerate(matches):
            column = index % columns
            row = index // columns
            x = cx1 + column * (card_w + card_gap)
            y = cy1 + row * (card_h + card_gap)
            self._draw_match_card(
                image,
                draw,
                match,
                avatars,
                points,
                (x, y, x + card_w, y + card_h),
            )

        self._draw_progress_panel(
            draw,
            right_bounds,
            selected_round,
            total_rounds,
            matches,
            len(standings),
        )
        self._draw_dynamic_footer(
            image,
            f"RONDE {selected_round}/{total_rounds} EN COURS - BON DUEL A TOUS !",
        )
        return self._export(image)

    # ==========================================================
    # RENDU CLASSEMENT
    # ==========================================================

    def _draw_full_standings_grid(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        standings: list[SwissStandingVisual],
        avatars: dict[str, Image.Image],
        bounds: tuple[int, int, int, int],
        *,
        title: str,
        subtitle: str,
        accent,
    ) -> None:
        x1, y1, x2, y2 = self._draw_panel(draw, bounds, title, subtitle, accent)
        count = len(standings)
        columns = 1 if count <= 18 else 2 if count <= 40 else 3

        # Le classement final dispose de moins de hauteur à cause du podium.
        # Une quatrième colonne est donc autorisée uniquement si nécessaire.
        while columns < 4:
            test_rows = math.ceil(count / columns)
            test_gap = 5 if columns >= 3 else 8
            test_height = (y2 - y1 - test_gap * (test_rows - 1)) // max(1, test_rows)
            if test_height >= 36:
                break
            columns += 1

        rows = math.ceil(count / columns)
        gap = 5 if columns >= 3 else 8
        col_w = (x2 - x1 - gap * (columns - 1)) // columns
        row_h = min(
            int(self.theme.swiss_standing_row_height),
            max(34, (y2 - y1 - gap * (rows - 1)) // max(1, rows)),
        )
        compact = row_h < 55 or columns >= 3

        for index, standing in enumerate(standings):
            column = index // rows
            row = index % rows
            rx1 = x1 + column * (col_w + gap)
            ry1 = y1 + row * (row_h + gap)
            self._draw_standing_row(
                image,
                draw,
                standing,
                avatars,
                (rx1, ry1, rx1 + col_w, ry1 + row_h),
                compact=compact,
            )

    async def render_standings(self, tournament: Any) -> io.BytesIO:
        settings = await self._settings(int(tournament.id))
        current_round = int(settings["current_round"])
        total_rounds = int(settings["total_rounds"])
        standings = await self._standings(int(tournament.id))
        urls = await self._avatar_urls(tournament)
        avatars = await self._resolve_swiss_avatars(standings, [], urls)

        image, draw, header_h, footer_h = self._new_canvas(tournament)
        self._draw_swiss_header(
            image,
            draw,
            tournament,
            len(standings),
            current_round,
            total_rounds,
            final_mode=False,
        )

        margin = int(self.theme.swiss_outer_margin)
        bounds = (
            margin,
            header_h + int(self.theme.swiss_content_top_gap),
            image.width - margin,
            image.height - footer_h - int(self.theme.swiss_content_bottom_gap),
        )
        self._draw_full_standings_grid(
            image,
            draw,
            standings,
            avatars,
            bounds,
            title="CLASSEMENT GENERAL",
            subtitle=f"APRES LA RONDE {current_round}/{total_rounds}",
            accent=self.GOLD,
        )
        self._draw_dynamic_footer(image, self.theme.swiss_footer_standings_text)
        return self._export(image)

    # ==========================================================
    # RENDU FINAL
    # ==========================================================

    def _draw_podium_card(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        standing: SwissStandingVisual,
        avatars: dict[str, Image.Image],
        bounds: tuple[int, int, int, int],
    ) -> None:
        x1, y1, x2, y2 = bounds
        color = self._rank_color(standing.rank)
        draw.rounded_rectangle(
            bounds,
            radius=12,
            fill=(*self._blend_color(self.PANEL, color, 0.10), 250),
            outline=color,
            width=3,
        )
        draw.rectangle((x1, y1, x2, y1 + 7), fill=color)

        rank_labels = {1: "1ER", 2: "2E", 3: "3E"}
        draw.text(
            ((x1 + x2) // 2, y1 + 28),
            rank_labels.get(standing.rank, f"#{standing.rank}"),
            font=self._font(30, bold=True, italic=True),
            fill=color,
            anchor="mm",
        )

        avatar_size = min(self.theme.swiss_podium_avatar_size, y2 - y1 - 110)
        avatar_x = x1 + 28
        avatar_y = (y1 + y2) // 2 - avatar_size // 2 + 12
        self._avatar(
            image,
            avatars,
            standing.discord_id,
            standing.username,
            avatar_x,
            avatar_y,
            avatar_size,
            color,
        )

        text_x = avatar_x + avatar_size + 24
        available = x2 - text_x - 24
        name_font = self._font(31 if standing.rank == 1 else 27, bold=True, italic=True)
        name = self._fit_text(draw, standing.username, name_font, available)
        draw.text((text_x, y1 + 82), name, font=name_font, fill=self.TEXT, anchor="la")
        draw.text(
            (text_x, y1 + 135),
            f"{standing.points} POINTS",
            font=self._font(28, bold=True, italic=True),
            fill=color,
            anchor="la",
        )
        draw.text(
            (text_x, y1 + 180),
            f"{standing.wins}V  {standing.losses}D  {standing.double_losses}DL  {standing.byes}BYE",
            font=self._font(17, bold=True),
            fill=self.MUTED,
            anchor="la",
        )

    async def render_final(self, tournament: Any) -> io.BytesIO:
        settings = await self._settings(int(tournament.id))
        current_round = int(settings["current_round"])
        total_rounds = int(settings["total_rounds"])
        standings = await self._standings(int(tournament.id))
        urls = await self._avatar_urls(tournament)
        avatars = await self._resolve_swiss_avatars(standings, [], urls)

        image, draw, header_h, footer_h = self._new_canvas(tournament)
        self._draw_swiss_header(
            image,
            draw,
            tournament,
            len(standings),
            current_round,
            total_rounds,
            final_mode=True,
        )

        margin = int(self.theme.swiss_outer_margin)
        top = header_h + 18
        podium_h = int(self.theme.swiss_podium_card_height)
        gap = 18
        card_w = (image.width - margin * 2 - gap * 2) // 3
        podium_order = [2, 1, 3]

        for visual_index, rank in enumerate(podium_order):
            if rank > len(standings):
                continue
            standing = standings[rank - 1]
            x1 = margin + visual_index * (card_w + gap)
            vertical_shift = 0 if rank == 1 else 30
            y1 = top + vertical_shift
            y2 = y1 + podium_h - vertical_shift
            self._draw_podium_card(
                image,
                draw,
                standing,
                avatars,
                (x1, y1, x1 + card_w, y2),
            )

        list_top = top + podium_h + 22
        list_bounds = (
            margin,
            list_top,
            image.width - margin,
            image.height - footer_h - int(self.theme.swiss_content_bottom_gap),
        )
        self._draw_full_standings_grid(
            image,
            draw,
            standings,
            avatars,
            list_bounds,
            title="CLASSEMENT FINAL",
            subtitle=f"{len(standings)} JOUEURS - {total_rounds} RONDES",
            accent=self.GOLD,
        )
        self._draw_dynamic_footer(image, self.theme.swiss_footer_final_text)
        return self._export(image)
