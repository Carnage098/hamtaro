from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


Color = tuple[int, int, int]


@dataclass(slots=True)
class HamtaroBracketTheme:
    """
    Thème graphique officiel du bracket Hamtaro.

    Objectifs visuels :

    - format 16:9 proche de l'affiche Hamtaro Cup ;
    - ambiance esport sombre ;
    - côté gauche rouge ;
    - côté droit bleu ;
    - centre réservé à la finale et au champion ;
    - cartes compactes avec seed, avatar, pseudo et score ;
    - progression visuelle vers la finale ;
    - véritable illustration Hamtaro ;
    - connecteurs lumineux ;
    - header et footer proches de la maquette finale.

    Toutes les ressources présentes dans graphics/assets/
    restent facultatives.

    Le BracketImageService doit vérifier qu'un fichier existe
    avant de tenter de l'afficher.
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

    # Logo central du tournoi.
    logo_filename: str = "hamtaro_logo.png"

    # Fond optionnel du renderer.
    background_filename: str = "bracket_background.png"

    # Illustration Hamtaro du header.
    header_mascot_filename: str = "hamtaro_header.png"

    # Trophée central.
    trophy_filename: str = "trophy.png"

    # Illustration Hamtaro du champion.
    champion_filename: str = "champion_hamtaro.png"

    # Lauriers décoratifs du champion.
    champion_laurel_filename: str = "champion_laurel.png"

    # Petite illustration Hamtaro du footer.
    footer_icon_filename: str = "hamtaro_footer.png"

    # Logo Discord du footer.
    discord_logo_filename: str = "discord_logo.png"

    # ==========================================================
    # COULEURS GÉNÉRALES
    # ==========================================================

    background: Color = (
        3,
        7,
        15,
    )

    background_center: Color = (
        2,
        6,
        13,
    )

    background_center_light: Color = (
        4,
        12,
        25,
    )

    header_background: Color = (
        4,
        7,
        13,
    )

    footer_background: Color = (
        4,
        8,
        16,
    )

    panel: Color = (
        12,
        18,
        30,
    )

    panel_alternate: Color = (
        17,
        25,
        41,
    )

    panel_light: Color = (
        25,
        35,
        54,
    )

    panel_highlight: Color = (
        34,
        44,
        66,
    )

    panel_shadow: Color = (
        0,
        0,
        0,
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

    subtle_text: Color = (
        130,
        140,
        161,
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
    # COULEURS DU BRACKET GAUCHE
    # ==========================================================

    left_side: Color = (
        255,
        67,
        46,
    )

    left_side_light: Color = (
        255,
        118,
        89,
    )

    left_side_dark: Color = (
        105,
        18,
        17,
    )

    left_side_deep: Color = (
        61,
        9,
        10,
    )

    left_background: Color = (
        24,
        7,
        10,
    )

    left_background_glow: Color = (
        86,
        12,
        8,
    )

    # ==========================================================
    # COULEURS DU BRACKET DROIT
    # ==========================================================

    right_side: Color = (
        42,
        145,
        255,
    )

    right_side_light: Color = (
        108,
        194,
        255,
    )

    right_side_dark: Color = (
        12,
        47,
        104,
    )

    right_side_deep: Color = (
        5,
        25,
        65,
    )

    right_background: Color = (
        5,
        19,
        43,
    )

    right_background_glow: Color = (
        2,
        52,
        112,
    )

    # ==========================================================
    # COULEURS DES RÉSULTATS
    # ==========================================================

    champion_gold: Color = (
        255,
        199,
        55,
    )

    champion_gold_light: Color = (
        255,
        226,
        125,
    )

    champion_gold_dark: Color = (
        104,
        70,
        10,
    )

    champion_gold_deep: Color = (
        63,
        38,
        3,
    )

    winner_green: Color = (
        65,
        221,
        128,
    )

    winner_green_dark: Color = (
        19,
        98,
        61,
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

    # Le score n'utilise plus du blanc pur.
    score_background: Color = (
        220,
        224,
        232,
    )

    score_winner_background: Color = (
        242,
        230,
        207,
    )

    score_loser_background: Color = (
        183,
        190,
        204,
    )

    score_text: Color = (
        15,
        18,
        26,
    )

    score_winner_text: Color = (
        77,
        39,
        4,
    )

    score_loser_text: Color = (
        47,
        52,
        64,
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

    center_separator_width: int = 2

    # ==========================================================
    # HEADER
    # ==========================================================

    title_font_size: int = 42
    title_number_font_size: int = 42

    subtitle_font_size: int = 17
    information_font_size: int = 14
    round_font_size: int = 13

    header_title_x: int = 48
    header_title_y: int = 17

    header_metadata_y: int = 69

    # Espace laissé à l'illustration Hamtaro.
    header_mascot_x: int = 31
    header_mascot_y: int = 6

    header_mascot_width: int = 78
    header_mascot_height: int = 94

    # Le texte est décalé lorsque la mascotte est affichée.
    header_title_with_mascot_x: int = 126

    header_logo_maximum_width: int = 220
    header_logo_maximum_height: int = 106

    header_logo_vertical_offset: int = 1

    header_information_box_height: int = 64
    header_information_box_radius: int = 3
    header_information_box_border_width: int = 1
    header_information_box_gap: int = 6

    date_box_width: int = 180
    tournament_id_box_width: int = 145
    organizer_box_width: int = 220

    header_separator_height: int = 3

    header_red_separator_ratio: float = 0.5

    # ==========================================================
    # FOOTER
    # ==========================================================

    footer_title_font_size: int = 15
    footer_information_font_size: int = 13
    footer_center_font_size: int = 16

    footer_icon_size: int = 32
    footer_discord_logo_size: int = 30

    footer_horizontal_padding: int = 26

    footer_top_separator_height: int = 2

    discord_invite_text: str = (
        "HTTPS://DISCORD.GG/HAMTARO"
    )

    footer_center_text: str = (
        "MERCI À TOUS LES PARTICIPANTS !"
    )

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

    match_shadow_offset_x: int = 3
    match_shadow_offset_y: int = 4
    match_shadow_blur_radius: int = 5

    avatar_border_width: int = 1
    avatar_winner_border_width: int = 2

    # ==========================================================
    # POLICES DES MATCHS
    # ==========================================================

    normal_name_font_size: int = 18
    normal_score_font_size: int = 18
    normal_seed_font_size: int = 14

    compact_name_font_size: int = 13
    compact_score_font_size: int = 14
    compact_seed_font_size: int = 11

    semifinal_name_font_size: int = 17
    semifinal_score_font_size: int = 19

    # ==========================================================
    # TITRES DES RONDES
    # ==========================================================

    round_title_vertical_padding: int = 4
    round_title_underline_width: int = 74
    round_title_underline_height: int = 2

    round_title_background_enabled: bool = False
    round_title_background_radius: int = 3

    # ==========================================================
    # FINALE
    # ==========================================================

    final_title_font_size: int = 22
    final_name_font_size: int = 22
    final_score_font_size: int = 23

    final_title_height: int = 34
    final_title_width: int = 136
    final_vertical_offset: int = 14

    final_avatar_size: int = 40

    final_title_background: Color = (
        91,
        17,
        14,
    )

    final_title_border: Color = (
        191,
        54,
        38,
    )

    final_title_radius: int = 5

    final_glow_radius: int = 10
    final_glow_alpha: int = 100

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

    champion_card_background: Color = (
        5,
        10,
        20,
    )

    champion_trophy_width: int = 70
    champion_trophy_height: int = 70

    champion_image_width: int = 128
    champion_image_height: int = 128

    champion_laurel_width: int = 186
    champion_laurel_height: int = 142

    champion_name_plate_width: int = 178
    champion_name_plate_height: int = 37
    champion_name_plate_radius: int = 4

    champion_glow_radius: int = 18
    champion_glow_alpha: int = 105

    champion_particle_count: int = 26
    champion_particle_radius: int = 2

    # ==========================================================
    # STATISTIQUES
    # ==========================================================

    statistics_card_width: int = 420
    statistics_card_height: int = 104
    statistics_card_radius: int = 5
    statistics_card_border_width: int = 1

    statistics_title_font_size: int = 14
    statistics_value_font_size: int = 19
    statistics_label_font_size: int = 11

    statistics_title_color: Color = (
        255,
        75,
        55,
    )

    statistics_icon_size: int = 17

    statistics_column_count: int = 4
    statistics_separator_width: int = 1

    statistics_background: Color = (
        7,
        13,
        25,
    )

    # ==========================================================
    # EFFETS
    # ==========================================================

    side_background_alpha: int = 120
    side_glow_alpha: int = 82

    connector_glow_alpha: int = 90
    connector_secondary_alpha: int = 150

    connector_blur_radius: int = 5
    connector_joint_radius: int = 2

    panel_shadow_alpha: int = 115
    panel_shadow_offset: int = 3

    particle_alpha: int = 48
    particle_count: int = 90

    particle_minimum_radius: int = 1
    particle_maximum_radius: int = 2

    vignette_alpha: int = 92

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
    def header_mascot_path(
        self,
    ) -> Path:
        return (
            self.assets_directory
            / self.header_mascot_filename
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
    def champion_laurel_path(
        self,
    ) -> Path:
        return (
            self.assets_directory
            / self.champion_laurel_filename
        )

    @property
    def footer_icon_path(
        self,
    ) -> Path:
        return (
            self.assets_directory
            / self.footer_icon_filename
        )

    @property
    def discord_logo_path(
        self,
    ) -> Path:
        return (
            self.assets_directory
            / self.discord_logo_filename
        )

    # ==========================================================
    # NORMALISATION DU NOMBRE DE JOUEURS
    # ==========================================================

    @staticmethod
    def normalized_capacity(
        player_capacity: int,
    ) -> int:
        """
        Normalise le nombre de joueurs vers la puissance de deux
        prise en charge la plus proche.

        Exemple :
        - 27 joueurs utilisent une capacité graphique de 32 ;
        - 51 joueurs utilisent une capacité graphique de 64.
        """

        supported = (
            2,
            4,
            8,
            16,
            32,
            64,
            128,
        )

        if player_capacity <= 2:
            return 2

        for capacity in supported:
            if player_capacity <= capacity:
                return capacity

        return 128

    # ==========================================================
    # TAILLE DE L'IMAGE
    # ==========================================================

    def canvas_size(
        self,
        player_capacity: int,
    ) -> tuple[int, int]:
        """
        Retourne les dimensions 16:9 du rendu.
        """

        capacity = self.normalized_capacity(
            player_capacity
        )

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

        return sizes[capacity]

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
        Retourne la hauteur du rendu.
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
        """

        capacity = self.normalized_capacity(
            player_capacity
        )

        widths = {
            2: 300,
            4: 260,
            8: 220,
            16: 180,
            32: 165,
            64: 148,
            128: 145,
        }

        return widths[capacity]

    def box_width_for_round(
        self,
        player_capacity: int,
        round_index: int,
        total_rounds: int,
    ) -> int:
        """
        Augmente légèrement la largeur des cartes lorsque les
        joueurs approchent de la finale.

        round_index commence à zéro.
        """

        base_width = self.box_width(
            player_capacity
        )

        if total_rounds <= 1:
            return base_width

        progress = max(
            0.0,
            min(
                1.0,
                round_index
                / max(
                    1,
                    total_rounds - 1,
                ),
            ),
        )

        maximum_bonus = {
            2: 0,
            4: 12,
            8: 18,
            16: 22,
            32: 26,
            64: 30,
            128: 32,
        }[
            self.normalized_capacity(
                player_capacity
            )
        ]

        return (
            base_width
            + round(
                maximum_bonus
                * progress
            )
        )

    def box_height(
        self,
        player_capacity: int,
    ) -> int:
        """
        Hauteur totale d'une carte contenant deux joueurs.
        """

        capacity = self.normalized_capacity(
            player_capacity
        )

        heights = {
            2: 96,
            4: 88,
            8: 78,
            16: 68,
            32: 58,
            64: 46,
            128: 42,
        }

        return heights[capacity]

    def box_height_for_round(
        self,
        player_capacity: int,
        round_index: int,
        total_rounds: int,
    ) -> int:
        """
        Augmente légèrement la hauteur des cartes des derniers
        tours sans modifier la hauteur du premier tour.
        """

        base_height = self.box_height(
            player_capacity
        )

        if total_rounds <= 1:
            return base_height

        progress = max(
            0.0,
            min(
                1.0,
                round_index
                / max(
                    1,
                    total_rounds - 1,
                ),
            ),
        )

        maximum_bonus = {
            2: 0,
            4: 4,
            8: 6,
            16: 8,
            32: 10,
            64: 12,
            128: 12,
        }[
            self.normalized_capacity(
                player_capacity
            )
        ]

        return (
            base_height
            + round(
                maximum_bonus
                * progress
            )
        )

    def final_box_width(
        self,
        player_capacity: int,
    ) -> int:
        """
        Largeur de la grande finale centrale.
        """

        capacity = self.normalized_capacity(
            player_capacity
        )

        widths = {
            2: 380,
            4: 350,
            8: 330,
            16: 300,
            32: 280,
            64: 220,
            128: 260,
        }

        return widths[capacity]

    def final_box_height(
        self,
        player_capacity: int,
    ) -> int:
        """
        Hauteur de la grande finale centrale.
        """

        capacity = self.normalized_capacity(
            player_capacity
        )

        heights = {
            2: 132,
            4: 126,
            8: 120,
            16: 112,
            32: 106,
            64: 96,
            128: 96,
        }

        return heights[capacity]

    # ==========================================================
    # COLONNES INTERNES DES MATCHS
    # ==========================================================

    def seed_column_width(
        self,
        player_capacity: int,
    ) -> int:
        capacity = self.normalized_capacity(
            player_capacity
        )

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
            capacity,
            self.seed_column_minimum_width,
        )

    def score_column_width(
        self,
        player_capacity: int,
    ) -> int:
        capacity = self.normalized_capacity(
            player_capacity
        )

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
            capacity,
            self.score_column_minimum_width,
        )

    # ==========================================================
    # AVATARS
    # ==========================================================

    def player_avatar_size(
        self,
        player_capacity: int,
    ) -> int:
        capacity = self.normalized_capacity(
            player_capacity
        )

        sizes = {
            2: 42,
            4: 40,
            8: 36,
            16: 31,
            32: 27,
            64: 20,
            128: 18,
        }

        return sizes[capacity]

    def player_avatar_size_for_round(
        self,
        player_capacity: int,
        round_index: int,
        total_rounds: int,
    ) -> int:
        """
        Agrandit progressivement les avatars lorsque les joueurs
        se rapprochent de la finale.
        """

        base_size = self.player_avatar_size(
            player_capacity
        )

        if total_rounds <= 1:
            return base_size

        progress = max(
            0.0,
            min(
                1.0,
                round_index
                / max(
                    1,
                    total_rounds - 1,
                ),
            ),
        )

        maximum_bonus = {
            2: 0,
            4: 4,
            8: 6,
            16: 8,
            32: 10,
            64: 11,
            128: 10,
        }[
            self.normalized_capacity(
                player_capacity
            )
        ]

        return (
            base_size
            + round(
                maximum_bonus
                * progress
            )
        )

    def avatar_size(
        self,
        density_hint: int,
    ) -> int:
        """
        Compatibilité avec l'ancien service.

        L'ancien service transmet généralement :
        - 32 pour un bracket normal ;
        - 64 pour un bracket compact.
        """

        if density_hint >= 128:
            return 18

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

        capacity = self.normalized_capacity(
            player_capacity
        )

        gaps = {
            2: 90,
            4: 72,
            8: 54,
            16: 40,
            32: 28,
            64: 18,
            128: 18,
        }

        return gaps[capacity]

    def center_reserved_width(
        self,
        player_capacity: int,
    ) -> int:
        """
        Largeur centrale réservée à la finale,
        au champion et aux statistiques.
        """

        capacity = self.normalized_capacity(
            player_capacity
        )

        widths = {
            2: 480,
            4: 440,
            8: 390,
            16: 340,
            32: 310,
            64: 310,
            128: 370,
        }

        return widths[capacity]

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

        capacity = self.normalized_capacity(
            player_capacity
        )

        gaps = {
            2: 120,
            4: 110,
            8: 96,
            16: 83,
            32: 75,
            64: 53,
            128: 46,
        }

        return gaps[capacity]

    # Ancien nom conservé pour compatibilité.
    def vertical_gap(
        self,
        player_capacity: int,
    ) -> int:
        return self.first_round_vertical_gap(
            player_capacity
        )

    # ==========================================================
    # POLICES ADAPTATIVES
    # ==========================================================

    def player_name_font_size(
        self,
        player_capacity: int,
    ) -> int:
        capacity = self.normalized_capacity(
            player_capacity
        )

        sizes = {
            2: 21,
            4: 20,
            8: 18,
            16: 16,
            32: 14,
            64: 12,
            128: 11,
        }

        return sizes[capacity]

    def player_name_font_size_for_round(
        self,
        player_capacity: int,
        round_index: int,
        total_rounds: int,
    ) -> int:
        """
        Augmente légèrement la police des noms dans les derniers
        tours du bracket.
        """

        base_size = self.player_name_font_size(
            player_capacity
        )

        if total_rounds <= 1:
            return base_size

        progress = max(
            0.0,
            min(
                1.0,
                round_index
                / max(
                    1,
                    total_rounds - 1,
                ),
            ),
        )

        maximum_bonus = {
            2: 0,
            4: 1,
            8: 2,
            16: 3,
            32: 3,
            64: 4,
            128: 3,
        }[
            self.normalized_capacity(
                player_capacity
            )
        ]

        return (
            base_size
            + round(
                maximum_bonus
                * progress
            )
        )

    def player_score_font_size(
        self,
        player_capacity: int,
    ) -> int:
        capacity = self.normalized_capacity(
            player_capacity
        )

        sizes = {
            2: 22,
            4: 21,
            8: 19,
            16: 17,
            32: 15,
            64: 13,
            128: 12,
        }

        return sizes[capacity]

    def player_score_font_size_for_round(
        self,
        player_capacity: int,
        round_index: int,
        total_rounds: int,
    ) -> int:
        base_size = self.player_score_font_size(
            player_capacity
        )

        if total_rounds <= 1:
            return base_size

        progress = max(
            0.0,
            min(
                1.0,
                round_index
                / max(
                    1,
                    total_rounds - 1,
                ),
            ),
        )

        return (
            base_size
            + round(
                4
                * progress
            )
        )

    def player_seed_font_size(
        self,
        player_capacity: int,
    ) -> int:
        capacity = self.normalized_capacity(
            player_capacity
        )

        sizes = {
            2: 16,
            4: 15,
            8: 14,
            16: 13,
            32: 11,
            64: 10,
            128: 9,
        }

        return sizes[capacity]

    def round_font_size_for(
        self,
        player_capacity: int,
    ) -> int:
        capacity = self.normalized_capacity(
            player_capacity
        )

        sizes = {
            2: 18,
            4: 17,
            8: 16,
            16: 15,
            32: 13,
            64: 12,
            128: 11,
        }

        return sizes[capacity]

    # ==========================================================
    # ÉPAISSEUR ET LUEUR DES CONNEXIONS
    # ==========================================================

    def connector_width(
        self,
        player_capacity: int,
    ) -> int:
        capacity = self.normalized_capacity(
            player_capacity
        )

        if capacity >= 32:
            return 2

        return 3

    def connector_middle_width(
        self,
        player_capacity: int,
    ) -> int:
        return (
            self.connector_width(
                player_capacity
            )
            + 2
        )

    def connector_glow_width(
        self,
        player_capacity: int,
    ) -> int:
        return (
            self.connector_width(
                player_capacity
            )
            + 6
        )

    # ==========================================================
    # OPACITÉ SELON LA RONDE
    # ==========================================================

    def round_card_opacity(
        self,
        round_index: int,
        total_rounds: int,
    ) -> int:
        """
        Les premières rondes sont légèrement plus discrètes.
        Les derniers tours deviennent progressivement plus nets.
        """

        if total_rounds <= 1:
            return 255

        progress = max(
            0.0,
            min(
                1.0,
                round_index
                / max(
                    1,
                    total_rounds - 1,
                ),
            ),
        )

        return round(
            218
            + (
                37
                * progress
            )
        )

    def round_glow_alpha(
        self,
        round_index: int,
        total_rounds: int,
    ) -> int:
        """
        Renforce la lueur des connecteurs à proximité de la finale.
        """

        if total_rounds <= 1:
            return self.connector_glow_alpha

        progress = max(
            0.0,
            min(
                1.0,
                round_index
                / max(
                    1,
                    total_rounds - 1,
                ),
            ),
        )

        return round(
            55
            + (
                55
                * progress
            )
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
