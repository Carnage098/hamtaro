from services.team_2v2_service import (
    A_WIN,
    B_WIN,
    DOUBLE_LOSS,
    resolve_encounter,
    standing_sort_key,
)


def test_clean_2_0_is_three_points_in_swiss():
    r = resolve_encounter("swiss", [A_WIN, A_WIN])
    assert r.ready
    assert r.winner_side == "a"
    assert r.points_a == 3
    assert r.points_b == 0


def test_clean_1_1_requires_tiebreak():
    r = resolve_encounter("swiss", [A_WIN, B_WIN])
    assert not r.ready
    assert r.needs_tiebreak


def test_win_plus_double_loss_wins_but_scores_zero():
    r = resolve_encounter("swiss", [A_WIN, DOUBLE_LOSS])
    assert r.ready
    assert r.winner_side == "a"
    assert r.points_a == 0
    assert r.points_b == 0
    assert r.status == "complete_penalized"
    assert r.double_losses == 1


def test_loss_plus_double_loss_is_zero_points():
    r = resolve_encounter("swiss", [A_WIN, DOUBLE_LOSS])
    assert r.points_b == 0


def test_two_double_losses_are_zero_and_no_winner_in_swiss():
    r = resolve_encounter("swiss", [DOUBLE_LOSS, DOUBLE_LOSS])
    assert r.ready
    assert r.winner_side is None
    assert r.points_a == 0
    assert r.points_b == 0
    assert r.status == "double_loss"


def test_tiebreak_double_loss_zeroes_match():
    r = resolve_encounter("swiss", [A_WIN, B_WIN, DOUBLE_LOSS])
    assert r.ready
    assert r.winner_side is None
    assert r.points_a == 0
    assert r.points_b == 0


def test_dl_team_is_below_clean_team_at_equal_points():
    clean = {
        "points": 0,
        "double_losses": 0,
        "wins": 0,
        "losses": 1,
        "buchholz": 0,
        "board_wins": 0,
        "board_losses": 2,
        "team_name": "Clean",
    }
    penalized = {
        "points": 0,
        "double_losses": 1,
        "wins": 1,
        "losses": 0,
        "buchholz": 99,
        "board_wins": 1,
        "board_losses": 0,
        "team_name": "DL",
    }
    assert standing_sort_key(clean) < standing_sort_key(penalized)


def test_elimination_double_loss_without_winner_needs_staff():
    r = resolve_encounter("elimination", [DOUBLE_LOSS, DOUBLE_LOSS])
    assert not r.ready
    assert r.needs_staff
