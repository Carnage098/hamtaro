from __future__ import annotations

import asyncio
import io
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps

from graphics.theme import HamtaroBracketTheme


@dataclass(slots=True)
class PlayerVisual:
    """Données graphiques représentant un joueur dans une case."""

    discord_id: str | None
    name: str
    score: str
    avatar_url: str | None
    winner: bool = False
    seed: int | None = None
    deck: str | None = None


class BracketImageService:
    """
    Génère les images PNG HD utilisées par :

    - /bracket ;
    - /final_bracket ;
    - /preview_bracket.

    Cette version produit un bracket symétrique, plus resserré,
    avec des seeds, des scores séparés, une finale renforcée et
    des effets de fond plus discrets.
    """

    SUPPORTED_PLAYER_CAPACITIES = {2, 4, 8, 16, 32, 64, 128}

    def __init__(
        self,
        db: Any,
        theme: HamtaroBracketTheme | None = None,
    ):
        self.db = db
        self.theme = theme or HamtaroBracketTheme()

        self._avatar_cache: dict[str, Image.Image] = {}
        self._asset_cache: dict[str, Image.Image] = {}

    # ==========================================================
    # RACCOURCIS VERS LE THÈME
    # ==========================================================

    @property
    def BG(self) -> tuple[int, int, int]:
        return self.theme.background

    @property
    def PANEL(self) -> tuple[int, int, int]:
        return self.theme.panel

    @property
    def PANEL_ALT(self) -> tuple[int, int, int]:
        return self.theme.panel_alternate

    @property
    def TEXT(self) -> tuple[int, int, int]:
        return self.theme.text

    @property
    def MUTED(self) -> tuple[int, int, int]:
        return self.theme.muted_text

    @property
    def RED(self) -> tuple[int, int, int]:
        return self.theme.left_side

    @property
    def BLUE(self) -> tuple[int, int, int]:
        return self.theme.right_side

    @property
    def GOLD(self) -> tuple[int, int, int]:
        return self.theme.champion_gold

    @property
    def GREEN(self) -> tuple[int, int, int]:
        return self.theme.winner_green

    @property
    def LINE(self) -> tuple[int, int, int]:
        return self.theme.connector_line

    # ==========================================================
    # OUTILS GÉNÉRAUX
    # ==========================================================

    @staticmethod
    def _status_value(status: Any) -> str:
        """Retourne la valeur textuelle d'un statut."""

        return getattr(status, "value", str(status)).lower()

    @staticmethod
    def _safe_text(value: str | None, maximum: int = 20) -> str:
        """Raccourcit un texte trop long."""

        cleaned = (value or "À déterminer").strip()

        if len(cleaned) <= maximum:
            return cleaned

        return cleaned[: maximum - 1] + "…"

    @staticmethod
    def _blend_color(
        first: tuple[int, int, int],
        second: tuple[int, int, int],
        ratio: float,
    ) -> tuple[int, int, int]:
        """Mélange deux couleurs RGB."""

        ratio = max(0.0, min(1.0, ratio))

        return tuple(
            int(a + (b - a) * ratio)
            for a, b in zip(first, second)
        )

    @staticmethod
    def _player_key(
        discord_id: Any,
        name: str | None,
    ) -> str:
        """Construit la clé utilisée pour l'avatar et le seed."""

        if discord_id:
            return str(discord_id)

        return f"name:{name or '?'}"

    @staticmethod
    def _score_for(match: Any, slot: int) -> str:
        """Retourne le score du joueur occupant le slot demandé."""

        player_id = getattr(match, f"player{slot}_id", None)

        if getattr(match, "is_bye", False):
            return "BYE" if player_id else "—"

        status = BracketImageService._status_value(
            getattr(match, "status", "")
        )

        if status in {
            "completed",
            "finished",
            "validated",
            "approved",
            "reported",
        }:
            score = getattr(match, f"player{slot}_score", None)

            if score is not None:
                return str(score)

        return "—"

    @staticmethod
    def _round_title(round_number: int) -> str:
        """Retourne le nom graphique du round."""

        names = {
            1: "FINALE",
            2: "DEMI-FINALES",
            3: "QUARTS",
            4: "HUITIÈMES",
            5: "SEIZIÈMES",
            6: "32ES DE FINALE",
            7: "64ES DE FINALE",
        }

        return names.get(round_number, f"ROUND {round_number}")

    @staticmethod
    def _font(
        size: int,
        bold: bool = False,
    ) -> ImageFont.ImageFont:
        """Charge une police disponible sur Railway/Linux."""

        if bold:
            candidates = (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/"
                "LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            )
        else:
            candidates = (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation2/"
                "LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            )

        for path in candidates:
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue

        return ImageFont.load_default()

    @staticmethod
    def _text_width(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
    ) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    @staticmethod
    def _text_height(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
    ) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[3] - bbox[1]

    # ==========================================================
    # RESSOURCES GRAPHIQUES
    # ==========================================================

    def _load_asset(self, path: str | Path) -> Image.Image | None:
        """Charge une ressource graphique facultative."""

        asset_path = Path(path)

        try:
            cache_key = str(asset_path.resolve())
        except OSError:
            cache_key = str(asset_path)

        cached = self._asset_cache.get(cache_key)

        if cached is not None:
            return cached.copy()

        if not asset_path.exists() or not asset_path.is_file():
            return None

        try:
            with Image.open(asset_path) as source:
                image = source.convert("RGBA")
        except (OSError, ValueError):
            return None

        self._asset_cache[cache_key] = image.copy()
        return image

    @staticmethod
    def _contain_image(
        image: Image.Image,
        maximum_width: int,
        maximum_height: int,
    ) -> Image.Image:
        """Redimensionne une image sans modifier ses proportions."""

        result = image.copy()
        result.thumbnail(
            (maximum_width, maximum_height),
            Image.Resampling.LANCZOS,
        )
        return result

    def _draw_optional_background(self, canvas: Image.Image) -> None:
        """Dessine le fond personnalisé lorsqu'il est disponible."""

        background = self._load_asset(self.theme.background_path)

        if background is None:
            return

        resized = ImageOps.fit(
            background,
            canvas.size,
            method=Image.Resampling.LANCZOS,
        )
        canvas.alpha_composite(resized)

        overlay = Image.new(
            "RGBA",
            canvas.size,
            (*self.BG, 205),
        )
        canvas.alpha_composite(overlay)

    def _draw_optional_logo(
        self,
        canvas: Image.Image,
        x: int,
        y: int,
        maximum_width: int = 140,
        maximum_height: int = 110,
    ) -> bool:
        """Dessine le logo Hamtaro s'il est disponible."""

        logo = self._load_asset(self.theme.logo_path)

        if logo is None:
            return False

        logo = self._contain_image(
            logo,
            maximum_width,
            maximum_height,
        )
        canvas.alpha_composite(logo, (x, y))
        return True

    def _draw_optional_trophy(
        self,
        canvas: Image.Image,
        center_x: int,
        y: int,
        maximum_width: int = 80,
        maximum_height: int = 80,
    ) -> bool:
        """Dessine le trophée facultatif dans la carte du champion."""

        trophy = self._load_asset(self.theme.trophy_path)

        if trophy is None:
            return False

        trophy = self._contain_image(
            trophy,
            maximum_width,
            maximum_height,
        )

        canvas.alpha_composite(
            trophy,
            (center_x - trophy.width // 2, y),
        )
        return True

    # ==========================================================
    # AVATARS
    # ==========================================================

    async def _download_avatar_with_session(
        self,
        session: aiohttp.ClientSession,
        url: str | None,
        key: str,
    ) -> Image.Image:
        """Télécharge un avatar avec une session HTTP existante."""

        cached = self._avatar_cache.get(key)

        if cached is not None:
            return cached.copy()

        image: Image.Image | None = None

        if url:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        raw = await response.read()

                        with Image.open(io.BytesIO(raw)) as source:
                            image = source.convert("RGBA")
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                OSError,
                ValueError,
            ):
                image = None

        if image is None:
            image = self._create_fallback_avatar(key)

        image = ImageOps.fit(
            image,
            (128, 128),
            method=Image.Resampling.LANCZOS,
        )

        self._avatar_cache[key] = image.copy()
        return image

    def _create_fallback_avatar(self, key: str) -> Image.Image:
        """Crée un avatar de remplacement avec une initiale."""

        image = Image.new(
            "RGBA",
            (128, 128),
            (42, 49, 69, 255),
        )
        draw = ImageDraw.Draw(image)

        draw.ellipse(
            (8, 8, 120, 120),
            fill=(74, 84, 113, 255),
        )

        cleaned_key = key[5:] if key.startswith("name:") else key
        initial = (cleaned_key[:1] or "?").upper()
        font = self._font(56, bold=True)

        bbox = draw.textbbox((0, 0), initial, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        draw.text(
            (
                (128 - text_width) // 2,
                (128 - text_height) // 2 - 7,
            ),
            initial,
            font=font,
            fill=(255, 255, 255, 255),
        )

        return image

    @staticmethod
    def _circle_avatar(
        image: Image.Image,
        size: int,
    ) -> Image.Image:
        """Transforme un avatar carré en avatar rond."""

        avatar = ImageOps.fit(
            image,
            (size, size),
            method=Image.Resampling.LANCZOS,
        )

        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)

        result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        result.paste(avatar, (0, 0), mask)
        return result

    async def _resolve_avatar_map(
        self,
        matches: list[Any],
        supplied: dict[str, str] | None,
    ) -> dict[str, Image.Image]:
        """Télécharge les avatars nécessaires au bracket."""

        supplied = supplied or {}
        identities: dict[str, str | None] = {}

        for match in matches:
            for slot in (1, 2):
                discord_id = getattr(match, f"player{slot}_id", None)
                name = getattr(match, f"player{slot}_name", None) or "?"
                key = self._player_key(discord_id, name)

                if discord_id:
                    identities[key] = supplied.get(key)
                elif name and name != "À déterminer":
                    identities[key] = None

        if not identities:
            return {}

        timeout = aiohttp.ClientTimeout(total=12, connect=5)
        connector = aiohttp.TCPConnector(limit=12)

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
        ) as session:
            tasks = [
                self._download_avatar_with_session(session, url, key)
                for key, url in identities.items()
            ]
            images = await asyncio.gather(*tasks)

        return dict(zip(identities.keys(), images))

    # ==========================================================
    # SEEDS ET DONNÉES VISUELLES
    # ==========================================================

    def _build_seed_map(
        self,
        bracket: dict[int, list[Any]],
    ) -> dict[str, int]:
        """
        Attribue un seed à chaque joueur à partir du premier tour.

        Si la base contient déjà player1_seed/player2_seed, cette
        valeur reste prioritaire au moment du dessin.
        """

        first_round_number = max(bracket)
        first_round = bracket.get(first_round_number, [])
        seeds: dict[str, int] = {}
        next_seed = 1

        for match in first_round:
            for slot in (1, 2):
                discord_id = getattr(match, f"player{slot}_id", None)
                name = getattr(match, f"player{slot}_name", None)

                if not discord_id and not name:
                    continue

                key = self._player_key(discord_id, name)

                if key not in seeds:
                    seeds[key] = next_seed
                    next_seed += 1

        return seeds

    def _match_players(
        self,
        match: Any,
        avatar_urls: dict[str, str] | None,
        seed_map: dict[str, int],
    ) -> tuple[PlayerVisual, PlayerVisual]:
        """Transforme les joueurs d'un match en données graphiques."""

        winner_id = getattr(match, "winner_id", None)
        avatar_urls = avatar_urls or {}
        players: list[PlayerVisual] = []

        for slot in (1, 2):
            player_id = getattr(match, f"player{slot}_id", None)
            player_name = (
                getattr(match, f"player{slot}_name", None)
                or "À déterminer"
            )
            key = self._player_key(player_id, player_name)

            explicit_seed = getattr(
                match,
                f"player{slot}_seed",
                None,
            )

            player = PlayerVisual(
                discord_id=str(player_id) if player_id else None,
                name=player_name,
                score=self._score_for(match, slot),
                avatar_url=(
                    avatar_urls.get(str(player_id))
                    if player_id
                    else None
                ),
                winner=bool(
                    winner_id
                    and player_id
                    and str(winner_id) == str(player_id)
                ),
                seed=explicit_seed or seed_map.get(key),
                deck=getattr(match, f"player{slot}_deck", None),
            )
            players.append(player)

        return players[0], players[1]

    # ==========================================================
    # DESSIN DES CASES DE MATCH
    # ==========================================================

    def _draw_match_box(
        self,
        canvas: Image.Image,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        width: int,
        height: int,
        match: Any,
        side_color: tuple[int, int, int],
        avatars: dict[str, Image.Image],
        avatar_urls: dict[str, str] | None,
        seed_map: dict[str, int],
        compact: bool,
        final_box: bool = False,
    ) -> None:
        """Dessine une case contenant les deux participants."""

        radius = 14 if compact else 18
        border_width = 4 if final_box else 3
        panel_fill = (
            self._blend_color(self.PANEL, self.GOLD, 0.08)
            if final_box
            else self.PANEL
        )

        draw.rounded_rectangle(
            (x, y, x + width, y + height),
            radius=radius,
            fill=panel_fill,
            outline=side_color,
            width=border_width,
        )

        row_height = height // 2
        draw.line(
            (x + 10, y + row_height, x + width - 10, y + row_height),
            fill=self.LINE,
            width=2,
        )

        players = self._match_players(
            match,
            avatar_urls,
            seed_map,
        )

        if final_box:
            avatar_size = min(48, row_height - 12)
            name_size = max(
                getattr(self.theme, "normal_name_font_size", 22) + 2,
                24,
            )
            score_size = max(
                getattr(self.theme, "normal_score_font_size", 22) + 2,
                24,
            )
        elif compact:
            avatar_size = min(32, row_height - 10)
            name_size = getattr(
                self.theme,
                "compact_name_font_size",
                18,
            )
            score_size = getattr(
                self.theme,
                "compact_score_font_size",
                18,
            )
        else:
            avatar_size = min(42, row_height - 10)
            name_size = max(
                getattr(self.theme, "normal_name_font_size", 22),
                21,
            )
            score_size = max(
                getattr(self.theme, "normal_score_font_size", 22),
                21,
            )

        name_font = self._font(name_size, bold=True)
        score_font = self._font(score_size, bold=True)
        seed_font = self._font(max(14, name_size - 5), bold=True)

        seed_badge_size = 28 if compact else 32
        score_box_width = 48 if compact else 56

        if final_box:
            seed_badge_size = 34
            score_box_width = 62

        for index, player in enumerate(players):
            row_y = y + index * row_height
            row_bottom = row_y + row_height

            if player.winner:
                winner_fill = self._blend_color(
                    panel_fill,
                    self.GREEN,
                    0.14,
                )
                draw.rectangle(
                    (
                        x + border_width,
                        row_y + 2,
                        x + width - border_width,
                        row_bottom - 2,
                    ),
                    fill=winner_fill,
                )

                draw.rounded_rectangle(
                    (
                        x + 3,
                        row_y + 6,
                        x + 10,
                        row_bottom - 6,
                    ),
                    radius=3,
                    fill=self.GREEN,
                )

            seed_x = x + 14
            seed_y = row_y + (row_height - seed_badge_size) // 2
            seed_fill = self._blend_color(self.PANEL_ALT, side_color, 0.18)

            draw.rounded_rectangle(
                (
                    seed_x,
                    seed_y,
                    seed_x + seed_badge_size,
                    seed_y + seed_badge_size,
                ),
                radius=8,
                fill=seed_fill,
                outline=self._blend_color(self.LINE, side_color, 0.35),
                width=1,
            )

            seed_text = str(player.seed) if player.seed is not None else "—"
            draw.text(
                (
                    seed_x + seed_badge_size // 2,
                    seed_y + seed_badge_size // 2,
                ),
                seed_text,
                font=seed_font,
                fill=self.TEXT if player.seed is not None else self.MUTED,
                anchor="mm",
            )

            avatar_x = seed_x + seed_badge_size + 9
            avatar_y = row_y + (row_height - avatar_size) // 2
            key = self._player_key(player.discord_id, player.name)
            avatar = avatars.get(key)

            if avatar is not None:
                circle = self._circle_avatar(avatar, avatar_size)
                canvas.alpha_composite(circle, (avatar_x, avatar_y))
            else:
                draw.ellipse(
                    (
                        avatar_x,
                        avatar_y,
                        avatar_x + avatar_size,
                        avatar_y + avatar_size,
                    ),
                    fill=self.PANEL_ALT,
                    outline=self.LINE,
                    width=1,
                )

            score_x = x + width - score_box_width - 10
            score_y = row_y + 8
            score_height = row_height - 16
            score_fill = (
                self._blend_color(self.PANEL_ALT, self.GOLD, 0.18)
                if player.winner
                else self.PANEL_ALT
            )

            draw.rounded_rectangle(
                (
                    score_x,
                    score_y,
                    score_x + score_box_width,
                    score_y + score_height,
                ),
                radius=9,
                fill=score_fill,
                outline=(
                    self.GOLD
                    if player.winner
                    else self.LINE
                ),
                width=2 if player.winner else 1,
            )

            draw.text(
                (
                    score_x + score_box_width // 2,
                    score_y + score_height // 2,
                ),
                player.score,
                font=score_font,
                fill=self.GOLD if player.winner else self.TEXT,
                anchor="mm",
            )

            name_x = avatar_x + avatar_size + 10
            name_right = score_x - 10
            available_width = max(50, name_right - name_x)

            maximum_chars = max(
                8,
                int(available_width / max(8, name_size * 0.56)),
            )
            name = self._safe_text(player.name, maximum_chars)
            name_color = self.TEXT if player.winner else self.MUTED

            text_height = self._text_height(draw, name, name_font)
            name_y = row_y + (row_height - text_height) // 2 - 2

            draw.text(
                (name_x, name_y),
                name,
                font=name_font,
                fill=name_color,
            )

    # ==========================================================
    # PLACEMENT DES MATCHS
    # ==========================================================

    def _layout(
        self,
        bracket: dict[int, list[Any]],
        width: int,
        header_height: int,
        footer_height: int,
        box_width: int,
        box_height: int,
        margin_x: int,
        player_capacity: int,
        final_width: int,
        final_height: int,
        final_mode: bool,
    ) -> tuple[
        dict[int, list[tuple[int, int, str]]],
        int,
    ]:
        """Calcule les positions du bracket symétrique."""

        total_rounds = max(bracket)
        first_round_matches = bracket.get(total_rounds, [])
        first_round_count = len(first_round_matches)

        if first_round_count < 1:
            raise ValueError("Le premier tour du bracket est vide.")

        left_first_count = math.ceil(first_round_count / 2)
        right_first_count = first_round_count - left_first_count
        matches_per_side = max(left_first_count, right_first_count, 1)

        preferred_vertical_gap = getattr(
            self.theme,
            "vertical_gap",
            lambda _: box_height + 30,
        )(player_capacity)

        vertical_gap = max(
            box_height + 22,
            preferred_vertical_gap,
        )

        first_round_span = (
            (matches_per_side - 1) * vertical_gap
            + box_height
        )

        top_padding = 78
        bottom_padding = 92
        champion_reserve = 300 if final_mode else 0

        content_height = max(
            700 if not final_mode else 960,
            top_padding
            + first_round_span
            + bottom_padding
            + champion_reserve,
        )

        content_top = header_height + top_padding
        center_y = content_top + first_round_span // 2

        if final_mode:
            center_y -= min(100, champion_reserve // 3)

        positions: dict[int, list[tuple[int, int, str]]] = {}
        side_column_count = max(0, total_rounds - 1)
        final_x = width // 2 - final_width // 2
        final_y = center_y - final_height // 2
        center_gap = 38

        if side_column_count > 0:
            left_inner_limit = final_x - center_gap
            right_inner_start = final_x + final_width + center_gap

            if side_column_count == 1:
                left_columns = [left_inner_limit - box_width]
                right_columns = [right_inner_start]
            else:
                left_available = left_inner_limit - margin_x
                right_available = width - margin_x - right_inner_start

                left_step = (
                    left_available - box_width
                ) / (side_column_count - 1)
                right_step = (
                    right_available - box_width
                ) / (side_column_count - 1)

                minimum_step = box_width + 42
                left_step = max(minimum_step, left_step)
                right_step = max(minimum_step, right_step)

                left_columns = [
                    int(margin_x + depth * left_step)
                    for depth in range(side_column_count)
                ]
                right_columns = [
                    int(width - margin_x - box_width - depth * right_step)
                    for depth in range(side_column_count)
                ]

                left_columns[-1] = left_inner_limit - box_width
                right_columns[-1] = right_inner_start

            for round_number in range(total_rounds, 1, -1):
                matches = bracket.get(round_number, [])
                left_count = math.ceil(len(matches) / 2)
                right_count = len(matches) - left_count
                depth = total_rounds - round_number

                left_x = left_columns[min(depth, len(left_columns) - 1)]
                right_x = right_columns[min(depth, len(right_columns) - 1)]

                if round_number == total_rounds:
                    left_y_positions = [
                        content_top + index * vertical_gap
                        for index in range(left_count)
                    ]
                    right_y_positions = [
                        content_top + index * vertical_gap
                        for index in range(right_count)
                    ]
                else:
                    child_positions = positions.get(round_number + 1, [])
                    left_children = [
                        position
                        for position in child_positions
                        if position[2] == "left"
                    ]
                    right_children = [
                        position
                        for position in child_positions
                        if position[2] == "right"
                    ]

                    left_y_positions = self._parent_y_positions(
                        left_children,
                        left_count,
                        box_height,
                    )
                    right_y_positions = self._parent_y_positions(
                        right_children,
                        right_count,
                        box_height,
                    )

                positions[round_number] = [
                    *[(left_x, y, "left") for y in left_y_positions],
                    *[(right_x, y, "right") for y in right_y_positions],
                ]

        positions[1] = [(final_x, final_y, "center")]

        final_image_height = (
            header_height
            + content_height
            + footer_height
        )

        return positions, final_image_height

    @staticmethod
    def _parent_y_positions(
        children: list[tuple[int, int, str]],
        parent_count: int,
        box_height: int,
    ) -> list[int]:
        """Place chaque match parent entre ses deux matchs enfants."""

        if parent_count <= 0 or not children:
            return []

        positions: list[int] = []

        for parent_index in range(parent_count):
            first_child_index = min(
                parent_index * 2,
                len(children) - 1,
            )
            second_child_index = min(
                first_child_index + 1,
                len(children) - 1,
            )

            first_center = children[first_child_index][1] + box_height // 2
            second_center = children[second_child_index][1] + box_height // 2
            parent_center = (first_center + second_center) // 2
            positions.append(parent_center - box_height // 2)

        return positions

    # ==========================================================
    # LIGNES ENTRE LES MATCHS
    # ==========================================================

    def _draw_connectors(
        self,
        draw: ImageDraw.ImageDraw,
        bracket: dict[int, list[Any]],
        positions: dict[int, list[tuple[int, int, str]]],
        box_width: int,
        box_height: int,
        final_width: int,
        final_height: int,
    ) -> None:
        """Dessine les lignes reliant les matchs."""

        total_rounds = max(bracket)

        for round_number in range(total_rounds, 1, -1):
            current_positions = positions.get(round_number, [])
            next_positions = positions.get(round_number - 1, [])

            if not next_positions:
                continue

            side_indexes = {"left": 0, "right": 0}

            for x, y, side in current_positions:
                target_is_final = round_number - 1 == 1

                if target_is_final:
                    target = next_positions[0]
                else:
                    target_candidates = [
                        position
                        for position in next_positions
                        if position[2] == side
                    ]

                    if not target_candidates:
                        continue

                    local_index = side_indexes[side]
                    target_index = min(
                        local_index // 2,
                        len(target_candidates) - 1,
                    )
                    target = target_candidates[target_index]
                    side_indexes[side] += 1

                target_x, target_y, _ = target
                start_y = y + box_height // 2
                end_y = target_y + (
                    final_height // 2
                    if target_is_final
                    else box_height // 2
                )

                if side == "left":
                    start_x = x + box_width
                    end_x = target_x
                else:
                    start_x = x
                    end_x = target_x + (
                        final_width
                        if target_is_final
                        else box_width
                    )

                middle_x = (start_x + end_x) // 2
                side_color = self.RED if side == "left" else self.BLUE
                line_color = self._blend_color(
                    self.LINE,
                    side_color,
                    0.55,
                )

                draw.line(
                    (start_x, start_y, middle_x, start_y),
                    fill=line_color,
                    width=4,
                )
                draw.line(
                    (middle_x, start_y, middle_x, end_y),
                    fill=line_color,
                    width=4,
                )
                draw.line(
                    (middle_x, end_y, end_x, end_y),
                    fill=line_color,
                    width=4,
                )

                draw.ellipse(
                    (
                        start_x - 3,
                        start_y - 3,
                        start_x + 3,
                        start_y + 3,
                    ),
                    fill=line_color,
                )

    # ==========================================================
    # FOND ET ZONES COLORÉES
    # ==========================================================

    def _draw_background_effects(
        self,
        image: Image.Image,
        header_height: int,
        footer_height: int,
    ) -> None:
        """Ajoute deux zones latérales discrètes, rouge et bleue."""

        width, height = image.size
        content_bottom = height - footer_height
        effect_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        effect_draw = ImageDraw.Draw(effect_layer)

        left_inner = int(width * 0.39)
        right_inner = int(width * 0.61)

        effect_draw.polygon(
            (
                (0, header_height),
                (int(width * 0.31), header_height),
                (left_inner, content_bottom),
                (0, content_bottom),
            ),
            fill=(*self.RED, 23),
        )

        effect_draw.polygon(
            (
                (int(width * 0.69), header_height),
                (width, header_height),
                (width, content_bottom),
                (right_inner, content_bottom),
            ),
            fill=(*self.BLUE, 23),
        )

        effect_draw.polygon(
            (
                (0, header_height),
                (int(width * 0.23), header_height),
                (int(width * 0.31), content_bottom),
                (0, content_bottom),
            ),
            fill=(*self.RED, 12),
        )

        effect_draw.polygon(
            (
                (int(width * 0.77), header_height),
                (width, header_height),
                (width, content_bottom),
                (int(width * 0.69), content_bottom),
            ),
            fill=(*self.BLUE, 12),
        )

        image.alpha_composite(effect_layer)

    def _draw_final_focus(
        self,
        image: Image.Image,
        final_position: tuple[int, int, str],
        final_width: int,
        final_height: int,
    ) -> None:
        """Ajoute un léger halo doré autour de la finale."""

        x, y, _ = final_position
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)

        for expansion, alpha in ((34, 12), (22, 18), (12, 24)):
            layer_draw.rounded_rectangle(
                (
                    x - expansion,
                    y - expansion,
                    x + final_width + expansion,
                    y + final_height + expansion,
                ),
                radius=28,
                fill=(*self.GOLD, alpha),
            )

        image.alpha_composite(layer)

    # ==========================================================
    # CARTE DU CHAMPION
    # ==========================================================

    def _draw_champion_card(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        tournament: Any,
        final_match: Any,
        final_position: tuple[int, int, str],
        final_height: int,
        avatars: dict[str, Image.Image],
        seed_map: dict[str, int],
    ) -> None:
        """Dessine la carte du champion sous la finale."""

        champion_name = getattr(final_match, "winner_name", None)
        champion_id = getattr(final_match, "winner_id", None)

        if not champion_name:
            return

        card_width = getattr(self.theme, "champion_card_width", 650)
        card_height = getattr(self.theme, "champion_card_height", 350)
        card_width = min(card_width, 620)
        card_height = min(card_height, 330)

        card_x = image.width // 2 - card_width // 2
        final_y = final_position[1]
        card_y = final_y + final_height + 48

        draw.rounded_rectangle(
            (
                card_x,
                card_y,
                card_x + card_width,
                card_y + card_height,
            ),
            radius=28,
            fill=self._blend_color(self.PANEL, self.GOLD, 0.10),
            outline=self.GOLD,
            width=5,
        )

        title_font = self._font(
            max(
                getattr(self.theme, "champion_title_font_size", 31),
                31,
            ),
            bold=True,
        )
        name_font = self._font(
            max(
                getattr(self.theme, "champion_name_font_size", 34),
                34,
            ),
            bold=True,
        )
        info_font = self._font(22)
        score_font = self._font(23, bold=True)

        trophy_drawn = self._draw_optional_trophy(
            image,
            center_x=image.width // 2,
            y=card_y + 54,
            maximum_width=72,
            maximum_height=72,
        )

        draw.text(
            (image.width // 2, card_y + 28),
            "CHAMPION",
            font=title_font,
            fill=self.GOLD,
            anchor="ma",
        )

        key = self._player_key(champion_id, champion_name)
        avatar = avatars.get(key)
        avatar_size = min(
            getattr(self.theme, "champion_avatar_size", 112),
            108,
        )
        avatar_x = card_x + 46
        avatar_y = card_y + 154

        if avatar is not None:
            circle = self._circle_avatar(avatar, avatar_size)
            image.alpha_composite(circle, (avatar_x, avatar_y))

        name_x = avatar_x + avatar_size + 34
        name_y = card_y + 157

        draw.text(
            (name_x, name_y),
            self._safe_text(champion_name, 28),
            font=name_font,
            fill=self.TEXT,
        )

        champion_seed = seed_map.get(key)
        tournament_id = getattr(tournament, "id", "?")
        tournament_format = getattr(
            tournament,
            "format",
            "Format inconnu",
        )

        info_parts = [f"Tournoi #{tournament_id}", str(tournament_format)]

        if champion_seed is not None:
            info_parts.append(f"Seed #{champion_seed}")

        draw.text(
            (name_x, card_y + 218),
            " • ".join(info_parts),
            font=info_font,
            fill=self.MUTED,
        )

        player1_score = getattr(final_match, "player1_score", 0)
        player2_score = getattr(final_match, "player2_score", 0)
        final_score = getattr(final_match, "score", None)

        if not final_score:
            final_score = f"{player1_score}-{player2_score}"

        draw.text(
            (name_x, card_y + 263),
            f"Score de la finale : {final_score}",
            font=score_font,
            fill=self.GOLD,
        )

        if not trophy_drawn:
            draw.ellipse(
                (
                    image.width // 2 - 8,
                    card_y + 83,
                    image.width // 2 + 8,
                    card_y + 99,
                ),
                fill=self.GOLD,
            )

    # ==========================================================
    # EN-TÊTE, TITRES DES ROUNDS ET PIED DE PAGE
    # ==========================================================

    def _draw_header(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        tournament: Any,
        player_capacity: int,
        header_height: int,
        final_mode: bool,
    ) -> None:
        width = image.width
        tournament_name = getattr(tournament, "name", "Tournoi Hamtaro")
        tournament_id = getattr(tournament, "id", "?")
        tournament_format = getattr(
            tournament,
            "format",
            "Format inconnu",
        )
        status = self._status_value(getattr(tournament, "status", "active"))

        title_font = self._font(
            max(getattr(self.theme, "title_font_size", 52), 56),
            bold=True,
        )
        subtitle_font = self._font(
            max(getattr(self.theme, "subtitle_font_size", 26), 28),
            bold=True,
        )
        information_font = self._font(
            max(getattr(self.theme, "information_font_size", 21), 22)
        )

        draw.rectangle(
            (0, 0, width, header_height),
            fill=(*self.theme.header_background, 255),
        )

        draw.line(
            (0, header_height - 2, width, header_height - 2),
            fill=self._blend_color(self.LINE, self.TEXT, 0.20),
            width=2,
        )

        logo_drawn = self._draw_optional_logo(
            image,
            x=54,
            y=28,
            maximum_width=110,
            maximum_height=100,
        )

        brand_x = 182 if logo_drawn else 64
        draw.text(
            (brand_x, 30),
            "HAMTARO",
            font=title_font,
            fill=self.TEXT,
        )

        draw.text(
            (brand_x, 104),
            "BRACKET FINAL" if final_mode else "BRACKET EN DIRECT",
            font=subtitle_font,
            fill=self.GOLD if final_mode else self.BLUE,
        )

        draw.text(
            (width // 2, 34),
            self._safe_text(tournament_name, 48),
            font=title_font,
            fill=self.TEXT,
            anchor="ma",
        )

        tournament_info = (
            f"Tournoi #{tournament_id}  •  {tournament_format}"
            f"  •  Élimination directe  •  {player_capacity} joueurs"
        )

        draw.text(
            (width // 2, 111),
            tournament_info,
            font=information_font,
            fill=self.MUTED,
            anchor="ma",
        )

        status_text = status.upper()
        status_color = self.GREEN if final_mode else self.BLUE
        status_font = subtitle_font
        text_width = self._text_width(draw, status_text, status_font)
        pill_width = max(150, text_width + 46)
        pill_height = 54
        pill_x = width - 64 - pill_width
        pill_y = 44

        draw.rounded_rectangle(
            (
                pill_x,
                pill_y,
                pill_x + pill_width,
                pill_y + pill_height,
            ),
            radius=18,
            fill=self._blend_color(self.PANEL, status_color, 0.18),
            outline=status_color,
            width=2,
        )

        draw.text(
            (
                pill_x + pill_width // 2,
                pill_y + pill_height // 2,
            ),
            status_text,
            font=status_font,
            fill=status_color,
            anchor="mm",
        )

    def _draw_round_headers(
        self,
        draw: ImageDraw.ImageDraw,
        positions: dict[int, list[tuple[int, int, str]]],
        header_height: int,
        box_width: int,
        final_width: int,
    ) -> None:
        phase_font = self._font(
            max(getattr(self.theme, "round_font_size", 23), 25),
            bold=True,
        )
        title_y = header_height + 22
        underline_y = header_height + 57

        for round_number, round_positions in positions.items():
            if not round_positions:
                continue

            if round_number == 1:
                x, _, _ = round_positions[0]
                center_x = x + final_width // 2

                draw.text(
                    (center_x, title_y),
                    self._round_title(round_number),
                    font=phase_font,
                    fill=self.GOLD,
                    anchor="ma",
                )
                draw.line(
                    (center_x - 52, underline_y, center_x + 52, underline_y),
                    fill=self.GOLD,
                    width=4,
                )
                continue

            displayed_sides: set[str] = set()

            for x, _, side in round_positions:
                if side in displayed_sides:
                    continue

                displayed_sides.add(side)
                center_x = x + box_width // 2
                color = self.RED if side == "left" else self.BLUE

                draw.text(
                    (center_x, title_y),
                    self._round_title(round_number),
                    font=phase_font,
                    fill=color,
                    anchor="ma",
                )
                draw.line(
                    (center_x - 48, underline_y, center_x + 48, underline_y),
                    fill=color,
                    width=3,
                )

    def _draw_footer(
        self,
        draw: ImageDraw.ImageDraw,
        image_width: int,
        image_height: int,
        footer_height: int,
        tournament_id: Any,
        final_mode: bool,
    ) -> None:
        footer_y = image_height - footer_height

        draw.rectangle(
            (0, footer_y, image_width, image_height),
            fill=(*self.theme.footer_background, 255),
        )
        draw.line(
            (0, footer_y, image_width, footer_y),
            fill=self._blend_color(self.LINE, self.TEXT, 0.18),
            width=2,
        )

        left_title_font = self._font(29, bold=True)
        left_info_font = self._font(22)
        right_font = self._font(25, bold=True)

        draw.text(
            (64, footer_y + 30),
            "Organisé avec Hamtaro Tournament Bot",
            font=left_title_font,
            fill=self.TEXT,
        )
        draw.text(
            (64, footer_y + 78),
            f"ID tournoi #{tournament_id}",
            font=left_info_font,
            fill=self.MUTED,
        )

        footer_right = (
            "Merci à tous les participants !"
            if final_mode
            else "Résultats actualisés après validation du staff"
        )

        draw.text(
            (image_width - 64, footer_y + 57),
            footer_right,
            font=right_font,
            fill=self.GOLD if final_mode else self.BLUE,
            anchor="ra",
        )

    # ==========================================================
    # GÉNÉRATION DE L'IMAGE
    # ==========================================================

    async def render(
        self,
        tournament: Any,
        bracket: dict[int, list[Any]],
        *,
        avatar_urls: dict[str, str] | None = None,
        final_mode: bool = False,
    ) -> io.BytesIO:
        """Génère l'image PNG complète du bracket."""

        if not bracket:
            raise ValueError(
                "Aucun bracket n'a été généré pour ce tournoi."
            )

        total_rounds = max(bracket)
        first_round_matches = len(bracket.get(total_rounds, []))

        if first_round_matches < 1:
            raise ValueError("Le premier tour du tournoi est vide.")

        player_capacity = first_round_matches * 2

        if player_capacity not in self.SUPPORTED_PLAYER_CAPACITIES:
            raise ValueError(
                "Le moteur graphique prend uniquement en charge "
                "les brackets de 2, 4, 8, 16, 32, 64 ou 128 joueurs."
            )

        width = self.theme.image_width(player_capacity)
        header_height = max(
            176,
            min(getattr(self.theme, "header_height", 200), 200),
        )
        footer_height = max(
            118,
            min(getattr(self.theme, "footer_height", 130), 130),
        )
        box_width = self.theme.box_width(player_capacity)
        box_height = self.theme.box_height(player_capacity)
        margin_x = getattr(self.theme, "horizontal_margin", 64)

        final_width = min(
            max(box_width + 100, 360),
            460,
        )
        final_height = max(box_height + 18, 124)

        positions, height = self._layout(
            bracket=bracket,
            width=width,
            header_height=header_height,
            footer_height=footer_height,
            box_width=box_width,
            box_height=box_height,
            margin_x=margin_x,
            player_capacity=player_capacity,
            final_width=final_width,
            final_height=final_height,
            final_mode=final_mode,
        )

        image = Image.new(
            "RGBA",
            (width, height),
            (*self.BG, 255),
        )

        self._draw_optional_background(image)
        self._draw_background_effects(
            image,
            header_height,
            footer_height,
        )

        draw = ImageDraw.Draw(image)

        self._draw_header(
            image=image,
            draw=draw,
            tournament=tournament,
            player_capacity=player_capacity,
            header_height=header_height,
            final_mode=final_mode,
        )

        self._draw_round_headers(
            draw=draw,
            positions=positions,
            header_height=header_height,
            box_width=box_width,
            final_width=final_width,
        )

        if positions.get(1):
            self._draw_final_focus(
                image,
                positions[1][0],
                final_width,
                final_height,
            )
            draw = ImageDraw.Draw(image)

        self._draw_connectors(
            draw=draw,
            bracket=bracket,
            positions=positions,
            box_width=box_width,
            box_height=box_height,
            final_width=final_width,
            final_height=final_height,
        )

        all_matches = [
            match
            for matches in bracket.values()
            for match in matches
        ]
        avatars = await self._resolve_avatar_map(
            all_matches,
            avatar_urls,
        )
        seed_map = self._build_seed_map(bracket)

        for round_number, matches in bracket.items():
            round_positions = positions.get(round_number, [])

            for match, position in zip(matches, round_positions):
                x, y, side = position

                if side == "center":
                    side_color = self.GOLD
                    current_width = final_width
                    current_height = final_height
                    final_box = True
                elif side == "left":
                    side_color = self.RED
                    current_width = box_width
                    current_height = box_height
                    final_box = False
                else:
                    side_color = self.BLUE
                    current_width = box_width
                    current_height = box_height
                    final_box = False

                self._draw_match_box(
                    canvas=image,
                    draw=draw,
                    x=x,
                    y=y,
                    width=current_width,
                    height=current_height,
                    match=match,
                    side_color=side_color,
                    avatars=avatars,
                    avatar_urls=avatar_urls,
                    seed_map=seed_map,
                    compact=player_capacity >= 64,
                    final_box=final_box,
                )

        final_matches = bracket.get(1, [])
        final_match = final_matches[0] if final_matches else None

        if (
            final_mode
            and final_match is not None
            and positions.get(1)
        ):
            self._draw_champion_card(
                image=image,
                draw=draw,
                tournament=tournament,
                final_match=final_match,
                final_position=positions[1][0],
                final_height=final_height,
                avatars=avatars,
                seed_map=seed_map,
            )

        tournament_id = getattr(tournament, "id", "?")
        self._draw_footer(
            draw=draw,
            image_width=width,
            image_height=height,
            footer_height=footer_height,
            tournament_id=tournament_id,
            final_mode=final_mode,
        )

        output = io.BytesIO()
        image.convert("RGB").save(
            output,
            format="PNG",
            optimize=True,
            compress_level=7,
        )
        output.seek(0)
        return output
