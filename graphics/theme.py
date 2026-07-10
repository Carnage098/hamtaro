from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


Color = tuple[int, int, int]


@dataclass(slots=True)
class HamtaroBracketTheme:
    """
    Thème graphique officiel du bracket Hamtaro.

    Objectifs visuels :

    - format proche de l'affiche Hamtaro Cup ;
    - image 16:9 ;
    - côté gauche rouge ;
    - côté droit bleu ;
    - centre noir réservé à la finale ;
    - cases compactes avec seed, avatar, pseudo et score ;
    - grande zone champion en mode final ;
    - header et footer proches de la maquette.

    Toutes les ressources présentes dans graphics/assets/
    restent facultatives.
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
    champion_filename: str = "champion_hamtaro.png"
    footer_icon_filename: str = "hamtaro_footer.png"

    # ==========================================================
    # COULEURS GÉNÉRALES
    # ==========================================================

    background: Color = (
        4,
        7,
        14,
    )

    background_center: Color = (
        3,
        6,
        12,
    )

    header_background: Color = (
        4,
        7,
        13,
    )

    footer_background: Color = (
        5,
        8,
        15,
    )

    panel: Color = (
        13,
        19,
        31,
    )

    panel_alternate: Color = (
        18,
        26,
        42,
    )

    panel_light: Color = (
        25,
        34,
        52,
    )

    text: Color = (
        248,
        249,
        252,
    )

    muted_text: Color = (
        173,
        181,
        199,
    )

    disabled_text: Color = (
        108,
        117,
        139,
    )

    connector_line: Color = (
        74,
        83,
        104,
    )

    separator: Color = (
        45,
        55,
        76,
    )

    # ==========================================================
    # COULEURS DU BRACKET
    # ==========================================================

    left_side: Color = (
        255,
        65,
        45,
    )

    left_side_dark: Color = (
        105,
        18,
        17,
    )

    left_background: Color = (
        24,
        7,
        10,
    )

    right_side: Color = (
        39,
        135,
        255,
    )

    right_side_dark: Color = (
        12,
        47,
        104,
    )

    right_background: Color = (
        5,
        19,
        43,
    )

    # ==========================================================
    # COULEURS DES RÉSULTATS
    # ==========================================================

    champion_gold: Color = (
        255,
        199,
        55,
    )

    champion_gold_dark: Color = (
        104,
        70,
        10,
    )

    winner_green: Color = (
        65,
        221,
        128,
    )

    loser_red: Color = (
        191,
        65,
        73,
    )

    pending_orange: Color = (
        247,
        158,
        48,
    )

    score_background: Color = (
        232,
        234,
        239,
    )

    score_text: Color = (
        15,
        18,
        26,
    )

    # ==========================================================
    # FORMAT GÉNÉRAL
    # ==========================================================

    header_height: int = 112
    footer_height: int = 54

    horizontal_margin: int = 24
    vertical_margin: int = 14

    round_labels_height: int = 28
    bracket_top_padding: int = 10
    bracket_bottom_padding: int = 10

    # ==========================================================
    # HEADER
    # ==========================================================

    title_font_size: int = 40
    subtitle_font_size: int = 18
    information_font_size: int = 14
    round_font_size: int = 13

    header_title_x: int = 48
    header_title_y: int = 18

    header_metadata_y: int = 69

    header_logo_maximum_width: int = 220
    header_logo_maximum_height: int = 104

    header_information_box_height: int = 64
    header_information_box_radius: int = 3

    date_box_width: int = 180
    tournament_id_box_width: int = 145
    organizer_box_width: int = 220

    header_separator_height: int = 3

    # ==========================================================
    # FOOTER
    # ==========================================================

    footer_title_font_size: int = 15
    footer_information_font_size: int = 13

    footer_icon_size: int = 32
    footer_horizontal_padding: int = 26

    # ==========================================================
    # CASES DES MATCHS
    # ==========================================================

    normal_box_radius: int = 5
    compact_box_radius: int = 3
    final_box_radius: int = 7

    normal_box_border_width: int = 2
    compact_box_border_width: int = 2
    final_box_border_width: int = 3

    player_row_separator_width: int = 1
    winner_indicator_width: int = 3

    seed_column_minimum_width: int = 22
    score_column_minimum_width: int = 28

    match_inner_padding: int = 4
    avatar_left_padding: int = 4
    name_left_padding: int = 5

    # ==========================================================
    # POLICES DES MATCHS
    # ==========================================================

    normal_name_font_size: int = 18
    normal_score_font_size: int = 18
    normal_seed_font_size: int = 14

    compact_name_font_size: int = 13
    compact_score_font_size: int = 14
    compact_seed_font_size: int = 11

    # ==========================================================
    # FINALE
    # ==========================================================

    final_title_font_size: int = 22
    final_name_font_size: int = 22
    final_score_font_size: int = 23

    final_title_height: int = 34
    final_vertical_offset: int = 14

    # ==========================================================
    # CARTE DU CHAMPION
    # ==========================================================

    champion_title_font_size: int = 28
    champion_name_font_size: int = 26
    champion_information_font_size: int = 15

    champion_avatar_size: int = 112

    champion_card_width: int = 280
    champion_card_height: int = 320
    champion_card_radius: int = 8
    champion_card_border_width: int = 2

    champion_trophy_width: int = 70
    champion_trophy_height: int = 70

    champion_image_width: int = 128
    champion_image_height: int = 128

    # ==========================================================
    # STATISTIQUES
    # ==========================================================

    statistics_card_width: int = 420
    statistics_card_height: int = 104
    statistics_card_radius: int = 5

    statistics_title_font_size: int = 14
    statistics_value_font_size: int = 19
    statistics_label_font_size: int = 11

    # ==========================================================
    # EFFETS
    # ==========================================================

    side_background_alpha: int = 120
    side_glow_alpha: int = 90
    connector_glow_alpha: int = 95

    panel_shadow_alpha: int = 100
    panel_shadow_offset: int = 3

    particle_alpha: int = 55
    particle_count: int = 90

    # ==========================================================
    # CHEMINS DES RESSOURCES
    # ==========================================================

    @property
    def logo_path(
        self,
    ) -> Path:
        return (
            self.assets_directory
            / self.logo_filename
        )

    @property
    def background_path(
        self,
    ) -> Path:
        return (
            self.assets_directory
            / self.background_filename
        )

    @property
    def trophy_path(
        self,
    ) -> Path:
        return (
            self.assets_directory
            / self.trophy_filename
        )

    @property
    def champion_path(
        self,
    ) -> Path:
        return (
            self.assets_directory
            / self.champion_filename
        )

    @property
    def footer_icon_path(
        self,
    ) -> Path:
        return (
            self.assets_directory
            / self.footer_icon_filename
        )

    # ==========================================================
    # TAILLE DE L'IMAGE
    # ==========================================================

    def canvas_size(
        self,
        player_capacity: int,
    ) -> tuple[int, int]:
        """
        Retourne les dimensions de l'image.

        Toutes les résolutions conservent un format proche
        du 16:9 utilisé par l'affiche originale.
        """

        sizes = {
            2: (
                1600,
                900,
            ),
            4: (
                1600,
                900,
            ),
            8: (
                1600,
                900,
            ),
            16: (
                1600,
                900,
            ),
            32: (
                1800,
                1012,
            ),
            64: (
                1920,
                1080,
            ),
            128: (
                2560,
                1440,
            ),
        }

        return sizes.get(
            player_capacity,
            (
                1920,
                1080,
            ),
        )

    def image_width(
        self,
        player_capacity: int,
    ) -> int:
        """
        Compatibilité avec le BracketImageService actuel.
        """

        width, _ = self.canvas_size(
            player_capacity
        )

        return width

    def image_height(
        self,
        player_capacity: int,
    ) -> int:
        """
        Hauteur fixe du rendu 16:9.
        """

        _, height = self.canvas_size(
            player_capacity
        )

        return height

    # ==========================================================
    # DIMENSIONS DES CASES
    # ==========================================================

    def box_width(
        self,
        player_capacity: int,
    ) -> int:
        """
        Largeur des matchs ordinaires.

        Pour 64 joueurs, cinq colonnes sont affichées
        de chaque côté de la finale.
        """

        widths = {
            2: 300,
            4: 260,
            8: 220,
            16: 180,
            32: 165,
            64: 145,
            128: 145,
        }

        return widths.get(
            player_capacity,
            145,
        )

    def box_height(
        self,
        player_capacity: int,
    ) -> int:
        """
        Hauteur totale d'une case contenant deux joueurs.
        """

        heights = {
            2: 96,
            4: 88,
            8: 78,
            16: 68,
            32: 58,
            64: 46,
            128: 42,
        }

        return heights.get(
            player_capacity,
            46,
        )

    def final_box_width(
        self,
        player_capacity: int,
    ) -> int:
        """
        Largeur de la grande finale centrale.
        """

        widths = {
            2: 380,
            4: 350,
            8: 330,
            16: 300,
            32: 280,
            64: 220,
            128: 260,
        }

        return widths.get(
            player_capacity,
            220,
        )

    def final_box_height(
        self,
        player_capacity: int,
    ) -> int:
        """
        Hauteur de la grande finale centrale.
        """

        heights = {
            2: 132,
            4: 126,
            8: 120,
            16: 112,
            32: 106,
            64: 96,
            128: 96,
        }

        return heights.get(
            player_capacity,
            96,
        )

    # ==========================================================
    # COLONNES INTERNES DES MATCHS
    # ==========================================================

    def seed_column_width(
        self,
        player_capacity: int,
    ) -> int:
        widths = {
            2: 34,
            4: 32,
            8: 30,
            16: 28,
            32: 25,
            64: 22,
            128: 22,
        }

        return widths.get(
            player_capacity,
            self.seed_column_minimum_width,
        )

    def score_column_width(
        self,
        player_capacity: int,
    ) -> int:
        widths = {
            2: 44,
            4: 42,
            8: 40,
            16: 36,
            32: 32,
            64: 28,
            128: 28,
        }

        return widths.get(
            player_capacity,
            self.score_column_minimum_width,
        )

    # ==========================================================
    # AVATARS
    # ==========================================================

    def player_avatar_size(
        self,
        player_capacity: int,
    ) -> int:
        sizes = {
            2: 42,
            4: 40,
            8: 36,
            16: 31,
            32: 27,
            64: 20,
            128: 18,
        }

        return sizes.get(
            player_capacity,
            20,
        )

    def avatar_size(
        self,
        density_hint: int,
    ) -> int:
        """
        Compatibilité avec l'ancien service.

        L'ancien service envoie :
        - 32 pour un bracket normal ;
        - 64 pour un bracket compact.
        """

        if density_hint >= 64:
            return 20

        return 28

    # ==========================================================
    # ESPACEMENT HORIZONTAL
    # ==========================================================

    def column_gap(
        self,
        player_capacity: int,
    ) -> int:
        """
        Distance entre deux colonnes du bracket.
        """

        gaps = {
            2: 90,
            4: 72,
            8: 54,
            16: 40,
            32: 28,
            64: 18,
            128: 18,
        }

        return gaps.get(
            player_capacity,
            18,
        )

    def center_reserved_width(
        self,
        player_capacity: int,
    ) -> int:
        """
        Largeur centrale réservée à la finale,
        au champion et aux statistiques.
        """

        widths = {
            2: 480,
            4: 440,
            8: 390,
            16: 340,
            32: 300,
            64: 300,
            128: 360,
        }

        return widths.get(
            player_capacity,
            300,
        )

    # ==========================================================
    # ESPACEMENT VERTICAL
    # ==========================================================

    def bracket_content_top(
        self,
    ) -> int:
        """
        Position verticale du début des matchs.
        """

        return (
            self.header_height
            + self.round_labels_height
            + self.bracket_top_padding
        )

    def bracket_content_bottom(
        self,
        player_capacity: int,
    ) -> int:
        """
        Position verticale maximale des matchs.
        """

        return (
            self.image_height(
                player_capacity
            )
            - self.footer_height
            - self.bracket_bottom_padding
        )

    def first_round_vertical_gap(
        self,
        player_capacity: int,
    ) -> int:
        """
        Distance entre les débuts de deux matchs du premier tour.
        """

        gaps = {
            2: 120,
            4: 110,
            8: 96,
            16: 83,
            32: 75,
            64: 53,
            128: 46,
        }

        return gaps.get(
            player_capacity,
            53,
        )

    # ==========================================================
    # POLICES ADAPTATIVES
    # ==========================================================

    def player_name_font_size(
        self,
        player_capacity: int,
    ) -> int:
        sizes = {
            2: 21,
            4: 20,
            8: 18,
            16: 16,
            32: 14,
            64: 12,
            128: 11,
        }

        return sizes.get(
            player_capacity,
            12,
        )

    def player_score_font_size(
        self,
        player_capacity: int,
    ) -> int:
        sizes = {
            2: 22,
            4: 21,
            8: 19,
            16: 17,
            32: 15,
            64: 13,
            128: 12,
        }

        return sizes.get(
            player_capacity,
            13,
        )

    def player_seed_font_size(
        self,
        player_capacity: int,
    ) -> int:
        sizes = {
            2: 16,
            4: 15,
            8: 14,
            16: 13,
            32: 11,
            64: 10,
            128: 9,
        }

        return sizes.get(
            player_capacity,
            10,
        )

    def round_font_size_for(
        self,
        player_capacity: int,
    ) -> int:
        sizes = {
            2: 18,
            4: 17,
            8: 16,
            16: 15,
            32: 13,
            64: 12,
            128: 11,
        }

        return sizes.get(
            player_capacity,
            12,
        )

    # ==========================================================
    # ÉPAISSEUR DES CONNEXIONS
    # ==========================================================

    def connector_width(
        self,
        player_capacity: int,
    ) -> int:
        if player_capacity >= 128:
            return 2

        if player_capacity >= 32:
            return 2

        return 3

    def connector_glow_width(
        self,
        player_capacity: int,
    ) -> int:
        return (
            self.connector_width(
                player_capacity
            )
            + 4
        )

    # ==========================================================
    # VALIDATION
    # ==========================================================

    @staticmethod
    def validate_player_capacity(
        player_capacity: int,
    ) -> None:
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
                "Le thème graphique Hamtaro prend uniquement "
                "en charge les brackets de 2, 4, 8, 16, 32, "
                "64 ou 128 joueurs."
            )
