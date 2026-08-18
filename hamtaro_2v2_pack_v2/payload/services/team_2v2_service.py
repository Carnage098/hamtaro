from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

A_WIN = "a_win"
B_WIN = "b_win"
DOUBLE_LOSS = "double_loss"


@dataclass(frozen=True, slots=True)
class EncounterResolution:
    ready: bool
    needs_tiebreak: bool = False
    needs_staff: bool = False
    winner_side: str | None = None
    points_a: int = 0
    points_b: int = 0
    status: str = "open"
    double_losses: int = 0


def normalize_result(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value).strip().lower()
    aliases = {
        "a": A_WIN,
        "a_win": A_WIN,
        "team_a": A_WIN,
        "b": B_WIN,
        "b_win": B_WIN,
        "team_b": B_WIN,
        "dl": DOUBLE_LOSS,
        "double_loss": DOUBLE_LOSS,
        "double-loss": DOUBLE_LOSS,
    }
    return aliases.get(value)


def resolve_encounter(
    mode: str,
    board_results: Sequence[str | None],
) -> EncounterResolution:
    """
    Résout une rencontre 2v2 Hamtaro.

    Règle suisse spéciale :
    - 2-0 ou 2-1 sans double loss : 3 points au vainqueur.
    - 1 victoire + 1 double loss : l'équipe avec la victoire gagne la
      rencontre, MAIS 0 point pour les deux équipes.
    - défaite + double loss : 0 point, une défaite et une pénalité DL.
    - toute rencontre contenant une double loss ne peut jamais donner 3 points.
    - à 1-1 propre après les deux boards initiaux, un board 3 est nécessaire.

    En élimination, les points ne sont pas utilisés. Une situation sans
    vainqueur après une double loss décisive doit être arbitrée par le staff.
    """
    mode = str(mode).strip().lower()
    if mode not in {"swiss", "elimination"}:
        raise ValueError("mode doit être 'swiss' ou 'elimination'")

    results = [normalize_result(r) for r in board_results]
    if len(results) < 2 or results[0] is None or results[1] is None:
        return EncounterResolution(ready=False, status="open")

    first_two = results[:2]
    a = first_two.count(A_WIN)
    b = first_two.count(B_WIN)
    dl = first_two.count(DOUBLE_LOSS)

    # Une DL sur un des deux boards initiaux : pas de duel décisif si une
    # équipe possède déjà l'unique victoire de la rencontre.
    if dl:
        if a > b:
            return EncounterResolution(
                ready=True,
                winner_side="a",
                points_a=0,
                points_b=0,
                status="complete_penalized",
                double_losses=dl,
            )
        if b > a:
            return EncounterResolution(
                ready=True,
                winner_side="b",
                points_a=0,
                points_b=0,
                status="complete_penalized",
                double_losses=dl,
            )

        # 2 DL : aucun vainqueur sportif.
        if mode == "elimination":
            return EncounterResolution(
                ready=False,
                needs_staff=True,
                status="needs_staff",
                double_losses=dl,
            )
        return EncounterResolution(
            ready=True,
            winner_side=None,
            points_a=0,
            points_b=0,
            status="double_loss",
            double_losses=dl,
        )

    # Victoire propre 2-0.
    if a == 2:
        return EncounterResolution(
            ready=True,
            winner_side="a",
            points_a=3 if mode == "swiss" else 0,
            points_b=0,
            status="complete",
        )
    if b == 2:
        return EncounterResolution(
            ready=True,
            winner_side="b",
            points_a=0,
            points_b=3 if mode == "swiss" else 0,
            status="complete",
        )

    # 1-1 propre : board décisif.
    if len(results) < 3 or results[2] is None:
        return EncounterResolution(
            ready=False,
            needs_tiebreak=True,
            status="tiebreak_required",
        )

    third = results[2]
    if third == A_WIN:
        return EncounterResolution(
            ready=True,
            winner_side="a",
            points_a=3 if mode == "swiss" else 0,
            points_b=0,
            status="complete",
        )
    if third == B_WIN:
        return EncounterResolution(
            ready=True,
            winner_side="b",
            points_a=0,
            points_b=3 if mode == "swiss" else 0,
            status="complete",
        )

    # Double loss sur le duel décisif : 0 point pour tout le monde en suisse.
    if third == DOUBLE_LOSS:
        if mode == "elimination":
            return EncounterResolution(
                ready=False,
                needs_staff=True,
                status="needs_staff",
                double_losses=1,
            )
        return EncounterResolution(
            ready=True,
            winner_side=None,
            points_a=0,
            points_b=0,
            status="double_loss",
            double_losses=1,
        )

    return EncounterResolution(ready=False, status="open")


def standing_sort_key(row: dict) -> tuple:
    """
    Tri volontairement sévère pour les double losses.

    A points égaux :
    1) aucune DL avant toute équipe ayant une DL ;
    2) moins de DL ;
    3) plus de victoires ;
    4) meilleur Buchholz ;
    5) meilleure différence de boards ;
    6) moins de défaites.
    """
    points = int(row.get("points", 0))
    dls = int(row.get("double_losses", 0))
    wins = int(row.get("wins", 0))
    losses = int(row.get("losses", 0))
    buchholz = int(row.get("buchholz", 0))
    board_diff = int(row.get("board_wins", 0)) - int(row.get("board_losses", 0))
    return (
        -points,
        1 if dls > 0 else 0,
        dls,
        -wins,
        -buchholz,
        -board_diff,
        losses,
        str(row.get("team_name", "")).casefold(),
    )
