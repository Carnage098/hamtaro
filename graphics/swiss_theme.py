from __future__ import annotations

from dataclasses import dataclass

from graphics.theme import Color, HamtaroBracketTheme


@dataclass(slots=True)
class HamtaroSwissTheme(HamtaroBracketTheme):
    """Thème du tableau des rondes suisses, dérivé de la V18."""

    swiss_width: int = 2560
    swiss_height: int = 1440

    swiss_outer_margin: int = 24
    swiss_panel_gap: int = 18
    swiss_content_top_gap: int = 18
    swiss_content_bottom_gap: int = 18

    swiss_panel_radius: int = 10
    swiss_panel_border_width: int = 2
    swiss_panel_header_height: int = 62

    swiss_left_panel_width: int = 720
    swiss_right_panel_width: int = 500

    swiss_section_title_font_size: int = 30
    swiss_section_subtitle_font_size: int = 17

    swiss_standing_row_height: int = 60
    swiss_standing_avatar_size: int = 38
    swiss_standing_name_font_size: int = 20
    swiss_standing_stats_font_size: int = 15
    swiss_standing_points_font_size: int = 22

    swiss_match_card_height: int = 108
    swiss_match_card_gap: int = 12
    swiss_match_avatar_size: int = 36
    swiss_match_name_font_size: int = 18
    swiss_match_points_font_size: int = 14
    swiss_match_status_font_size: int = 14
    swiss_match_table_font_size: int = 16

    swiss_progress_row_height: int = 50
    swiss_progress_font_size: int = 18
    swiss_stat_value_font_size: int = 28
    swiss_stat_label_font_size: int = 14

    swiss_rank_gold: Color = (255, 199, 55)
    swiss_rank_silver: Color = (207, 214, 226)
    swiss_rank_bronze: Color = (205, 127, 50)

    swiss_pending: Color = (42, 145, 255)
    swiss_completed: Color = (65, 221, 128)
    swiss_double_loss: Color = (226, 72, 84)
    swiss_bye: Color = (173, 181, 199)

    swiss_podium_card_width: int = 690
    swiss_podium_card_height: int = 260
    swiss_podium_avatar_size: int = 116

    swiss_footer_round_text: str = "RONDE SUISSE EN COURS - BON DUEL A TOUS !"
    swiss_footer_standings_text: str = "CLASSEMENT ACTUALISE APRES VALIDATION DU STAFF"
    swiss_footer_final_text: str = "CLASSEMENT FINAL DES RONDES SUISSES"
