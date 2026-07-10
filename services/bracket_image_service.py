from __future__ import annotations

import asyncio
import io
import math
from dataclasses import dataclass
from typing import Any

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps
from graphics.theme import HamtaroBracketTheme
from pathlib import Path

@dataclass(slots=True)
class PlayerVisual:
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

    - /bracket
    - /final_bracket

    Le moteur est indépendant des commandes Discord.
    Il reçoit un tournoi, des matchs et les URLs des avatars,
    puis retourne une image PNG stockée en mémoire.
    """

    BG = (10, 13, 22)
    PANEL = (23, 28, 43)
    PANEL_ALT = (30, 36, 55)

    TEXT = (245, 247, 252)
    MUTED = (157, 165, 184)

    RED = (224, 67, 75)
    BLUE = (76, 145, 255)
    GOLD = (245, 196, 70)
    GREEN = (73, 197, 126)

    LINE = (87, 96, 120)

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
    # OUTILS GÉNÉRAUX
    # ==========================================================

    @staticmethod
    def _status_value(
        status: Any,
    ) -> str:
        """
        Retourne la valeur texte d'un statut.

        Compatible avec :
        - Enum ;
        - chaîne de caractères ;
        - valeur inconnue.
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
        Raccourcit un texte trop long afin qu'il reste lisible
        dans les cases du bracket.
        """

        value = (
            value
            or "À déterminer"
        ).strip()

        if len(value) <= maximum:
            return value

        return value[: maximum - 1] + "…"

    @staticmethod
    def _score_for(
        match: Any,
        slot: int,
    ) -> str:
        """
        Retourne le score à afficher pour un joueur.

        slot :
        - 1 pour le joueur 1 ;
        - 2 pour le joueur 2.
        """

        if getattr(
            match,
            "is_bye",
            False,
        ):

            player_id = getattr(
                match,
                f"player{slot}_id",
                None,
            )

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

            value = getattr(
                match,
                f"player{slot}_score",
                None,
            )

            if value is not None:
                return str(value)

        return "—"

    @staticmethod
    def _round_title(
        round_number: int,
    ) -> str:
        """
        Retourne le nom graphique d'un round.
        """

        names = {
            1: "FINALE",
            2: "DEMI-FINALE",
            3: "QUARTS",
            4: "HUITIÈMES",
            5: "SEIZIÈMES",
            6: "32ES",
            7: "64ES",
        }

        return names.get(
            round_number,
            f"ROUND {round_number}",
        )

    @staticmethod
    def _font(
        size: int,
        bold: bool = False,
    ) -> ImageFont.FreeTypeFont:
        """
        Charge une police disponible sur Railway/Linux.

        Le moteur essaie plusieurs polices afin d'éviter
        une erreur si une police n'est pas installée.
        """

        candidates = (
            (
                "/usr/share/fonts/truetype/dejavu/"
                "DejaVuSans-Bold.ttf"
            )
            if bold
            else (
                "/usr/share/fonts/truetype/dejavu/"
                "DejaVuSans.ttf"
            ),
            (
                "/usr/share/fonts/truetype/liberation2/"
                "LiberationSans-Bold.ttf"
            )
            if bold
            else (
                "/usr/share/fonts/truetype/liberation2/"
                "LiberationSans-Regular.ttf"
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

    # ==========================================================
    # AVATARS
    # ==========================================================

    async def _download_avatar(
        self,
        url: str | None,
        key: str,
    ) -> Image.Image:
        """
        Télécharge un avatar Discord.

        Si l'avatar n'est pas disponible, génère un avatar
        de remplacement contenant l'initiale du joueur.
        """

        if key in self._avatar_cache:

            return self._avatar_cache[
                key
            ].copy()

        image: Image.Image | None = None

        if url:

            try:

                timeout = aiohttp.ClientTimeout(
                    total=8
                )

                async with aiohttp.ClientSession(
                    timeout=timeout
                ) as session:

                    async with session.get(
                        url
                    ) as response:

                        if response.status == 200:

                            raw = await response.read()

                            image = Image.open(
                                io.BytesIO(raw)
                            ).convert("RGBA")

            except Exception:

                image = None

        if image is None:

            image = Image.new(
                "RGBA",
                (128, 128),
                (54, 62, 86, 255),
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

            initial = (
                key[:1]
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
                    / 2,
                    (
                        128
                        - text_height
                    )
                    / 2
                    - 6,
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

        image = ImageOps.fit(
            image,
            (128, 128),
            method=Image.Resampling.LANCZOS,
        )

        self._avatar_cache[
            key
        ] = image.copy()

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

        ImageDraw.Draw(
            mask
        ).ellipse(
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
        Prépare tous les avatars nécessaires au bracket.

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

                    identities[
                        str(discord_id)
                    ] = supplied.get(
                        str(discord_id)
                    )

                elif name:

                    identities[
                        f"name:{name}"
                    ] = None

        tasks = [
            self._download_avatar(
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
    # DONNÉES VISUELLES D'UN MATCH
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
        Transforme les deux joueurs d'un match en objets
        directement utilisables par le moteur graphique.
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
    # DESSIN D'UNE CASE DE MATCH
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
        side_color: tuple[
            int,
            int,
            int,
        ],
        avatars: dict[
            str,
            Image.Image,
        ],
        avatar_urls: dict[
            str,
            str,
        ] | None,
        compact: bool,
    ) -> None:
        """
        Dessine une case contenant les deux joueurs du match.
        """

        radius = 14

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
            height
            // 2
        )

        draw.line(
            (
                x + 8,
                y + row_height,
                x + width - 8,
                y + row_height,
            ),
            fill=self.LINE,
            width=2,
        )

        players = self._match_players(
            match,
            avatar_urls,
        )

        avatar_size = (
            34
            if compact
            else 42
        )

        name_font = self._font(
            20
            if compact
            else 24,
            bold=True,
        )

        score_font = self._font(
            22
            if compact
            else 28,
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

                canvas.alpha_composite(
                    circle,
                    (
                        x + 12,
                        row_y
                        + (
                            row_height
                            - avatar_size
                        )
                        // 2,
                    ),
                )

            name_color = (
                self.TEXT
                if player.winner
                else self.MUTED
            )

            if (
                not player.discord_id
                and player.name
                == "À déterminer"
            ):

                name_color = (
                    self.MUTED
                )

            name = self._safe_text(
                player.name,
                15
                if compact
                else 20,
            )

            name_x = (
                x + 58
                if compact
                else x + 66
            )

            draw.text(
                (
                    name_x,
                    row_y + 12,
                ),
                name,
                font=name_font,
                fill=name_color,
            )

            score_bbox = draw.textbbox(
                (0, 0),
                player.score,
                font=score_font,
            )

            score_width = (
                score_bbox[2]
                - score_bbox[0]
            )

            draw.text(
                (
                    x
                    + width
                    - 16
                    - score_width,
                    row_y + 10,
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

                draw.rectangle(
                    (
                        x + 2,
                        row_y + 4,
                        x + 7,
                        row_y
                        + row_height
                        - 4,
                    ),
                    fill=self.GREEN,
                )

    # ==========================================================
    # CALCUL DU PLACEMENT DES MATCHS
    # ==========================================================

    def _layout(
        self,
        bracket: dict[
            int,
            list[Any],
        ],
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
                tuple[
                    int,
                    int,
                    str,
                ]
            ],
        ],
        int,
    ]:
        """
        Calcule la position de chaque match.

        Les premiers matchs sont répartis sur deux côtés :

        - moitié gauche ;
        - moitié droite.

        Les deux arbres convergent ensuite vers la finale centrale.
        """

        total_rounds = max(
            bracket
        )

        first_round_count = len(
            bracket[
                total_rounds
            ]
        )

        per_side = max(
            1,
            math.ceil(
                first_round_count
                / 2
            ),
        )

        gap_y = max(
            118,
            box_height + 28,
        )

        content_height = max(
            900,
            per_side
            * gap_y
            + 180,
        )

        center_y = (
            header_height
            + content_height
            // 2
        )

        positions: dict[
            int,
            list[
                tuple[
                    int,
                    int,
                    str,
                ]
            ],
        ] = {}

        available_half = (
            width
            // 2
            - margin_x
            - 230
        )

        column_gap = max(
            box_width + 100,
            available_half
            // max(
                1,
                total_rounds - 1,
            ),
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
                len(matches)
                / 2
            )

            left_matches = matches[
                :left_count
            ]

            right_matches = matches[
                left_count:
            ]

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

            if (
                round_number
                == total_rounds
            ):

                left_y_positions = [
                    header_height
                    + 90
                    + index
                    * gap_y
                    for index in range(
                        len(left_matches)
                    )
                ]

                right_y_positions = [
                    header_height
                    + 90
                    + index
                    * gap_y
                    for index in range(
                        len(right_matches)
                    )
                ]

            else:

                child_positions = positions[
                    round_number + 1
                ]

                left_children = [
                    position
                    for position
                    in child_positions
                    if position[2]
                    == "left"
                ]

                right_children = [
                    position
                    for position
                    in child_positions
                    if position[2]
                    == "right"
                ]

                if (
                    left_matches
                    and left_children
                ):

                    left_y_positions = [
                        int(
                            (
                                left_children[
                                    index * 2
                                ][1]
                                + left_children[
                                    min(
                                        index
                                        * 2
                                        + 1,
                                        len(
                                            left_children
                                        )
                                        - 1,
                                    )
                                ][1]
                            )
                            / 2
                        )
                        for index in range(
                            len(left_matches)
                        )
                    ]

                else:

                    left_y_positions = []

                if (
                    right_matches
                    and right_children
                ):

                    right_y_positions = [
                        int(
                            (
                                right_children[
                                    index * 2
                                ][1]
                                + right_children[
                                    min(
                                        index
                                        * 2
                                        + 1,
                                        len(
                                            right_children
                                        )
                                        - 1,
                                    )
                                ][1]
                            )
                            / 2
                        )
                        for index in range(
                            len(right_matches)
                        )
                    ]

                else:

                    right_y_positions = []

            positions[
                round_number
            ] = (
                [
                    (
                        left_x,
                        y,
                        "left",
                    )
                    for y
                    in left_y_positions
                ]
                + [
                    (
                        right_x,
                        y,
                        "right",
                    )
                    for y
                    in right_y_positions
                ]
            )

        final_x = (
            width
            // 2
            - box_width
            // 2
        )

        positions[1] = [
            (
                final_x,
                center_y
                - box_height
                // 2,
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

    # ==========================================================
    # LIGNES ENTRE LES MATCHS
    # ==========================================================

    def _draw_connectors(
        self,
        draw: ImageDraw.ImageDraw,
        bracket: dict[
            int,
            list[Any],
        ],
        positions: dict[
            int,
            list[
                tuple[
                    int,
                    int,
                    str,
                ]
            ],
        ],
        box_width: int,
        box_height: int,
    ) -> None:
        """
        Dessine les lignes reliant chaque match au tour suivant.
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

            for index, (
                x,
                y,
                side,
            ) in enumerate(
                current_positions
            ):

                same_side_next = [
                    position
                    for position
                    in next_positions
                    if position[2]
                    == side
                ]

                if (
                    round_number - 1
                    == 1
                ):

                    target = (
                        next_positions[0]
                    )

                elif same_side_next:

                    target = same_side_next[
                        min(
                            index
                            // 2,
                            len(
                                same_side_next
                            )
                            - 1,
                        )
                    ]

                else:

                    continue

                target_x, target_y, _ = target

                start_y = (
                    y
                    + box_height
                    // 2
                )

                end_y = (
                    target_y
                    + box_height
                    // 2
                )

                if side == "left":

                    start_x = (
                        x
                        + box_width
                    )

                    end_x = (
                        target_x
                    )

                    middle_x = (
                        start_x
                        + end_x
                    ) // 2

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

                draw.line(
                    (
                        start_x,
                        start_y,
                        middle_x,
                        start_y,
                    ),
                    fill=self.LINE,
                    width=4,
                )

                draw.line(
                    (
                        middle_x,
                        start_y,
                        middle_x,
                        end_y,
                    ),
                    fill=self.LINE,
                    width=4,
                )

                draw.line(
                    (
                        middle_x,
                        end_y,
                        end_x,
                        end_y,
                    ),
                    fill=self.LINE,
                    width=4,
                )

    # ==========================================================
    # GÉNÉRATION DE L'IMAGE COMPLÈTE
    # ==========================================================

    async def render(
        self,
        tournament: Any,
        bracket: dict[
            int,
            list[Any],
        ],
        *,
        avatar_urls: dict[
            str,
            str,
        ] | None = None,
        final_mode: bool = False,
    ) -> io.BytesIO:
        """
        Génère le PNG complet.

        final_mode=False :
            bracket actif.

        final_mode=True :
            bracket final avec carte du champion.
        """

        if not bracket:

            raise ValueError(
                "Aucun bracket n'a été généré pour ce tournoi."
            )

        total_rounds = max(
            bracket
        )

        first_round_matches = len(
            bracket[
                total_rounds
            ]
        )

        player_capacity = (
            first_round_matches
            * 2
        )

        if player_capacity > 128:

            raise ValueError(
                "Le renderer prend en charge jusqu'à 128 joueurs."
            )

        width_by_size = {
            2: 2600,
            4: 3200,
            8: 4300,
            16: 5900,
            32: 7600,
            64: 9800,
            128: 12000,
        }

        width = width_by_size.get(
            player_capacity,
            min(
                12000,
                3000
                + total_rounds
                * 1400,
            ),
        )

        header_height = 300
        footer_height = 230

        box_width = (
            320
            if player_capacity >= 64
            else 360
        )

        box_height = (
            94
            if player_capacity >= 64
            else 106
        )

        margin_x = 110

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

        draw = ImageDraw.Draw(
            image
        )

        # ------------------------------------------------------
        # Fond graphique
        # ------------------------------------------------------

        for y in range(
            header_height,
            height - footer_height,
            90,
        ):

            alpha = (
                18
                if (
                    y
                    // 90
                )
                % 2
                == 0
                else 8
            )

            draw.rectangle(
                (
                    0,
                    y,
                    width,
                    y + 45,
                ),
                fill=(
                    255,
                    255,
                    255,
                    alpha,
                ),
            )

        title_font = self._font(
            64,
            bold=True,
        )

        subtitle_font = self._font(
            30,
            bold=True,
        )

        small_font = self._font(
            23
        )

        phase_font = self._font(
            24,
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
            "Inconnu",
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
                14,
                17,
                28,
                255,
            ),
        )

        draw.text(
            (
                90,
                52,
            ),
            "🐹 HAMTARO",
            font=title_font,
            fill=self.TEXT,
        )

        draw.text(
            (
                90,
                135,
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

        info = (
            f"Tournoi #{tournament_id}"
            f"  •  {tournament_format}"
            f"  •  Élimination directe"
            f"  •  {player_capacity} joueurs"
        )

        draw.text(
            (
                width // 2,
                155,
            ),
            info,
            font=small_font,
            fill=self.MUTED,
            anchor="ma",
        )

        draw.text(
            (
                width - 100,
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

            if round_number == 1:

                x, _, _ = (
                    round_positions[0]
                )

                draw.text(
                    (
                        x
                        + box_width
                        // 2,
                        header_height
                        + 18,
                    ),
                    self._round_title(
                        round_number
                    ),
                    font=phase_font,
                    fill=self.GOLD,
                    anchor="ma",
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

                draw.text(
                    (
                        x
                        + box_width
                        // 2,
                        header_height
                        + 18,
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
        # Traits du bracket
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
            for matches
            in bracket.values()
            for match
            in matches
        ]

        avatars = await self._resolve_avatar_map(
            all_matches,
            avatar_urls,
        )

        # ------------------------------------------------------
        # Dessin de chaque match
        # ------------------------------------------------------

        for (
            round_number,
            matches,
        ) in bracket.items():

            round_positions = positions[
                round_number
            ]

            for match, (
                x,
                y,
                side,
            ) in zip(
                matches,
                round_positions,
            ):

                if side == "center":

                    side_color = (
                        self.GOLD
                    )

                elif side == "left":

                    side_color = (
                        self.RED
                    )

                else:

                    side_color = (
                        self.BLUE
                    )

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
                        player_capacity
                        >= 64
                    ),
                )

        # ------------------------------------------------------
        # Carte du champion
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

        champion_name = (
            getattr(
                final_match,
                "winner_name",
                None,
            )
            if final_match
            else None
        )

        champion_id = (
            getattr(
                final_match,
                "winner_id",
                None,
            )
            if final_match
            else None
        )

        if (
            final_mode
            and champion_name
        ):

            card_width = 620
            card_height = 260

            card_x = (
                width
                // 2
                - card_width
                // 2
            )

            final_y = (
                positions[1][0][1]
            )

            card_y = (
                final_y
                + box_height
                + 52
            )

            draw.rounded_rectangle(
                (
                    card_x,
                    card_y,
                    card_x
                    + card_width,
                    card_y
                    + card_height,
                ),
                radius=28,
                fill=(
                    32,
                    29,
                    19,
                ),
                outline=self.GOLD,
                width=5,
            )

            draw.text(
                (
                    width // 2,
                    card_y + 34,
                ),
                "🏆 CHAMPION",
                font=self._font(
                    38,
                    bold=True,
                ),
                fill=self.GOLD,
                anchor="ma",
            )

            key = (
                str(champion_id)
                if champion_id
                else (
                    f"name:"
                    f"{champion_name}"
                )
            )

            avatar = avatars.get(
                key
            )

            if avatar is not None:

                circle = self._circle_avatar(
                    avatar,
                    110,
                )

                image.alpha_composite(
                    circle,
                    (
                        card_x + 52,
                        card_y + 90,
                    ),
                )

            draw.text(
                (
                    card_x + 190,
                    card_y + 104,
                ),
                self._safe_text(
                    champion_name,
                    28,
                ),
                font=self._font(
                    40,
                    bold=True,
                ),
                fill=self.TEXT,
            )

            draw.text(
                (
                    card_x + 190,
                    card_y + 164,
                ),
                (
                    f"Tournoi "
                    f"#{tournament_id}"
                    f" • "
                    f"{tournament_format}"
                ),
                font=self._font(
                    24
                ),
                fill=self.MUTED,
            )

        # ------------------------------------------------------
        # Bandeau inférieur
        # ------------------------------------------------------

        footer_y = (
            height
            - footer_height
        )

        draw.rectangle(
            (
                0,
                footer_y,
                width,
                height,
            ),
            fill=(
                14,
                17,
                28,
                255,
            ),
        )

        draw.text(
            (
                90,
                footer_y + 56,
            ),
            (
                "Organisé avec "
                "Hamtaro Tournament Bot"
            ),
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
            (
                f"ID tournoi "
                f"#{tournament_id}"
            ),
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
