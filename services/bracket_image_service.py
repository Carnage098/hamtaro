from __future__ import annotations

import asyncio
import io
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
from PIL import (
    Image,
    ImageDraw,
    ImageFilter,
    ImageFont,
    ImageOps,
)

from graphics.theme import HamtaroBracketTheme


Color = tuple[int, int, int]
Position = tuple[int, int, str]


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


@dataclass(slots=True, frozen=True)
class RoundGeometry:
    """Dimensions calculées pour une ronde du bracket."""

    width: int
    height: int
    avatar_size: int
    name_font_size: int
    score_font_size: int
    seed_font_size: int


class BracketImageService:
    """
    Génère les images PNG HD utilisées par :

    - /bracket ;
    - /final_bracket ;
    - /preview_bracket.

    Le renderer produit une affiche esport symétrique :

    - branche gauche rouge ;
    - branche droite bleue ;
    - vrais avatars Discord ;
    - finale centrale renforcée ;
    - illustration Hamtaro dans le header et le bloc champion ;
    - connecteurs lumineux ;
    - statistiques et footer proches de la maquette Hamtaro Cup.

    Les assets restent facultatifs. Lorsqu'un fichier est absent,
    le renderer dessine automatiquement une version de secours.
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
    ) -> None:
        self.db = db
        self.theme = theme or HamtaroBracketTheme()

        self._avatar_cache: dict[str, Image.Image] = {}
        self._asset_cache: dict[str, Image.Image] = {}

    # ==========================================================
    # RACCOURCIS VERS LE THÈME
    # ==========================================================

    @property
    def BG(self) -> Color:
        return self.theme.background

    @property
    def PANEL(self) -> Color:
        return self.theme.panel

    @property
    def PANEL_ALT(self) -> Color:
        return self.theme.panel_alternate

    @property
    def TEXT(self) -> Color:
        return self.theme.text

    @property
    def MUTED(self) -> Color:
        return self.theme.muted_text

    @property
    def RED(self) -> Color:
        return self.theme.left_side

    @property
    def BLUE(self) -> Color:
        return self.theme.right_side

    @property
    def GOLD(self) -> Color:
        return self.theme.champion_gold

    @property
    def GREEN(self) -> Color:
        return self.theme.winner_green

    @property
    def LINE(self) -> Color:
        return self.theme.connector_line

    # ==========================================================
    # OUTILS GÉNÉRAUX
    # ==========================================================

    @staticmethod
    def _status_value(
        status: Any,
    ) -> str:
        """Retourne la valeur textuelle normalisée d'un statut."""

        return getattr(
            status,
            "value",
            str(status),
        ).lower().strip()

    @staticmethod
    def _safe_text(
        value: str | None,
        maximum: int = 20,
    ) -> str:
        """Raccourcit un texte trop long sans produire une chaîne vide."""

        cleaned = (
            value
            or "À déterminer"
        ).strip() or "À déterminer"

        if len(cleaned) <= maximum:
            return cleaned

        return (
            cleaned[
                : max(
                    1,
                    maximum - 1,
                )
            ]
            + "…"
        )

    @staticmethod
    def _blend_color(
        first: Color,
        second: Color,
        ratio: float,
    ) -> Color:
        """Mélange deux couleurs RGB."""

        ratio = max(
            0.0,
            min(
                1.0,
                ratio,
            ),
        )

        return tuple(
            int(
                first_value
                + (
                    second_value
                    - first_value
                )
                * ratio
            )
            for first_value, second_value in zip(
                first,
                second,
            )
        )

    @staticmethod
    def _with_alpha(
        color: Color,
        alpha: int,
    ) -> tuple[int, int, int, int]:
        return (
            *color,
            max(
                0,
                min(
                    255,
                    alpha,
                ),
            ),
        )

    @staticmethod
    def _player_key(
        discord_id: Any,
        name: str | None,
    ) -> str:
        """Construit la clé utilisée pour l'avatar et le seed."""

        if discord_id not in (
            None,
            "",
        ):
            return str(discord_id)

        return f"name:{name or '?'}"

    @staticmethod
    def _score_for(
        match: Any,
        slot: int,
    ) -> str:
        """Retourne le score du joueur occupant le slot demandé."""

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
            "finished",
            "validated",
            "approved",
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
        """Retourne l'intitulé court affiché au-dessus d'une ronde."""

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

    @staticmethod
    def _font(
        size: int,
        bold: bool = False,
        italic: bool = False,
    ) -> ImageFont.ImageFont:
        """Charge une police disponible sur Railway/Linux."""

        size = max(
            8,
            int(size),
        )

        if bold and italic:
            candidates = (
                (
                    "/usr/share/fonts/truetype/"
                    "dejavu/DejaVuSans-BoldOblique.ttf"
                ),
                (
                    "/usr/share/fonts/truetype/liberation2/"
                    "LiberationSans-BoldItalic.ttf"
                ),
                (
                    "/usr/share/fonts/truetype/freefont/"
                    "FreeSansBoldOblique.ttf"
                ),
            )

        elif bold:
            candidates = (
                (
                    "/usr/share/fonts/truetype/"
                    "dejavu/DejaVuSans-Bold.ttf"
                ),
                (
                    "/usr/share/fonts/truetype/liberation2/"
                    "LiberationSans-Bold.ttf"
                ),
                (
                    "/usr/share/fonts/truetype/freefont/"
                    "FreeSansBold.ttf"
                ),
            )

        elif italic:
            candidates = (
                (
                    "/usr/share/fonts/truetype/"
                    "dejavu/DejaVuSans-Oblique.ttf"
                ),
                (
                    "/usr/share/fonts/truetype/liberation2/"
                    "LiberationSans-Italic.ttf"
                ),
                (
                    "/usr/share/fonts/truetype/freefont/"
                    "FreeSansOblique.ttf"
                ),
            )

        else:
            candidates = (
                (
                    "/usr/share/fonts/truetype/"
                    "dejavu/DejaVuSans.ttf"
                ),
                (
                    "/usr/share/fonts/truetype/liberation2/"
                    "LiberationSans-Regular.ttf"
                ),
                (
                    "/usr/share/fonts/truetype/freefont/"
                    "FreeSans.ttf"
                ),
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
            (
                0,
                0,
            ),
            text,
            font=font,
        )

        return (
            bbox[2]
            - bbox[0]
        )

    @staticmethod
    def _text_height(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
    ) -> int:
        bbox = draw.textbbox(
            (
                0,
                0,
            ),
            text,
            font=font,
        )

        return (
            bbox[3]
            - bbox[1]
        )

    @classmethod
    def _fit_text(
        cls,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        maximum_width: int,
    ) -> str:
        """Coupe un texte jusqu'à ce qu'il entre dans la largeur donnée."""

        cleaned = (
            text
            or "À déterminer"
        ).strip() or "À déterminer"

        if (
            cls._text_width(
                draw,
                cleaned,
                font,
            )
            <= maximum_width
        ):
            return cleaned

        suffix = "…"
        low = 1
        high = len(cleaned)
        best = suffix

        while low <= high:
            middle = (
                low
                + high
            ) // 2

            candidate = (
                cleaned[:middle].rstrip()
                + suffix
            )

            if (
                cls._text_width(
                    draw,
                    candidate,
                    font,
                )
                <= maximum_width
            ):
                best = candidate
                low = middle + 1

            else:
                high = middle - 1

        return best

    # ==========================================================
    # RESSOURCES GRAPHIQUES
    # ==========================================================

    def _theme_path(
        self,
        property_name: str,
        filename: str,
    ) -> Path:
        """Retourne un chemin d'asset même avec un ancien theme.py."""

        value = getattr(
            self.theme,
            property_name,
            None,
        )

        if value is not None:
            return Path(value)

        assets_directory = Path(
            getattr(
                self.theme,
                "assets_directory",
                (
                    Path(__file__).resolve().parent.parent
                    / "graphics"
                    / "assets"
                ),
            )
        )

        return (
            assets_directory
            / filename
        )

    def _load_asset(
        self,
        path: str | Path,
    ) -> Image.Image | None:
        """Charge une ressource graphique facultative avec cache."""

        asset_path = Path(path)

        try:
            cache_key = str(
                asset_path.resolve()
            )

        except OSError:
            cache_key = str(asset_path)

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
        """Redimensionne une image sans modifier ses proportions."""

        result = image.copy()

        result.thumbnail(
            (
                max(
                    1,
                    maximum_width,
                ),
                max(
                    1,
                    maximum_height,
                ),
            ),
            Image.Resampling.LANCZOS,
        )

        return result

    def _draw_optional_background(
        self,
        canvas: Image.Image,
    ) -> None:
        """Dessine le fond personnalisé lorsqu'il est disponible."""

        path = self._theme_path(
            "background_path",
            "bracket_background.png",
        )

        background = self._load_asset(
            path
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
                *self.BG,
                190,
            ),
        )

        canvas.alpha_composite(
            overlay
        )

    def _draw_asset_centered(
        self,
        canvas: Image.Image,
        path: Path,
        center_x: int,
        y: int,
        maximum_width: int,
        maximum_height: int,
    ) -> Image.Image | None:
        asset = self._load_asset(
            path
        )

        if asset is None:
            return None

        asset = self._contain_image(
            asset,
            maximum_width,
            maximum_height,
        )

        canvas.alpha_composite(
            asset,
            (
                center_x
                - asset.width // 2,
                y,
            ),
        )

        return asset

    # ==========================================================
    # AVATARS
    # ==========================================================

    async def _download_avatar_with_session(
        self,
        session: aiohttp.ClientSession,
        url: str | None,
        key: str,
        display_name: str,
    ) -> Image.Image:
        """Télécharge un avatar ou crée un fallback avec l'initiale du nom."""

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
                display_name
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
        display_name: str,
    ) -> Image.Image:
        """Crée un avatar de remplacement lisible et non numérique."""

        image = Image.new(
            "RGBA",
            (
                128,
                128,
            ),
            (
                24,
                31,
                48,
                255,
            ),
        )

        draw = ImageDraw.Draw(
            image
        )

        seed = sum(
            ord(character)
            for character in display_name
        )

        accent = (
            72
            + seed % 70,
            84
            + (
                seed
                * 3
            )
            % 70,
            118
            + (
                seed
                * 5
            )
            % 70,
        )

        draw.ellipse(
            (
                5,
                5,
                123,
                123,
            ),
            fill=(
                *accent,
                255,
            ),
        )

        draw.ellipse(
            (
                13,
                13,
                115,
                115,
            ),
            fill=(
                33,
                42,
                64,
                255,
            ),
            outline=(
                255,
                255,
                255,
                75,
            ),
            width=2,
        )

        initial = (
            display_name.strip()[:1]
            or "?"
        ).upper()

        font = self._font(
            56,
            bold=True,
        )

        draw.text(
            (
                64,
                63,
            ),
            initial,
            font=font,
            fill=(
                255,
                255,
                255,
                255,
            ),
            anchor="mm",
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

    def _paste_avatar(
        self,
        canvas: Image.Image,
        avatar: Image.Image,
        x: int,
        y: int,
        size: int,
        border_color: Color,
        border_width: int,
    ) -> None:
        """
        Colle un avatar rond avec un véritable contour visible.
        """

        border_width = max(
            1,
            border_width,
        )

        outer_size = (
            size
            + border_width
            * 2
        )

        border = Image.new(
            "RGBA",
            (
                outer_size,
                outer_size,
            ),
            (
                0,
                0,
                0,
                0,
            ),
        )

        border_draw = ImageDraw.Draw(
            border
        )

        border_draw.ellipse(
            (
                0,
                0,
                outer_size - 1,
                outer_size - 1,
            ),
            fill=(
                *border_color,
                255,
            ),
        )

        circle = self._circle_avatar(
            avatar,
            size,
        )

        border.alpha_composite(
            circle,
            (
                border_width,
                border_width,
            ),
        )

        canvas.alpha_composite(
            border,
            (
                x - border_width,
                y - border_width,
            ),
        )

    async def _resolve_avatar_map(
        self,
        matches: list[Any],
        supplied: dict[str, str] | None,
    ) -> dict[str, Image.Image]:
        """
        Télécharge tous les avatars nécessaires
        dans une seule session HTTP.
        """

        supplied = supplied or {}

        identities: dict[
            str,
            tuple[str | None, str],
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
                    or "À déterminer"
                )

                if (
                    not discord_id
                    and name == "À déterminer"
                ):
                    continue

                key = self._player_key(
                    discord_id,
                    name,
                )

                url = None

                if discord_id not in (
                    None,
                    "",
                ):
                    url = (
                        supplied.get(
                            str(discord_id)
                        )
                        or supplied.get(
                            key
                        )
                    )

                identities[
                    key
                ] = (
                    url,
                    name,
                )

        if not identities:
            return {}

        timeout = aiohttp.ClientTimeout(
            total=12,
            connect=5,
        )

        connector = aiohttp.TCPConnector(
            limit=12
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
                    display_name,
                )
                for (
                    key,
                    (
                        url,
                        display_name,
                    ),
                ) in identities.items()
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
    # SEEDS ET DONNÉES VISUELLES
    # ==========================================================

    def _build_seed_map(
        self,
        bracket: dict[int, list[Any]],
    ) -> dict[str, int]:
        """
        Attribue un seed de secours à partir du premier tour.
        """

        first_round_number = max(
            bracket
        )

        first_round = bracket.get(
            first_round_number,
            [],
        )

        seeds: dict[str, int] = {}
        next_seed = 1

        for match in first_round:
            for slot in (
                1,
                2,
            ):
                discord_id = getattr(
                    match,
                    f"player{slot}_id",
                    None,
                )

                name = getattr(
                    match,
                    f"player{slot}_name",
                    None,
                )

                if (
                    not discord_id
                    and not name
                ):
                    continue

                key = self._player_key(
                    discord_id,
                    name,
                )

                if key not in seeds:
                    explicit_seed = getattr(
                        match,
                        f"player{slot}_seed",
                        None,
                    )

                    seeds[
                        key
                    ] = (
                        explicit_seed
                        or next_seed
                    )

                    next_seed += 1

        return seeds

    def _match_players(
        self,
        match: Any,
        avatar_urls: dict[str, str] | None,
        seed_map: dict[str, int],
    ) -> tuple[
        PlayerVisual,
        PlayerVisual,
    ]:
        """
        Transforme les deux participants d'un match
        en données visuelles.
        """

        winner_id = getattr(
            match,
            "winner_id",
            None,
        )

        winner_name = getattr(
            match,
            "winner_name",
            None,
        )

        avatar_urls = (
            avatar_urls
            or {}
        )

        players: list[
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

            key = self._player_key(
                player_id,
                player_name,
            )

            explicit_seed = getattr(
                match,
                f"player{slot}_seed",
                None,
            )

            player_winner = False

            if (
                winner_id not in (
                    None,
                    "",
                )
                and player_id not in (
                    None,
                    "",
                )
            ):
                player_winner = (
                    str(winner_id)
                    == str(player_id)
                )

            elif (
                winner_name
                and player_name
            ):
                player_winner = (
                    winner_name
                    == player_name
                )

            players.append(
                PlayerVisual(
                    discord_id=(
                        str(player_id)
                        if player_id
                        not in (
                            None,
                            "",
                        )
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
                        not in (
                            None,
                            "",
                        )
                        else None
                    ),
                    winner=player_winner,
                    seed=(
                        explicit_seed
                        or seed_map.get(
                            key
                        )
                    ),
                    deck=getattr(
                        match,
                        f"player{slot}_deck",
                        None,
                    ),
                )
            )

        return (
            players[0],
            players[1],
        )

    # ==========================================================
    # GÉOMÉTRIE ADAPTATIVE
    # ==========================================================

    def _round_geometry(
        self,
        player_capacity: int,
        round_number: int,
        total_rounds: int,
    ) -> RoundGeometry:
        """
        Retourne les dimensions adaptées
        à une ronde latérale.
        """

        round_index = (
            total_rounds
            - round_number
        )

        side_rounds = max(
            1,
            total_rounds - 1,
        )

        width_method = getattr(
            self.theme,
            "box_width_for_round",
            None,
        )

        height_method = getattr(
            self.theme,
            "box_height_for_round",
            None,
        )

        avatar_method = getattr(
            self.theme,
            "player_avatar_size_for_round",
            None,
        )

        name_method = getattr(
            self.theme,
            "player_name_font_size_for_round",
            None,
        )

        score_method = getattr(
            self.theme,
            "player_score_font_size_for_round",
            None,
        )

        width = (
            width_method(
                player_capacity,
                round_index,
                side_rounds,
            )
            if callable(
                width_method
            )
            else self.theme.box_width(
                player_capacity
            )
        )

        height = (
            height_method(
                player_capacity,
                round_index,
                side_rounds,
            )
            if callable(
                height_method
            )
            else self.theme.box_height(
                player_capacity
            )
        )

        avatar_size = (
            avatar_method(
                player_capacity,
                round_index,
                side_rounds,
            )
            if callable(
                avatar_method
            )
            else self.theme.player_avatar_size(
                player_capacity
            )
        )

        name_size = (
            name_method(
                player_capacity,
                round_index,
                side_rounds,
            )
            if callable(
                name_method
            )
            else self.theme.player_name_font_size(
                player_capacity
            )
        )

        score_size = (
            score_method(
                player_capacity,
                round_index,
                side_rounds,
            )
            if callable(
                score_method
            )
            else self.theme.player_score_font_size(
                player_capacity
            )
        )

        return RoundGeometry(
            width=max(
                80,
                int(width),
            ),
            height=max(
                34,
                int(height),
            ),
            avatar_size=max(
                14,
                int(avatar_size),
            ),
            name_font_size=max(
                9,
                int(name_size),
            ),
            score_font_size=max(
                10,
                int(score_size),
            ),
            seed_font_size=max(
                8,
                int(
                    self.theme.player_seed_font_size(
                        player_capacity
                    )
                ),
            ),
        )

    def _all_geometries(
        self,
        player_capacity: int,
        total_rounds: int,
    ) -> dict[int, RoundGeometry]:
        """
        Calcule les dimensions de toutes les rondes.
        """

        geometries: dict[
            int,
            RoundGeometry,
        ] = {}

        for round_number in range(
            total_rounds,
            1,
            -1,
        ):
            geometries[
                round_number
            ] = self._round_geometry(
                player_capacity,
                round_number,
                total_rounds,
            )

        final_width = int(
            self.theme.final_box_width(
                player_capacity
            )
        )

        final_height = int(
            self.theme.final_box_height(
                player_capacity
            )
        )

        geometries[
            1
        ] = RoundGeometry(
            width=max(
                180,
                final_width,
            ),
            height=max(
                78,
                final_height,
            ),
            avatar_size=max(
                30,
                int(
                    getattr(
                        self.theme,
                        "final_avatar_size",
                        40,
                    )
                ),
            ),
            name_font_size=max(
                16,
                int(
                    getattr(
                        self.theme,
                        "final_name_font_size",
                        22,
                    )
                ),
            ),
            score_font_size=max(
                18,
                int(
                    getattr(
                        self.theme,
                        "final_score_font_size",
                        23,
                    )
                ),
            ),
            seed_font_size=max(
                11,
                int(
                    self.theme.player_seed_font_size(
                        player_capacity
                    )
                )
                + 2,
            ),
        )

        return geometries

    def _layout(
        self,
        bracket: dict[int, list[Any]],
        player_capacity: int,
        width: int,
        height: int,
        geometries: dict[int, RoundGeometry],
        final_mode: bool,
    ) -> dict[
        int,
        list[Position],
    ]:
        """
        Calcule un bracket symétrique
        dans le canvas 16:9.
        """

        total_rounds = max(
            bracket
        )

        header_height = int(
            getattr(
                self.theme,
                "header_height",
                112,
            )
        )

        footer_height = int(
            getattr(
                self.theme,
                "footer_height",
                54,
            )
        )

        round_labels_height = int(
            getattr(
                self.theme,
                "round_labels_height",
                28,
            )
        )

        top_padding = int(
            getattr(
                self.theme,
                "bracket_top_padding",
                10,
            )
        )

        bottom_padding = int(
            getattr(
                self.theme,
                "bracket_bottom_padding",
                10,
            )
        )

        margin_x = int(
            getattr(
                self.theme,
                "horizontal_margin",
                24,
            )
        )

        content_top = (
            header_height
            + round_labels_height
            + top_padding
        )

        content_bottom = (
            height
            - footer_height
            - bottom_padding
        )

        content_height = max(
            1,
            content_bottom
            - content_top,
        )

        final_geometry = geometries[
            1
        ]

        final_x = (
            width // 2
            - final_geometry.width // 2
        )

        if final_mode:
            final_y = max(
                content_top + 105,
                min(
                    int(
                        height
                        * 0.315
                    ),
                    (
                        content_bottom
                        - final_geometry.height
                        - 400
                    ),
                ),
            )

        else:
            final_y = (
                content_top
                + content_height // 2
                - final_geometry.height // 2
            )

        positions: dict[
            int,
            list[Position],
        ] = {
            1: [
                (
                    final_x,
                    final_y,
                    "center",
                )
            ]
        }

        side_round_count = (
            total_rounds
            - 1
        )

        if side_round_count <= 0:
            return positions

        column_gap_method = getattr(
            self.theme,
            "column_gap",
            None,
        )

        center_gap = max(
            18,
            int(
                column_gap_method(
                    player_capacity
                )
                if callable(
                    column_gap_method
                )
                else 18
            ),
        )

        left_outer_start = margin_x
        right_outer_edge = (
            width
            - margin_x
        )

        left_inner_start = (
            final_x
            - center_gap
            - geometries[2].width
        )

        right_inner_start = (
            final_x
            + final_geometry.width
            + center_gap
        )

        if side_round_count == 1:
            left_x_by_round = {
                2: left_inner_start,
            }

            right_x_by_round = {
                2: right_inner_start,
            }

        else:
            left_x_by_round: dict[
                int,
                int,
            ] = {}

            right_x_by_round: dict[
                int,
                int,
            ] = {}

            for (
                depth,
                round_number,
            ) in enumerate(
                range(
                    total_rounds,
                    1,
                    -1,
                )
            ):
                ratio = (
                    depth
                    / max(
                        1,
                        side_round_count - 1,
                    )
                )

                geometry = geometries[
                    round_number
                ]

                left_x = round(
                    left_outer_start
                    + (
                        left_inner_start
                        - left_outer_start
                    )
                    * ratio
                )

                right_x = round(
                    right_outer_edge
                    - geometry.width
                    - (
                        right_outer_edge
                        - geometries[
                            total_rounds
                        ].width
                        - right_inner_start
                    )
                    * ratio
                )

                if round_number == 2:
                    left_x = (
                        left_inner_start
                    )

                    right_x = (
                        right_inner_start
                    )

                left_x_by_round[
                    round_number
                ] = left_x

                right_x_by_round[
                    round_number
                ] = right_x

        first_round = bracket.get(
            total_rounds,
            [],
        )

        first_left_count = math.ceil(
            len(first_round)
            / 2
        )

        first_right_count = (
            len(first_round)
            - first_left_count
        )

        first_geometry = geometries[
            total_rounds
        ]

        def initial_y_positions(
            count: int,
        ) -> list[int]:
            if count <= 0:
                return []

            if count == 1:
                return [
                    (
                        content_top
                        + content_height // 2
                        - first_geometry.height // 2
                    )
                ]

            available = max(
                0,
                content_height
                - first_geometry.height,
            )

            fitted_step = (
                available
                / (
                    count
                    - 1
                )
            )

            first_gap_method = getattr(
                self.theme,
                "first_round_vertical_gap",
                None,
            )

            preferred = float(
                first_gap_method(
                    player_capacity
                )
                if callable(
                    first_gap_method
                )
                else (
                    first_geometry.height
                    + 8
                )
            )

            step = min(
                fitted_step,
                max(
                    first_geometry.height
                    + 2,
                    preferred,
                ),
            )

            span = (
                step
                * (
                    count
                    - 1
                )
                + first_geometry.height
            )

            start = (
                content_top
                + max(
                    0,
                    int(
                        (
                            content_height
                            - span
                        )
                        / 2
                    ),
                )
            )

            return [
                round(
                    start
                    + index
                    * step
                )
                for index in range(
                    count
                )
            ]

        left_first_y = (
            initial_y_positions(
                first_left_count
            )
        )

        right_first_y = (
            initial_y_positions(
                first_right_count
            )
        )

        positions[
            total_rounds
        ] = [
            *[
                (
                    left_x_by_round[
                        total_rounds
                    ],
                    y,
                    "left",
                )
                for y in left_first_y
            ],
            *[
                (
                    right_x_by_round[
                        total_rounds
                    ],
                    y,
                    "right",
                )
                for y in right_first_y
            ],
        ]

        for round_number in range(
            total_rounds - 1,
            1,
            -1,
        ):
            matches = bracket.get(
                round_number,
                [],
            )

            left_count = math.ceil(
                len(matches)
                / 2
            )

            right_count = (
                len(matches)
                - left_count
            )

            child_geometry = geometries[
                round_number + 1
            ]

            current_geometry = geometries[
                round_number
            ]

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

            left_y = self._parent_y_positions(
                left_children,
                left_count,
                child_geometry.height,
                current_geometry.height,
            )

            right_y = self._parent_y_positions(
                right_children,
                right_count,
                child_geometry.height,
                current_geometry.height,
            )

            positions[
                round_number
            ] = [
                *[
                    (
                        left_x_by_round[
                            round_number
                        ],
                        y,
                        "left",
                    )
                    for y in left_y
                ],
                *[
                    (
                        right_x_by_round[
                            round_number
                        ],
                        y,
                        "right",
                    )
                    for y in right_y
                ],
            ]

        return positions

    @staticmethod
    def _parent_y_positions(
        children: list[Position],
        parent_count: int,
        child_height: int,
        parent_height: int,
    ) -> list[int]:
        """
        Place chaque match parent
        entre ses deux matchs enfants.
        """

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

            first_center = (
                children[
                    first_index
                ][1]
                + child_height // 2
            )

            second_center = (
                children[
                    second_index
                ][1]
                + child_height // 2
            )

            parent_center = (
                first_center
                + second_center
            ) // 2

            result.append(
                parent_center
                - parent_height // 2
            )

        return result
            # ==========================================================
    # FOND ET AMBIANCE
    # ==========================================================

    def _draw_background_effects(
        self,
        image: Image.Image,
        header_height: int,
        footer_height: int,
        tournament_id: Any,
    ) -> None:
        """
        Dessine le dégradé rouge/bleu, les particules
        et le vignettage.
        """

        width, height = image.size

        content_bottom = (
            height
            - footer_height
        )

        center_x = width // 2

        gradient = Image.new(
            "RGBA",
            image.size,
            (
                0,
                0,
                0,
                0,
            ),
        )

        pixels = gradient.load()

        left_background = getattr(
            self.theme,
            "left_background",
            (
                24,
                7,
                10,
            ),
        )

        right_background = getattr(
            self.theme,
            "right_background",
            (
                5,
                19,
                43,
            ),
        )

        center_background = getattr(
            self.theme,
            "background_center",
            self.BG,
        )

        for x in range(
            width
        ):
            normalized = (
                x
                / max(
                    1,
                    width - 1,
                )
            )

            if normalized <= 0.5:
                local = (
                    normalized
                    / 0.5
                )

                color = self._blend_color(
                    left_background,
                    center_background,
                    local,
                )

            else:
                local = (
                    (
                        normalized
                        - 0.5
                    )
                    / 0.5
                )

                color = self._blend_color(
                    center_background,
                    right_background,
                    local,
                )

            edge_strength = (
                abs(
                    normalized
                    - 0.5
                )
                * 2
            )

            alpha = round(
                205
                * (
                    0.55
                    + edge_strength
                    * 0.45
                )
            )

            for y in range(
                header_height,
                content_bottom,
            ):
                pixels[
                    x,
                    y,
                ] = (
                    *color,
                    alpha,
                )

        image.alpha_composite(
            gradient
        )

        glow = Image.new(
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
            glow
        )

        glow_draw.ellipse(
            (
                -width // 3,
                header_height
                - height // 4,
                width // 2,
                height
                + height // 3,
            ),
            fill=(
                *self.RED,
                int(
                    getattr(
                        self.theme,
                        "side_glow_alpha",
                        82,
                    )
                ),
            ),
        )

        glow_draw.ellipse(
            (
                width // 2,
                header_height
                - height // 4,
                width
                + width // 3,
                height
                + height // 3,
            ),
            fill=(
                *self.BLUE,
                int(
                    getattr(
                        self.theme,
                        "side_glow_alpha",
                        82,
                    )
                ),
            ),
        )

        glow = glow.filter(
            ImageFilter.GaussianBlur(
                max(
                    80,
                    width // 10,
                )
            )
        )

        image.alpha_composite(
            glow
        )

        particle_layer = Image.new(
            "RGBA",
            image.size,
            (
                0,
                0,
                0,
                0,
            ),
        )

        particle_draw = ImageDraw.Draw(
            particle_layer
        )

        randomizer = random.Random(
            str(
                tournament_id
            )
        )

        particle_count = int(
            getattr(
                self.theme,
                "particle_count",
                90,
            )
        )

        particle_alpha = int(
            getattr(
                self.theme,
                "particle_alpha",
                48,
            )
        )

        for _ in range(
            particle_count
        ):
            x = randomizer.randrange(
                0,
                width,
            )

            y = randomizer.randrange(
                header_height,
                max(
                    header_height + 1,
                    content_bottom,
                ),
            )

            distance = (
                abs(
                    x
                    - center_x
                )
                / max(
                    1,
                    center_x,
                )
            )

            if (
                randomizer.random()
                > (
                    0.25
                    + distance
                    * 0.6
                )
            ):
                continue

            radius = randomizer.choice(
                (
                    1,
                    1,
                    1,
                    2,
                )
            )

            color = (
                self.RED
                if x < center_x
                else self.BLUE
            )

            alpha = randomizer.randint(
                max(
                    8,
                    particle_alpha // 3,
                ),
                particle_alpha,
            )

            particle_draw.ellipse(
                (
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                ),
                fill=(
                    *color,
                    alpha,
                ),
            )

        image.alpha_composite(
            particle_layer
        )

        vignette = Image.new(
            "L",
            image.size,
            0,
        )

        vignette_pixels = (
            vignette.load()
        )

        vignette_alpha = int(
            getattr(
                self.theme,
                "vignette_alpha",
                92,
            )
        )

        for y in range(
            height
        ):
            vertical = (
                abs(
                    (
                        y
                        / max(
                            1,
                            height - 1,
                        )
                    )
                    - 0.5
                )
                * 2
            )

            for x in range(
                width
            ):
                horizontal = (
                    abs(
                        (
                            x
                            / max(
                                1,
                                width - 1,
                            )
                        )
                        - 0.5
                    )
                    * 2
                )

                strength = max(
                    horizontal,
                    vertical,
                )

                vignette_pixels[
                    x,
                    y,
                ] = round(
                    vignette_alpha
                    * strength ** 2.2
                )

        vignette_layer = Image.new(
            "RGBA",
            image.size,
            (
                0,
                0,
                0,
                0,
            ),
        )

        vignette_layer.putalpha(
            vignette
        )

        image.alpha_composite(
            vignette_layer
        )

    # ==========================================================
    # HEADER
    # ==========================================================

    def _draw_hamster_fallback(
        self,
        canvas: Image.Image,
        center_x: int,
        center_y: int,
        size: int,
    ) -> None:
        """
        Dessine une petite mascotte hamster
        si l'asset est absent.
        """

        layer = Image.new(
            "RGBA",
            canvas.size,
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

        radius = size // 2

        orange = (
            218,
            125,
            57,
        )

        cream = (
            255,
            239,
            208,
        )

        dark = (
            39,
            25,
            22,
        )

        draw.ellipse(
            (
                center_x
                - radius
                + 5,
                center_y
                - radius
                + 6,
                center_x
                + radius
                - 5,
                center_y
                + radius,
            ),
            fill=(
                *cream,
                255,
            ),
            outline=(
                *self.GOLD,
                220,
            ),
            width=max(
                1,
                size // 28,
            ),
        )

        ear = max(
            8,
            size // 5,
        )

        draw.ellipse(
            (
                center_x
                - radius
                + 1,
                center_y
                - radius,
                center_x
                - radius
                + ear
                * 2,
                center_y
                - radius
                + ear
                * 2,
            ),
            fill=(
                *orange,
                255,
            ),
        )

        draw.ellipse(
            (
                center_x
                + radius
                - ear
                * 2,
                center_y
                - radius,
                center_x
                + radius
                - 1,
                center_y
                - radius
                + ear
                * 2,
            ),
            fill=(
                *orange,
                255,
            ),
        )

        draw.pieslice(
            (
                center_x
                - radius
                + 7,
                center_y
                - radius
                + 5,
                center_x
                + radius
                - 7,
                center_y
                + radius
                - 3,
            ),
            190,
            350,
            fill=(
                *orange,
                255,
            ),
        )

        eye_radius = max(
            2,
            size // 24,
        )

        eye_y = (
            center_y
            + size // 20
        )

        for eye_x in (
            center_x
            - size // 7,
            center_x
            + size // 7,
        ):
            draw.ellipse(
                (
                    eye_x
                    - eye_radius,
                    eye_y
                    - eye_radius,
                    eye_x
                    + eye_radius,
                    eye_y
                    + eye_radius,
                ),
                fill=(
                    *dark,
                    255,
                ),
            )

        draw.ellipse(
            (
                center_x - 2,
                eye_y
                + size // 12,
                center_x + 2,
                eye_y
                + size // 12
                + 4,
            ),
            fill=(
                *dark,
                255,
            ),
        )

        canvas.alpha_composite(
            layer
        )

    def _draw_logo_fallback(
        self,
        draw: ImageDraw.ImageDraw,
        center_x: int,
        y: int,
        width: int,
        height: int,
    ) -> None:
        """
        Dessine un emblème Hamtaro lorsqu'aucun
        logo PNG n'est fourni.
        """

        left = (
            center_x
            - width // 2
        )

        right = (
            center_x
            + width // 2
        )

        bottom = (
            y
            + height
        )

        draw.polygon(
            (
                (
                    left + 15,
                    y + 12,
                ),
                (
                    right - 15,
                    y + 12,
                ),
                (
                    right,
                    y
                    + height // 2,
                ),
                (
                    center_x,
                    bottom,
                ),
                (
                    left,
                    y
                    + height // 2,
                ),
            ),
            fill=(
                8,
                11,
                18,
                245,
            ),
            outline=self.RED,
        )

        draw.line(
            (
                left + 8,
                y
                + height // 2,
                center_x,
                bottom - 7,
                right - 8,
                y
                + height // 2,
            ),
            fill=self.GOLD,
            width=2,
        )

        title_font = self._font(
            max(
                16,
                height // 5,
            ),
            bold=True,
        )

        subtitle_font = self._font(
            max(
                8,
                height // 11,
            ),
            bold=True,
        )

        draw.text(
            (
                center_x,
                y
                + height
                * 0.43,
            ),
            "HAMTARO",
            font=title_font,
            fill=self.TEXT,
            anchor="mm",
        )

        draw.text(
            (
                center_x,
                y
                + height
                * 0.66,
            ),
            "TOURNAMENT BOT",
            font=subtitle_font,
            fill=self.RED,
            anchor="mm",
        )

    def _draw_information_card(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        width: int,
        height: int,
        label: str,
        value: str,
        accent: Color | None = None,
    ) -> None:
        radius = int(
            getattr(
                self.theme,
                "header_information_box_radius",
                3,
            )
        )

        border_width = int(
            getattr(
                self.theme,
                "header_information_box_border_width",
                1,
            )
        )

        draw.rounded_rectangle(
            (
                x,
                y,
                x + width,
                y + height,
            ),
            radius=radius,
            fill=(
                *self._blend_color(
                    self.PANEL,
                    self.BG,
                    0.20,
                ),
                235,
            ),
            outline=(
                *self._blend_color(
                    self.LINE,
                    accent
                    or self.TEXT,
                    0.25,
                ),
                255,
            ),
            width=border_width,
        )

        label_font = self._font(
            max(
                9,
                int(
                    getattr(
                        self.theme,
                        "information_font_size",
                        14,
                    )
                )
                - 3,
            )
        )

        value_font = self._font(
            max(
                11,
                int(
                    getattr(
                        self.theme,
                        "information_font_size",
                        14,
                    )
                ),
            ),
            bold=True,
        )

        draw.text(
            (
                x + 14,
                y + 11,
            ),
            label.upper(),
            font=label_font,
            fill=self.MUTED,
        )

        draw.text(
            (
                x + 14,
                y
                + height
                - 13,
            ),
            self._safe_text(
                value,
                23,
            ),
            font=value_font,
            fill=accent
            or self.TEXT,
            anchor="ls",
        )

    def _draw_header(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        tournament: Any,
        player_capacity: int,
    ) -> None:
        """
        Dessine le header complet
        de la maquette Hamtaro Cup.
        """

        width = image.width

        header_height = int(
            getattr(
                self.theme,
                "header_height",
                112,
            )
        )

        draw.rectangle(
            (
                0,
                0,
                width,
                header_height,
            ),
            fill=(
                *getattr(
                    self.theme,
                    "header_background",
                    self.BG,
                ),
                246,
            ),
        )

        mascot_width = int(
            getattr(
                self.theme,
                "header_mascot_width",
                78,
            )
        )

        mascot_height = int(
            getattr(
                self.theme,
                "header_mascot_height",
                94,
            )
        )

        mascot_x = int(
            getattr(
                self.theme,
                "header_mascot_x",
                31,
            )
        )

        mascot_y = int(
            getattr(
                self.theme,
                "header_mascot_y",
                6,
            )
        )

        mascot_path = self._theme_path(
            "header_mascot_path",
            "hamtaro_header.png",
        )

        mascot = self._load_asset(
            mascot_path
        )

        if mascot is not None:
            mascot = self._contain_image(
                mascot,
                mascot_width,
                mascot_height,
            )

            image.alpha_composite(
                mascot,
                (
                    mascot_x,
                    mascot_y,
                ),
            )

            title_x = int(
                getattr(
                    self.theme,
                    "header_title_with_mascot_x",
                    126,
                )
            )

        else:
            self._draw_hamster_fallback(
                image,
                mascot_x
                + mascot_width // 2,
                mascot_y
                + mascot_height // 2,
                min(
                    mascot_width,
                    mascot_height,
                ),
            )

            title_x = int(
                getattr(
                    self.theme,
                    "header_title_with_mascot_x",
                    126,
                )
            )

        title_font = self._font(
            int(
                getattr(
                    self.theme,
                    "title_font_size",
                    42,
                )
            ),
            bold=True,
            italic=True,
        )

        number_font = self._font(
            int(
                getattr(
                    self.theme,
                    "title_number_font_size",
                    42,
                )
            ),
            bold=True,
            italic=True,
        )

        subtitle_font = self._font(
            int(
                getattr(
                    self.theme,
                    "subtitle_font_size",
                    17,
                )
            ),
            bold=True,
        )

        tournament_id = getattr(
            tournament,
            "id",
            "?",
        )

        tournament_name = str(
            getattr(
                tournament,
                "name",
                "HAMTARO CUP",
            )
        ).upper()

        title_y = int(
            getattr(
                self.theme,
                "header_title_y",
                17,
            )
        )

        draw.text(
            (
                title_x,
                title_y,
            ),
            tournament_name,
            font=title_font,
            fill=self.TEXT,
        )

        title_width = self._text_width(
            draw,
            tournament_name,
            title_font,
        )

        draw.text(
            (
                title_x
                + title_width
                + 12,
                title_y,
            ),
            f"#{tournament_id}",
            font=number_font,
            fill=self.RED,
        )

        tournament_format = str(
            getattr(
                tournament,
                "format",
                "FORMAT INCONNU",
            )
        ).upper()

        metadata = (
            f"FORMAT : {tournament_format}   •   "
            f"ÉLIMINATION DIRECTE   •   "
            f"{player_capacity} JOUEURS"
        )

        draw.text(
            (
                title_x,
                int(
                    getattr(
                        self.theme,
                        "header_metadata_y",
                        69,
                    )
                ),
            ),
            metadata,
            font=subtitle_font,
            fill=self.MUTED,
        )

        logo_width = int(
            getattr(
                self.theme,
                "header_logo_maximum_width",
                220,
            )
        )

        logo_height = int(
            getattr(
                self.theme,
                "header_logo_maximum_height",
                106,
            )
        )

        logo_y = int(
            getattr(
                self.theme,
                "header_logo_vertical_offset",
                1,
            )
        )

        logo_path = self._theme_path(
            "logo_path",
            "hamtaro_logo.png",
        )

        logo = self._draw_asset_centered(
            image,
            logo_path,
            width // 2,
            logo_y,
            logo_width,
            logo_height,
        )

        if logo is None:
            self._draw_logo_fallback(
                draw,
                width // 2,
                logo_y + 3,
                logo_width,
                logo_height - 6,
            )

        box_height = int(
            getattr(
                self.theme,
                "header_information_box_height",
                64,
            )
        )

        box_gap = int(
            getattr(
                self.theme,
                "header_information_box_gap",
                6,
            )
        )

        date_width = int(
            getattr(
                self.theme,
                "date_box_width",
                180,
            )
        )

        id_width = int(
            getattr(
                self.theme,
                "tournament_id_box_width",
                145,
            )
        )

        organizer_width = int(
            getattr(
                self.theme,
                "organizer_box_width",
                220,
            )
        )

        total_width = (
            date_width
            + id_width
            + organizer_width
            + box_gap
            * 2
        )

        info_x = (
            width
            - int(
                getattr(
                    self.theme,
                    "horizontal_margin",
                    24,
                )
            )
            - total_width
        )

        info_y = max(
            8,
            (
                header_height
                - box_height
            )
            // 2,
        )

        date_value = str(
            getattr(
                tournament,
                "date",
                None,
            )
            or getattr(
                tournament,
                "start_date",
                None,
            )
            or "DATE À DÉFINIR"
        )

        organizer = str(
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

        self._draw_information_card(
            draw,
            info_x,
            info_y,
            date_width,
            box_height,
            "Date",
            date_value,
        )

        self._draw_information_card(
            draw,
            info_x
            + date_width
            + box_gap,
            info_y,
            id_width,
            box_height,
            "ID du tournoi",
            f"#{tournament_id}",
            self.RED,
        )

        self._draw_information_card(
            draw,
            (
                info_x
                + date_width
                + id_width
                + box_gap
                * 2
            ),
            info_y,
            organizer_width,
            box_height,
            "Organisé par",
            organizer,
        )

        separator_height = int(
            getattr(
                self.theme,
                "header_separator_height",
                3,
            )
        )

        draw.rectangle(
            (
                0,
                header_height
                - separator_height,
                width // 2,
                header_height,
            ),
            fill=self.RED,
        )

        draw.rectangle(
            (
                width // 2,
                header_height
                - separator_height,
                width,
                header_height,
            ),
            fill=self.BLUE,
        )

    # ==========================================================
    # TITRES DES RONDES
    # ==========================================================

    def _draw_round_headers(
        self,
        draw: ImageDraw.ImageDraw,
        positions: dict[
            int,
            list[Position],
        ],
        geometries: dict[
            int,
            RoundGeometry,
        ],
        player_capacity: int,
    ) -> None:
        header_height = int(
            getattr(
                self.theme,
                "header_height",
                112,
            )
        )

        title_y = (
            header_height
            + 12
        )

        underline_y = (
            header_height
            + int(
                getattr(
                    self.theme,
                    "round_labels_height",
                    28,
                )
            )
            - 3
        )

        font = self._font(
            int(
                self.theme.round_font_size_for(
                    player_capacity
                )
            ),
            bold=True,
        )

        underline_width = int(
            getattr(
                self.theme,
                "round_title_underline_width",
                74,
            )
        )

        underline_height = int(
            getattr(
                self.theme,
                "round_title_underline_height",
                2,
            )
        )

        for round_number in sorted(
            positions,
            reverse=True,
        ):
            round_positions = positions[
                round_number
            ]

            if not round_positions:
                continue

            geometry = geometries[
                round_number
            ]

            if round_number == 1:
                x, _, _ = (
                    round_positions[0]
                )

                center_x = (
                    x
                    + geometry.width // 2
                )

                title = self._round_title(
                    round_number
                )

                title_width = int(
                    getattr(
                        self.theme,
                        "final_title_width",
                        136,
                    )
                )

                title_height = int(
                    getattr(
                        self.theme,
                        "final_title_height",
                        34,
                    )
                )

                draw.rounded_rectangle(
                    (
                        center_x
                        - title_width // 2,
                        header_height
                        + 4,
                        center_x
                        + title_width // 2,
                        header_height
                        + 4
                        + title_height,
                    ),
                    radius=int(
                        getattr(
                            self.theme,
                            "final_title_radius",
                            5,
                        )
                    ),
                    fill=getattr(
                        self.theme,
                        "final_title_background",
                        self._blend_color(
                            self.PANEL,
                            self.RED,
                            0.32,
                        ),
                    ),
                    outline=getattr(
                        self.theme,
                        "final_title_border",
                        self.RED,
                    ),
                    width=1,
                )

                draw.text(
                    (
                        center_x,
                        header_height
                        + 4
                        + title_height // 2,
                    ),
                    title,
                    font=self._font(
                        int(
                            getattr(
                                self.theme,
                                "final_title_font_size",
                                22,
                            )
                        ),
                        bold=True,
                    ),
                    fill=self.TEXT,
                    anchor="mm",
                )

                continue

            seen: set[str] = set()

            for (
                x,
                _,
                side,
            ) in round_positions:
                if side in seen:
                    continue

                seen.add(
                    side
                )

                center_x = (
                    x
                    + geometry.width // 2
                )

                color = (
                    self.RED
                    if side == "left"
                    else self.BLUE
                )

                draw.text(
                    (
                        center_x,
                        title_y,
                    ),
                    self._round_title(
                        round_number
                    ),
                    font=font,
                    fill=self.TEXT,
                    anchor="ma",
                )

                draw.rounded_rectangle(
                    (
                        center_x
                        - underline_width // 2,
                        underline_y,
                        center_x
                        + underline_width // 2,
                        underline_y
                        + underline_height,
                    ),
                    radius=max(
                        1,
                        underline_height // 2,
                    ),
                    fill=color,
                )
