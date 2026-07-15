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
    - titres principaux et informations du header très lisibles ;
    - finale centrale renforcée ;
    - carte du champion plus spectaculaire.

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

    logo_filename: str = "hamtaro_logo.png"
    background_filename: str = "bracket_background.png"
    header_mascot_filename: str = "hamtaro_header.png"
    trophy_filename: str = "trophy.png"
    champion_filename: str = "champion_hamtaro.png"
    champion_laurel_filename: str = "champion_laurel.png"
    footer_icon_filename: str = "hamtaro_footer.png"
    discord_logo_filename: str = "discord_logo.png"

    # ==========================================================
    # COULEURS GÉNÉRALES
    # ==========================================================

    background: Color = (3, 7, 14)
    header_background: Color = (4, 7, 13)
    footer_background: Color = (4, 8, 16)

    panel: Color = (12, 18, 30)
    panel_alternate: Color = (17, 25, 41)
    panel_light: Color = (25, 35, 54)
    panel_highlight: Color = (34, 44, 66)
    panel_shadow: Color = (0, 0, 0)

    text: Color = (248, 249, 252)
    muted_text: Color = (173, 181, 199)
    disabled_text: Color = (108, 117, 139)
    subtle_text: Color = (130, 140, 161)

    connector_line: Color = (74, 83, 104)
    separator: Color = (45, 55, 76)

    # ==========================================================
    # COULEURS DU BRACKET GAUCHE
    # ==========================================================

    left_side: Color = (255, 67, 46)
    left_side_light: Color = (255, 118, 89)
    left_side_dark: Color = (105, 18, 17)
    left_side_deep: Color = (61, 9, 10)

    left_background: Color = (26, 8, 11)
    left_background_glow: Color = (102, 20, 16)

    # ==========================================================
    # COULEURS DU BRACKET DROIT
    # ==========================================================

    right_side: Color = (42, 145, 255)
    right_side_light: Color = (108, 194, 255)
    right_side_dark: Color = (12, 47, 104)
    right_side_deep: Color = (5, 25, 65)

    right_background: Color = (5, 19, 43)
    right_background_glow: Color = (2, 52, 112)

    # ==========================================================
    # COULEURS DES RÉSULTATS
    # ==========================================================

    champion_gold: Color = (255, 199, 55)
    champion_gold_light: Color = (255, 226, 125)
    champion_gold_dark: Color = (104, 70, 10)
    champion_gold_deep: Color = (63, 38, 3)

    winner_green: Color = (65, 221, 128)
    winner_green_dark: Color = (19, 98, 61)

    loser_red: Color = (191, 65, 73)
    pending_orange: Color = (247, 158, 48)

    # Colonnes de score volontairement assombries.
    score_background: Color = (207, 210, 218)
    score_winner_background: Color = (230, 215, 176)
    score_loser_background: Color = (174, 181, 194)

    score_text: Color = (15, 18, 26)
    score_winner_text: Color = (77, 39, 4)
    score_loser_text: Color = (47, 52, 64)

    # ==========================================================
    # FORMAT GÉNÉRAL
    # ==========================================================

    header_height: int = 164
    footer_height: int = 64

    horizontal_margin: int = 24
    vertical_margin: int = 14

    round_labels_height: int = 54
    bracket_top_padding: int = 10
    bracket_bottom_padding: int = 10

    center_separator_width: int = 2

    # ==========================================================
    # HEADER
    # ==========================================================

    title_font_size: int = 64
    title_number_font_size: int = 52

    subtitle_font_size: int = 24
    information_font_size: int = 21
    round_font_size: int = 21

    header_title_x: int = 48
    header_title_y: int = 14
    header_metadata_y: int = 92

    header_mascot_x: int = 22
    header_mascot_y: int = 12
    header_mascot_width: int = 100
    header_mascot_height: int = 128

    header_title_with_mascot_x: int = 144

    header_logo_maximum_width: int = 236
    header_logo_maximum_height: int = 150
    header_logo_vertical_offset: int = 0

    header_information_box_height: int = 90
    header_information_box_radius: int = 6
    header_information_box_border_width: int = 2
    header_information_box_gap: int = 10

    date_box_width: int = 220
    tournament_id_box_width: int = 180
    organizer_box_width: int = 260

    header_separator_height: int = 4
    header_red_separator_ratio: float = 0.5

    # ==========================================================
    # FOOTER
    # ==========================================================

    footer_title_font_size: int = 18
    footer_information_font_size: int = 16
    footer_center_font_size: int = 19

    footer_icon_size: int = 38
    footer_discord_logo_size: int = 36

    footer_horizontal_padding: int = 26
    footer_top_separator_height: int = 2

    discord_invite_text: str = "HTTPS://DISCORD.GG/HAMTARO"
    footer_center_text: str = "MERCI À TOUS LES PARTICIPANTS !"

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

    round_title_vertical_padding: int = 7
    round_title_underline_width: int = 132
    round_title_underline_height: int = 4

    round_title_background_enabled: bool = True
    round_title_background_radius: int = 3

    # ==========================================================
    # FINALE
    # ==========================================================

    final_title_font_size: int = 32
    final_name_font_size: int = 25
    final_score_font_size: int = 26

    final_title_height: int = 44
    final_title_width: int = 176
    final_vertical_offset: int = 10

    final_avatar_size: int = 52

    final_title_background: Color = (91, 17, 14)
    final_title_border: Color = (191, 54, 38)
    final_title_radius: int = 5

    final_glow_radius: int = 14
    final_glow_alpha: int = 110

    # ==========================================================
    # CARTE DU CHAMPION
    # ==========================================================

    champion_title_font_size: int = 38
    champion_name_font_size: int = 32
    champion_information_font_size: int = 17

    champion_avatar_size: int = 132

    champion_card_width: int = 330
    champion_card_height: int = 360
    champion_card_radius: int = 8
    champion_card_border_width: int = 2

    champion_card_background: Color = (5, 10, 20)

    champion_trophy_width: int = 82
    champion_trophy_height: int = 82

    champion_image_width: int = 144
    champion_image_height: int = 144

    champion_laurel_width: int = 212
    champion_laurel_height: int = 164

    champion_name_plate_width: int = 220
    champion_name_plate_height: int = 43
    champion_name_plate_radius: int = 4

    champion_glow_radius: int = 24
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

    statistics_title_font_size: int = 17
    statistics_value_font_size: int = 22
    statistics_label_font_size: int = 13

    statistics_title_color: Color = (255, 75, 55)
    statistics_icon_size: int = 17

    statistics_column_count: int = 4
    statistics_separator_width: int = 1

    statistics_background: Color = (7, 13, 25)

    # ==========================================================
    # EFFETS
    # ==========================================================

    side_background_alpha: int = 120
    side_glow_alpha: int = 82

    connector_glow_alpha: int = 70
    connector_secondary_alpha: int = 150

    connector_blur_radius: int = 4
    connector_joint_radius: int = 1

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
    def logo_path(self) -> Path:
        return self.assets_directory / self.logo_filename

    @property
    def background_path(self) -> Path:
        return self.assets_directory / self.background_filename

    @property
    def header_mascot_path(self) -> Path:
        return self.assets_directory / self.header_mascot_filename

    @property
    def trophy_path(self) -> Path:
        return self.assets_directory / self.trophy_filename

    @property
    def champion_path(self) -> Path:
        return self.assets_directory / self.champion_filename

    @property
    def champion_laurel_path(self) -> Path:
        return self.assets_directory / self.champion_laurel_filename

    @property
    def footer_icon_path(self) -> Path:
        return self.assets_directory / self.footer_icon_filename

    @property
    def discord_logo_path(self) -> Path:
        return self.assets_directory / self.discord_logo_filename

    # ==========================================================
    # NORMALISATION DU NOMBRE DE JOUEURS
    # ==========================================================

    @staticmethod
    def normalized_capacity(player_capacity: int) -> int:
        """
        Normalise le nombre de joueurs vers la puissance de deux
        prise en charge la plus proche.
        """

        supported = (2, 4, 8, 16, 32, 64, 128)

        if player_capacity <= 2:
            return 2

        for capacity in supported:
            if player_capacity <= capacity:
                return capacity

        return 128

    # ==========================================================
    # TAILLE DE L'IMAGE
    # ==========================================================

    def canvas_size(self, player_capacity: int) -> tuple[int, int]:
        """
        Retourne les dimensions 16:9 du rendu.
        """

        capacity = self.normalized_capacity(player_capacity)

        sizes = {
            2: (1600, 900),
            4: (1600, 900),
            8: (1600, 900),
            16: (1728, 972),
            32: (1920, 1080),
            64: (2048, 1152),
            128: (2560, 1440),
        }

        return sizes[capacity]

    def image_width(self, player_capacity: int) -> int:
        width, _ = self.canvas_size(player_capacity)
        return width

    def image_height(self, player_capacity: int) -> int:
        _, height = self.canvas_size(player_capacity)
        return height

    # ==========================================================
    # DIMENSIONS DES CASES
    # ==========================================================

    def box_width(self, player_capacity: int) -> int:
        """
        Largeur des matchs ordinaires.
        """

        capacity = self.normalized_capacity(player_capacity)

        widths = {
            2: 310,
            4: 270,
            8: 230,
            16: 188,
            32: 172,
            64: 162,
            128: 150,
        }

        return widths[capacity]

    def box_width_for_round(
        self,
        player_capacity: int,
        round_index: int,
        total_rounds: int,
    ) -> int:
        """
        Élargit les cartes à mesure que l'on approche de la finale.
        """

        capacity = self.normalized_capacity(player_capacity)
        round_index = max(0, min(round_index, max(0, total_rounds - 1)))

        widths_by_capacity = {
            16: (190, 198, 210),
            32: (172, 178, 184, 192),
            64: (162, 170, 180, 190, 204),
            128: (150, 156, 162, 168, 174, 180),
        }

        widths = widths_by_capacity.get(capacity)

        if not widths:
            return self.box_width(player_capacity)

        return widths[min(round_index, len(widths) - 1)]

    def box_height(self, player_capacity: int) -> int:
        """
        Hauteur totale d'une carte contenant deux joueurs.
        """

        capacity = self.normalized_capacity(player_capacity)

        heights = {
            2: 96,
            4: 88,
            8: 78,
            16: 68,
            32: 58,
            64: 48,
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
        Augmente légèrement la hauteur des cartes en approchant
        du centre pour rendre avatars et textes plus lisibles.
        """

        capacity = self.normalized_capacity(player_capacity)
        round_index = max(0, min(round_index, max(0, total_rounds - 1)))

        heights_by_capacity = {
            16: (68, 72, 76),
            32: (58, 62, 66, 70),
            64: (48, 52, 56, 60, 64),
            128: (42, 44, 46, 48, 50, 52),
        }

        heights = heights_by_capacity.get(capacity)

        if not heights:
            return self.box_height(player_capacity)

        return heights[min(round_index, len(heights) - 1)]

    def final_box_width(self, player_capacity: int) -> int:
        """
        Largeur de la grande finale centrale.
        """

        capacity = self.normalized_capacity(player_capacity)

        widths = {
            2: 390,
            4: 365,
            8: 345,
            16: 320,
            32: 295,
            64: 300,
            128: 280,
        }

        return widths[capacity]

    def final_box_height(self, player_capacity: int) -> int:
        """
        Hauteur de la grande finale centrale.
        """

        capacity = self.normalized_capacity(player_capacity)

        heights = {
            2: 134,
            4: 128,
            8: 122,
            16: 116,
            32: 110,
            64: 126,
            128: 102,
        }

        return heights[capacity]

    # ==========================================================
    # COLONNES INTERNES DES MATCHS
    # ==========================================================

    def seed_column_width(self, player_capacity: int) -> int:
        capacity = self.normalized_capacity(player_capacity)

        widths = {
            2: 34,
            4: 32,
            8: 30,
            16: 28,
            32: 25,
            64: 22,
            128: 22,
        }

        return widths.get(capacity, self.seed_column_minimum_width)

    def score_column_width(self, player_capacity: int) -> int:
        capacity = self.normalized_capacity(player_capacity)

        widths = {
            2: 44,
            4: 42,
            8: 40,
            16: 36,
            32: 32,
            64: 29,
            128: 28,
        }

        return widths.get(capacity, self.score_column_minimum_width)

    # ==========================================================
    # AVATARS
    # ==========================================================

    def player_avatar_size(self, player_capacity: int) -> int:
        capacity = self.normalized_capacity(player_capacity)

        sizes = {
            2: 42,
            4: 40,
            8: 36,
            16: 31,
            32: 27,
            64: 21,
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
        Agrandit progressivement les avatars en allant vers le centre.
        """

        capacity = self.normalized_capacity(player_capacity)
        round_index = max(0, min(round_index, max(0, total_rounds - 1)))

        sizes_by_capacity = {
            16: (31, 33, 35),
            32: (27, 29, 31, 33),
            64: (21, 22, 23, 25, 27),
            128: (18, 19, 20, 21, 22, 23),
        }

        sizes = sizes_by_capacity.get(capacity)

        if not sizes:
            return self.player_avatar_size(player_capacity)

        return sizes[min(round_index, len(sizes) - 1)]

    def avatar_size(self, density_hint: int) -> int:
        """
        Compatibilité avec l'ancien service.
        """

        if density_hint >= 128:
            return 18

        if density_hint >= 64:
            return 20

        return 28

    # ==========================================================
    # ESPACEMENT HORIZONTAL
    # ==========================================================

    def column_gap(self, player_capacity: int) -> int:
        """
        Distance entre deux colonnes du bracket.
        """

        capacity = self.normalized_capacity(player_capacity)

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

    def center_reserved_width(self, player_capacity: int) -> int:
        """
        Largeur centrale réservée à la finale,
        au champion et aux statistiques.
        """

        capacity = self.normalized_capacity(player_capacity)

        widths = {
            2: 480,
            4: 440,
            8: 390,
            16: 340,
            32: 315,
            64: 360,
            128: 370,
        }

        return widths[capacity]

    # ==========================================================
    # ESPACEMENT VERTICAL
    # ==========================================================

    def bracket_content_top(self) -> int:
        """
        Position verticale du début des matchs.
        """

        return self.header_height + self.round_labels_height + self.bracket_top_padding

    def bracket_content_bottom(self, player_capacity: int) -> int:
        """
        Position verticale maximale des matchs.
        """

        return self.image_height(player_capacity) - self.footer_height - self.bracket_bottom_padding

    def first_round_vertical_gap(self, player_capacity: int) -> int:
        """
        Distance entre les débuts de deux matchs du premier tour.
        """

        capacity = self.normalized_capacity(player_capacity)

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
    def vertical_gap(self, player_capacity: int) -> int:
        return self.first_round_vertical_gap(player_capacity)

    # ==========================================================
    # POLICES ADAPTATIVES
    # ==========================================================

    def player_name_font_size(self, player_capacity: int) -> int:
        capacity = self.normalized_capacity(player_capacity)

        sizes = {
            2: 21,
            4: 20,
            8: 18,
            16: 16,
            32: 14,
            64: 14,
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
        Augmente légèrement la police des noms dans les derniers tours.
        """

        capacity = self.normalized_capacity(player_capacity)
        round_index = max(0, min(round_index, max(0, total_rounds - 1)))

        sizes_by_capacity = {
            32: (14, 14, 15, 16),
            64: (13, 13, 14, 15, 16),
            128: (11, 11, 12, 12, 13, 14),
        }

        sizes = sizes_by_capacity.get(capacity)

        if not sizes:
            return self.player_name_font_size(player_capacity)

        return sizes[min(round_index, len(sizes) - 1)]

    def player_score_font_size(self, player_capacity: int) -> int:
        capacity = self.normalized_capacity(player_capacity)

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
        capacity = self.normalized_capacity(player_capacity)
        round_index = max(0, min(round_index, max(0, total_rounds - 1)))

        sizes_by_capacity = {
            32: (15, 15, 16, 17),
            64: (14, 14, 15, 16, 17),
            128: (12, 12, 13, 13, 14, 15),
        }

        sizes = sizes_by_capacity.get(capacity)

        if not sizes:
            return self.player_score_font_size(player_capacity)

        return sizes[min(round_index, len(sizes) - 1)]

    def player_seed_font_size(self, player_capacity: int) -> int:
        capacity = self.normalized_capacity(player_capacity)

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

    def round_font_size_for(self, player_capacity: int) -> int:
        capacity = self.normalized_capacity(player_capacity)

        sizes = {
            2: 29,
            4: 28,
            8: 26,
            16: 24,
            32: 22,
            64: 23,
            128: 18,
        }

        return sizes[capacity]

    # ==========================================================
    # ÉPAISSEUR ET LUEUR DES CONNEXIONS
    # ==========================================================

    def connector_width(self, player_capacity: int) -> int:
        capacity = self.normalized_capacity(player_capacity)

        if capacity >= 32:
            return 2

        return 3

    def connector_middle_width(self, player_capacity: int) -> int:
        return self.connector_width(player_capacity) + 2

    def connector_glow_width(self, player_capacity: int) -> int:
        return self.connector_width(player_capacity) + 5

    # ==========================================================
    # OPACITÉ SELON LA RONDE
    # ==========================================================

    def round_card_opacity(self, round_index: int, total_rounds: int) -> int:
        """
        Les premières rondes sont légèrement plus discrètes.
        Les derniers tours deviennent progressivement plus nets.
        """

        if total_rounds <= 1:
            return 255

        progress = max(0.0, min(1.0, round_index / max(1, total_rounds - 1)))
        return round(218 + (37 * progress))

    def round_glow_alpha(self, round_index: int, total_rounds: int) -> int:
        """
        Renforce légèrement la lueur des connecteurs à proximité de la finale.
        """

        if total_rounds <= 1:
            return self.connector_glow_alpha

        progress = max(0.0, min(1.0, round_index / max(1, total_rounds - 1)))
        return round(50 + (35 * progress))

    # ==========================================================
    # VALIDATION
    # ==========================================================

    @staticmethod
    def validate_player_capacity(player_capacity: int) -> None:
        supported = {2, 4, 8, 16, 32, 64, 128}

        if player_capacity not in supported:
            raise ValueError(
                "Le thème graphique Hamtaro prend uniquement "
                "en charge les brackets de 2, 4, 8, 16, 32, "
                "64 ou 128 joueurs."
            )
