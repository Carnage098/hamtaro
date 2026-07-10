from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


Color = tuple[int, int, int]


@dataclass(slots=True)
class HamtaroBracketTheme:
    """
    Configuration graphique du bracket Hamtaro.

    Cette classe centralise :

    - les couleurs ;
    - les dimensions ;
    - les tailles de texte ;
    - les tailles des cases ;
    - les chemins vers les ressources graphiques.

    Les images placées dans graphics/assets sont facultatives.
    Le bracket fonctionne même si elles sont absentes.
    """

    # ==========================================================
    # DOSSIER DES RESSOURCES
    # ==========================================================

    assets_directory: Path = field(
        default_factory=lambda: (
            Path(__file__).resolve().parent
            / "assets"
        )
    )

    logo_filename: str = "hamtaro_logo.png"
    background_filename: str = "bracket_background.png"
    trophy_filename: str = "trophy.png"

    # ==========================================================
    # COULEURS PRINCIPALES
    # ==========================================================

    background: Color = (
        8,
        11,
        20,
    )

    panel: Color = (
        21,
        27,
        42,
    )

    panel_alternate: Color = (
        28,
        35,
        53,
    )

    header_background: Color = (
        10,
        14,
        25,
    )

    footer_background: Color = (
        10,
        14,
        25,
    )

    text: Color = (
        245,
        247,
        252,
    )

    muted_text: Color = (
        154,
        164,
        187,
    )

    connector_line: Color = (
        75,
        84,
        107,
    )

    # ==========================================================
    # COULEURS DES DEUX CÔTÉS
    # ==========================================================

    left_side: Color = (
        225,
        68,
        81,
    )

    right_side: Color = (
        72,
        139,
        255,
    )

    # ==========================================================
    # COULEURS DES RÉSULTATS
    # ==========================================================

    champion_gold: Color = (
        245,
        196,
        70,
    )

    winner_green: Color = (
        74,
        201,
        128,
    )

    loser_red: Color = (
        183,
        70,
        78,
    )

    pending_orange: Color = (
        244,
        166,
        62,
    )

    # ==========================================================
    # DIMENSIONS GÉNÉRALES
    # ==========================================================

    header_height: int = 230
    footer_height: int = 150

    horizontal_margin: int = 64

    round_title_offset: int = 20
    bracket_content_offset: int = 82

    # ==========================================================
    # DIMENSIONS DES CASES
    # ==========================================================

    normal_box_radius: int = 16
    compact_box_radius: int = 12

    normal_box_border_width: int = 3
    final_box_border_width: int = 4

    player_row_separator_width: int = 2

    # ==========================================================
    # TEXTES DU BANDEAU
    # ==========================================================

    title_font_size: int = 52
    subtitle_font_size: int = 26
    information_font_size: int = 21
    round_font_size: int = 23

    # ==========================================================
    # TEXTES DES JOUEURS
    # ==========================================================

    normal_name_font_size: int = 22
    normal_score_font_size: int = 22

    compact_name_font_size: int = 18
    compact_score_font_size: int = 18

    # ==========================================================
    # CARTE DU CHAMPION
    # ==========================================================

    champion_title_font_size: int = 31
    champion_name_font_size: int = 34
    champion_information_font_size: int = 22

    champion_avatar_size: int = 112

    champion_card_width: int = 650
    champion_card_height: int = 350

    # ==========================================================
    # CHEMINS DES RESSOURCES
    # ==========================================================

    @property
    def logo_path(
        self,
    ) -> Path:
        """
        Chemin du logo Hamtaro facultatif.
        """

        return (
            self.assets_directory
            / self.logo_filename
        )

    @property
    def background_path(
        self,
    ) -> Path:
        """
        Chemin du fond graphique facultatif.
        """

        return (
            self.assets_directory
            / self.background_filename
        )

    @property
    def trophy_path(
        self,
    ) -> Path:
        """
        Chemin du trophée facultatif.
        """

        return (
            self.assets_directory
            / self.trophy_filename
        )

    # ==========================================================
    # LARGEUR DE L'IMAGE
    # ==========================================================

    def image_width(
        self,
        player_capacity: int,
    ) -> int:
        """
        Retourne une largeur adaptée au nombre de joueurs.

        Les valeurs sont prévues pour garder :

        - des cases lisibles ;
        - des colonnes suffisamment proches ;
        - une finale bien visible au centre ;
        - un rendu moins excessivement panoramique.
        """

        widths = {
            2: 1700,
            4: 2050,
            8: 2400,
            16: 2850,
            32: 3300,
            64: 3800,
            128: 4300,
        }

        return widths.get(
            player_capacity,
            3300,
        )

    # ==========================================================
    # LARGEUR DES CASES
    # ==========================================================

    def box_width(
        self,
        player_capacity: int,
    ) -> int:
        """
        Retourne la largeur d'une case de match.
        """

        widths = {
            2: 350,
            4: 340,
            8: 315,
            16: 295,
            32: 275,
            64: 250,
            128: 230,
        }

        return widths.get(
            player_capacity,
            275,
        )

    # ==========================================================
    # HAUTEUR DES CASES
    # ==========================================================

    def box_height(
        self,
        player_capacity: int,
    ) -> int:
        """
        Retourne la hauteur d'une case contenant deux joueurs.
        """

        heights = {
            2: 122,
            4: 120,
            8: 116,
            16: 112,
            32: 106,
            64: 96,
            128: 88,
        }

        return heights.get(
            player_capacity,
            106,
        )

    # ==========================================================
    # TAILLE DES AVATARS
    # ==========================================================

    def avatar_size(
        self,
        density_hint: int,
    ) -> int:
        """
        Retourne la taille des avatars dans les cases.

        Le BracketImageService transmet actuellement :

        - 32 pour le rendu normal ;
        - 64 pour le rendu compact.
        """

        if density_hint >= 64:
            return 30

        return 40

    # ==========================================================
    # ESPACEMENT VERTICAL
    # ==========================================================

    def vertical_gap(
        self,
        player_capacity: int,
    ) -> int:
        """
        Espacement recommandé entre deux matchs du premier tour.

        Cette méthode est prévue pour une évolution ultérieure
        du BracketImageService.
        """

        gaps = {
            2: 150,
            4: 148,
            8: 146,
            16: 142,
            32: 136,
            64: 126,
            128: 116,
        }

        return gaps.get(
            player_capacity,
            136,
        )

    # ==========================================================
    # ESPACEMENT HORIZONTAL
    # ==========================================================

    def column_gap(
        self,
        player_capacity: int,
    ) -> int:
        """
        Espacement recommandé entre deux colonnes de matchs.

        Cette méthode pourra remplacer plus tard le calcul
        automatique actuellement effectué dans _layout().
        """

        gaps = {
            2: 460,
            4: 440,
            8: 415,
            16: 390,
            32: 365,
            64: 340,
            128: 320,
        }

        return gaps.get(
            player_capacity,
            365,
        )

    # ==========================================================
    # VALIDATION
    # ==========================================================

    @staticmethod
    def validate_player_capacity(
        player_capacity: int,
    ) -> None:
        """
        Vérifie que le nombre de joueurs est pris en charge.
        """

        supported = {
            2,
            4,
            8,
            16,
            32,
            64,
            128,
        }

        if player_capacity not in supported:
            raise ValueError(
                "Le thème graphique prend uniquement en charge "
                "2, 4, 8, 16, 32, 64 ou 128 joueurs."
            )
