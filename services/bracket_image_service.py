from __future__ import annotations

import asyncio
import io
import math

from dataclasses import dataclass
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
    Données graphiques représentant un joueur dans une case.
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
    Génère les images PNG HD utilisées par :

    - /bracket ;
    - /final_bracket ;
    - la future commande temporaire /bracket_preview.

    Le moteur reçoit les données d'un tournoi et retourne
    une image PNG stockée dans un objet BytesIO.
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

    def __init__(
        self,
        db: Any,
        theme: HamtaroBracketTheme | None = None,
    ):
        self.db = db

        self.theme = (
            theme
            or HamtaroBracketTheme()
        )

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
        """
        Retourne la valeur textuelle d'un statut.

        Compatible avec :
        - un Enum ;
        - une chaîne ;
        - une autre valeur.
        """

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
        """
        Raccourcit un texte trop long.
        """

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
    def _score_for(
        match: Any,
        slot: int,
    ) -> str:
        """
        Retourne le score du joueur occupant le slot demandé.

        slot :
        - 1 : joueur 1 ;
        - 2 : joueur 2.
        """

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

        status = BracketImageService._status_value(
            getattr(
                match,
                "status",
                "",
            )
        )

        if status in {
            "completed",
            "validated",
            "reported",
        }:
            score = getattr(
                match,
                f"player{slot}_score",
                None,
            )

            if score is not None:
                return str(score)

        return "—"

    @staticmethod
    def _round_title(
        round_number: int,
    ) -> str:
        """
        Retourne le nom graphique du round.
        """

        names = {
            1: "FINALE",
            2: "DEMI-FINALES",
            3: "QUARTS",
            4: "HUITIÈMES",
            5: "SEIZIÈMES",
            6: "32ES DE FINALE",
            7: "64ES DE FINALE",
        }

        return names.get(
            round_number,
            f"ROUND {round_number}",
        )

    @staticmethod
    def _font(
        size: int,
        bold: bool = False,
    ) -> ImageFont.ImageFont:
        """
        Charge une police disponible sur Railway/Linux.

        Une police Pillow par défaut est utilisée si aucune
        des polices prévues n'est disponible.
        """

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
        """
        Calcule la largeur d'un texte.
        """

        bbox = draw.textbbox(
            (0, 0),
            text,
            font=font,
        )

        return (
            bbox[2]
            - bbox[0]
        )

    # ==========================================================
    # RESSOURCES GRAPHIQUES
    # ==========================================================

    def _load_asset(
        self,
        path: str | Path,
    ) -> Image.Image | None:
        """
        Charge une ressource graphique facultative.

        Le moteur continue à fonctionner si le fichier
        n'existe pas.
        """

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
        """
        Redimensionne une image sans modifier ses proportions.
        """

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
        """
        Dessine le fond personnalisé lorsqu'il est disponible.
        """

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
            (
                self.BG[0],
                self.BG[1],
                self.BG[2],
                195,
            ),
        )

        canvas.alpha_composite(
            overlay
        )

    def _draw_optional_logo(
        self,
        canvas: Image.Image,
        x: int,
        y: int,
        maximum_width: int = 180,
        maximum_height: int = 150,
    ) -> bool:
        """
        Dessine le logo Hamtaro s'il est disponible.
        """

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
        maximum_width: int = 90,
        maximum_height: int = 90,
    ) -> bool:
        """
        Dessine le trophée facultatif dans la carte du champion.
        """

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

    # ==========================================================
    # AVATARS
    # ==========================================================

    async def _download_avatar_with_session(
        self,
        session: aiohttp.ClientSession,
        url: str | None,
        key: str,
    ) -> Image.Image:
        """
        Télécharge un avatar avec une session HTTP existante.
        """

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
            (128, 128),
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
        """
        Crée un avatar de remplacement avec une initiale.
        """

        image = Image.new(
            "RGBA",
            (128, 128),
            (
                54,
                62,
                86,
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
                81,
                91,
                121,
                255,
            ),
        )

        cleaned_key = key

        if cleaned_key.startswith(
            "name:"
        ):
            cleaned_key = cleaned_key[5:]

        initial = (
            cleaned_key[:1]
            or "?"
        ).upper()

        font = self._font(
            56,
            bold=True,
        )

        bbox = draw.textbbox(
            (0, 0),
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
        """
        Transforme un avatar carré en avatar rond.
        """

        avatar = ImageOps.fit(
            image,
            (size, size),
            method=Image.Resampling.LANCZOS,
        )

        mask = Image.new(
            "L",
            (size, size),
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
            (size, size),
            (
                0,
                0,
                0,
                0,
            ),
        )

        result.paste(
            avatar,
            (0, 0),
            mask,
        )

        return result

    async def _resolve_avatar_map(
        self,
        matches: list[Any],
        supplied: dict[str, str] | None,
    ) -> dict[str, Image.Image]:
        """
        Télécharge les avatars nécessaires au bracket.

        supplied :

            {
                "discord_id": "avatar_url"
            }
        """

        supplied = supplied or {}

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

                    identities[key] = supplied.get(
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
    # DONNÉES VISUELLES DES JOUEURS
    # ==========================================================

    def _match_players(
        self,
        match: Any,
        avatar_urls: dict[str, str] | None,
    ) -> tuple[
        PlayerVisual,
        PlayerVisual,
    ]:
        """
        Transforme les joueurs d'un match en données graphiques.
        """

        winner_id = getattr(
            match,
            "winner_id",
            None,
        )

        player1_id = getattr(
            match,
            "player1_id",
            None,
        )

        player2_id = getattr(
            match,
            "player2_id",
            None,
        )

        player1_name = (
            getattr(
                match,
                "player1_name",
                None,
            )
            or "À déterminer"
        )

        player2_name = (
            getattr(
                match,
                "player2_name",
                None,
            )
            or "À déterminer"
        )

        avatar_urls = (
            avatar_urls
            or {}
        )

        player1 = PlayerVisual(
            discord_id=(
                str(player1_id)
                if player1_id
                else None
            ),
            name=player1_name,
            score=self._score_for(
                match,
                1,
            ),
            avatar_url=(
                avatar_urls.get(
                    str(player1_id)
                )
                if player1_id
                else None
            ),
            winner=bool(
                winner_id
                and player1_id
                and str(winner_id)
                == str(player1_id)
            ),
        )

        player2 = PlayerVisual(
            discord_id=(
                str(player2_id)
                if player2_id
                else None
            ),
            name=player2_name,
            score=self._score_for(
                match,
                2,
            ),
            avatar_url=(
                avatar_urls.get(
                    str(player2_id)
                )
                if player2_id
                else None
            ),
            winner=bool(
                winner_id
                and player2_id
                and str(winner_id)
                == str(player2_id)
            ),
        )

        return (
            player1,
            player2,
        )

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
        compact: bool,
    ) -> None:
        """
        Dessine une case contenant les deux participants.
        """

        radius = (
            12
            if compact
            else 16
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
            width=3,
        )

        row_height = (
            height // 2
        )

        draw.line(
            (
                x + 9,
                y + row_height,
                x + width - 9,
                y + row_height,
            ),
            fill=self.LINE,
            width=2,
        )

        players = self._match_players(
            match,
            avatar_urls,
        )

        avatar_size = self.theme.avatar_size(
            64
            if compact
            else 32
        )

        name_font = self._font(
            (
                self.theme.compact_name_font_size
                if compact
                else self.theme.normal_name_font_size
            ),
            bold=True,
        )

        score_font = self._font(
            (
                self.theme.compact_score_font_size
                if compact
                else self.theme.normal_score_font_size
            ),
            bold=True,
        )

        for index, player in enumerate(
            players
        ):
            row_y = (
                y
                + index
                * row_height
            )

            key = (
                player.discord_id
                or f"name:{player.name}"
            )

            avatar = avatars.get(
                key
            )

            if avatar is not None:
                circle = self._circle_avatar(
                    avatar,
                    avatar_size,
                )

                avatar_x = (
                    x + 12
                )

                avatar_y = (
                    row_y
                    + (
                        row_height
                        - avatar_size
                    )
                    // 2
                )

                canvas.alpha_composite(
                    circle,
                    (
                        avatar_x,
                        avatar_y,
                    ),
                )

            player_is_unknown = (
                player.name
                == "À déterminer"
            )

            if player.winner:
                name_color = self.TEXT

            elif player_is_unknown:
                name_color = self.MUTED

            else:
                name_color = self.MUTED

            name = self._safe_text(
                player.name,
                (
                    15
                    if compact
                    else 20
                ),
            )

            name_x = (
                x + 58
                if compact
                else x + 66
            )

            name_y = (
                row_y
                + max(
                    8,
                    (
                        row_height
                        - (
                            self.theme.compact_name_font_size
                            if compact
                            else self.theme.normal_name_font_size
                        )
                    )
                    // 2
                    - 4,
                )
            )

            draw.text(
                (
                    name_x,
                    name_y,
                ),
                name,
                font=name_font,
                fill=name_color,
            )

            score_width = self._text_width(
                draw,
                player.score,
                score_font,
            )

            score_x = (
                x
                + width
                - 16
                - score_width
            )

            score_y = (
                row_y + 9
            )

            draw.text(
                (
                    score_x,
                    score_y,
                ),
                player.score,
                font=score_font,
                fill=(
                    self.GOLD
                    if player.winner
                    else self.TEXT
                ),
            )

            if player.winner:
                draw.rounded_rectangle(
                    (
                        x + 2,
                        row_y + 5,
                        x + 8,
                        row_y
                        + row_height
                        - 5,
                    ),
                    radius=3,
                    fill=self.GREEN,
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
    ) -> tuple[
        dict[
            int,
            list[
                tuple[int, int, str]
            ],
        ],
        int,
    ]:
        """
        Calcule les positions des matchs.

        Pour les grands tournois :

        - la moitié des joueurs progresse depuis la gauche ;
        - l'autre moitié progresse depuis la droite ;
        - les deux arbres se rejoignent vers la finale.
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

        vertical_gap = max(
            box_height + 30,
            124,
        )

        content_height = max(
            950,
            (
                matches_per_side
                * vertical_gap
            )
            + 220,
        )

        content_top = (
            header_height + 80
        )

        center_y = (
            header_height
            + content_height // 2
        )

        positions: dict[
            int,
            list[
                tuple[int, int, str]
            ],
        ] = {}

        rounds_before_final = max(
            1,
            total_rounds - 1,
        )

        center_reserved_width = max(
            700,
            box_width + 360,
        )

        usable_half_width = (
            width // 2
            - margin_x
            - center_reserved_width // 2
        )

        column_gap = max(
            box_width + 90,
            usable_half_width
            // rounds_before_final,
        )

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

            left_x = (
                margin_x
                + depth
                * column_gap
            )

            right_x = (
                width
                - margin_x
                - box_width
                - depth
                * column_gap
            )

            if round_number == total_rounds:
                left_y_positions = [
                    content_top
                    + index
                    * vertical_gap
                    for index in range(
                        left_count
                    )
                ]

                right_y_positions = [
                    content_top
                    + index
                    * vertical_gap
                    for index in range(
                        right_count
                    )
                ]

            else:
                child_positions = positions.get(
                    round_number + 1,
                    [],
                )

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
            - box_width // 2
        )

        final_y = (
            center_y
            - box_height // 2
        )

        positions[1] = [
            (
                final_x,
                final_y,
                "center",
            )
        ]

        final_height = (
            header_height
            + content_height
            + footer_height
        )

        return (
            positions,
            final_height,
        )

    @staticmethod
    def _parent_y_positions(
        children: list[
            tuple[int, int, str]
        ],
        parent_count: int,
    ) -> list[int]:
        """
        Place chaque match parent entre ses deux matchs enfants.
        """

        if (
            parent_count <= 0
            or not children
        ):
            return []

        positions: list[int] = []

        for parent_index in range(
            parent_count
        ):
            first_child_index = (
                parent_index * 2
            )

            second_child_index = min(
                first_child_index + 1,
                len(children) - 1,
            )

            if first_child_index >= len(
                children
            ):
                first_child_index = (
                    len(children) - 1
                )

            first_y = children[
                first_child_index
            ][1]

            second_y = children[
                second_child_index
            ][1]

            positions.append(
                (
                    first_y
                    + second_y
                )
                // 2
            )

        return positions

    # ==========================================================
    # LIGNES ENTRE LES MATCHS
    # ==========================================================

    def _draw_connectors(
        self,
        draw: ImageDraw.ImageDraw,
        bracket: dict[int, list[Any]],
        positions: dict[
            int,
            list[
                tuple[int, int, str]
            ],
        ],
        box_width: int,
        box_height: int,
    ) -> None:
        """
        Dessine les lignes reliant les matchs.
        """

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
                    target = next_positions[0]

                else:
                    target_candidates = [
                        position
                        for position in next_positions
                        if position[2] == side
                    ]

                    if not target_candidates:
                        continue

                    local_index = side_indexes[
                        side
                    ]

                    target_index = min(
                        local_index // 2,
                        len(target_candidates) - 1,
                    )

                    target = target_candidates[
                        target_index
                    ]

                    side_indexes[
                        side
                    ] += 1

                target_x, target_y, _ = target

                start_y = (
                    y + box_height // 2
                )

                end_y = (
                    target_y
                    + box_height // 2
                )

                if side == "left":
                    start_x = (
                        x + box_width
                    )

                    end_x = target_x

                else:
                    start_x = x

                    end_x = (
                        target_x
                        + box_width
                    )

                middle_x = (
                    start_x
                    + end_x
                ) // 2

                line_color = (
                    self.RED
                    if side == "left"
                    else self.BLUE
                )

                muted_line = tuple(
                    int(
                        (
                            color
                            + neutral
                        )
                        / 2
                    )
                    for color, neutral in zip(
                        line_color,
                        self.LINE,
                    )
                )

                draw.line(
                    (
                        start_x,
                        start_y,
                        middle_x,
                        start_y,
                    ),
                    fill=muted_line,
                    width=4,
                )

                draw.line(
                    (
                        middle_x,
                        start_y,
                        middle_x,
                        end_y,
                    ),
                    fill=muted_line,
                    width=4,
                )

                draw.line(
                    (
                        middle_x,
                        end_y,
                        end_x,
                        end_y,
                    ),
                    fill=muted_line,
                    width=4,
                )

    # ==========================================================
    # FOND ET HALOS
    # ==========================================================

    def _draw_background_effects(
        self,
        image: Image.Image,
        header_height: int,
        footer_height: int,
    ) -> None:
        """
        Ajoute les halos rouge et bleu de chaque côté.
        """

        width, height = image.size

        effect_layer = Image.new(
            "RGBA",
            image.size,
            (
                0,
                0,
                0,
                0,
            ),
        )

        effect_draw = ImageDraw.Draw(
            effect_layer
        )

        content_bottom = (
            height - footer_height
        )

        halo_width = max(
            500,
            width // 5,
        )

        for step in range(
            10,
            0,
            -1,
        ):
            alpha = (
                5 + step * 2
            )

            expansion = (
                step * 80
            )

            effect_draw.ellipse(
                (
                    -halo_width - expansion,
                    header_height - expansion,
                    halo_width + expansion,
                    content_bottom + expansion,
                ),
                fill=(
                    self.RED[0],
                    self.RED[1],
                    self.RED[2],
                    alpha,
                ),
            )

            effect_draw.ellipse(
                (
                    width
                    - halo_width
                    - expansion,
                    header_height
                    - expansion,
                    width
                    + halo_width
                    + expansion,
                    content_bottom
                    + expansion,
                ),
                fill=(
                    self.BLUE[0],
                    self.BLUE[1],
                    self.BLUE[2],
                    alpha,
                ),
            )

        image.alpha_composite(
            effect_layer
        )

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
        box_height: int,
        avatars: dict[str, Image.Image],
    ) -> None:
        """
        Dessine la carte du champion sous la finale.
        """

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

        width = image.width

        card_width = 650
        card_height = 350

        card_x = (
            width // 2
            - card_width // 2
        )

        final_y = final_position[1]

        card_y = (
            final_y
            + box_height
            + 52
        )

        draw.rounded_rectangle(
            (
                card_x,
                card_y,
                card_x + card_width,
                card_y + card_height,
            ),
            radius=30,
            fill=(
                32,
                29,
                19,
            ),
            outline=self.GOLD,
            width=5,
        )

        trophy_drawn = self._draw_optional_trophy(
            image,
            center_x=width // 2,
            y=card_y + 68,
            maximum_width=82,
            maximum_height=82,
        )

        title_y = (
            card_y + 30
        )

        draw.text(
            (
                width // 2,
                title_y,
            ),
            (
                "CHAMPION"
                if trophy_drawn
                else "🏆 CHAMPION"
            ),
            font=self._font(
                self.theme.champion_title_font_size,
                bold=True,
            ),
            fill=self.GOLD,
            anchor="ma",
        )

        key = (
            str(champion_id)
            if champion_id
            else f"name:{champion_name}"
        )

        avatar = avatars.get(
            key
        )

        avatar_y = (
            card_y + 170
        )

        if avatar is not None:
            circle = self._circle_avatar(
                avatar,
                self.theme.champion_avatar_size,
            )

            image.alpha_composite(
                circle,
                (
                    card_x + 48,
                    avatar_y,
                ),
            )

        name_x = (
            card_x + 190
        )

        draw.text(
            (
                name_x,
                card_y + 175,
            ),
            self._safe_text(
                champion_name,
                28,
            ),
            font=self._font(
                self.theme.champion_name_font_size,
                bold=True,
            ),
            fill=self.TEXT,
        )

        tournament_id = getattr(
            tournament,
            "id",
            "?",
        )

        tournament_format = getattr(
            tournament,
            "format",
            "Format inconnu",
        )

        draw.text(
            (
                name_x,
                card_y + 238,
            ),
            (
                f"Tournoi #{tournament_id}"
                f" • {tournament_format}"
            ),
            font=self._font(
                24
            ),
            fill=self.MUTED,
        )

        final_score = getattr(
            final_match,
            "score",
            None,
        )

        if not final_score:
            player1_score = getattr(
                final_match,
                "player1_score",
                0,
            )

            player2_score = getattr(
                final_match,
                "player2_score",
                0,
            )

            final_score = (
                f"{player1_score}"
                f"-"
                f"{player2_score}"
            )

        draw.text(
            (
                name_x,
                card_y + 280,
            ),
            f"Score de la finale : {final_score}",
            font=self._font(
                22,
                bold=True,
            ),
            fill=self.GOLD,
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
        """
        Génère une image PNG complète.

        final_mode=False :
            bracket du tournoi actif.

        final_mode=True :
            affiche finale avec champion.
        """

        if not bracket:
            raise ValueError(
                "Aucun bracket n'a été généré pour ce tournoi."
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
            first_round_matches * 2
        )

        if (
            player_capacity
            not in self.SUPPORTED_PLAYER_CAPACITIES
        ):
            raise ValueError(
                "Le moteur graphique prend uniquement en charge "
                "les brackets de 2, 4, 8, 16, 32, 64 "
                "ou 128 joueurs."
            )

        width = self.theme.image_width(
            player_capacity
        )

        header_height = (
            self.theme.header_height
        )

        footer_height = (
            self.theme.footer_height
        )

        box_width = self.theme.box_width(
            player_capacity
        )

        box_height = self.theme.box_height(
            player_capacity
        )

        margin_x = (
            self.theme.horizontal_margin
        )

        positions, height = self._layout(
            bracket,
            width,
            header_height,
            footer_height,
            box_width,
            box_height,
            margin_x,
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

        self._draw_background_effects(
            image,
            header_height,
            footer_height,
        )

        draw = ImageDraw.Draw(
            image
        )

        # ------------------------------------------------------
        # Lignes graphiques du fond
        # ------------------------------------------------------

        

        # ------------------------------------------------------
        # Polices
        # ------------------------------------------------------

        title_font = self._font(
            self.theme.title_font_size,
            bold=True,
        )

        subtitle_font = self._font(
            self.theme.subtitle_font_size,
            bold=True,
        )

        small_font = self._font(
            self.theme.information_font_size
        )

        phase_font = self._font(
            self.theme.round_font_size,
            bold=True,
        )

        tournament_name = getattr(
            tournament,
            "name",
            "Tournoi Hamtaro",
        )

        tournament_id = getattr(
            tournament,
            "id",
            "?",
        )

        tournament_format = getattr(
            tournament,
            "format",
            "Format inconnu",
        )

        status = self._status_value(
            getattr(
                tournament,
                "status",
                "",
            )
        )

        title = (
            "BRACKET FINAL"
            if final_mode
            else "BRACKET EN DIRECT"
        )

        # ------------------------------------------------------
        # Bandeau supérieur
        # ------------------------------------------------------

        draw.rectangle(
            (
                0,
                0,
                width,
                header_height,
            ),
            fill=(
                self.theme.header_background[0],
                self.theme.header_background[1],
                self.theme.header_background[2],
                255,
            ),
        )

        logo_drawn = self._draw_optional_logo(
            image,
            x=70,
            y=54,
            maximum_width=150,
            maximum_height=125,
        )

        brand_x = (
            245
            if logo_drawn
            else 90
        )

        draw.text(
            (
                brand_x,
                52,
            ),
            "HAMTARO",
            font=title_font,
            fill=self.TEXT,
        )

        draw.text(
            (
                brand_x,
                142,
            ),
            title,
            font=subtitle_font,
            fill=(
                self.GOLD
                if final_mode
                else self.BLUE
            ),
        )

        draw.text(
            (
                width // 2,
                56,
            ),
            self._safe_text(
                tournament_name,
                55,
            ),
            font=title_font,
            fill=self.TEXT,
            anchor="ma",
        )

        tournament_info = (
            f"Tournoi #{tournament_id}"
            f"  •  {tournament_format}"
            f"  •  Élimination directe"
            f"  •  {player_capacity} joueurs"
        )

        draw.text(
            (
                width // 2,
                158,
            ),
            tournament_info,
            font=small_font,
            fill=self.MUTED,
            anchor="ma",
        )

        draw.text(
            (
                width - 95,
                62,
            ),
            status.upper(),
            font=subtitle_font,
            fill=(
                self.GREEN
                if final_mode
                else self.BLUE
            ),
            anchor="ra",
        )

        # ------------------------------------------------------
        # Titres des rounds
        # ------------------------------------------------------

        for (
            round_number,
            round_positions,
        ) in positions.items():
            if not round_positions:
                continue

            if round_number == 1:
                final_x, _, _ = (
                    round_positions[0]
                )

                draw.text(
                    (
                        final_x
                        + box_width // 2,
                        header_height + 18,
                    ),
                    self._round_title(
                        round_number
                    ),
                    font=phase_font,
                    fill=self.GOLD,
                    anchor="ma",
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

                draw.text(
                    (
                        x + box_width // 2,
                        header_height + 18,
                    ),
                    self._round_title(
                        round_number
                    ),
                    font=phase_font,
                    fill=(
                        self.RED
                        if side == "left"
                        else self.BLUE
                    ),
                    anchor="ma",
                )

        # ------------------------------------------------------
        # Lignes du bracket
        # ------------------------------------------------------

        self._draw_connectors(
            draw,
            bracket,
            positions,
            box_width,
            box_height,
        )

        # ------------------------------------------------------
        # Chargement des avatars
        # ------------------------------------------------------

        all_matches = [
            match
            for matches in bracket.values()
            for match in matches
        ]

        avatars = await self._resolve_avatar_map(
            all_matches,
            avatar_urls,
        )

        # ------------------------------------------------------
        # Cases de matchs
        # ------------------------------------------------------

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
                x, y, side = position

                if side == "center":
                    side_color = self.GOLD

                elif side == "left":
                    side_color = self.RED

                else:
                    side_color = self.BLUE

                self._draw_match_box(
                    image,
                    draw,
                    x,
                    y,
                    box_width,
                    box_height,
                    match,
                    side_color,
                    avatars,
                    avatar_urls,
                    compact=(
                        player_capacity >= 64
                    ),
                )

        # ------------------------------------------------------
        # Champion
        # ------------------------------------------------------

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
            final_mode
            and final_match is not None
            and positions.get(1)
        ):
            self._draw_champion_card(
                image,
                draw,
                tournament,
                final_match,
                positions[1][0],
                box_height,
                avatars,
            )

        # ------------------------------------------------------
        # Bandeau inférieur
        # ------------------------------------------------------

        footer_y = (
            height - footer_height
        )

        draw.rectangle(
            (
                0,
                footer_y,
                width,
                height,
            ),
            fill=(
                self.theme.footer_background[0],
                self.theme.footer_background[1],
                self.theme.footer_background[2],
                255,
            ),
        )

        draw.text(
            (
                90,
                footer_y + 56,
            ),
            "Organisé avec Hamtaro Tournament Bot",
            font=self._font(
                30,
                bold=True,
            ),
            fill=self.TEXT,
        )

        draw.text(
            (
                90,
                footer_y + 112,
            ),
            f"ID tournoi #{tournament_id}",
            font=self._font(
                23
            ),
            fill=self.MUTED,
        )

        footer_right = (
            "Merci à tous les participants !"
            if final_mode
            else (
                "Résultats actualisés selon "
                "les validations du staff"
            )
        )

        draw.text(
            (
                width - 90,
                footer_y + 82,
            ),
            footer_right,
            font=self._font(
                26,
                bold=True,
            ),
            fill=(
                self.GOLD
                if final_mode
                else self.BLUE
            ),
            anchor="ra",
        )

        # ------------------------------------------------------
        # Export PNG
        # ------------------------------------------------------

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
