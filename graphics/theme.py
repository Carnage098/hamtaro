from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class HamtaroBracketTheme:
    """
    Configuration visuelle officielle des brackets Hamtaro.

    Cette classe centralise :
    - les couleurs ;
    - les tailles ;
    - les chemins des ressources ;
    - les paramètres du rendu.

    Le renderer peut ainsi évoluer sans avoir à modifier
    toutes les fonctions de dessin.
    """

    # ==========================================================
    # DOSSIERS
    # ==========================================================

    base_directory: Path = Path(__file__).resolve().parent
    assets_directory: Path = Path(__file__).resolve().parent / "assets"

    # ==========================================================
    # RESSOURCES FACULTATIVES
    # ==========================================================

    logo_filename: str = "hamtaro_logo.png"
    trophy_filename: str = "trophy.png"
    background_filename: str = "bracket_background.png"
    champion_frame_filename: str = "champion_frame.png"

    # ==========================================================
    # COULEURS PRINCIPALES
    # ==========================================================

    background: tuple[int, int, int] = (
        10,
        13,
        22,
    )

    header_background: tuple[int, int, int] = (
        14,
        17,
        28,
    )

    footer_background: tuple[int, int, int] = (
        14,
        17,
        28,
    )

    panel: tuple[int, int, int] = (
        23,
        28,
        43,
    )

    panel_alternate: tuple[int, int, int] = (
        30,
        36,
        55,
    )

    text: tuple[int, int, int] = (
        245,
        247,
        252,
    )

    muted_text: tuple[int, int, int] = (
        157,
        165,
        184,
    )

    left_side: tuple[int, int, int] = (
        224,
        67,
        75,
    )

    right_side: tuple[int, int, int] = (
        76,
        145,
        255,
    )

    champion_gold: tuple[int, int, int] = (
        245,
        196,
        70,
    )

    winner_green: tuple[int, int, int] = (
        73,
        197,
        126,
    )

    connector_line: tuple[int, int, int] = (
        87,
        96,
        120,
    )

    # ==========================================================
    # COULEURS DES CLASSEMENTS
    # ==========================================================

    finalist_silver: tuple[int, int, int] = (
        194,
        199,
        210,
    )

    semifinalist_bronze: tuple[int, int, int] = (
        190,
        125,
        72,
    )

    defeated_red: tuple[int, int, int] = (
        155,
        65,
        72,
    )

    # ==========================================================
    # DIMENSIONS GÉNÉRALES
    # ==========================================================

    header_height: int = 300
    footer_height: int = 230
    horizontal_margin: int = 110

    normal_box_width: int = 360
    normal_box_height: int = 106

    compact_box_width: int = 320
    compact_box_height: int = 94

    normal_avatar_size: int = 42
    compact_avatar_size: int = 34

    champion_avatar_size: int = 110

    # ==========================================================
    # DIMENSIONS DES IMAGES PAR TAILLE DE BRACKET
    # ==========================================================

    width_2_players: int = 2600
    width_4_players: int = 3200
    width_8_players: int = 4300
    width_16_players: int = 5900
    width_32_players: int = 7600
    width_64_players: int = 9800
    width_128_players: int = 12000

    # ==========================================================
    # POLICES
    # ==========================================================

    title_font_size: int = 64
    subtitle_font_size: int = 30
    information_font_size: int = 23
    round_font_size: int = 24

    normal_name_font_size: int = 24
    compact_name_font_size: int = 20

    normal_score_font_size: int = 28
    compact_score_font_size: int = 22

    champion_title_font_size: int = 38
    champion_name_font_size: int = 40

    # ==========================================================
    # PROPRIÉTÉS CALCULÉES
    # ==========================================================

    @property
    def logo_path(self) -> Path:
        """
        Chemin du logo Hamtaro.
        """

        return (
            self.assets_directory
            / self.logo_filename
        )

    @property
    def trophy_path(self) -> Path:
        """
        Chemin de l’image du trophée.
        """

        return (
            self.assets_directory
            / self.trophy_filename
        )

    @property
    def background_path(self) -> Path:
        """
        Chemin du fond graphique.
        """

        return (
            self.assets_directory
            / self.background_filename
        )

    @property
    def champion_frame_path(self) -> Path:
        """
        Chemin du cadre spécial du champion.
        """

        return (
            self.assets_directory
            / self.champion_frame_filename
        )

    # ==========================================================
    # OUTILS
    # ==========================================================

    def image_width(
        self,
        player_capacity: int,
    ) -> int:
        """
        Retourne la largeur recommandée selon la taille
        du bracket.
        """

        sizes = {
            2: self.width_2_players,
            4: self.width_4_players,
            8: self.width_8_players,
            16: self.width_16_players,
            32: self.width_32_players,
            64: self.width_64_players,
            128: self.width_128_players,
        }

        return sizes.get(
            player_capacity,
            self.width_128_players,
        )

    def box_width(
        self,
        player_capacity: int,
    ) -> int:
        """
        Retourne la largeur d’une case.
        """

        if player_capacity >= 64:
            return self.compact_box_width

        return self.normal_box_width

    def box_height(
        self,
        player_capacity: int,
    ) -> int:
        """
        Retourne la hauteur d’une case.
        """

        if player_capacity >= 64:
            return self.compact_box_height

        return self.normal_box_height

    def avatar_size(
        self,
        player_capacity: int,
    ) -> int:
        """
        Retourne la taille d’un avatar.
        """

        if player_capacity >= 64:
            return self.compact_avatar_size

        return self.normal_avatar_size
