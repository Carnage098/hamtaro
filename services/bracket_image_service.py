from __future__ import annotations

import asyncio
import io
import math
import random
from dataclasses import dataclass
from functools import lru_cache
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
    
    Le renderer produit une affiche esport symétrique avec :
    
    - une branche rouge à gauche ;
    - une branche bleue à droite ;
    - les avatars Discord ;
    - une finale centrale ;
    - des illustrations Hamtaro ;
    - des connecteurs lumineux ;
    - un bloc champion ;
    - les statistiques du tournoi.
    
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
    # ÉCHELLE D'AFFICHAGE EFFECTIVE
    # ==========================================================

    @staticmethod
    def _display_scale(canvas_width: int) -> float:
        """Échelle stable pour les textes et éléments d'interface HD."""

        return max(0.90, min(1.25, canvas_width / 2048))

    def _effective_header_height(self, *, canvas_height: int) -> int:
        """Hauteur minimale du header pour qu'il reste lisible en HD."""

        configured = int(getattr(self.theme, "header_height", 124))
        return max(configured, round(canvas_height * 0.15))

    def _effective_footer_height(self, *, canvas_height: int) -> int:
        """Hauteur minimale du footer pour qu'il reste lisible en HD."""

        configured = int(getattr(self.theme, "footer_height", 54))
        return max(configured, round(canvas_height * 0.058))
    
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
        """Raccourcit un texte trop long."""
    
        cleaned = (
            value
            or "A determiner"
        ).strip() or "A determiner"
    
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
        """Ajoute une composante alpha à une couleur RGB."""
    
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
                else "-"
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
    
        return "-"
    
    @staticmethod
    def _round_title(
        round_number: int,
    ) -> str:
        """Retourne l'intitulé affiché au-dessus d'une ronde."""
    
        names = {
            1: "FINALE",
            2: "DEMI-FINALES",
            3: "QUARTS",
            4: "8EMES",
            5: "16EMES",
            6: "32EMES",
            7: "64EMES",
        }
    
        return names.get(
            round_number,
            f"ROUND {round_number}",
        )
    
    @staticmethod
    @lru_cache(maxsize=256)
    def _font(
        size: int,
        bold: bool = False,
        italic: bool = False,
    ) -> ImageFont.ImageFont:
        """
        Charge une police TrueType redimensionnable.

        Railway ne fournit pas toujours les mêmes chemins de polices.
        Les noms génériques sont donc essayés avant les chemins Linux.
        Le dernier fallback conserve la taille demandée avec les versions
        récentes de Pillow, ce qui évite les minuscules textes du rendu.
        """

        size = max(8, int(size))

        if bold and italic:
            filenames = (
                "DejaVuSans-BoldOblique.ttf",
                "LiberationSans-BoldItalic.ttf",
                "FreeSansBoldOblique.ttf",
            )
        elif bold:
            filenames = (
                "DejaVuSans-Bold.ttf",
                "LiberationSans-Bold.ttf",
                "FreeSansBold.ttf",
            )
        elif italic:
            filenames = (
                "DejaVuSans-Oblique.ttf",
                "LiberationSans-Italic.ttf",
                "FreeSansOblique.ttf",
            )
        else:
            filenames = (
                "DejaVuSans.ttf",
                "LiberationSans-Regular.ttf",
                "FreeSans.ttf",
            )

        search_directories = (
            Path("/usr/share/fonts/truetype/dejavu"),
            Path("/usr/share/fonts/truetype/liberation2"),
            Path("/usr/share/fonts/truetype/freefont"),
            Path("/usr/local/share/fonts"),
            Path("/app/fonts"),
        )

        candidates: list[str | Path] = [*filenames]
        candidates.extend(
            directory / filename
            for directory in search_directories
            for filename in filenames
        )

        for candidate in candidates:
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except (OSError, ValueError):
                continue

        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    @staticmethod
    def _text_width(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
    ) -> int:
        """Retourne la largeur réelle d'un texte."""
    
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
        """Retourne la hauteur réelle d'un texte."""
    
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
            or "A determiner"
        ).strip() or "A determiner"
    
        if (
            cls._text_width(
                draw,
                cleaned,
                font,
            )
            <= maximum_width
        ):
            return cleaned
    
        suffix = "..."
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
        """
        Retourne un chemin d'asset.
    
        La méthode reste compatible avec une ancienne version
        de theme.py ne possédant pas encore toutes les propriétés.
        """
    
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
        """Charge et place un asset horizontalement au centre."""
    
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
        """
        Télécharge un avatar Discord.
    
        Un avatar de remplacement est créé lorsque le téléchargement
        échoue ou qu'aucune URL n'est disponible.
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
                            io.BytesIO(
                                raw
                            )
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
        """
        Crée un avatar de remplacement.
    
        L'avatar contient l'initiale du joueur plutôt qu'un simple
        cercle gris ou un nombre.
        """
    
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
            ord(
                character
            )
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
        """
        Transforme un avatar carré en avatar circulaire.
    
        Cette méthode doit être alignée avec les autres méthodes
        de BracketImageService et non placée dans
        _create_fallback_avatar().
        """
    
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
        """Colle un avatar rond avec un véritable contour visible."""
    
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
    
    # ==========================================================
    # LA SUITE REPREND ICI
    # ==========================================================
            
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
                    or "A determiner"
                )
    
                if (
                    not discord_id
                    and name == "A determiner"
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
                or "A determiner"
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
    
        header_height = self._effective_header_height(
            canvas_height=height,
        )

        footer_height = self._effective_footer_height(
            canvas_height=height,
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
        """Dessine un fond esport sombre, rouge à gauche et bleu à droite."""

        width, height = image.size
        content_bottom = height - footer_height
        center_x = width // 2

        left_background = getattr(self.theme, "left_background", (26, 8, 11))
        right_background = getattr(self.theme, "right_background", (5, 19, 43))
        center_background = getattr(self.theme, "background_center", self.BG)

        gradient = Image.new("RGBA", image.size, (0, 0, 0, 0))
        gradient_draw = ImageDraw.Draw(gradient)

        for x in range(width):
            normalized = x / max(1, width - 1)
            if normalized <= 0.5:
                color = self._blend_color(
                    left_background,
                    center_background,
                    normalized / 0.5,
                )
            else:
                color = self._blend_color(
                    center_background,
                    right_background,
                    (normalized - 0.5) / 0.5,
                )

            edge_strength = abs(normalized - 0.5) * 2
            alpha = round(228 * (0.72 + edge_strength * 0.28))
            gradient_draw.line(
                (x, header_height, x, content_bottom),
                fill=(*color, alpha),
                width=1,
            )

        image.alpha_composite(gradient)

        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_alpha = min(42, int(getattr(self.theme, "side_glow_alpha", 42)))
        left_glow = self._blend_color(self.RED, left_background, 0.72)
        right_glow = self._blend_color(self.BLUE, right_background, 0.72)

        glow_draw.ellipse(
            (
                -width // 3,
                header_height - height // 4,
                int(width * 0.46),
                height + height // 3,
            ),
            fill=(*left_glow, glow_alpha),
        )
        glow_draw.ellipse(
            (
                int(width * 0.54),
                header_height - height // 4,
                width + width // 3,
                height + height // 3,
            ),
            fill=(*right_glow, glow_alpha),
        )
        glow = glow.filter(ImageFilter.GaussianBlur(max(70, width // 12)))
        image.alpha_composite(glow)

        particle_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        particle_draw = ImageDraw.Draw(particle_layer)
        randomizer = random.Random(str(tournament_id))
        particle_count = int(getattr(self.theme, "particle_count", 90))
        particle_alpha = int(getattr(self.theme, "particle_alpha", 48))

        for _ in range(particle_count):
            x = randomizer.randrange(0, width)
            y = randomizer.randrange(header_height, max(header_height + 1, content_bottom))
            distance = abs(x - center_x) / max(1, center_x)
            if randomizer.random() > 0.25 + distance * 0.6:
                continue
            radius = randomizer.choice((1, 1, 1, 2))
            color = self.RED if x < center_x else self.BLUE
            alpha = randomizer.randint(max(8, particle_alpha // 3), particle_alpha)
            particle_draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill=(*color, alpha),
            )

        image.alpha_composite(particle_layer)

        vignette_alpha = int(getattr(self.theme, "vignette_alpha", 92))
        vignette_mask = Image.new("L", image.size, 255)
        vignette_draw = ImageDraw.Draw(vignette_mask)
        inset_x = max(80, width // 10)
        inset_y = max(60, height // 10)
        vignette_draw.ellipse(
            (inset_x, inset_y, width - inset_x, height - inset_y),
            fill=0,
        )
        vignette_mask = vignette_mask.filter(
            ImageFilter.GaussianBlur(max(70, width // 16))
        )
        vignette_mask = vignette_mask.point(
            lambda value: round(value * vignette_alpha / 255)
        )
        vignette_layer = Image.new("RGBA", image.size, (0, 0, 0, 255))
        vignette_layer.putalpha(vignette_mask)
        image.alpha_composite(vignette_layer)
    
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
        """Dessine un emblème Hamtaro lisible lorsqu'aucun logo PNG n'existe."""

        left = center_x - width // 2
        right = center_x + width // 2
        bottom = y + height

        draw.polygon(
            (
                (left + 18, y + 10),
                (right - 18, y + 10),
                (right, y + height // 2),
                (center_x, bottom),
                (left, y + height // 2),
            ),
            fill=(8, 11, 18, 248),
            outline=self.RED,
        )
        draw.line(
            (
                left + 10,
                y + height // 2,
                center_x,
                bottom - 8,
                right - 10,
                y + height // 2,
            ),
            fill=self.GOLD,
            width=2,
        )

        title_text = "HAMTARO"
        subtitle_text = "TOURNAMENT BOT"

        # Les deux textes sont ajustés à la largeur intérieure de l'emblème.
        # Cela évite notamment que « TOURNAMENT BOT » dépasse du blason.
        title_size = max(24, height // 4)
        title_font = self._font(title_size, bold=True)
        title_maximum_width = max(80, width - 54)
        while (
            title_size > 16
            and self._text_width(draw, title_text, title_font) > title_maximum_width
        ):
            title_size -= 1
            title_font = self._font(title_size, bold=True)

        subtitle_size = max(11, height // 11)
        subtitle_font = self._font(subtitle_size, bold=True)
        subtitle_maximum_width = max(70, width - 70)
        while (
            subtitle_size > 9
            and self._text_width(draw, subtitle_text, subtitle_font)
            > subtitle_maximum_width
        ):
            subtitle_size -= 1
            subtitle_font = self._font(subtitle_size, bold=True)

        draw.text(
            (center_x, y + height * 0.37),
            title_text,
            font=title_font,
            fill=self.TEXT,
            anchor="mm",
        )
        draw.text(
            (center_x, y + height * 0.61),
            subtitle_text,
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
        """Dessine une carte d'information du header avec texte bien lisible."""

        radius = int(getattr(self.theme, "header_information_box_radius", 5))
        border_width = int(
            getattr(self.theme, "header_information_box_border_width", 1)
        )

        draw.rounded_rectangle(
            (x, y, x + width, y + height),
            radius=radius,
            fill=(*self._blend_color(self.PANEL, self.BG, 0.12), 242),
            outline=(*self._blend_color(self.LINE, accent or self.TEXT, 0.32), 255),
            width=border_width,
        )

        information_size = int(getattr(self.theme, "information_font_size", 20))
        label_font = self._font(max(14, information_size - 5), bold=True)
        value_font = self._font(max(20, information_size + 1), bold=True)
        fitted_value = self._fit_text(
            draw,
            self._safe_text(value, 30),
            value_font,
            max(30, width - 32),
        )

        draw.text(
            (x + 16, y + 14),
            label.upper(),
            font=label_font,
            fill=self.MUTED,
        )
        draw.text(
            (x + 16, y + height - 17),
            fitted_value,
            font=value_font,
            fill=accent or self.TEXT,
            anchor="ls",
        )
    
    def _draw_header(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        tournament: Any,
        player_capacity: int,
    ) -> None:
        """Dessine un header plus spectaculaire avec titres agrandis."""

        width = image.width
        header_height = self._effective_header_height(canvas_height=image.height)
        display_scale = self._display_scale(width)

        draw.rectangle(
            (0, 0, width, header_height),
            fill=(*getattr(self.theme, "header_background", self.BG), 255),
        )

        logo_width = max(
            int(238 * display_scale),
            int(getattr(self.theme, "header_logo_maximum_width", 220)),
        )
        logo_height = min(
            header_height - 16,
            max(
                int(142 * display_scale),
                int(getattr(self.theme, "header_logo_maximum_height", 136)),
            ),
        )
        logo_y = max(
            2,
            int(getattr(self.theme, "header_logo_vertical_offset", 0)),
        )

        configured_mascot_width = int(getattr(self.theme, "header_mascot_width", 100))
        configured_mascot_height = int(getattr(self.theme, "header_mascot_height", 128))
        mascot_width = max(62, round(configured_mascot_width * 0.80 * display_scale))
        mascot_height = max(78, round(configured_mascot_height * 0.80 * display_scale))
        mascot_x = int(getattr(self.theme, "header_mascot_x", 22))
        mascot_y = max(8, (header_height - mascot_height) // 2)

        mascot_path = self._theme_path("header_mascot_path", "hamtaro_header.png")
        mascot = self._load_asset(mascot_path)
        if mascot is not None:
            mascot = self._contain_image(mascot, mascot_width, mascot_height)
            image.alpha_composite(
                mascot,
                (
                    mascot_x + (mascot_width - mascot.width) // 2,
                    mascot_y + (mascot_height - mascot.height) // 2,
                ),
            )
        else:
            self._draw_hamster_fallback(
                image,
                mascot_x + mascot_width // 2,
                mascot_y + mascot_height // 2,
                min(mascot_width, mascot_height),
            )

        title_x = max(
            mascot_x + mascot_width + 18,
            int(getattr(self.theme, "header_title_with_mascot_x", 132)),
        )
        title_size = max(
            int(72 * display_scale),
            int(getattr(self.theme, "title_font_size", 60)),
            72,
        )
        number_size = max(
            int(54 * display_scale),
            int(getattr(self.theme, "title_number_font_size", 46)),
            54,
        )
        subtitle_size = max(
            int(22 * display_scale),
            int(getattr(self.theme, "subtitle_font_size", 20)),
            22,
        )

        title_font = self._font(title_size, bold=True, italic=True)
        number_font = self._font(number_size, bold=True, italic=True)
        subtitle_font = self._font(subtitle_size, bold=True)

        tournament_id = getattr(tournament, "id", "?")
        raw_name = str(getattr(tournament, "name", "HAMTARO CUP")).strip().upper()
        tournament_name = (
            "HAMTARO CUP"
            if raw_name.replace(" ", "") == "HAMTAROCUP"
            else raw_name
        )

        logo_left = width // 2 - logo_width // 2
        available_title_width = max(260, logo_left - title_x - 28)
        number_label = f"#{tournament_id}"
        number_width = self._text_width(draw, number_label, number_font)
        tournament_name = self._fit_text(
            draw,
            tournament_name,
            title_font,
            max(120, available_title_width - number_width - 20),
        )

        title_y = max(10, int(getattr(self.theme, "header_title_y", 14)) - 2)
        draw.text(
            (title_x + 3, title_y + 3),
            tournament_name,
            font=title_font,
            fill=(0, 0, 0, 190),
        )
        draw.text(
            (title_x, title_y),
            tournament_name,
            font=title_font,
            fill=self.TEXT,
        )

        title_width = self._text_width(draw, tournament_name, title_font)
        number_x = title_x + title_width + 12
        draw.text(
            (number_x + 2, title_y + 2),
            number_label,
            font=number_font,
            fill=(0, 0, 0, 180),
        )
        draw.text(
            (number_x, title_y),
            number_label,
            font=number_font,
            fill=self.RED,
        )

        tournament_format = str(getattr(tournament, "format", "FORMAT INCONNU")).upper()
        metadata = (
            f"FORMAT : {tournament_format}   |   "
            f"ELIMINATION DIRECTE   |   {player_capacity} JOUEURS"
        )
        metadata = self._fit_text(draw, metadata, subtitle_font, available_title_width)
        metadata_y = min(
            header_height - subtitle_size - 14,
            max(title_y + title_size + 4, int(getattr(self.theme, "header_metadata_y", 92)) - 4),
        )
        draw.text(
            (title_x, metadata_y),
            metadata,
            font=subtitle_font,
            fill=self.MUTED,
        )

        logo_path = self._theme_path("logo_path", "hamtaro_logo.png")
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
                logo_y + 2,
                logo_width,
                logo_height - 4,
            )

        center_title_font = self._font(
            max(
                int(24 * display_scale),
                int(getattr(self.theme, "center_title_font_size", 24)),
            ),
            bold=True,
            italic=True,
        )
        center_title_y = min(header_height - 18, logo_y + logo_height - 16)
        draw.text(
            (width // 2 + 1, center_title_y + 1),
            "HAMTARO CUP",
            font=center_title_font,
            fill=(0, 0, 0, 170),
            anchor="mm",
        )
        draw.text(
            (width // 2, center_title_y),
            "HAMTARO CUP",
            font=center_title_font,
            fill=self.TEXT,
            anchor="mm",
        )

        box_height = min(
            header_height - 24,
            max(
                int(88 * display_scale),
                int(getattr(self.theme, "header_information_box_height", 88)),
            ),
        )
        box_gap = max(8, int(getattr(self.theme, "header_information_box_gap", 8)))
        date_width = max(
            int(205 * display_scale),
            int(getattr(self.theme, "date_box_width", 205)),
        )
        id_width = max(
            int(165 * display_scale),
            int(getattr(self.theme, "tournament_id_box_width", 165)),
        )
        organizer_width = max(
            int(235 * display_scale),
            int(getattr(self.theme, "organizer_box_width", 235)),
        )
        total_width = date_width + id_width + organizer_width + box_gap * 2
        margin = int(getattr(self.theme, "horizontal_margin", 24))
        info_x = width - margin - total_width
        info_y = max(10, (header_height - box_height) // 2)

        date_value = str(
            getattr(tournament, "date", None)
            or getattr(tournament, "start_date", None)
            or "DATE A DEFINIR"
        )
        organizer = str(
            getattr(tournament, "organizer_name", None)
            or getattr(tournament, "organizer", None)
            or "HAMTARO BOT"
        )

        self._draw_information_card(draw, info_x, info_y, date_width, box_height, "Date", date_value)
        self._draw_information_card(
            draw,
            info_x + date_width + box_gap,
            info_y,
            id_width,
            box_height,
            "ID du tournoi",
            f"#{tournament_id}",
            self.RED,
        )
        self._draw_information_card(
            draw,
            info_x + date_width + id_width + box_gap * 2,
            info_y,
            organizer_width,
            box_height,
            "Organise par",
            organizer,
        )

        separator_height = max(3, int(getattr(self.theme, "header_separator_height", 3)))
        draw.rectangle((0, header_height - separator_height, width // 2, header_height), fill=self.RED)
        draw.rectangle((width // 2, header_height - separator_height, width, header_height), fill=self.BLUE)

    # ==========================================================
    # TITRES DES RONDES
    # ==========================================================
    
    def _draw_round_headers(
        self,
        draw: ImageDraw.ImageDraw,
        positions: dict[int, list[Position]],
        geometries: dict[int, RoundGeometry],
        player_capacity: int,
    ) -> None:
        """Dessine des intitulés de rondes plus grands et mieux détachés."""

        canvas_height = int(self.theme.image_height(player_capacity))
        canvas_width = int(self.theme.image_width(player_capacity))
        display_scale = self._display_scale(canvas_width)
        header_height = self._effective_header_height(canvas_height=canvas_height)
        labels_height = int(getattr(self.theme, "round_labels_height", 48))

        label_center_y = header_height + labels_height // 2 - 1
        underline_y = header_height + labels_height - 6
        font_size = max(
            int(22 * display_scale),
            int(self.theme.round_font_size_for(player_capacity)) + 2,
            int(getattr(self.theme, "round_font_size", 20)) + 2,
        )
        font = self._font(font_size, bold=True)
        underline_width = max(
            int(122 * display_scale),
            int(getattr(self.theme, "round_title_underline_width", 122)),
        )
        underline_height = max(
            4,
            int(getattr(self.theme, "round_title_underline_height", 4)),
        )
        backgrounds_enabled = bool(
            getattr(self.theme, "round_title_background_enabled", True)
        )
        background_radius = int(
            getattr(self.theme, "round_title_background_radius", 4)
        )

        for round_number in sorted(positions, reverse=True):
            round_positions = positions[round_number]
            if not round_positions:
                continue

            geometry = geometries[round_number]

            if round_number == 1:
                x, _, _ = round_positions[0]
                center_x = x + geometry.width // 2
                title = self._round_title(round_number)
                title_width = max(
                    int(176 * display_scale),
                    int(getattr(self.theme, "final_title_width", 176)),
                )
                title_height = max(
                    int(44 * display_scale),
                    int(getattr(self.theme, "final_title_height", 44)),
                )
                title_top = header_height + 4

                draw.rounded_rectangle(
                    (
                        center_x - title_width // 2,
                        title_top,
                        center_x + title_width // 2,
                        title_top + title_height,
                    ),
                    radius=int(getattr(self.theme, "final_title_radius", 5)),
                    fill=getattr(
                        self.theme,
                        "final_title_background",
                        self._blend_color(self.PANEL, self.RED, 0.30),
                    ),
                    outline=self.GOLD,
                    width=2,
                )

                final_font = self._font(
                    max(
                        int(30 * display_scale),
                        int(getattr(self.theme, "final_title_font_size", 30)),
                    ),
                    bold=True,
                )
                draw.text(
                    (center_x, title_top + title_height // 2 - 1),
                    title,
                    font=final_font,
                    fill=self.TEXT,
                    anchor="mm",
                )
                draw.rounded_rectangle(
                    (
                        center_x - title_width // 3,
                        title_top + title_height - 4,
                        center_x + title_width // 3,
                        title_top + title_height,
                    ),
                    radius=2,
                    fill=self.GOLD,
                )
                continue

            seen: set[str] = set()
            for x, _, side in round_positions:
                if side in seen:
                    continue
                seen.add(side)

                center_x = x + geometry.width // 2
                color = self.RED if side == "left" else self.BLUE
                title = self._round_title(round_number)
                text_width = self._text_width(draw, title, font)
                background_width = max(
                    underline_width,
                    min(geometry.width + 28, text_width + 28),
                )
                background_height = max(30, font_size + 12)
                background_top = label_center_y - background_height // 2 - 2

                if backgrounds_enabled:
                    draw.rounded_rectangle(
                        (
                            center_x - background_width // 2,
                            background_top,
                            center_x + background_width // 2,
                            background_top + background_height,
                        ),
                        radius=background_radius,
                        fill=self._blend_color(self.BG, color, 0.13),
                        outline=self._blend_color(self.LINE, color, 0.45),
                        width=1,
                    )

                draw.text(
                    (center_x, label_center_y - 2),
                    title,
                    font=font,
                    fill=self.TEXT,
                    anchor="mm",
                )
                draw.rounded_rectangle(
                    (
                        center_x - underline_width // 2,
                        underline_y,
                        center_x + underline_width // 2,
                        underline_y + underline_height,
                    ),
                    radius=max(1, underline_height // 2),
                    fill=color,
                )

    # ==========================================================
    # CONNECTEURS LUMINEUX
    # ==========================================================
    
    @staticmethod
    def _connector_points(
        source_center: tuple[int, int],
        target_center: tuple[int, int],
        side: str,
    ) -> list[tuple[int, int]]:
        """
        Construit un connecteur à angles droits.
    
        Pour la branche gauche :
        la ligne sort vers la droite.
    
        Pour la branche droite :
        la ligne sort vers la gauche.
        """
    
        source_x, source_y = source_center
        target_x, target_y = target_center
    
        middle_x = (
            source_x
            + target_x
        ) // 2
    
        if side == "left":
            middle_x = max(
                source_x + 5,
                min(
                    target_x - 5,
                    middle_x,
                ),
            )
    
        elif side == "right":
            middle_x = min(
                source_x - 5,
                max(
                    target_x + 5,
                    middle_x,
                ),
            )
    
        return [
            (
                source_x,
                source_y,
            ),
            (
                middle_x,
                source_y,
            ),
            (
                middle_x,
                target_y,
            ),
            (
                target_x,
                target_y,
            ),
        ]
    
    def _draw_glowing_polyline(
        self,
        image: Image.Image,
        points: list[tuple[int, int]],
        color: Color,
        player_capacity: int,
        glow_alpha: int | None = None,
    ) -> None:
        """
        Dessine une ligne en trois couches :
    
        - lueur floutée ;
        - ligne intermédiaire sombre ;
        - ligne principale lumineuse.
        """
    
        if len(points) < 2:
            return
    
        main_width = int(
            self.theme.connector_width(
                player_capacity
            )
        )
    
        middle_method = getattr(
            self.theme,
            "connector_middle_width",
            None,
        )
    
        middle_width = int(
            middle_method(
                player_capacity
            )
            if callable(
                middle_method
            )
            else main_width + 2
        )
    
        glow_width = int(
            self.theme.connector_glow_width(
                player_capacity
            )
        )
    
        if glow_alpha is None:
            glow_alpha = int(
                getattr(
                    self.theme,
                    "connector_glow_alpha",
                    90,
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
    
        glow_draw.line(
            points,
            fill=(
                *color,
                glow_alpha,
            ),
            width=glow_width,
            joint="curve",
        )
    
        glow_layer = glow_layer.filter(
            ImageFilter.GaussianBlur(
                int(
                    getattr(
                        self.theme,
                        "connector_blur_radius",
                        5,
                    )
                )
            )
        )
    
        image.alpha_composite(
            glow_layer
        )
    
        line_layer = Image.new(
            "RGBA",
            image.size,
            (
                0,
                0,
                0,
                0,
            ),
        )
    
        line_draw = ImageDraw.Draw(
            line_layer
        )
    
        dark_color = self._blend_color(
            color,
            self.BG,
            0.58,
        )
    
        line_draw.line(
            points,
            fill=(
                *dark_color,
                245,
            ),
            width=middle_width,
            joint="curve",
        )
    
        line_draw.line(
            points,
            fill=(
                *color,
                255,
            ),
            width=main_width,
            joint="curve",
        )
    
        joint_radius = int(
            getattr(
                self.theme,
                "connector_joint_radius",
                2,
            )
        )
    
        if joint_radius > 0:
            for x, y in points[
                1:-1
            ]:
                line_draw.ellipse(
                    (
                        x - joint_radius,
                        y - joint_radius,
                        x + joint_radius,
                        y + joint_radius,
                    ),
                    fill=(
                        *color,
                        255,
                    ),
                )
    
        image.alpha_composite(
            line_layer
        )
    
    def _draw_connectors(
        self,
        image: Image.Image,
        bracket: dict[int, list[Any]],
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
        """
        Relie les matchs de chaque ronde à la ronde suivante.
    
        Les branches gauches sont rouges.
        Les branches droites sont bleues.
        """
    
        total_rounds = max(
            bracket
        )
    
        for child_round in range(
            total_rounds,
            2,
            -1,
        ):
            parent_round = (
                child_round - 1
            )
    
            child_positions = positions.get(
                child_round,
                [],
            )
    
            parent_positions = positions.get(
                parent_round,
                [],
            )
    
            child_geometry = geometries[
                child_round
            ]
    
            parent_geometry = geometries[
                parent_round
            ]
    
            for side in (
                "left",
                "right",
            ):
                side_children = [
                    position
                    for position in child_positions
                    if position[2]
                    == side
                ]
    
                side_parents = [
                    position
                    for position in parent_positions
                    if position[2]
                    == side
                ]
    
                color = (
                    self.RED
                    if side == "left"
                    else self.BLUE
                )
    
                round_index = (
                    total_rounds
                    - child_round
                )
    
                side_rounds = max(
                    1,
                    total_rounds - 1,
                )
    
                round_glow_method = getattr(
                    self.theme,
                    "round_glow_alpha",
                    None,
                )
    
                glow_alpha = (
                    int(
                        round_glow_method(
                            round_index,
                            side_rounds,
                        )
                    )
                    if callable(
                        round_glow_method
                    )
                    else int(
                        getattr(
                            self.theme,
                            "connector_glow_alpha",
                            90,
                        )
                    )
                )
    
                for parent_index, parent_position in enumerate(
                    side_parents
                ):
                    parent_x, parent_y, _ = (
                        parent_position
                    )
    
                    parent_center_y = (
                        parent_y
                        + parent_geometry.height // 2
                    )
    
                    if side == "left":
                        parent_target_x = (
                            parent_x
                        )
    
                    else:
                        parent_target_x = (
                            parent_x
                            + parent_geometry.width
                        )
    
                    for child_offset in (
                        0,
                        1,
                    ):
                        child_index = (
                            parent_index * 2
                            + child_offset
                        )
    
                        if child_index >= len(
                            side_children
                        ):
                            continue
    
                        child_x, child_y, _ = (
                            side_children[
                                child_index
                            ]
                        )
    
                        child_center_y = (
                            child_y
                            + child_geometry.height // 2
                        )
    
                        if side == "left":
                            child_source_x = (
                                child_x
                                + child_geometry.width
                            )
    
                        else:
                            child_source_x = (
                                child_x
                            )
    
                        points = self._connector_points(
                            (
                                child_source_x,
                                child_center_y,
                            ),
                            (
                                parent_target_x,
                                parent_center_y,
                            ),
                            side,
                        )
    
                        self._draw_glowing_polyline(
                            image,
                            points,
                            color,
                            player_capacity,
                            glow_alpha,
                        )
    
        final_positions = positions.get(
            1,
            [],
        )
    
        semifinal_positions = positions.get(
            2,
            [],
        )
    
        if (
            not final_positions
            or not semifinal_positions
        ):
            return
    
        final_x, final_y, _ = (
            final_positions[0]
        )
    
        final_geometry = geometries[
            1
        ]
    
        final_center_y = (
            final_y
            + final_geometry.height // 2
        )
    
        semifinal_geometry = geometries[
            2
        ]
    
        left_semifinals = [
            position
            for position in semifinal_positions
            if position[2]
            == "left"
        ]
    
        right_semifinals = [
            position
            for position in semifinal_positions
            if position[2]
            == "right"
        ]
    
        if left_semifinals:
            semifinal_x, semifinal_y, _ = (
                left_semifinals[0]
            )
    
            source = (
                semifinal_x
                + semifinal_geometry.width,
                semifinal_y
                + semifinal_geometry.height // 2,
            )
    
            target = (
                final_x,
                final_center_y,
            )
    
            self._draw_glowing_polyline(
                image,
                self._connector_points(
                    source,
                    target,
                    "left",
                ),
                self.RED,
                player_capacity,
                int(
                    getattr(
                        self.theme,
                        "connector_glow_alpha",
                        90,
                    )
                )
                + 20,
            )
    
        if right_semifinals:
            semifinal_x, semifinal_y, _ = (
                right_semifinals[0]
            )
    
            source = (
                semifinal_x,
                semifinal_y
                + semifinal_geometry.height // 2,
            )
    
            target = (
                final_x
                + final_geometry.width,
                final_center_y,
            )
    
            self._draw_glowing_polyline(
                image,
                self._connector_points(
                    source,
                    target,
                    "right",
                ),
                self.BLUE,
                player_capacity,
                int(
                    getattr(
                        self.theme,
                        "connector_glow_alpha",
                        90,
                    )
                )
                + 20,
            )
    
    # ==========================================================
    # OMBRES ET LUEURS DES CARTES
    # ==========================================================
    
    def _draw_card_shadow(
        self,
        image: Image.Image,
        x: int,
        y: int,
        width: int,
        height: int,
        radius: int,
    ) -> None:
        """
        Dessine une ombre légère derrière une carte.
        """
    
        shadow_layer = Image.new(
            "RGBA",
            image.size,
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
    
        offset_x = int(
            getattr(
                self.theme,
                "match_shadow_offset_x",
                getattr(
                    self.theme,
                    "panel_shadow_offset",
                    3,
                ),
            )
        )
    
        offset_y = int(
            getattr(
                self.theme,
                "match_shadow_offset_y",
                getattr(
                    self.theme,
                    "panel_shadow_offset",
                    3,
                ),
            )
        )
    
        alpha = int(
            getattr(
                self.theme,
                "panel_shadow_alpha",
                115,
            )
        )
    
        shadow_draw.rounded_rectangle(
            (
                x + offset_x,
                y + offset_y,
                x + width + offset_x,
                y + height + offset_y,
            ),
            radius=radius,
            fill=(
                0,
                0,
                0,
                alpha,
            ),
        )
    
        blur_radius = int(
            getattr(
                self.theme,
                "match_shadow_blur_radius",
                5,
            )
        )
    
        shadow_layer = shadow_layer.filter(
            ImageFilter.GaussianBlur(
                blur_radius
            )
        )
    
        image.alpha_composite(
            shadow_layer
        )
    
    def _draw_card_glow(
        self,
        image: Image.Image,
        x: int,
        y: int,
        width: int,
        height: int,
        radius: int,
        color: Color,
        alpha: int,
        blur_radius: int,
        glow_width: int = 5,
    ) -> None:
        """
        Dessine une lueur extérieure autour d'une carte.
        """
    
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
    
        glow_draw.rounded_rectangle(
            (
                x - glow_width,
                y - glow_width,
                x + width + glow_width,
                y + height + glow_width,
            ),
            radius=(
                radius
                + glow_width
            ),
            outline=(
                *color,
                alpha,
            ),
            width=max(
                2,
                glow_width,
            ),
        )
    
        glow_layer = glow_layer.filter(
            ImageFilter.GaussianBlur(
                blur_radius
            )
        )
    
        image.alpha_composite(
            glow_layer
        )
    
    # ==========================================================
    # LIGNES DES JOUEURS
    # ==========================================================
    
    def _draw_player_row(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        player: PlayerVisual,
        avatar_map: dict[str, Image.Image],
        x: int,
        y: int,
        width: int,
        height: int,
        side: str,
        geometry: RoundGeometry,
        player_capacity: int,
        final_card: bool = False,
    ) -> None:
        """Dessine une ligne de joueur lisible et moins éblouissante."""

        if side == "left":
            accent = self.RED
        elif side == "right":
            accent = self.BLUE
        else:
            accent = self.GOLD

        seed_width = int(self.theme.seed_column_width(player_capacity))
        score_width = int(self.theme.score_column_width(player_capacity))

        if final_card:
            seed_width = max(32, seed_width + 6)
            score_width = max(44, score_width + 10)

        separator = getattr(self.theme, "separator", self.LINE)
        row_background = (
            self._blend_color(self.PANEL, accent, 0.13)
            if player.winner
            else self._blend_color(self.PANEL, self.BG, 0.05)
        )

        draw.rectangle(
            (x, y, x + width, y + height),
            fill=(*row_background, 250),
        )

        if player.winner:
            indicator_width = max(
                3,
                int(getattr(self.theme, "winner_indicator_width", 3)),
            )
            indicator_x1 = x if side != "right" else x + width - indicator_width
            draw.rectangle(
                (
                    indicator_x1,
                    y,
                    indicator_x1 + indicator_width,
                    y + height,
                ),
                fill=self.GREEN,
            )

        seed_x2 = x + seed_width
        score_x1 = x + width - score_width

        draw.rectangle(
            (x, y, seed_x2, y + height),
            fill=(
                *self._blend_color(self.PANEL_ALT, accent, 0.11),
                255,
            ),
        )

        original_score_background = (
            getattr(
                self.theme,
                "score_winner_background",
                self.theme.score_background,
            )
            if player.winner
            else getattr(
                self.theme,
                "score_loser_background",
                self.theme.score_background,
            )
        )
        score_background = self._blend_color(
            original_score_background,
            self.PANEL,
            0.24 if final_card else 0.36,
        )
        draw.rectangle(
            (score_x1, y, x + width, y + height),
            fill=score_background,
        )

        draw.line((seed_x2, y, seed_x2, y + height), fill=separator, width=1)
        draw.line((score_x1, y, score_x1, y + height), fill=separator, width=1)

        seed_text = str(player.seed) if player.seed is not None else "-"
        seed_font = self._font(geometry.seed_font_size, bold=True)
        draw.text(
            (x + seed_width // 2, y + height // 2),
            seed_text,
            font=seed_font,
            fill=self.TEXT if player.seed is not None else self.MUTED,
            anchor="mm",
        )

        avatar_size = min(
            geometry.avatar_size,
            max(14, height - (6 if not final_card else 8)),
        )
        avatar_x = seed_x2 + int(getattr(self.theme, "avatar_left_padding", 4))
        avatar_y = y + (height - avatar_size) // 2
        avatar_key = self._player_key(player.discord_id, player.name)
        avatar = avatar_map.get(avatar_key) or self._create_fallback_avatar(player.name)
        border_color = self.GREEN if player.winner else accent
        border_width = int(
            getattr(
                self.theme,
                "avatar_winner_border_width" if player.winner else "avatar_border_width",
                2 if player.winner else 1,
            )
        )
        if final_card:
            border_width = max(2, border_width)

        self._paste_avatar(
            image,
            avatar,
            avatar_x,
            avatar_y,
            avatar_size,
            border_color,
            border_width,
        )

        name_font = self._font(geometry.name_font_size, bold=player.winner or final_card)
        name_x = (
            avatar_x
            + avatar_size
            + int(getattr(self.theme, "name_left_padding", 5))
        )
        available_name_width = max(10, score_x1 - name_x - 5)
        display_name = self._fit_text(
            draw,
            player.name,
            name_font,
            available_name_width,
        )
        name_color = (
            self.TEXT
            if player.name != "A determiner"
            else getattr(self.theme, "disabled_text", self.MUTED)
        )
        draw.text(
            (name_x, y + height // 2),
            display_name,
            font=name_font,
            fill=name_color,
            anchor="lm",
        )

        score_font = self._font(geometry.score_font_size, bold=True)
        luminance = (
            score_background[0] * 0.2126
            + score_background[1] * 0.7152
            + score_background[2] * 0.0722
        )
        if luminance >= 138:
            score_color = (
                getattr(self.theme, "score_winner_text", self.theme.score_text)
                if player.winner
                else getattr(self.theme, "score_loser_text", self.theme.score_text)
            )
        else:
            score_color = self.TEXT

        draw.text(
            (score_x1 + score_width // 2, y + height // 2),
            player.score,
            font=score_font,
            fill=score_color,
            anchor="mm",
        )

    # ==========================================================
    # CARTES DES MATCHS
    # ==========================================================
    
    def _draw_match_card(
        self,
        image: Image.Image,
        match: Any,
        avatar_map: dict[str, Image.Image],
        avatar_urls: dict[str, str] | None,
        seed_map: dict[str, int],
        x: int,
        y: int,
        side: str,
        geometry: RoundGeometry,
        player_capacity: int,
        round_number: int,
        total_rounds: int,
        final_card: bool = False,
    ) -> None:
        """Dessine une carte de match, avec une finale centrale renforcée."""

        if side == "left":
            accent = self.RED
        elif side == "right":
            accent = self.BLUE
        else:
            accent = self.GOLD

        radius = int(
            getattr(
                self.theme,
                "final_box_radius"
                if final_card
                else (
                    "compact_box_radius"
                    if player_capacity >= 32
                    else "normal_box_radius"
                ),
                8 if final_card else 4,
            )
        )
        border_width = int(
            getattr(
                self.theme,
                "final_box_border_width"
                if final_card
                else (
                    "compact_box_border_width"
                    if player_capacity >= 32
                    else "normal_box_border_width"
                ),
                3 if final_card else 2,
            )
        )
        if final_card:
            border_width = max(3, border_width)

        opacity_method = getattr(self.theme, "round_card_opacity", None)
        round_index = total_rounds - round_number
        side_round_count = max(1, total_rounds - 1)
        card_opacity = (
            int(opacity_method(round_index, side_round_count))
            if callable(opacity_method)
            else 255
        )
        if final_card:
            card_opacity = 255

        self._draw_card_shadow(
            image,
            x,
            y,
            geometry.width,
            geometry.height,
            radius,
        )

        if final_card:
            self._draw_card_glow(
                image,
                x,
                y,
                geometry.width,
                geometry.height,
                radius,
                self.GOLD,
                min(
                    230,
                    int(getattr(self.theme, "final_glow_alpha", 110)) + 35,
                ),
                int(getattr(self.theme, "final_glow_radius", 14)) + 2,
                glow_width=9,
            )

        card_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        card_draw = ImageDraw.Draw(card_layer)
        card_background = (
            self._blend_color(self.PANEL, self.GOLD, 0.055)
            if final_card
            else self.PANEL
        )
        card_draw.rounded_rectangle(
            (x, y, x + geometry.width, y + geometry.height),
            radius=radius,
            fill=(*card_background, card_opacity),
            outline=(*accent, 255),
            width=border_width,
        )
        image.alpha_composite(card_layer)

        draw = ImageDraw.Draw(image)

        if final_card:
            # Les deux couleurs des branches restent visibles autour de la finale.
            split_x = x + geometry.width // 2
            draw.line(
                (x + radius, y + 2, split_x, y + 2),
                fill=self.RED,
                width=3,
            )
            draw.line(
                (split_x, y + 2, x + geometry.width - radius, y + 2),
                fill=self.BLUE,
                width=3,
            )
            draw.line(
                (x + 2, y + radius, x + 2, y + geometry.height - radius),
                fill=self.RED,
                width=3,
            )
            draw.line(
                (
                    x + geometry.width - 2,
                    y + radius,
                    x + geometry.width - 2,
                    y + geometry.height - radius,
                ),
                fill=self.BLUE,
                width=3,
            )

        player1, player2 = self._match_players(match, avatar_urls, seed_map)
        row_height = geometry.height // 2

        self._draw_player_row(
            image,
            draw,
            player1,
            avatar_map,
            x + border_width,
            y + border_width,
            geometry.width - border_width * 2,
            row_height - border_width,
            side,
            geometry,
            player_capacity,
            final_card,
        )

        second_y = y + row_height
        self._draw_player_row(
            image,
            draw,
            player2,
            avatar_map,
            x + border_width,
            second_y,
            geometry.width - border_width * 2,
            geometry.height - row_height - border_width,
            side,
            geometry,
            player_capacity,
            final_card,
        )

        separator_width = max(
            1,
            int(getattr(self.theme, "player_row_separator_width", 1)),
        )
        draw.line(
            (
                x + border_width,
                second_y,
                x + geometry.width - border_width,
                second_y,
            ),
            fill=self.GOLD if final_card else getattr(self.theme, "separator", self.LINE),
            width=2 if final_card else separator_width,
        )

        status = self._status_value(getattr(match, "status", ""))
        if not final_card and status in {"pending", "waiting_validation", "reported"}:
            pending_color = getattr(
                self.theme,
                "pending_orange",
                (247, 158, 48),
            )
            radius_status = max(2, geometry.height // 18)
            draw.ellipse(
                (
                    x + geometry.width - radius_status * 2 - 4,
                    y + 4,
                    x + geometry.width - 4,
                    y + radius_status * 2 + 4,
                ),
                fill=pending_color,
            )

    def _draw_all_match_cards(
        self,
        image: Image.Image,
        bracket: dict[int, list[Any]],
        positions: dict[
            int,
            list[Position],
        ],
        geometries: dict[
            int,
            RoundGeometry,
        ],
        avatar_map: dict[str, Image.Image],
        avatar_urls: dict[str, str] | None,
        seed_map: dict[str, int],
        player_capacity: int,
    ) -> None:
        """
        Dessine toutes les cartes latérales et la finale.
        """
    
        total_rounds = max(
            bracket
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
    
            round_positions = positions.get(
                round_number,
                [],
            )
    
            geometry = geometries[
                round_number
            ]
    
            for index, match in enumerate(
                matches
            ):
                if index >= len(
                    round_positions
                ):
                    break
    
                x, y, side = (
                    round_positions[
                        index
                    ]
                )
    
                self._draw_match_card(
                    image,
                    match,
                    avatar_map,
                    avatar_urls,
                    seed_map,
                    x,
                    y,
                    side,
                    geometry,
                    player_capacity,
                    round_number,
                    total_rounds,
                )
    
        final_matches = bracket.get(
            1,
            [],
        )
    
        final_positions = positions.get(
            1,
            [],
        )
    
        if (
            final_matches
            and final_positions
        ):
            final_x, final_y, _ = (
                final_positions[0]
            )
    
            self._draw_match_card(
                image,
                final_matches[0],
                avatar_map,
                avatar_urls,
                seed_map,
                final_x,
                final_y,
                "center",
                geometries[1],
                player_capacity,
                1,
                total_rounds,
                final_card=True,
            )
                # ==========================================================
    # HALO DE LA FINALE
    # ==========================================================
    
    def _draw_final_focus(
        self,
        image: Image.Image,
        position: Position,
        geometry: RoundGeometry,
    ) -> None:
        """
        Ajoute un halo doré autour de la carte de finale.
        """
    
        x, y, _ = position
    
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
    
        draw.rounded_rectangle(
            (
                x - 14,
                y - 14,
                x
                + geometry.width
                + 14,
                y
                + geometry.height
                + 14,
            ),
            radius=18,
            outline=(
                *self.GOLD,
                int(
                    getattr(
                        self.theme,
                        "final_glow_alpha",
                        100,
                    )
                ),
            ),
            width=10,
        )
    
        layer = layer.filter(
            ImageFilter.GaussianBlur(
                int(
                    getattr(
                        self.theme,
                        "final_glow_radius",
                        10,
                    )
                )
            )
        )
    
        image.alpha_composite(
            layer
        )
    
    # ==========================================================
    # CHAMPION
    # ==========================================================
    
    def _draw_trophy_fallback(
        self,
        draw: ImageDraw.ImageDraw,
        center_x: int,
        y: int,
        width: int,
        height: int,
    ) -> None:
        """
        Dessine un trophée doré lorsque trophy.png est absent.
        """
    
        cup_top = (
            y
            + height // 8
        )
    
        cup_bottom = (
            y
            + height // 2
        )
    
        draw.rounded_rectangle(
            (
                center_x
                - width // 4,
                cup_top,
                center_x
                + width // 4,
                cup_bottom,
            ),
            radius=max(
                2,
                width // 12,
            ),
            fill=self.GOLD,
        )
    
        draw.arc(
            (
                center_x
                - width // 2,
                cup_top,
                center_x
                - width // 8,
                cup_bottom
                + height // 6,
            ),
            70,
            290,
            fill=self.GOLD,
            width=max(
                2,
                width // 12,
            ),
        )
    
        draw.arc(
            (
                center_x
                + width // 8,
                cup_top,
                center_x
                + width // 2,
                cup_bottom
                + height // 6,
            ),
            250,
            110,
            fill=self.GOLD,
            width=max(
                2,
                width // 12,
            ),
        )
    
        stem_y = cup_bottom
    
        draw.rectangle(
            (
                center_x
                - width // 18,
                stem_y,
                center_x
                + width // 18,
                y
                + height
                * 3
                // 4,
            ),
            fill=self.GOLD,
        )
    
        draw.rounded_rectangle(
            (
                center_x
                - width // 4,
                y
                + height
                * 3
                // 4,
                center_x
                + width // 4,
                y
                + height
                * 7
                // 8,
            ),
            radius=3,
            fill=self.GOLD,
        )
    
    def _draw_laurel_fallback(
        self,
        draw: ImageDraw.ImageDraw,
        center_x: int,
        center_y: int,
        width: int,
        height: int,
    ) -> None:
        """
        Dessine des lauriers lorsque champion_laurel.png
        est absent.
        """
    
        for direction in (
            -1,
            1,
        ):
            base_x = (
                center_x
                + direction
                * width
                // 2
            )
    
            draw.arc(
                (
                    center_x
                    - width // 2,
                    center_y
                    - height // 2,
                    center_x
                    + width // 2,
                    center_y
                    + height // 2,
                ),
                (
                    115
                    if direction == -1
                    else 245
                ),
                (
                    245
                    if direction == -1
                    else 115
                ),
                fill=self.GOLD,
                width=2,
            )
    
            for index in range(
                7
            ):
                ratio = (
                    index + 1
                ) / 8
    
                leaf_y = (
                    center_y
                    + height // 2
                    - int(
                        height
                        * ratio
                    )
                )
    
                curve = int(
                    (
                        ratio
                        - 0.5
                    )
                    ** 2
                    * width
                    * 0.8
                )
    
                leaf_x = (
                    base_x
                    - direction
                    * (
                        width // 5
                        + curve
                    )
                )
    
                leaf_width = max(
                    5,
                    width // 15,
                )
    
                leaf_height = max(
                    9,
                    height // 12,
                )
    
                draw.ellipse(
                    (
                        leaf_x
                        - leaf_width // 2,
                        leaf_y
                        - leaf_height // 2,
                        leaf_x
                        + leaf_width // 2,
                        leaf_y
                        + leaf_height // 2,
                    ),
                    fill=self.GOLD,
                )
    
    def _champion_deck(
        self,
        final_match: Any,
        champion_id: Any,
        champion_name: str,
    ) -> str:
        """
        Cherche le deck du champion dans la finale.
        """
    
        for slot in (
            1,
            2,
        ):
            player_id = getattr(
                final_match,
                f"player{slot}_id",
                None,
            )
    
            player_name = getattr(
                final_match,
                f"player{slot}_name",
                None,
            )
    
            same_id = (
                champion_id
                not in (
                    None,
                    "",
                )
                and player_id
                not in (
                    None,
                    "",
                )
                and str(
                    champion_id
                )
                == str(
                    player_id
                )
            )
    
            same_name = (
                champion_name
                and player_name
                == champion_name
            )
    
            if (
                same_id
                or same_name
            ):
                return str(
                    getattr(
                        final_match,
                        f"player{slot}_deck",
                        None,
                    )
                    or "NON RENSEIGNE"
                )
    
        return "NON RENSEIGNE"
    
    def _draw_champion_card(
        self,
        image: Image.Image,
        tournament: Any,
        final_match: Any,
        final_position: Position,
        final_geometry: RoundGeometry,
        avatars: dict[str, Image.Image],
        seed_map: dict[str, int],
    ) -> tuple[int, int, int, int] | None:
        """
        Dessine la carte du champion.

        Le grand gagnant apparaît avec son avatar Discord en visuel principal,
        les lauriers au-dessus et Hamtaro placé à côté de lui avec un trophée.
        Une seconde carte plus compacte met également en avant le finaliste
        battu à la deuxième place.
        """

        champion_name = getattr(final_match, "winner_name", None)
        champion_id = getattr(final_match, "winner_id", None)
        if not champion_name:
            return None

        def draw_colored_trophy(
            target_draw: ImageDraw.ImageDraw,
            center_x: int,
            y: int,
            width: int,
            height: int,
            color: Color,
        ) -> None:
            cup_top = y + height // 8
            cup_bottom = y + height // 2
            stroke = max(2, width // 12)
            target_draw.rounded_rectangle(
                (
                    center_x - width // 4,
                    cup_top,
                    center_x + width // 4,
                    cup_bottom,
                ),
                radius=max(2, width // 12),
                fill=color,
            )
            target_draw.arc(
                (
                    center_x - width // 2,
                    cup_top,
                    center_x - width // 8,
                    cup_bottom + height // 6,
                ),
                70,
                290,
                fill=color,
                width=stroke,
            )
            target_draw.arc(
                (
                    center_x + width // 8,
                    cup_top,
                    center_x + width // 2,
                    cup_bottom + height // 6,
                ),
                250,
                110,
                fill=color,
                width=stroke,
            )
            target_draw.rectangle(
                (
                    center_x - width // 18,
                    cup_bottom,
                    center_x + width // 18,
                    y + height * 3 // 4,
                ),
                fill=color,
            )
            target_draw.rounded_rectangle(
                (
                    center_x - width // 4,
                    y + height * 3 // 4,
                    center_x + width // 4,
                    y + height * 7 // 8,
                ),
                radius=3,
                fill=color,
            )

        card_width = max(356, int(getattr(self.theme, "champion_card_width", 370)))
        card_height = max(430, int(getattr(self.theme, "champion_card_height", 440)))
        card_x = image.width // 2 - card_width // 2
        card_y = final_position[1] + final_geometry.height + 18

        footer_top = image.height - self._effective_footer_height(canvas_height=image.height)
        maximum_bottom = footer_top - int(getattr(self.theme, "statistics_card_height", 104)) - 26
        if card_y + card_height > maximum_bottom:
            card_height = max(355, maximum_bottom - card_y)

        glow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)
        glow_draw.rounded_rectangle(
            (card_x - 7, card_y - 7, card_x + card_width + 7, card_y + card_height + 7),
            radius=int(getattr(self.theme, "champion_card_radius", 8)) + 10,
            outline=(*self.GOLD, int(getattr(self.theme, "champion_glow_alpha", 105))),
            width=12,
        )
        glow_layer = glow_layer.filter(
            ImageFilter.GaussianBlur(int(getattr(self.theme, "champion_glow_radius", 22)))
        )
        image.alpha_composite(glow_layer)

        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (card_x, card_y, card_x + card_width, card_y + card_height),
            radius=int(getattr(self.theme, "champion_card_radius", 8)),
            fill=getattr(
                self.theme,
                "champion_card_background",
                self._blend_color(self.PANEL, self.BG, 0.25),
            ),
            outline=self.GOLD,
            width=int(getattr(self.theme, "champion_card_border_width", 2)),
        )

        center_x = image.width // 2
        draw.line((card_x + 12, card_y + 3, center_x, card_y + 3), fill=self.RED, width=3)
        draw.line((center_x, card_y + 3, card_x + card_width - 12, card_y + 3), fill=self.BLUE, width=3)

        trophy_width = int(getattr(self.theme, "champion_trophy_width", 82))
        trophy_height = int(getattr(self.theme, "champion_trophy_height", 82))
        trophy_y = card_y + 8
        trophy_path = self._theme_path("trophy_path", "trophy.png")
        trophy = self._draw_asset_centered(image, trophy_path, center_x, trophy_y, trophy_width, trophy_height)
        if trophy is None:
            self._draw_trophy_fallback(draw, center_x, trophy_y, trophy_width, trophy_height)

        champion_title_size = int(getattr(self.theme, "champion_title_font_size", 38))
        title_font = self._font(champion_title_size, bold=True, italic=True)
        title_y = trophy_y + trophy_height + 2
        draw.text((center_x, title_y), "CHAMPION", font=title_font, fill=self.GOLD, anchor="ma")

        avatar_size = min(
            max(110, int(getattr(self.theme, "champion_avatar_size", 126))),
            140,
        )
        mascot_size = max(
            66,
            min(
                int(getattr(self.theme, "champion_mascot_size", 82)),
                avatar_size - 24,
            ),
        )
        visual_gap = int(getattr(self.theme, "champion_visual_gap", 18))
        visual_group_width = avatar_size + mascot_size + visual_gap
        avatar_top = title_y + max(34, int(champion_title_size * 0.82))
        avatar_left = center_x - visual_group_width // 2
        mascot_left = avatar_left + avatar_size + visual_gap
        mascot_top = avatar_top + max(10, avatar_size - mascot_size - 8)
        avatar_center_y = avatar_top + avatar_size // 2

        laurel_width = min(int(getattr(self.theme, "champion_laurel_width", 212)), card_width - 50)
        laurel_height = int(getattr(self.theme, "champion_laurel_height", 164))
        laurel_path = self._theme_path("champion_laurel_path", "champion_laurel.png")
        avatar_center_x = avatar_left + avatar_size // 2
        laurel = self._draw_asset_centered(
            image,
            laurel_path,
            avatar_center_x,
            avatar_center_y - laurel_height // 2,
            laurel_width,
            laurel_height,
        )
        if laurel is None:
            self._draw_laurel_fallback(draw, avatar_center_x, avatar_center_y, laurel_width, laurel_height)

        champion_key = self._player_key(champion_id, champion_name)
        champion_avatar = avatars.get(champion_key)
        if champion_avatar is None:
            champion_avatar = self._create_fallback_avatar(champion_name)
        self._paste_avatar(
            image,
            champion_avatar,
            avatar_left,
            avatar_top,
            avatar_size,
            self._blend_color(self.GOLD, self.TEXT, 0.15),
            4,
        )

        champion_path = self._theme_path("champion_path", "champion_hamtaro.png")
        mascot = self._draw_asset_centered(
            image,
            champion_path,
            mascot_left + mascot_size // 2,
            mascot_top,
            mascot_size,
            mascot_size,
        )
        if mascot is None:
            self._draw_hamster_fallback(
                image,
                mascot_left + mascot_size // 2,
                mascot_top + mascot_size // 2,
                mascot_size,
            )

        handoff_trophy_width = max(
            28,
            int(getattr(self.theme, "champion_handoff_trophy_width", 36)),
        )
        handoff_trophy_height = max(
            28,
            int(getattr(self.theme, "champion_handoff_trophy_height", 36)),
        )
        handoff_center_x = avatar_left + avatar_size + visual_gap // 2 + 6
        handoff_y = avatar_top + avatar_size // 2 - handoff_trophy_height // 2 - 2
        handoff_color = self._blend_color(self.GOLD, self.TEXT, 0.12)
        draw_colored_trophy(
            draw,
            handoff_center_x,
            handoff_y,
            handoff_trophy_width,
            handoff_trophy_height,
            handoff_color,
        )

        name_plate_width = min(card_width - 34, int(getattr(self.theme, "champion_name_plate_width", 220)) + 20)
        name_plate_height = int(getattr(self.theme, "champion_name_plate_height", 43))
        name_plate_y = avatar_top + avatar_size + 18
        draw.rounded_rectangle(
            (
                center_x - name_plate_width // 2,
                name_plate_y,
                center_x + name_plate_width // 2,
                name_plate_y + name_plate_height,
            ),
            radius=int(getattr(self.theme, "champion_name_plate_radius", 4)),
            fill=self._blend_color(self.RED, self.BG, 0.28),
            outline=self.RED,
            width=2,
        )

        name_font = self._font(int(getattr(self.theme, "champion_name_font_size", 32)), bold=True, italic=True)
        fitted_name = self._fit_text(draw, champion_name, name_font, name_plate_width - 18)
        draw.text(
            (center_x, name_plate_y + name_plate_height // 2),
            fitted_name,
            font=name_font,
            fill=self.TEXT,
            anchor="mm",
        )

        # Bandeau dédié au deck du champion, placé immédiatement sous son nom.
        # Le nom du deck est ainsi visible avant les informations de la 2e place.
        champion_seed = seed_map.get(champion_key)
        deck = self._champion_deck(final_match, champion_id, champion_name)
        deck_plate_width = min(
            card_width - 30,
            int(getattr(self.theme, "champion_deck_plate_width", 310)),
        )
        deck_plate_height = int(
            getattr(self.theme, "champion_deck_plate_height", 38)
        )
        deck_plate_x = center_x - deck_plate_width // 2
        deck_plate_y = name_plate_y + name_plate_height + 8
        seed_badge_width = min(
            int(getattr(self.theme, "champion_seed_badge_width", 70)),
            deck_plate_width // 3,
        )
        draw.rounded_rectangle(
            (
                deck_plate_x,
                deck_plate_y,
                deck_plate_x + deck_plate_width,
                deck_plate_y + deck_plate_height,
            ),
            radius=int(getattr(self.theme, "champion_deck_plate_radius", 7)),
            fill=getattr(
                self.theme,
                "champion_deck_plate_background",
                self._blend_color(self.GOLD, self.BG, 0.86),
            ),
            outline=getattr(
                self.theme,
                "champion_deck_plate_border",
                self.GOLD,
            ),
            width=2,
        )
        draw.line(
            (
                deck_plate_x + deck_plate_width - seed_badge_width,
                deck_plate_y + 5,
                deck_plate_x + deck_plate_width - seed_badge_width,
                deck_plate_y + deck_plate_height - 5,
            ),
            fill=self._blend_color(self.GOLD, self.BG, 0.45),
            width=1,
        )
        deck_font = self._font(
            int(getattr(self.theme, "champion_deck_font_size", 18)),
            bold=True,
        )
        deck_label = f"DECK DU CHAMPION | {str(deck).upper()}"
        fitted_deck = self._fit_text(
            draw,
            deck_label,
            deck_font,
            deck_plate_width - seed_badge_width - 22,
        )
        draw.text(
            (
                deck_plate_x + 12,
                deck_plate_y + deck_plate_height // 2,
            ),
            fitted_deck,
            font=deck_font,
            fill=getattr(
                self.theme,
                "champion_deck_label_color",
                self.theme.champion_gold_light,
            ),
            anchor="lm",
        )
        seed_font = self._font(max(14, int(getattr(self.theme, "champion_information_font_size", 16))), bold=True)
        draw.text(
            (
                deck_plate_x + deck_plate_width - seed_badge_width // 2,
                deck_plate_y + deck_plate_height // 2,
            ),
            f"#{champion_seed or '?'}",
            font=seed_font,
            fill=self.TEXT,
            anchor="mm",
        )

        runner_slot = 2
        first_name = getattr(final_match, "player1_name", None)
        second_name = getattr(final_match, "player2_name", None)
        first_id = getattr(final_match, "player1_id", None)
        second_id = getattr(final_match, "player2_id", None)
        if (
            (champion_id not in (None, "") and str(first_id) == str(champion_id))
            or (champion_name and first_name == champion_name)
        ):
            runner_slot = 2
        else:
            runner_slot = 1

        runner_name = getattr(final_match, f"player{runner_slot}_name", None) or "Finaliste"
        runner_id = getattr(final_match, f"player{runner_slot}_id", None)
        runner_key = self._player_key(runner_id, runner_name)
        runner_seed = seed_map.get(runner_key)
        runner_deck = (
            getattr(final_match, f"player{runner_slot}_deck", None)
            or "NON RENSEIGNE"
        )
        runner_avatar = avatars.get(runner_key)
        if runner_avatar is None:
            runner_avatar = self._create_fallback_avatar(runner_name)

        runner_card_y = deck_plate_y + deck_plate_height + 10
        runner_card_height = int(getattr(self.theme, "runner_up_card_height", 62))
        runner_card_width = min(
            card_width - 26,
            int(getattr(self.theme, "runner_up_card_width", 310)),
        )
        runner_card_x = center_x - runner_card_width // 2
        platinum = getattr(self.theme, "runner_up_platinum", (184, 218, 255))
        draw.rounded_rectangle(
            (
                runner_card_x,
                runner_card_y,
                runner_card_x + runner_card_width,
                runner_card_y + runner_card_height,
            ),
            radius=int(getattr(self.theme, "runner_up_card_radius", 8)),
            fill=getattr(
                self.theme,
                "runner_up_background",
                self._blend_color(self.BLUE, self.BG, 0.42),
            ),
            outline=platinum,
            width=2,
        )
        self._paste_avatar(
            image,
            runner_avatar,
            runner_card_x + 10,
            runner_card_y + (runner_card_height - int(getattr(self.theme, "runner_up_avatar_size", 36))) // 2,
            int(getattr(self.theme, "runner_up_avatar_size", 36)),
            platinum,
            2,
        )
        draw_colored_trophy(
            draw,
            runner_card_x + runner_card_width - 30,
            runner_card_y + 11,
            int(getattr(self.theme, "runner_up_trophy_width", 26)),
            int(getattr(self.theme, "runner_up_trophy_height", 26)),
            platinum,
        )
        runner_title_font = self._font(
            int(getattr(self.theme, "runner_up_title_font_size", 15)),
            bold=True,
            italic=True,
        )
        runner_name_font = self._font(
            int(getattr(self.theme, "runner_up_name_font_size", 18)),
            bold=True,
        )
        runner_info_font = self._font(
            int(getattr(self.theme, "runner_up_information_font_size", 13)),
            bold=True,
        )
        draw.text(
            (runner_card_x + 54, runner_card_y + 9),
            "2E PLACE",
            font=runner_title_font,
            fill=platinum,
        )
        fitted_runner_name = self._fit_text(draw, runner_name, runner_name_font, runner_card_width - 120)
        draw.text(
            (runner_card_x + 54, runner_card_y + 27),
            fitted_runner_name,
            font=runner_name_font,
            fill=self.TEXT,
        )
        runner_info = self._fit_text(
            draw,
            f"DECK | {str(runner_deck).upper()}   |   SEED #{runner_seed or '?'}",
            runner_info_font,
            runner_card_width - 120,
        )
        draw.text(
            (runner_card_x + 54, runner_card_y + 44),
            runner_info,
            font=runner_info_font,
            fill=self.MUTED,
        )

        particle_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        particle_draw = ImageDraw.Draw(particle_layer)
        randomizer = random.Random(f"champion:{champion_name}")
        particle_count = int(getattr(self.theme, "champion_particle_count", 26))
        for _ in range(particle_count):
            px = randomizer.randint(card_x + 14, card_x + card_width - 14)
            py = randomizer.randint(title_y + 16, card_y + card_height - 14)
            if avatar_left - 16 <= px <= mascot_left + mascot_size + 10 and avatar_top - 12 <= py <= avatar_top + avatar_size + 14:
                continue
            radius = randomizer.choice((1, 1, 2))
            particle_draw.ellipse(
                (px - radius, py - radius, px + radius, py + radius),
                fill=(*self.GOLD, randomizer.randint(90, 210)),
            )
        image.alpha_composite(particle_layer)

        return (card_x, card_y, card_x + card_width, card_y + card_height)


    # ==========================================================
    # STATISTIQUES
    # ==========================================================
    
    def _statistics_values(
        self,
        tournament: Any,
        bracket: dict[int, list[Any]],
        player_capacity: int,
        final_mode: bool,
    ) -> tuple[
        tuple[str, str],
        ...,
    ]:
        """
        Prépare les quatre valeurs de la carte des statistiques.
        """
    
        all_matches = [
            match
            for matches in bracket.values()
            for match in matches
        ]
    
        completed_statuses = {
            "completed",
            "finished",
            "validated",
            "approved",
            "reported",
        }
    
        played = sum(
            1
            for match in all_matches
            if self._status_value(
                getattr(
                    match,
                    "status",
                    "",
                )
            )
            in completed_statuses
        )
    
        if (
            final_mode
            and played
            < len(
                all_matches
            )
        ):
            played = len(
                all_matches
            )
    
        duration = str(
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
            or "-"
        ).upper()
    
        return (
            (
                str(
                    player_capacity
                ),
                "JOUEURS",
            ),
            (
                str(
                    played
                ),
                "MATCHS JOUES",
            ),
            (
                duration,
                "DUREE TOTALE",
            ),
            (
                str(
                    max(
                        bracket
                    )
                ),
                "ROUNDS",
            ),
        )
    
    def _draw_stat_icon(
        self,
        draw: ImageDraw.ImageDraw,
        center_x: int,
        center_y: int,
        index: int,
        size: int,
    ) -> None:
        """
        Dessine les petites icônes des statistiques sans utiliser
        de police emoji.
        """
    
        color = self.TEXT
        half = size // 2
    
        if index == 0:
            draw.ellipse(
                (
                    center_x
                    - half // 2,
                    center_y
                    - half,
                    center_x
                    + half // 2,
                    center_y,
                ),
                outline=color,
                width=2,
            )
    
            draw.arc(
                (
                    center_x
                    - half,
                    center_y - 2,
                    center_x
                    + half,
                    center_y
                    + half,
                ),
                180,
                360,
                fill=color,
                width=2,
            )
    
        elif index == 1:
            draw.polygon(
                (
                    (
                        center_x,
                        center_y
                        - half,
                    ),
                    (
                        center_x
                        + half,
                        center_y
                        - half // 4,
                    ),
                    (
                        center_x
                        + half // 2,
                        center_y
                        + half,
                    ),
                    (
                        center_x
                        - half // 2,
                        center_y
                        + half,
                    ),
                    (
                        center_x
                        - half,
                        center_y
                        - half // 4,
                    ),
                ),
                outline=color,
            )
    
            draw.line(
                (
                    center_x,
                    center_y
                    - half,
                    center_x,
                    center_y
                    + half,
                ),
                fill=color,
                width=2,
            )
    
        elif index == 2:
            draw.ellipse(
                (
                    center_x
                    - half,
                    center_y
                    - half,
                    center_x
                    + half,
                    center_y
                    + half,
                ),
                outline=color,
                width=2,
            )
    
            draw.line(
                (
                    center_x,
                    center_y,
                    center_x,
                    center_y
                    - half
                    + 3,
                ),
                fill=color,
                width=2,
            )
    
            draw.line(
                (
                    center_x,
                    center_y,
                    center_x
                    + half
                    - 3,
                    center_y,
                ),
                fill=color,
                width=2,
            )
    
        else:
            draw.rounded_rectangle(
                (
                    center_x
                    - half,
                    center_y
                    - half,
                    center_x
                    + half,
                    center_y
                    + half,
                ),
                radius=3,
                outline=color,
                width=2,
            )
    
            draw.ellipse(
                (
                    center_x - 2,
                    center_y - 2,
                    center_x + 2,
                    center_y + 2,
                ),
                fill=color,
            )
    
    def _draw_statistics(
        self,
        image: Image.Image,
        tournament: Any,
        bracket: dict[int, list[Any]],
        player_capacity: int,
        final_mode: bool,
        champion_bounds: tuple[
            int,
            int,
            int,
            int,
        ]
        | None,
    ) -> None:
        """
        Dessine la carte des statistiques sous le champion.
        """
    
        draw = ImageDraw.Draw(
            image
        )
    
        width = int(
            getattr(
                self.theme,
                "statistics_card_width",
                420,
            )
        )
    
        height = int(
            getattr(
                self.theme,
                "statistics_card_height",
                104,
            )
        )
    
        footer_top = (
            image.height
            - int(
                getattr(
                    self.theme,
                    "footer_height",
                    54,
                )
            )
        )
    
        x = (
            image.width // 2
            - width // 2
        )
    
        preferred_y = (
            champion_bounds[3]
            + 14
            if champion_bounds
            is not None
            else footer_top
            - height
            - 18
        )
    
        y = min(
            preferred_y,
            footer_top
            - height
            - 12,
        )
    
        draw.rounded_rectangle(
            (
                x,
                y,
                x + width,
                y + height,
            ),
            radius=int(
                getattr(
                    self.theme,
                    "statistics_card_radius",
                    5,
                )
            ),
            fill=getattr(
                self.theme,
                "statistics_background",
                self._blend_color(
                    self.PANEL,
                    self.BG,
                    0.25,
                ),
            ),
            outline=self.BLUE,
            width=int(
                getattr(
                    self.theme,
                    "statistics_card_border_width",
                    1,
                )
            ),
        )
    
        title_font = self._font(
            int(
                getattr(
                    self.theme,
                    "statistics_title_font_size",
                    14,
                )
            ),
            bold=True,
        )
    
        draw.text(
            (
                image.width // 2,
                y + 12,
            ),
            "STATISTIQUES DU TOURNOI",
            font=title_font,
            fill=getattr(
                self.theme,
                "statistics_title_color",
                self.RED,
            ),
            anchor="ma",
        )
    
        values = self._statistics_values(
            tournament,
            bracket,
            player_capacity,
            final_mode,
        )
    
        column_width = (
            width / 4
        )
    
        icon_size = int(
            getattr(
                self.theme,
                "statistics_icon_size",
                17,
            )
        )
    
        value_font = self._font(
            int(
                getattr(
                    self.theme,
                    "statistics_value_font_size",
                    19,
                )
            ),
            bold=True,
        )
    
        label_font = self._font(
            int(
                getattr(
                    self.theme,
                    "statistics_label_font_size",
                    11,
                )
            )
        )
    
        for (
            index,
            (
                value,
                label,
            ),
        ) in enumerate(
            values
        ):
            center_x = round(
                x
                + column_width
                * (
                    index
                    + 0.5
                )
            )
    
            if index > 0:
                separator_x = round(
                    x
                    + column_width
                    * index
                )
    
                draw.line(
                    (
                        separator_x,
                        y + 40,
                        separator_x,
                        y
                        + height
                        - 10,
                    ),
                    fill=getattr(
                        self.theme,
                        "separator",
                        self.LINE,
                    ),
                    width=int(
                        getattr(
                            self.theme,
                            "statistics_separator_width",
                            1,
                        )
                    ),
                )
    
            self._draw_stat_icon(
                draw,
                center_x,
                y + 48,
                index,
                icon_size,
            )
    
            draw.text(
                (
                    center_x,
                    y + 66,
                ),
                value,
                font=value_font,
                fill=self.TEXT,
                anchor="ma",
            )
    
            draw.text(
                (
                    center_x,
                    y
                    + height
                    - 8,
                ),
                label,
                font=label_font,
                fill=self.MUTED,
                anchor="ms",
            )
                # ==========================================================
    # FOOTER
    # ==========================================================
    
    def _draw_discord_fallback(
        self,
        draw: ImageDraw.ImageDraw,
        center_x: int,
        center_y: int,
        size: int,
    ) -> None:
        """
        Dessine une icône Discord simplifiée lorsque
        discord_logo.png est absent.
        """
    
        draw.ellipse(
            (
                center_x - size // 2,
                center_y - size // 2,
                center_x + size // 2,
                center_y + size // 2,
            ),
            fill=self.BLUE,
        )
    
        font = self._font(
            max(
                10,
                size // 2,
            ),
            bold=True,
        )
    
        draw.text(
            (
                center_x,
                center_y,
            ),
            "D",
            font=font,
            fill=self.TEXT,
            anchor="mm",
        )
    
    def _draw_footer(
        self,
        image: Image.Image,
        final_mode: bool,
    ) -> None:
        """Dessine le footer avec le nom du serveur et l'avatar du bot."""

        draw = ImageDraw.Draw(image)
        footer_height = self._effective_footer_height(canvas_height=image.height)
        display_scale = self._display_scale(image.width)
        footer_y = image.height - footer_height
        padding = int(getattr(self.theme, "footer_horizontal_padding", 26))

        draw.rectangle(
            (0, footer_y, image.width, image.height),
            fill=(*getattr(self.theme, "footer_background", self.BG), 255),
        )
        separator_height = max(2, int(getattr(self.theme, "footer_top_separator_height", 2)))
        draw.rectangle((0, footer_y, image.width // 2, footer_y + separator_height), fill=self.RED)
        draw.rectangle((image.width // 2, footer_y, image.width, footer_y + separator_height), fill=self.BLUE)

        icon_size = max(int(38 * display_scale), int(getattr(self.theme, "footer_icon_size", 38)))
        icon_path = self._theme_path("footer_icon_path", "hamtaro_footer.png")
        icon = self._load_asset(icon_path)
        if icon is not None:
            icon = self._contain_image(icon, icon_size, icon_size)
            image.alpha_composite(icon, (padding, footer_y + (footer_height - icon.height) // 2))
        else:
            self._draw_hamster_fallback(
                image,
                padding + icon_size // 2,
                footer_y + footer_height // 2,
                icon_size,
            )

        draw = ImageDraw.Draw(image)
        normal_font = self._font(
            max(int(16 * display_scale), int(getattr(self.theme, "footer_information_font_size", 16)))
        )
        emphasis_font = self._font(
            max(int(18 * display_scale), int(getattr(self.theme, "footer_title_font_size", 18))),
            bold=True,
            italic=True,
        )
        server_font = self._font(
            max(
                int(22 * display_scale),
                int(getattr(self.theme, "footer_server_name_font_size", 23)),
            ),
            bold=True,
            italic=True,
        )
        baseline = footer_y + footer_height // 2
        left_x = padding + icon_size + 12
        # Labels statiques en ASCII pour eviter les caracteres carres
        # sur les environnements Railway qui chargent une police de secours.
        prefix = "ORGANISE AVEC"
        draw.text((left_x, baseline), prefix, font=normal_font, fill=self.MUTED, anchor="lm")
        prefix_width = self._text_width(draw, prefix, normal_font)
        draw.text(
            (left_x + prefix_width + 14, baseline),
            "HAMTARO TOURNAMENT BOT",
            font=emphasis_font,
            fill=self.RED,
            anchor="lm",
        )

        center_text = (
            str(getattr(self.theme, "footer_center_text", "MERCI A TOUS LES PARTICIPANTS !"))
            if final_mode
            else "RESULTATS ACTUALISES APRES VALIDATION DU STAFF"
        )
        center_font = self._font(
            max(int(18 * display_scale), int(getattr(self.theme, "footer_center_font_size", 18))),
            bold=True,
            italic=True,
        )
        draw.text((image.width // 2, baseline), center_text, font=center_font, fill=self.MUTED, anchor="mm")

        bot_avatar_size = max(
            int(50 * display_scale),
            int(getattr(self.theme, "footer_bot_avatar_size", 54)),
        )
        bot_avatar_x = image.width - padding - bot_avatar_size
        bot_avatar_y = footer_y + (footer_height - bot_avatar_size) // 2
        server_name = str(getattr(self.theme, "server_name", "FONT ROW")).upper()
        bot_avatar_path = self._theme_path("bot_avatar_path", "hamtaro_bot_avatar.png")
        bot_avatar = self._load_asset(bot_avatar_path)
        if bot_avatar is None:
            bot_avatar = self._load_asset(
                self._theme_path("footer_icon_path", "hamtaro_footer.png")
            )
        if bot_avatar is not None:
            self._paste_avatar(
                image,
                bot_avatar,
                bot_avatar_x,
                bot_avatar_y,
                bot_avatar_size,
                self.BLUE,
                int(getattr(self.theme, "footer_bot_avatar_border_width", 3)),
            )
        else:
            self._draw_hamster_fallback(
                image,
                bot_avatar_x + bot_avatar_size // 2,
                bot_avatar_y + bot_avatar_size // 2,
                bot_avatar_size,
            )
        draw = ImageDraw.Draw(image)
        draw.text(
            (bot_avatar_x - 16, baseline),
            server_name,
            font=server_font,
            fill=self.TEXT,
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
        """
        Génère l'image PNG complète du bracket.
    
        final_mode=False :
            affiche l'état actuel du tournoi.
    
        final_mode=True :
            affiche la version finale avec le champion,
            les statistiques et les décorations dorées.
        """
    
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
    
        validate = getattr(
            self.theme,
            "validate_player_capacity",
            None,
        )
    
        if callable(
            validate
        ):
            validate(
                player_capacity
            )
    
        elif (
            player_capacity
            not in self.SUPPORTED_PLAYER_CAPACITIES
        ):
            raise ValueError(
                "Le moteur graphique prend uniquement "
                "en charge les brackets de 2, 4, 8, 16, "
                "32, 64 ou 128 joueurs."
            )
    
        width = int(
            self.theme.image_width(
                player_capacity
            )
        )
    
        height = int(
            self.theme.image_height(
                player_capacity
            )
        )
    
        header_height = self._effective_header_height(
            canvas_height=height,
        )

        footer_height = self._effective_footer_height(
            canvas_height=height,
        )
    
        # ------------------------------------------------------
        # Calcul du placement
        # ------------------------------------------------------
    
        geometries = self._all_geometries(
            player_capacity,
            total_rounds,
        )
    
        positions = self._layout(
            bracket,
            player_capacity,
            width,
            height,
            geometries,
            final_mode,
        )
    
        # ------------------------------------------------------
        # Création du canvas
        # ------------------------------------------------------
    
        image = Image.new(
            "RGBA",
            (
                width,
                height,
            ),
            (
                *self.BG,
                255,
            ),
        )
    
        self._draw_optional_background(
            image
        )
    
        self._draw_background_effects(
            image,
            header_height,
            footer_height,
            getattr(
                tournament,
                "id",
                "?",
            ),
        )
    
        # ------------------------------------------------------
        # Header et titres des rondes
        # ------------------------------------------------------
    
        draw = ImageDraw.Draw(
            image
        )
    
        self._draw_header(
            image,
            draw,
            tournament,
            player_capacity,
        )
    
        self._draw_round_headers(
            draw,
            positions,
            geometries,
            player_capacity,
        )
    
        # ------------------------------------------------------
        # Halo de la finale
        # ------------------------------------------------------
    
        if positions.get(
            1
        ):
            self._draw_final_focus(
                image,
                positions[1][0],
                geometries[1],
            )
    
        # ------------------------------------------------------
        # Connecteurs
        # ------------------------------------------------------
    
        self._draw_connectors(
            image,
            bracket,
            positions,
            geometries,
            player_capacity,
        )
    
        # ------------------------------------------------------
        # Chargement des avatars
        # ------------------------------------------------------
    
        all_matches = [
            match
            for matches in bracket.values()
            for match in matches
        ]
    
        avatar_map = await self._resolve_avatar_map(
            all_matches,
            avatar_urls,
        )
    
        seed_map = self._build_seed_map(
            bracket
        )
    
        # ------------------------------------------------------
        # Cartes des matchs
        # ------------------------------------------------------
    
        self._draw_all_match_cards(
            image,
            bracket,
            positions,
            geometries,
            avatar_map,
            avatar_urls,
            seed_map,
            player_capacity,
        )
    
        # ------------------------------------------------------
        # Champion et statistiques
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
    
        champion_bounds: tuple[
            int,
            int,
            int,
            int,
        ] | None = None
    
        if (
            final_mode
            and final_match is not None
            and positions.get(
                1
            )
            and getattr(
                final_match,
                "winner_name",
                None,
            )
        ):
            champion_bounds = self._draw_champion_card(
                image,
                tournament,
                final_match,
                positions[1][0],
                geometries[1],
                avatar_map,
                seed_map,
            )
    
            self._draw_statistics(
                image,
                tournament,
                bracket,
                player_capacity,
                final_mode,
                champion_bounds,
            )
    
        # ------------------------------------------------------
        # Footer
        # ------------------------------------------------------
    
        self._draw_footer(
            image,
            final_mode,
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
    
        output.seek(
            0
        )
    
        return output
