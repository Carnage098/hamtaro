from __future__ import annotations

import asyncio
import io
import math
import random

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import aiohttp

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageOps,
)

from graphics.theme import HamtaroBracketTheme


@dataclass(slots=True)
class PlayerVisual:
    """
    Données visuelles d'un joueur dans une case de match.
    """

    discord_id: str | None
    name: str
    score: str
    avatar_url: str | None

    winner: bool = False
    seed: int | None = None
    deck: str | None = None


class BracketImageService:
    """
    Génère les images PNG de Hamtaro.

    Le rendu est conçu pour se rapprocher de l'affiche
    Hamtaro Cup :

    - format 16:9 ;
    - arbre rouge à gauche ;
    - arbre bleu à droite ;
    - finale centrale ;
    - seed, avatar, pseudo et score séparés ;
    - carte du champion en mode final ;
    - statistiques du tournoi.
    """

    SUPPORTED_PLAYER_CAPACITIES = {
        2,
        4,
        8,
        16,
        32,
        64,
        128,
    }

    COMPLETED_STATUSES = {
        "approved",
        "completed",
        "finished",
        "reported",
        "validated",
    }

    def __init__(
        self,
        db: Any,
        theme: HamtaroBracketTheme | None = None,
    ):
        self.db = db
        self.theme = theme or HamtaroBracketTheme()

        self._avatar_cache: dict[
            str,
            Image.Image,
        ] = {}

        self._asset_cache: dict[
            str,
            Image.Image,
        ] = {}

    # ==========================================================
    # RACCOURCIS VERS LE THÈME
    # ==========================================================

    @property
    def BG(
        self,
    ) -> tuple[int, int, int]:
        return self.theme.background

    @property
    def PANEL(
        self,
    ) -> tuple[int, int, int]:
        return self.theme.panel

    @property
    def PANEL_ALT(
        self,
    ) -> tuple[int, int, int]:
        return self.theme.panel_alternate

    @property
    def TEXT(
        self,
    ) -> tuple[int, int, int]:
        return self.theme.text

    @property
    def MUTED(
        self,
    ) -> tuple[int, int, int]:
        return self.theme.muted_text

    @property
    def RED(
        self,
    ) -> tuple[int, int, int]:
        return self.theme.left_side

    @property
    def BLUE(
        self,
    ) -> tuple[int, int, int]:
        return self.theme.right_side

    @property
    def GOLD(
        self,
    ) -> tuple[int, int, int]:
        return self.theme.champion_gold

    @property
    def GREEN(
        self,
    ) -> tuple[int, int, int]:
        return self.theme.winner_green

    @property
    def LINE(
        self,
    ) -> tuple[int, int, int]:
        return self.theme.connector_line

    # ==========================================================
    # OUTILS GÉNÉRAUX
    # ==========================================================

    @staticmethod
    def _status_value(
        status: Any,
    ) -> str:
        return getattr(
            status,
            "value",
            str(status),
        ).lower()

    @staticmethod
    def _safe_text(
        value: str | None,
        maximum: int = 20,
    ) -> str:
        cleaned = (
            value
            or "À déterminer"
        ).strip()

        if len(cleaned) <= maximum:
            return cleaned

        return (
            cleaned[: maximum - 1]
            + "…"
        )

    @staticmethod
    def _font(
        size: int,
        bold: bool = False,
    ) -> ImageFont.ImageFont:
        if bold:
            candidates = (
                "/usr/share/fonts/truetype/dejavu/"
                "DejaVuSans-Bold.ttf",

                "/usr/share/fonts/truetype/liberation2/"
                "LiberationSans-Bold.ttf",

                "/usr/share/fonts/truetype/freefont/"
                "FreeSansBold.ttf",
            )

        else:
            candidates = (
                "/usr/share/fonts/truetype/dejavu/"
                "DejaVuSans.ttf",

                "/usr/share/fonts/truetype/liberation2/"
                "LiberationSans-Regular.ttf",

                "/usr/share/fonts/truetype/freefont/"
                "FreeSans.ttf",
            )

        for path in candidates:
            try:
                return ImageFont.truetype(
                    path,
                    size=size,
                )

            except OSError:
                continue

        return ImageFont.load_default()

    @staticmethod
    def _text_width(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
    ) -> int:
        bbox = draw.textbbox(
            (0, 0),
            text,
            font=font,
        )

        return (
            bbox[2]
            - bbox[0]
        )

    @staticmethod
    def _format_date(
        value: Any,
    ) -> str:
        """
        Retourne une date lisible en français.
        """

        french_months = {
            1: "JANVIER",
            2: "FÉVRIER",
            3: "MARS",
            4: "AVRIL",
            5: "MAI",
            6: "JUIN",
            7: "JUILLET",
            8: "AOÛT",
            9: "SEPTEMBRE",
            10: "OCTOBRE",
            11: "NOVEMBRE",
            12: "DÉCEMBRE",
        }

        parsed: datetime | date | None = None

        if value is None:
            parsed = datetime.now()

        elif isinstance(
            value,
            (
                datetime,
                date,
            ),
        ):
            parsed = value

        else:
            raw = str(
                value
            ).strip()

            if not raw:
                parsed = datetime.now()

            else:
                parsers = (
                    lambda text: datetime.fromisoformat(
                        text.replace(
                            "Z",
                            "+00:00",
                        )
                    ),
                    lambda text: datetime.strptime(
                        text,
                        "%Y-%m-%d",
                    ),
                    lambda text: datetime.strptime(
                        text,
                        "%d/%m/%Y",
                    ),
                )

                for parser in parsers:
                    try:
                        parsed = parser(
                            raw
                        )
                        break

                    except (
                        ValueError,
                        TypeError,
                    ):
                        continue

                if parsed is None:
                    return raw.upper()

        month = french_months.get(
            parsed.month,
            str(parsed.month),
        )

        return (
            f"{parsed.day} "
            f"{month} "
            f"{parsed.year}"
        )

    @staticmethod
    def _round_title(
        round_number: int,
    ) -> str:
        names = {
            1: "FINALE",
            2: "DEMI-FINALES",
            3: "QUARTS",
            4: "8ÈMES",
            5: "16ÈMES",
            6: "32ÈMES",
            7: "64ÈMES",
        }

        return names.get(
            round_number,
            f"ROUND {round_number}",
        )

    @classmethod
    def _score_for(
        cls,
        match: Any,
        slot: int,
    ) -> str:
        player_id = getattr(
            match,
            f"player{slot}_id",
            None,
        )

        if getattr(
            match,
            "is_bye",
            False,
        ):
            return (
                "BYE"
                if player_id
                else "—"
            )

        status = cls._status_value(
            getattr(
                match,
                "status",
                "",
            )
        )

        if status in cls.COMPLETED_STATUSES:
            score = getattr(
                match,
                f"player{slot}_score",
                None,
            )

            if score is not None:
                return str(
                    score
                )

        return "—"

    @staticmethod
    def _first_existing_attribute(
        source: Any,
        names: tuple[str, ...],
        default: Any = None,
    ) -> Any:
        for name in names:
            value = getattr(
                source,
                name,
                None,
            )

            if value is not None:
                return value

        return default

    def _seed_for(
        self,
        match: Any,
        slot: int,
    ) -> int | None:
        value = self._first_existing_attribute(
            match,
            (
                f"player{slot}_seed",
                f"seed{slot}",
                f"seed_player{slot}",
                f"player_{slot}_seed",
            ),
        )

        if value is None:
            return None

        try:
            return int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

    def _deck_for(
        self,
        match: Any,
        slot: int,
    ) -> str | None:
        value = self._first_existing_attribute(
            match,
            (
                f"player{slot}_deck",
                f"deck{slot}",
                f"deck_player{slot}",
                f"player_{slot}_deck",
            ),
        )

        return (
            str(value).strip()
            if value
            else None
        )

    # ==========================================================
    # RESSOURCES GRAPHIQUES
    # ==========================================================

    def _load_asset(
        self,
        path: str | Path,
    ) -> Image.Image | None:
        asset_path = Path(
            path
        )

        try:
            cache_key = str(
                asset_path.resolve()
            )

        except OSError:
            cache_key = str(
                asset_path
            )

        cached = self._asset_cache.get(
            cache_key
        )

        if cached is not None:
            return cached.copy()

        if (
            not asset_path.exists()
            or not asset_path.is_file()
        ):
            return None

        try:
            with Image.open(
                asset_path
            ) as source:
                image = source.convert(
                    "RGBA"
                )

        except (
            OSError,
            ValueError,
        ):
            return None

        self._asset_cache[
            cache_key
        ] = image.copy()

        return image

    @staticmethod
    def _contain_image(
        image: Image.Image,
        maximum_width: int,
        maximum_height: int,
    ) -> Image.Image:
        result = image.copy()

        result.thumbnail(
            (
                maximum_width,
                maximum_height,
            ),
            Image.Resampling.LANCZOS,
        )

        return result

    def _draw_optional_background(
        self,
        canvas: Image.Image,
    ) -> None:
        background = self._load_asset(
            self.theme.background_path
        )

        if background is None:
            return

        resized = ImageOps.fit(
            background,
            canvas.size,
            method=Image.Resampling.LANCZOS,
        )

        canvas.alpha_composite(
            resized
        )

        overlay = Image.new(
            "RGBA",
            canvas.size,
            self.BG + (188,),
        )

        canvas.alpha_composite(
            overlay
        )

    def _draw_optional_logo(
        self,
        canvas: Image.Image,
        center_x: int,
        y: int,
        maximum_width: int,
        maximum_height: int,
    ) -> bool:
        logo = self._load_asset(
            self.theme.logo_path
        )

        if logo is None:
            return False

        logo = self._contain_image(
            logo,
            maximum_width,
            maximum_height,
        )

        x = (
            center_x
            - logo.width // 2
        )

        canvas.alpha_composite(
            logo,
            (
                x,
                y,
            ),
        )

        return True

    def _draw_optional_trophy(
        self,
        canvas: Image.Image,
        center_x: int,
        y: int,
        maximum_width: int,
        maximum_height: int,
    ) -> bool:
        trophy = self._load_asset(
            self.theme.trophy_path
        )

        if trophy is None:
            return False

        trophy = self._contain_image(
            trophy,
            maximum_width,
            maximum_height,
        )

        x = (
            center_x
            - trophy.width // 2
        )

        canvas.alpha_composite(
            trophy,
            (
                x,
                y,
            ),
        )

        return True

    def _draw_optional_champion_image(
        self,
        canvas: Image.Image,
        center_x: int,
        y: int,
        maximum_width: int,
        maximum_height: int,
    ) -> bool:
        champion = self._load_asset(
            self.theme.champion_path
        )

        if champion is None:
            return False

        champion = self._contain_image(
            champion,
            maximum_width,
            maximum_height,
        )

        x = (
            center_x
            - champion.width // 2
        )

        canvas.alpha_composite(
            champion,
            (
                x,
                y,
            ),
        )

        return True

    def _draw_optional_footer_icon(
        self,
        canvas: Image.Image,
        x: int,
        center_y: int,
    ) -> bool:
        icon = self._load_asset(
            self.theme.footer_icon_path
        )

        if icon is None:
            return False

        icon = self._contain_image(
            icon,
            self.theme.footer_icon_size,
            self.theme.footer_icon_size,
        )

        y = (
            center_y
            - icon.height // 2
        )

        canvas.alpha_composite(
            icon,
            (
                x,
                y,
            ),
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
        cached = self._avatar_cache.get(
            key
        )

        if cached is not None:
            return cached.copy()

        image: Image.Image | None = None

        if url:
            try:
                async with session.get(
                    url
                ) as response:
                    if response.status == 200:
                        raw = await response.read()

                        with Image.open(
                            io.BytesIO(raw)
                        ) as source:
                            image = source.convert(
                                "RGBA"
                            )

            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                OSError,
                ValueError,
            ):
                image = None

        if image is None:
            image = self._create_fallback_avatar(
                key
            )

        image = ImageOps.fit(
            image,
            (
                128,
                128,
            ),
            method=Image.Resampling.LANCZOS,
        )

        self._avatar_cache[
            key
        ] = image.copy()

        return image

    def _create_fallback_avatar(
        self,
        key: str,
    ) -> Image.Image:
        image = Image.new(
            "RGBA",
            (
                128,
                128,
            ),
            (
                36,
                47,
                70,
                255,
            ),
        )

        draw = ImageDraw.Draw(
            image
        )

        draw.ellipse(
            (
                8,
                8,
                120,
                120,
            ),
            fill=(
                70,
                84,
                116,
                255,
            ),
        )

        cleaned_key = (
            key[5:]
            if key.startswith(
                "name:"
            )
            else key
        )

        initial = (
            cleaned_key[:1]
            or "?"
        ).upper()

        font = self._font(
            56,
            bold=True,
        )

        bbox = draw.textbbox(
            (
                0,
                0,
            ),
            initial,
            font=font,
        )

        text_width = (
            bbox[2]
            - bbox[0]
        )

        text_height = (
            bbox[3]
            - bbox[1]
        )

        draw.text(
            (
                (
                    128
                    - text_width
                )
                // 2,
                (
                    128
                    - text_height
                )
                // 2
                - 7,
            ),
            initial,
            font=font,
            fill=(
                255,
                255,
                255,
                255,
            ),
        )

        return image

    @staticmethod
    def _circle_avatar(
        image: Image.Image,
        size: int,
    ) -> Image.Image:
        avatar = ImageOps.fit(
            image,
            (
                size,
                size,
            ),
            method=Image.Resampling.LANCZOS,
        )

        mask = Image.new(
            "L",
            (
                size,
                size,
            ),
            0,
        )

        mask_draw = ImageDraw.Draw(
            mask
        )

        mask_draw.ellipse(
            (
                0,
                0,
                size - 1,
                size - 1,
            ),
            fill=255,
        )

        result = Image.new(
            "RGBA",
            (
                size,
                size,
            ),
            (
                0,
                0,
                0,
                0,
            ),
        )

        result.paste(
            avatar,
            (
                0,
                0,
            ),
            mask,
        )

        return result

    async def _resolve_avatar_map(
        self,
        matches: list[Any],
        supplied: dict[str, str] | None,
    ) -> dict[str, Image.Image]:
        supplied = (
            supplied
            or {}
        )

        identities: dict[
            str,
            str | None,
        ] = {}

        for match in matches:
            for slot in (
                1,
                2,
            ):
                discord_id = getattr(
                    match,
                    f"player{slot}_id",
                    None,
                )

                name = (
                    getattr(
                        match,
                        f"player{slot}_name",
                        None,
                    )
                    or "?"
                )

                if discord_id:
                    key = str(
                        discord_id
                    )

                    identities[
                        key
                    ] = supplied.get(
                        key
                    )

                elif name:
                    identities[
                        f"name:{name}"
                    ] = None

        if not identities:
            return {}

        timeout = aiohttp.ClientTimeout(
            total=12,
            connect=5,
        )

        connector = aiohttp.TCPConnector(
            limit=12,
        )

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
        ) as session:
            tasks = [
                self._download_avatar_with_session(
                    session,
                    url,
                    key,
                )
                for key, url in identities.items()
            ]

            images = await asyncio.gather(
                *tasks
            )

        return dict(
            zip(
                identities.keys(),
                images,
            )
        )

    # ==========================================================
    # DONNÉES VISUELLES
    # ==========================================================

    def _match_players(
        self,
        match: Any,
        avatar_urls: dict[str, str] | None,
    ) -> tuple[
        PlayerVisual,
        PlayerVisual,
    ]:
        winner_id = getattr(
            match,
            "winner_id",
            None,
        )

        avatar_urls = (
            avatar_urls
            or {}
        )

        visuals: list[
            PlayerVisual
        ] = []

        for slot in (
            1,
            2,
        ):
            player_id = getattr(
                match,
                f"player{slot}_id",
                None,
            )

            player_name = (
                getattr(
                    match,
                    f"player{slot}_name",
                    None,
                )
                or "À déterminer"
            )

            visuals.append(
                PlayerVisual(
                    discord_id=(
                        str(player_id)
                        if player_id
                        else None
                    ),
                    name=player_name,
                    score=self._score_for(
                        match,
                        slot,
                    ),
                    avatar_url=(
                        avatar_urls.get(
                            str(player_id)
                        )
                        if player_id
                        else None
                    ),
                    winner=bool(
                        winner_id
                        and player_id
                        and str(winner_id)
                        == str(player_id)
                    ),
                    seed=self._seed_for(
                        match,
                        slot,
                    ),
                    deck=self._deck_for(
                        match,
                        slot,
                    ),
                )
            )

        return (
            visuals[0],
            visuals[1],
        )

    # ==========================================================
    # FOND
    # ==========================================================

    def _draw_background_effects(
        self,
        image: Image.Image,
        player_capacity: int,
        tournament_id: Any,
    ) -> None:
        """
        Dessine un fond rouge/noir/bleu discret.
        """

        width, height = image.size

        header_height = (
            self.theme.header_height
        )

        footer_y = (
            height
            - self.theme.footer_height
        )

        center_x = (
            width // 2
        )

        center_width = (
            self.theme.center_reserved_width(
                player_capacity
            )
        )

        center_left = (
            center_x
            - center_width // 2
        )

        center_right = (
            center_x
            + center_width // 2
        )

        layer = Image.new(
            "RGBA",
            image.size,
            (
                0,
                0,
                0,
                0,
            ),
        )

        draw = ImageDraw.Draw(
            layer
        )

        left_span = max(
            center_left,
            1,
        )

        for x in range(
            0,
            center_left,
        ):
            ratio = (
                1.0
                - x / left_span
            )

            alpha = int(
                self.theme.side_background_alpha
                * ratio
            )

            draw.line(
                (
                    x,
                    header_height,
                    x,
                    footer_y,
                ),
                fill=(
                    self.theme.left_background
                    + (alpha,)
                ),
            )

        right_span = max(
            width - center_right,
            1,
        )

        for x in range(
            center_right,
            width,
        ):
            ratio = (
                x - center_right
            ) / right_span

            alpha = int(
                self.theme.side_background_alpha
                * ratio
            )

            draw.line(
                (
                    x,
                    header_height,
                    x,
                    footer_y,
                ),
                fill=(
                    self.theme.right_background
                    + (alpha,)
                ),
            )

        draw.rectangle(
            (
                center_left,
                header_height,
                center_right,
                footer_y,
            ),
            fill=(
                self.theme.background_center
                + (228,)
            ),
        )

        glow_span = max(
            90,
            width // 14,
        )

        for offset in range(
            glow_span
        ):
            ratio = (
                1.0
                - offset
                / max(
                    glow_span - 1,
                    1,
                )
            )

            alpha = int(
                self.theme.side_glow_alpha
                * ratio
                * 0.34
            )

            draw.line(
                (
                    offset,
                    header_height,
                    offset,
                    footer_y,
                ),
                fill=(
                    self.RED
                    + (alpha,)
                ),
            )

            draw.line(
                (
                    width - 1 - offset,
                    header_height,
                    width - 1 - offset,
                    footer_y,
                ),
                fill=(
                    self.BLUE
                    + (alpha,)
                ),
            )

        try:
            seed = int(
                tournament_id
            )

        except (
            TypeError,
            ValueError,
        ):
            seed = 0

        rng = random.Random(
            seed
        )

        for _ in range(
            self.theme.particle_count
        ):
            side = rng.choice(
                (
                    "left",
                    "right",
                )
            )

            if side == "left":
                x = rng.randint(
                    0,
                    max(
                        1,
                        center_left - 1,
                    ),
                )

                color = self.RED

            else:
                x = rng.randint(
                    min(
                        width - 1,
                        center_right,
                    ),
                    width - 1,
                )

                color = self.BLUE

            y = rng.randint(
                header_height + 6,
                max(
                    header_height + 7,
                    footer_y - 6,
                ),
            )

            radius = rng.choice(
                (
                    1,
                    1,
                    1,
                    2,
                )
            )

            alpha = rng.randint(
                14,
                max(
                    15,
                    self.theme.particle_alpha,
                ),
            )

            draw.ellipse(
                (
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                ),
                fill=(
                    color
                    + (alpha,)
                ),
            )

        image.alpha_composite(
            layer
        )

    # ==========================================================
    # PLACEMENT
    # ==========================================================

    @staticmethod
    def _parent_y_positions(
        children: list[
            tuple[int, int, str]
        ],
        parent_count: int,
    ) -> list[int]:
        if (
            parent_count <= 0
            or not children
        ):
            return []

        result: list[int] = []

        for parent_index in range(
            parent_count
        ):
            first_index = min(
                parent_index * 2,
                len(children) - 1,
            )

            second_index = min(
                first_index + 1,
                len(children) - 1,
            )

            first_y = children[
                first_index
            ][1]

            second_y = children[
                second_index
            ][1]

            result.append(
                (
                    first_y
                    + second_y
                )
                // 2
            )

        return result

    def _layout(
        self,
        bracket: dict[int, list[Any]],
        player_capacity: int,
        final_mode: bool,
    ) -> dict[
        int,
        list[
            tuple[int, int, str]
        ],
    ]:
        """
        Calcule les positions sur un canevas 16:9.
        """

        total_rounds = max(
            bracket
        )

        first_round_matches = bracket.get(
            total_rounds,
            [],
        )

        first_round_count = len(
            first_round_matches
        )

        if first_round_count < 1:
            raise ValueError(
                "Le premier tour du bracket est vide."
            )

        width = self.theme.image_width(
            player_capacity
        )

        height = self.theme.image_height(
            player_capacity
        )

        box_width = self.theme.box_width(
            player_capacity
        )

        box_height = self.theme.box_height(
            player_capacity
        )

        final_width = (
            self.theme.final_box_width(
                player_capacity
            )
        )

        final_height = (
            self.theme.final_box_height(
                player_capacity
            )
        )

        margin_x = (
            self.theme.horizontal_margin
        )

        content_top = (
            self.theme.header_height
            + self.theme.round_labels_height
            + self.theme.bracket_top_padding
        )

        content_bottom = (
            height
            - self.theme.footer_height
            - self.theme.bracket_bottom_padding
        )

        available_height = max(
            box_height,
            content_bottom
            - content_top,
        )

        left_first_count = math.ceil(
            first_round_count / 2
        )

        right_first_count = (
            first_round_count
            - left_first_count
        )

        matches_per_side = max(
            left_first_count,
            right_first_count,
            1,
        )

        if matches_per_side > 1:
            maximum_gap = max(
                box_height,
                (
                    available_height
                    - box_height
                )
                // (
                    matches_per_side
                    - 1
                ),
            )

            if matches_per_side >= 8:
                vertical_gap = (
                    maximum_gap
                )

            else:
                requested_gap = max(
                    box_height + 18,
                    self.theme.first_round_vertical_gap(
                        player_capacity
                    ),
                )

                vertical_gap = min(
                    maximum_gap,
                    requested_gap,
                )

        else:
            vertical_gap = 0

        if matches_per_side == 1:
            total_span = box_height

        else:
            total_span = (
                box_height
                + (
                    matches_per_side
                    - 1
                )
                * vertical_gap
            )

        first_y = (
            content_top
            + max(
                0,
                (
                    available_height
                    - total_span
                )
                // 2,
            )
        )

        rounds_before_final = max(
            1,
            total_rounds - 1,
        )

        center_width = (
            self.theme.center_reserved_width(
                player_capacity
            )
        )

        left_inner_edge = (
            width // 2
            - center_width // 2
        )

        if rounds_before_final > 1:
            left_step = (
                left_inner_edge
                - box_width
                - margin_x
            ) / (
                rounds_before_final
                - 1
            )

        else:
            left_step = 0.0

        positions: dict[
            int,
            list[
                tuple[int, int, str]
            ],
        ] = {}

        for round_number in range(
            total_rounds,
            1,
            -1,
        ):
            matches = bracket.get(
                round_number,
                [],
            )

            left_count = math.ceil(
                len(matches) / 2
            )

            right_count = (
                len(matches)
                - left_count
            )

            depth = (
                total_rounds
                - round_number
            )

            left_x = round(
                margin_x
                + depth
                * left_step
            )

            right_x = round(
                width
                - margin_x
                - box_width
                - depth
                * left_step
            )

            if round_number == total_rounds:
                left_y_positions = [
                    first_y
                    + index
                    * vertical_gap
                    for index in range(
                        left_count
                    )
                ]

                right_y_positions = [
                    first_y
                    + index
                    * vertical_gap
                    for index in range(
                        right_count
                    )
                ]

            else:
                children = positions.get(
                    round_number + 1,
                    [],
                )

                left_children = [
                    position
                    for position in children
                    if position[2]
                    == "left"
                ]

                right_children = [
                    position
                    for position in children
                    if position[2]
                    == "right"
                ]

                left_y_positions = (
                    self._parent_y_positions(
                        left_children,
                        left_count,
                    )
                )

                right_y_positions = (
                    self._parent_y_positions(
                        right_children,
                        right_count,
                    )
                )

            positions[
                round_number
            ] = [
                *[
                    (
                        left_x,
                        y,
                        "left",
                    )
                    for y in left_y_positions
                ],
                *[
                    (
                        right_x,
                        y,
                        "right",
                    )
                    for y in right_y_positions
                ],
            ]

        final_x = (
            width // 2
            - final_width // 2
        )

        if final_mode:
            final_center_y = (
                content_top
                + int(
                    available_height
                    * 0.245
                )
            )

        else:
            final_center_y = (
                content_top
                + int(
                    available_height
                    * 0.43
                )
            )

        final_y = max(
            content_top + 38,
            final_center_y
            - final_height // 2,
        )

        positions[1] = [
            (
                final_x,
                final_y,
                "center",
            )
        ]

        return positions

    # ==========================================================
    # CONNEXIONS
    # ==========================================================

    def _draw_connectors(
        self,
        image: Image.Image,
        bracket: dict[int, list[Any]],
        positions: dict[
            int,
            list[
                tuple[int, int, str]
            ],
        ],
        player_capacity: int,
    ) -> None:
        box_width = self.theme.box_width(
            player_capacity
        )

        box_height = self.theme.box_height(
            player_capacity
        )

        final_width = (
            self.theme.final_box_width(
                player_capacity
            )
        )

        final_height = (
            self.theme.final_box_height(
                player_capacity
            )
        )

        line_width = (
            self.theme.connector_width(
                player_capacity
            )
        )

        glow_width = (
            self.theme.connector_glow_width(
                player_capacity
            )
        )

        glow_layer = Image.new(
            "RGBA",
            image.size,
            (
                0,
                0,
                0,
                0,
            ),
        )

        glow_draw = ImageDraw.Draw(
            glow_layer
        )

        total_rounds = max(
            bracket
        )

        for round_number in range(
            total_rounds,
            1,
            -1,
        ):
            current_positions = positions.get(
                round_number,
                [],
            )

            next_positions = positions.get(
                round_number - 1,
                [],
            )

            if not next_positions:
                continue

            side_indexes = {
                "left": 0,
                "right": 0,
            }

            for (
                x,
                y,
                side,
            ) in current_positions:
                if round_number - 1 == 1:
                    target = (
                        next_positions[0]
                    )

                    target_width = (
                        final_width
                    )

                    target_height = (
                        final_height
                    )

                else:
                    target_candidates = [
                        position
                        for position
                        in next_positions
                        if position[2]
                        == side
                    ]

                    if not target_candidates:
                        continue

                    local_index = (
                        side_indexes[
                            side
                        ]
                    )

                    target = target_candidates[
                        min(
                            local_index // 2,
                            len(
                                target_candidates
                            )
                            - 1,
                        )
                    ]

                    side_indexes[
                        side
                    ] += 1

                    target_width = (
                        box_width
                    )

                    target_height = (
                        box_height
                    )

                (
                    target_x,
                    target_y,
                    _,
                ) = target

                start_y = (
                    y
                    + box_height // 2
                )

                end_y = (
                    target_y
                    + target_height // 2
                )

                if side == "left":
                    start_x = (
                        x
                        + box_width
                    )

                    end_x = target_x

                else:
                    start_x = x

                    end_x = (
                        target_x
                        + target_width
                    )

                middle_x = (
                    start_x
                    + end_x
                ) // 2

                color = (
                    self.RED
                    if side == "left"
                    else self.BLUE
                )

                glow_color = (
                    color
                    + (
                        self.theme.connector_glow_alpha,
                    )
                )

                segments = (
                    (
                        start_x,
                        start_y,
                        middle_x,
                        start_y,
                    ),
                    (
                        middle_x,
                        start_y,
                        middle_x,
                        end_y,
                    ),
                    (
                        middle_x,
                        end_y,
                        end_x,
                        end_y,
                    ),
                )

                for segment in segments:
                    glow_draw.line(
                        segment,
                        fill=glow_color,
                        width=glow_width,
                    )

        image.alpha_composite(
            glow_layer
        )

        draw = ImageDraw.Draw(
            image
        )

        for round_number in range(
            total_rounds,
            1,
            -1,
        ):
            current_positions = positions.get(
                round_number,
                [],
            )

            next_positions = positions.get(
                round_number - 1,
                [],
            )

            if not next_positions:
                continue

            side_indexes = {
                "left": 0,
                "right": 0,
            }

            for (
                x,
                y,
                side,
            ) in current_positions:
                if round_number - 1 == 1:
                    target = (
                        next_positions[0]
                    )

                    target_width = (
                        final_width
                    )

                    target_height = (
                        final_height
                    )

                else:
                    target_candidates = [
                        position
                        for position
                        in next_positions
                        if position[2]
                        == side
                    ]

                    if not target_candidates:
                        continue

                    local_index = (
                        side_indexes[
                            side
                        ]
                    )

                    target = target_candidates[
                        min(
                            local_index // 2,
                            len(
                                target_candidates
                            )
                            - 1,
                        )
                    ]

                    side_indexes[
                        side
                    ] += 1

                    target_width = (
                        box_width
                    )

                    target_height = (
                        box_height
                    )

                (
                    target_x,
                    target_y,
                    _,
                ) = target

                start_y = (
                    y
                    + box_height // 2
                )

                end_y = (
                    target_y
                    + target_height // 2
                )

                if side == "left":
                    start_x = (
                        x
                        + box_width
                    )

                    end_x = target_x

                else:
                    start_x = x

                    end_x = (
                        target_x
                        + target_width
                    )

                middle_x = (
                    start_x
                    + end_x
                ) // 2

                color = (
                    self.RED
                    if side == "left"
                    else self.BLUE
                )

                draw.line(
                    (
                        start_x,
                        start_y,
                        middle_x,
                        start_y,
                    ),
                    fill=color,
                    width=line_width,
                )

                draw.line(
                    (
                        middle_x,
                        start_y,
                        middle_x,
                        end_y,
                    ),
                    fill=color,
                    width=line_width,
                )

                draw.line(
                    (
                        middle_x,
                        end_y,
                        end_x,
                        end_y,
                    ),
                    fill=color,
                    width=line_width,
                )

    # ==========================================================
    # CASES DES MATCHS
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
        player_capacity: int,
        *,
        is_final: bool = False,
    ) -> None:
        if is_final:
            radius = (
                self.theme.final_box_radius
            )

            border_width = (
                self.theme.final_box_border_width
            )

        elif player_capacity >= 64:
            radius = (
                self.theme.compact_box_radius
            )

            border_width = (
                self.theme.compact_box_border_width
            )

        else:
            radius = (
                self.theme.normal_box_radius
            )

            border_width = (
                self.theme.normal_box_border_width
            )

        shadow_layer = Image.new(
            "RGBA",
            canvas.size,
            (
                0,
                0,
                0,
                0,
            ),
        )

        shadow_draw = ImageDraw.Draw(
            shadow_layer
        )

        shadow_offset = (
            self.theme.panel_shadow_offset
        )

        shadow_draw.rounded_rectangle(
            (
                x + shadow_offset,
                y + shadow_offset,
                x + width + shadow_offset,
                y + height + shadow_offset,
            ),
            radius=radius,
            fill=(
                0,
                0,
                0,
                self.theme.panel_shadow_alpha,
            ),
        )

        canvas.alpha_composite(
            shadow_layer
        )

        draw.rounded_rectangle(
            (
                x,
                y,
                x + width,
                y + height,
            ),
            radius=radius,
            fill=self.PANEL,
            outline=side_color,
            width=border_width,
        )

        row_height = (
            height // 2
        )

        draw.line(
            (
                x + 1,
                y + row_height,
                x + width - 1,
                y + row_height,
            ),
            fill=self.theme.separator,
            width=self.theme.player_row_separator_width,
        )

        players = self._match_players(
            match,
            avatar_urls,
        )

        if is_final:
            seed_width = 0

            score_width = max(
                40,
                int(
                    width * 0.18
                ),
            )

            avatar_size = min(
                42,
                row_height - 8,
            )

            name_font_size = (
                self.theme.final_name_font_size
            )

            name_font = self._font(
                name_font_size,
                bold=True,
            )

            score_font = self._font(
                self.theme.final_score_font_size,
                bold=True,
            )

            seed_font = self._font(
                1
            )

        else:
            seed_width = (
                self.theme.seed_column_width(
                    player_capacity
                )
            )

            score_width = (
                self.theme.score_column_width(
                    player_capacity
                )
            )

            avatar_size = min(
                self.theme.player_avatar_size(
                    player_capacity
                ),
                max(
                    14,
                    row_height - 6,
                ),
            )

            name_font_size = (
                self.theme.player_name_font_size(
                    player_capacity
                )
            )

            name_font = self._font(
                name_font_size,
                bold=False,
            )

            score_font = self._font(
                self.theme.player_score_font_size(
                    player_capacity
                ),
                bold=True,
            )

            seed_font = self._font(
                self.theme.player_seed_font_size(
                    player_capacity
                ),
                bold=True,
            )

        if seed_width > 0:
            draw.line(
                (
                    x + seed_width,
                    y + 1,
                    x + seed_width,
                    y + height - 1,
                ),
                fill=self.theme.separator,
                width=1,
            )

        draw.line(
            (
                x + width - score_width,
                y + 1,
                x + width - score_width,
                y + height - 1,
            ),
            fill=self.theme.separator,
            width=1,
        )

        for index, player in enumerate(
            players
        ):
            row_y = (
                y
                + index
                * row_height
            )

            if player.winner:
                draw.rectangle(
                    (
                        x + 1,
                        row_y + 1,
                        x + width - 1,
                        row_y + row_height - 1,
                    ),
                    fill=(
                        self.GREEN[0],
                        self.GREEN[1],
                        self.GREEN[2],
                        18,
                    ),
                )

                draw.rectangle(
                    (
                        x + 1,
                        row_y + 2,
                        x
                        + self.theme.winner_indicator_width,
                        row_y
                        + row_height
                        - 2,
                    ),
                    fill=self.GREEN,
                )

            if seed_width > 0:
                seed_text = (
                    str(player.seed)
                    if player.seed is not None
                    else "—"
                )

                draw.text(
                    (
                        x + seed_width // 2,
                        row_y + row_height // 2,
                    ),
                    seed_text,
                    font=seed_font,
                    fill=(
                        self.TEXT
                        if player.seed is not None
                        else self.MUTED
                    ),
                    anchor="mm",
                )

            avatar_key = (
                player.discord_id
                or f"name:{player.name}"
            )

            avatar = avatars.get(
                avatar_key
            )

            avatar_x = (
                x
                + seed_width
                + self.theme.avatar_left_padding
            )

            avatar_y = (
                row_y
                + (
                    row_height
                    - avatar_size
                )
                // 2
            )

            if avatar is not None:
                circle = self._circle_avatar(
                    avatar,
                    avatar_size,
                )

                canvas.alpha_composite(
                    circle,
                    (
                        avatar_x,
                        avatar_y,
                    ),
                )

            name_x = (
                avatar_x
                + avatar_size
                + self.theme.name_left_padding
            )

            name_right = (
                x
                + width
                - score_width
                - 4
            )

            available_name_width = max(
                10,
                name_right
                - name_x,
            )

            maximum_characters = max(
                4,
                int(
                    available_name_width
                    / max(
                        6,
                        name_font_size
                        * 0.58,
                    )
                ),
            )

            name = self._safe_text(
                player.name,
                maximum_characters,
            )

            draw.text(
                (
                    name_x,
                    row_y + row_height // 2,
                ),
                name,
                font=name_font,
                fill=(
                    self.TEXT
                    if player.winner
                    else self.MUTED
                ),
                anchor="lm",
            )

            score_left = (
                x
                + width
                - score_width
            )

            score_fill = (
                self.theme.score_background
                if player.score != "—"
                else self.PANEL_ALT
            )

            draw.rectangle(
                (
                    score_left + 1,
                    row_y + 1,
                    x + width - 1,
                    row_y + row_height - 1,
                ),
                fill=score_fill,
            )

            draw.text(
                (
                    score_left
                    + score_width // 2,
                    row_y
                    + row_height // 2,
                ),
                player.score,
                font=score_font,
                fill=(
                    self.theme.score_text
                    if player.score != "—"
                    else self.MUTED
                ),
                anchor="mm",
            )

    # ==========================================================
    # HEADER
    # ==========================================================

    def _draw_header(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        tournament: Any,
        player_capacity: int,
        final_mode: bool,
    ) -> None:
        width = image.width

        header_height = (
            self.theme.header_height
        )

        tournament_id = getattr(
            tournament,
            "id",
            "?",
        )

        tournament_name = (
            getattr(
                tournament,
                "name",
                None,
            )
            or "HAMTARO CUP"
        )

        tournament_format = (
            getattr(
                tournament,
                "format",
                None,
            )
            or "FORMAT INCONNU"
        )

        organizer = (
            getattr(
                tournament,
                "organizer_name",
                None,
            )
            or getattr(
                tournament,
                "organizer",
                None,
            )
            or "HAMTARO BOT"
        )

        date_value = (
            self._first_existing_attribute(
                tournament,
                (
                    "date",
                    "start_date",
                    "created_at",
                    "created_on",
                ),
            )
        )

        draw.rectangle(
            (
                0,
                0,
                width,
                header_height,
            ),
            fill=self.theme.header_background,
        )

        title_font = self._font(
            self.theme.title_font_size,
            bold=True,
        )

        subtitle_font = self._font(
            self.theme.subtitle_font_size,
            bold=True,
        )

        title_x = (
            self.theme.header_title_x
        )

        title_y = (
            self.theme.header_title_y
        )

        header_icon = self._load_asset(
            self.theme.footer_icon_path
        )

        if header_icon is not None:
            header_icon = self._contain_image(
                header_icon,
                58,
                58,
            )

            image.alpha_composite(
                header_icon,
                (
                    22,
                    14,
                ),
            )

            title_x = 92

        base_title = self._safe_text(
            str(
                tournament_name
            ).upper(),
            26,
        )

        draw.text(
            (
                title_x,
                title_y,
            ),
            base_title,
            font=title_font,
            fill=self.TEXT,
        )

        title_width = self._text_width(
            draw,
            base_title,
            title_font,
        )

        id_text = (
            f" #{tournament_id}"
        )

        draw.text(
            (
                title_x + title_width,
                title_y,
            ),
            id_text,
            font=title_font,
            fill=self.RED,
        )

        metadata = (
            f"FORMAT : "
            f"{str(tournament_format).upper()}"
            f"   •   ÉLIMINATION DIRECTE"
            f"   •   {player_capacity} JOUEURS"
        )

        draw.text(
            (
                title_x,
                self.theme.header_metadata_y,
            ),
            metadata,
            font=subtitle_font,
            fill=self.MUTED,
        )

        logo_drawn = self._draw_optional_logo(
            image,
            center_x=width // 2,
            y=4,
            maximum_width=(
                self.theme.header_logo_maximum_width
            ),
            maximum_height=(
                self.theme.header_logo_maximum_height
            ),
        )

        if not logo_drawn:
            logo_font = self._font(
                26,
                bold=True,
            )

            small_logo_font = self._font(
                12,
                bold=True,
            )

            draw.rounded_rectangle(
                (
                    width // 2 - 105,
                    18,
                    width // 2 + 105,
                    94,
                ),
                radius=6,
                fill=self.PANEL,
                outline=self.GOLD,
                width=2,
            )

            draw.text(
                (
                    width // 2,
                    36,
                ),
                "HAMTARO",
                font=logo_font,
                fill=self.TEXT,
                anchor="ma",
            )

            draw.text(
                (
                    width // 2,
                    73,
                ),
                "TOURNAMENT BOT",
                font=small_logo_font,
                fill=self.RED,
                anchor="ma",
            )

        gap = 6

        total_boxes_width = (
            self.theme.date_box_width
            + self.theme.tournament_id_box_width
            + self.theme.organizer_box_width
            + gap * 2
        )

        box_x = (
            width
            - self.theme.horizontal_margin
            - total_boxes_width
        )

        box_y = 20

        box_height = (
            self.theme.header_information_box_height
        )

        boxes = (
            (
                self.theme.date_box_width,
                "DATE",
                self._format_date(
                    date_value
                ),
                self.TEXT,
            ),
            (
                self.theme.tournament_id_box_width,
                "ID DU TOURNOI",
                f"#{tournament_id}",
                self.RED,
            ),
            (
                self.theme.organizer_box_width,
                "ORGANISÉ PAR",
                self._safe_text(
                    str(
                        organizer
                    ).upper(),
                    19,
                ),
                self.TEXT,
            ),
        )

        label_font = self._font(
            11,
            bold=True,
        )

        value_font = self._font(
            15,
            bold=True,
        )

        for (
            box_width,
            label,
            value,
            value_color,
        ) in boxes:
            draw.rounded_rectangle(
                (
                    box_x,
                    box_y,
                    box_x + box_width,
                    box_y + box_height,
                ),
                radius=(
                    self.theme.header_information_box_radius
                ),
                fill=self.PANEL,
                outline=self.theme.separator,
                width=1,
            )

            draw.text(
                (
                    box_x + 12,
                    box_y + 10,
                ),
                label,
                font=label_font,
                fill=self.MUTED,
            )

            draw.text(
                (
                    box_x + 12,
                    box_y + 31,
                ),
                value,
                font=value_font,
                fill=value_color,
            )

            box_x += (
                box_width
                + gap
            )

        separator_y = (
            header_height
            - self.theme.header_separator_height
        )

        draw.rectangle(
            (
                0,
                separator_y,
                width // 2,
                header_height,
            ),
            fill=self.RED,
        )

        draw.rectangle(
            (
                width // 2,
                separator_y,
                width,
                header_height,
            ),
            fill=self.BLUE,
        )

    # ==========================================================
    # TITRES DES ROUNDS
    # ==========================================================

    def _draw_round_titles(
        self,
        draw: ImageDraw.ImageDraw,
        positions: dict[
            int,
            list[
                tuple[int, int, str]
            ],
        ],
        player_capacity: int,
    ) -> None:
        box_width = self.theme.box_width(
            player_capacity
        )

        final_width = (
            self.theme.final_box_width(
                player_capacity
            )
        )

        font = self._font(
            self.theme.round_font_size_for(
                player_capacity
            ),
            bold=True,
        )

        center_y = (
            self.theme.header_height
            + self.theme.round_labels_height // 2
        )

        for (
            round_number,
            round_positions,
        ) in positions.items():
            if not round_positions:
                continue

            if round_number == 1:
                (
                    x,
                    _,
                    _,
                ) = round_positions[0]

                plate_width = min(
                    140,
                    final_width - 12,
                )

                plate_height = 28

                plate_x = (
                    x
                    + final_width // 2
                    - plate_width // 2
                )

                plate_y = (
                    center_y
                    - plate_height // 2
                )

                draw.rounded_rectangle(
                    (
                        plate_x,
                        plate_y,
                        plate_x + plate_width,
                        plate_y + plate_height,
                    ),
                    radius=4,
                    fill=self.theme.left_side_dark,
                    outline=self.RED,
                    width=1,
                )

                draw.text(
                    (
                        x + final_width // 2,
                        center_y,
                    ),
                    self._round_title(
                        round_number
                    ),
                    font=font,
                    fill=self.TEXT,
                    anchor="mm",
                )

                continue

            displayed_sides: set[str] = set()

            for (
                x,
                _,
                side,
            ) in round_positions:
                if side in displayed_sides:
                    continue

                displayed_sides.add(
                    side
                )

                color = (
                    self.RED
                    if side == "left"
                    else self.BLUE
                )

                title_x = (
                    x
                    + box_width // 2
                )

                draw.text(
                    (
                        title_x,
                        center_y - 2,
                    ),
                    self._round_title(
                        round_number
                    ),
                    font=font,
                    fill=color,
                    anchor="mm",
                )

                line_half_width = min(
                    42,
                    box_width // 3,
                )

                draw.line(
                    (
                        title_x - line_half_width,
                        center_y + 12,
                        title_x + line_half_width,
                        center_y + 12,
                    ),
                    fill=color,
                    width=2,
                )

    # ==========================================================
    # CHAMPION ET STATISTIQUES
    # ==========================================================

    def _draw_fallback_trophy(
        self,
        draw: ImageDraw.ImageDraw,
        center_x: int,
        y: int,
    ) -> None:
        cup_width = 42
        cup_height = 34

        left = (
            center_x
            - cup_width // 2
        )

        right = (
            center_x
            + cup_width // 2
        )

        draw.rounded_rectangle(
            (
                left,
                y,
                right,
                y + cup_height,
            ),
            radius=8,
            fill=self.GOLD,
            outline=(
                255,
                230,
                130,
            ),
            width=2,
        )

        draw.arc(
            (
                left - 16,
                y + 3,
                left + 10,
                y + 27,
            ),
            start=70,
            end=290,
            fill=self.GOLD,
            width=4,
        )

        draw.arc(
            (
                right - 10,
                y + 3,
                right + 16,
                y + 27,
            ),
            start=250,
            end=110,
            fill=self.GOLD,
            width=4,
        )

        draw.rectangle(
            (
                center_x - 4,
                y + cup_height,
                center_x + 4,
                y + cup_height + 16,
            ),
            fill=self.GOLD,
        )

        draw.rounded_rectangle(
            (
                center_x - 18,
                y + cup_height + 14,
                center_x + 18,
                y + cup_height + 22,
            ),
            radius=3,
            fill=self.GOLD,
        )

    def _draw_statistics_card(
        self,
        draw: ImageDraw.ImageDraw,
        tournament: Any,
        bracket: dict[int, list[Any]],
        player_capacity: int,
        center_x: int,
        y: int,
    ) -> None:
        card_width = (
            self.theme.statistics_card_width
        )

        card_height = (
            self.theme.statistics_card_height
        )

        x = (
            center_x
            - card_width // 2
        )

        draw.rounded_rectangle(
            (
                x,
                y,
                x + card_width,
                y + card_height,
            ),
            radius=self.theme.statistics_card_radius,
            fill=self.PANEL,
            outline=self.BLUE,
            width=1,
        )

        draw.text(
            (
                center_x,
                y + 12,
            ),
            "STATISTIQUES DU TOURNOI",
            font=self._font(
                self.theme.statistics_title_font_size,
                bold=True,
            ),
            fill=self.RED,
            anchor="ma",
        )

        all_matches = [
            match
            for matches in bracket.values()
            for match in matches
        ]

        matches_played = sum(
            1
            for match in all_matches
            if self._status_value(
                getattr(
                    match,
                    "status",
                    "",
                )
            )
            in self.COMPLETED_STATUSES
        )

        rounds = max(
            bracket
        )

        duration = (
            getattr(
                tournament,
                "duration",
                None,
            )
            or getattr(
                tournament,
                "total_duration",
                None,
            )
            or "—"
        )

        statistics = (
            (
                str(
                    player_capacity
                ),
                "JOUEURS",
            ),
            (
                str(
                    matches_played
                ),
                "MATCHS JOUÉS",
            ),
            (
                str(
                    duration
                ).upper(),
                "DURÉE TOTALE",
            ),
            (
                str(
                    rounds
                ),
                "ROUNDS",
            ),
        )

        column_width = (
            card_width
            // len(
                statistics
            )
        )

        value_font = self._font(
            self.theme.statistics_value_font_size,
            bold=True,
        )

        label_font = self._font(
            self.theme.statistics_label_font_size,
            bold=True,
        )

        for (
            index,
            (
                value,
                label,
            ),
        ) in enumerate(
            statistics
        ):
            column_x = (
                x
                + index
                * column_width
            )

            center = (
                column_x
                + column_width // 2
            )

            if index > 0:
                draw.line(
                    (
                        column_x,
                        y + 42,
                        column_x,
                        y + card_height - 10,
                    ),
                    fill=self.theme.separator,
                    width=1,
                )

            draw.text(
                (
                    center,
                    y + 50,
                ),
                value,
                font=value_font,
                fill=self.TEXT,
                anchor="ma",
            )

            draw.text(
                (
                    center,
                    y + 78,
                ),
                label,
                font=label_font,
                fill=self.MUTED,
                anchor="ma",
            )

    def _draw_champion_card(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        tournament: Any,
        bracket: dict[int, list[Any]],
        final_match: Any,
        final_position: tuple[int, int, str],
        player_capacity: int,
        avatars: dict[str, Image.Image],
    ) -> None:
        champion_name = getattr(
            final_match,
            "winner_name",
            None,
        )

        champion_id = getattr(
            final_match,
            "winner_id",
            None,
        )

        if not champion_name:
            return

        center_x = (
            image.width // 2
        )

        final_height = (
            self.theme.final_box_height(
                player_capacity
            )
        )

        final_y = (
            final_position[1]
        )

        card_width = (
            self.theme.champion_card_width
        )

        card_height = (
            self.theme.champion_card_height
        )

        card_x = (
            center_x
            - card_width // 2
        )

        card_y = (
            final_y
            + final_height
            + 22
        )

        draw.rounded_rectangle(
            (
                card_x,
                card_y,
                card_x + card_width,
                card_y + card_height,
            ),
            radius=self.theme.champion_card_radius,
            fill=(
                7,
                11,
                20,
            ),
            outline=self.theme.champion_gold_dark,
            width=self.theme.champion_card_border_width,
        )

        trophy_y = (
            card_y + 12
        )

        trophy_drawn = (
            self._draw_optional_trophy(
                image,
                center_x,
                trophy_y,
                self.theme.champion_trophy_width,
                self.theme.champion_trophy_height,
            )
        )

        if not trophy_drawn:
            self._draw_fallback_trophy(
                draw,
                center_x,
                trophy_y + 4,
            )

        draw.text(
            (
                center_x,
                card_y + 91,
            ),
            "CHAMPION",
            font=self._font(
                self.theme.champion_title_font_size,
                bold=True,
            ),
            fill=self.GOLD,
            anchor="ma",
        )

        champion_image_y = (
            card_y + 116
        )

        champion_drawn = (
            self._draw_optional_champion_image(
                image,
                center_x,
                champion_image_y,
                self.theme.champion_image_width,
                self.theme.champion_image_height,
            )
        )

        if not champion_drawn:
            key = (
                str(champion_id)
                if champion_id
                else f"name:{champion_name}"
            )

            avatar = avatars.get(
                key
            )

            if avatar is not None:
                circle = self._circle_avatar(
                    avatar,
                    self.theme.champion_avatar_size,
                )

                image.alpha_composite(
                    circle,
                    (
                        center_x
                        - self.theme.champion_avatar_size
                        // 2,
                        champion_image_y,
                    ),
                )

        name_bar_y = (
            card_y + 238
        )

        draw.rounded_rectangle(
            (
                card_x + 22,
                name_bar_y,
                card_x + card_width - 22,
                name_bar_y + 38,
            ),
            radius=4,
            fill=self.theme.left_side_dark,
            outline=self.RED,
            width=1,
        )

        draw.text(
            (
                center_x,
                name_bar_y + 19,
            ),
            self._safe_text(
                champion_name,
                22,
            ),
            font=self._font(
                self.theme.champion_name_font_size,
                bold=True,
            ),
            fill=self.TEXT,
            anchor="mm",
        )

        winner_slot = 1

        if (
            getattr(
                final_match,
                "player2_id",
                None,
            )
            and champion_id
            and str(
                getattr(
                    final_match,
                    "player2_id",
                    None,
                )
            )
            == str(
                champion_id
            )
        ):
            winner_slot = 2

        deck = (
            self._deck_for(
                final_match,
                winner_slot,
            )
            or "NON RENSEIGNÉ"
        )

        seed = self._seed_for(
            final_match,
            winner_slot,
        )

        seed_text = (
            f"#{seed}"
            if seed is not None
            else "—"
        )

        draw.text(
            (
                center_x,
                card_y + 288,
            ),
            (
                "DECK : "
                f"{self._safe_text(deck.upper(), 22)}"
            ),
            font=self._font(
                self.theme.champion_information_font_size,
                bold=True,
            ),
            fill=self.MUTED,
            anchor="ma",
        )

        draw.text(
            (
                center_x,
                card_y + 310,
            ),
            f"SEED : {seed_text}",
            font=self._font(
                self.theme.champion_information_font_size,
                bold=True,
            ),
            fill=self.MUTED,
            anchor="ma",
        )

        stats_y = (
            card_y
            + card_height
            + 12
        )

        footer_y = (
            image.height
            - self.theme.footer_height
        )

        if (
            stats_y
            + self.theme.statistics_card_height
            <= footer_y - 8
        ):
            self._draw_statistics_card(
                draw,
                tournament,
                bracket,
                player_capacity,
                center_x,
                stats_y,
            )

    def _draw_active_center_card(
        self,
        draw: ImageDraw.ImageDraw,
        bracket: dict[int, list[Any]],
        final_position: tuple[int, int, str],
        player_capacity: int,
        width: int,
    ) -> None:
        final_y = (
            final_position[1]
        )

        final_height = (
            self.theme.final_box_height(
                player_capacity
            )
        )

        card_width = min(
            350,
            self.theme.center_reserved_width(
                player_capacity
            )
            - 20,
        )

        card_height = 126

        x = (
            width // 2
            - card_width // 2
        )

        y = (
            final_y
            + final_height
            + 26
        )

        all_matches = [
            match
            for matches in bracket.values()
            for match in matches
        ]

        completed = sum(
            1
            for match in all_matches
            if self._status_value(
                getattr(
                    match,
                    "status",
                    "",
                )
            )
            in self.COMPLETED_STATUSES
        )

        total = len(
            all_matches
        )

        progress = (
            0
            if total == 0
            else completed / total
        )

        draw.rounded_rectangle(
            (
                x,
                y,
                x + card_width,
                y + card_height,
            ),
            radius=6,
            fill=self.PANEL,
            outline=self.BLUE,
            width=1,
        )

        draw.text(
            (
                width // 2,
                y + 18,
            ),
            "TOURNOI EN COURS",
            font=self._font(
                18,
                bold=True,
            ),
            fill=self.BLUE,
            anchor="ma",
        )

        draw.text(
            (
                width // 2,
                y + 49,
            ),
            (
                f"{completed} / "
                f"{total} matchs terminés"
            ),
            font=self._font(
                15,
                bold=True,
            ),
            fill=self.TEXT,
            anchor="ma",
        )

        bar_x = (
            x + 24
        )

        bar_y = (
            y + 78
        )

        bar_width = (
            card_width - 48
        )

        bar_height = 14

        draw.rounded_rectangle(
            (
                bar_x,
                bar_y,
                bar_x + bar_width,
                bar_y + bar_height,
            ),
            radius=7,
            fill=self.PANEL_ALT,
        )

        filled_width = max(
            0,
            min(
                bar_width,
                int(
                    bar_width
                    * progress
                ),
            ),
        )

        if filled_width > 0:
            draw.rounded_rectangle(
                (
                    bar_x,
                    bar_y,
                    bar_x + filled_width,
                    bar_y + bar_height,
                ),
                radius=7,
                fill=self.BLUE,
            )

        draw.text(
            (
                width // 2,
                y + 105,
            ),
            (
                "Résultats mis à jour après "
                "validation du staff"
            ),
            font=self._font(
                11
            ),
            fill=self.MUTED,
            anchor="ma",
        )

    # ==========================================================
    # FOOTER
    # ==========================================================

    def _draw_footer(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        final_mode: bool,
    ) -> None:
        width, height = (
            image.size
        )

        footer_y = (
            height
            - self.theme.footer_height
        )

        center_y = (
            footer_y
            + self.theme.footer_height // 2
        )

        draw.rectangle(
            (
                0,
                footer_y,
                width,
                height,
            ),
            fill=self.theme.footer_background,
        )

        draw.line(
            (
                0,
                footer_y,
                width // 2,
                footer_y,
            ),
            fill=self.RED,
            width=2,
        )

        draw.line(
            (
                width // 2,
                footer_y,
                width,
                footer_y,
            ),
            fill=self.BLUE,
            width=2,
        )

        icon_x = (
            self.theme.footer_horizontal_padding
        )

        icon_drawn = (
            self._draw_optional_footer_icon(
                image,
                icon_x,
                center_y,
            )
        )

        text_x = (
            icon_x
            + self.theme.footer_icon_size
            + 10
            if icon_drawn
            else icon_x
        )

        footer_font = self._font(
            self.theme.footer_title_font_size,
            bold=True,
        )

        info_font = self._font(
            self.theme.footer_information_font_size,
            bold=True,
        )

        draw.text(
            (
                text_x,
                center_y,
            ),
            "ORGANISÉ AVEC",
            font=info_font,
            fill=self.MUTED,
            anchor="lm",
        )

        organized_width = (
            self._text_width(
                draw,
                "ORGANISÉ AVEC",
                info_font,
            )
        )

        draw.text(
            (
                text_x
                + organized_width
                + 14,
                center_y,
            ),
            "HAMTARO TOURNAMENT BOT",
            font=footer_font,
            fill=self.RED,
            anchor="lm",
        )

        center_text = (
            "MERCI À TOUS LES PARTICIPANTS !"
            if final_mode
            else (
                "TOURNOI EN COURS — "
                "BON DUEL À TOUS !"
            )
        )

        draw.text(
            (
                width // 2,
                center_y,
            ),
            center_text,
            font=footer_font,
            fill=self.TEXT,
            anchor="mm",
        )

        draw.text(
            (
                width
                - self.theme.footer_horizontal_padding,
                center_y,
            ),
            "DISCORD.GG/HAMTARO",
            font=info_font,
            fill=self.BLUE,
            anchor="rm",
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
        if not bracket:
            raise ValueError(
                "Aucun bracket n'a été généré "
                "pour ce tournoi."
            )

        total_rounds = max(
            bracket
        )

        first_round_matches = len(
            bracket.get(
                total_rounds,
                [],
            )
        )

        if first_round_matches < 1:
            raise ValueError(
                "Le premier tour du tournoi est vide."
            )

        player_capacity = (
            first_round_matches
            * 2
        )

        if (
            player_capacity
            not in self.SUPPORTED_PLAYER_CAPACITIES
        ):
            raise ValueError(
                "Le moteur graphique prend uniquement "
                "en charge les brackets de 2, 4, 8, "
                "16, 32, 64 ou 128 joueurs."
            )

        self.theme.validate_player_capacity(
            player_capacity
        )

        width = self.theme.image_width(
            player_capacity
        )

        height = self.theme.image_height(
            player_capacity
        )

        positions = self._layout(
            bracket,
            player_capacity,
            final_mode,
        )

        image = Image.new(
            "RGBA",
            (
                width,
                height,
            ),
            self.BG + (255,),
        )

        self._draw_optional_background(
            image
        )

        tournament_id = getattr(
            tournament,
            "id",
            0,
        )

        self._draw_background_effects(
            image,
            player_capacity,
            tournament_id,
        )

        draw = ImageDraw.Draw(
            image
        )

        self._draw_header(
            image,
            draw,
            tournament,
            player_capacity,
            final_mode,
        )

        self._draw_round_titles(
            draw,
            positions,
            player_capacity,
        )

        self._draw_connectors(
            image,
            bracket,
            positions,
            player_capacity,
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

        box_width = self.theme.box_width(
            player_capacity
        )

        box_height = self.theme.box_height(
            player_capacity
        )

        final_width = (
            self.theme.final_box_width(
                player_capacity
            )
        )

        final_height = (
            self.theme.final_box_height(
                player_capacity
            )
        )

        for (
            round_number,
            matches,
        ) in bracket.items():
            round_positions = positions.get(
                round_number,
                [],
            )

            for (
                match,
                position,
            ) in zip(
                matches,
                round_positions,
            ):
                (
                    x,
                    y,
                    side,
                ) = position

                is_final = (
                    round_number == 1
                )

                if is_final:
                    side_color = (
                        self.GOLD
                    )

                    current_width = (
                        final_width
                    )

                    current_height = (
                        final_height
                    )

                elif side == "left":
                    side_color = (
                        self.RED
                    )

                    current_width = (
                        box_width
                    )

                    current_height = (
                        box_height
                    )

                else:
                    side_color = (
                        self.BLUE
                    )

                    current_width = (
                        box_width
                    )

                    current_height = (
                        box_height
                    )

                self._draw_match_box(
                    image,
                    draw,
                    x,
                    y,
                    current_width,
                    current_height,
                    match,
                    side_color,
                    avatars,
                    avatar_urls,
                    player_capacity,
                    is_final=is_final,
                )

        final_matches = bracket.get(
            1,
            [],
        )

        final_match = (
            final_matches[0]
            if final_matches
            else None
        )

        if (
            final_match is not None
            and positions.get(1)
        ):
            if (
                final_mode
                and getattr(
                    final_match,
                    "winner_name",
                    None,
                )
            ):
                self._draw_champion_card(
                    image,
                    draw,
                    tournament,
                    bracket,
                    final_match,
                    positions[1][0],
                    player_capacity,
                    avatars,
                )

            else:
                self._draw_active_center_card(
                    draw,
                    bracket,
                    positions[1][0],
                    player_capacity,
                    width,
                )

        self._draw_footer(
            image,
            draw,
            final_mode,
        )

        output = io.BytesIO()

        image.convert(
            "RGB"
        ).save(
            output,
            format="PNG",
            optimize=True,
            compress_level=7,
        )

        output.seek(0)

        return output
