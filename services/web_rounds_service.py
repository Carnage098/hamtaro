from __future__ import annotations

from collections import defaultdict
from typing import Any

FINAL_STATUSES = {"approved", "cancelled", "completed", "finished", "validated"}
STATUS_LABELS = {
    "approved": "Validé", "cancelled": "Annulé", "completed": "Terminé",
    "finished": "Terminé", "playing": "En cours", "pending": "À jouer",
    "refused": "Refusé", "rejected": "Refusé", "reported": "Résultat envoyé",
    "validated": "Validé", "waiting": "En attente",
}


def row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return {}


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def round_label(number: int) -> str:
    return {
        1: "Finale", 2: "Demi-finales", 3: "Quarts de finale",
        4: "Huitièmes de finale", 5: "Seizièmes de finale",
        6: "Trente-deuxièmes de finale", 7: "Soixante-quatrièmes de finale",
    }.get(number, f"Ronde {number}")


class TournamentRoundsService:
    def __init__(self, db: Any) -> None:
        if db is None:
            raise RuntimeError("Connexion à la base Hamtaro introuvable.")
        self.db = db

    async def one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        row = await self.db.fetchone(query, params)
        return None if row is None else row_dict(row)

    async def all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(query, params)
        return [row_dict(row) for row in rows]

    async def table_exists(self, name: str) -> bool:
        return await self.one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ) is not None

    async def build_payload(self, tournament_id: int) -> dict[str, Any] | None:
        tournament = await self.one("SELECT * FROM tournaments WHERE id=?", (tournament_id,))
        if tournament is None:
            return None

        bracket_rows = []
        swiss_rows = []
        settings = None
        standings_rows = []

        if await self.table_exists("matches"):
            bracket_rows = await self.all(
                "SELECT * FROM matches WHERE tournament_id=? ORDER BY round DESC, match_number ASC, id ASC",
                (tournament_id,),
            )
        if await self.table_exists("swiss_matches"):
            swiss_rows = await self.all(
                "SELECT * FROM swiss_matches WHERE tournament_id=? ORDER BY round_number ASC, table_number ASC, id ASC",
                (tournament_id,),
            )
        if await self.table_exists("swiss_settings"):
            settings = await self.one("SELECT * FROM swiss_settings WHERE tournament_id=?", (tournament_id,))
        if await self.table_exists("swiss_standings"):
            standings_rows = await self.all("SELECT * FROM swiss_standings WHERE tournament_id=?", (tournament_id,))

        current_round = as_int((settings or {}).get("current_round") or tournament.get("current_round"))
        total_rounds = as_int((settings or {}).get("total_rounds") or tournament.get("total_rounds"))
        bracket = self.bracket_rounds(bracket_rows)
        swiss = self.swiss_rounds(swiss_rows, current_round)
        standings = self.standings(standings_rows)

        raw_type = str(tournament.get("tournament_type") or "").lower()
        has_swiss = bool(swiss or settings or raw_type == "swiss")
        has_bracket = bool(bracket)
        if has_swiss and has_bracket:
            display_type, display_label = "hybrid", "Rondes suisses + Top Cut"
        elif has_swiss:
            display_type, display_label = "swiss", "Rondes suisses"
        else:
            display_type, display_label = "single_elimination", "Élimination directe"

        return {
            "tournament": {
                "id": as_int(tournament.get("id")),
                "name": str(tournament.get("name") or "Tournoi Hamtaro"),
                "code": str(tournament.get("code") or ""),
                "format": str(tournament.get("format") or "Format inconnu"),
                "status": str(tournament.get("status") or ""),
                "current_round": current_round,
                "total_rounds": total_rounds,
                "display_type": display_type,
                "display_type_label": display_label,
            },
            "bracket": {"available": has_bracket, "rounds": bracket},
            "swiss": {
                "available": has_swiss,
                "current_round": current_round,
                "total_rounds": total_rounds,
                "rounds": swiss,
                "standings": standings,
            },
        }

    def score(self, row: dict[str, Any], player: int) -> str:
        value = row.get(f"player{player}_score")
        if value is not None:
            return str(value)
        raw = str(row.get("score") or "").replace("–", "-").replace(":", "-")
        parts = [part.strip() for part in raw.split("-")]
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            return parts[player - 1]
        return "—"

    def public_match(self, row: dict[str, Any], kind: str) -> dict[str, Any]:
        status = str(row.get("status") or "pending").lower()
        p1_id, p2_id = str(row.get("player1_id") or ""), str(row.get("player2_id") or "")
        p1_name = str(row.get("player1_name") or "À déterminer")
        is_bye = bool(as_int(row.get("is_bye"))) or not p2_id
        p2_name = "BYE" if is_bye else str(row.get("player2_name") or "À déterminer")
        winner_id, winner_name = str(row.get("winner_id") or ""), str(row.get("winner_name") or "")
        result = str(row.get("result") or "").lower().replace("-", "_").replace(" ", "_")
        double_loss = bool(as_int(row.get("is_double_loss"))) or result == "double_loss"
        final = status in FINAL_STATUSES or bool(winner_id) or is_bye or double_loss
        label = "Double défaite" if double_loss else "BYE" if is_bye else STATUS_LABELS.get(status, status.title())
        return {
            "id": as_int(row.get("id")), "kind": kind,
            "order": as_int(row.get("match_number") or row.get("bracket_position")),
            "table_number": as_int(row.get("table_number")),
            "status": status, "status_label": label, "is_final": final,
            "is_bye": is_bye, "is_double_loss": double_loss,
            "player1": {"name": p1_name, "score": self.score(row, 1), "winner": bool(winner_name and (winner_id == p1_id or winner_name == p1_name))},
            "player2": {"name": p2_name, "score": "—" if is_bye else self.score(row, 2), "winner": bool(winner_name and (winner_id == p2_id or winner_name == p2_name))},
        }

    def bracket_rounds(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            number = as_int(row.get("round"))
            if number > 0:
                grouped[number].append(self.public_match(row, "bracket"))
        result = []
        for number in sorted(grouped, reverse=True):
            matches = sorted(grouped[number], key=lambda m: (m["order"], m["id"]))
            result.append({
                "number": number, "label": round_label(number),
                "is_current": any(not m["is_final"] for m in matches),
                "match_count": len(matches),
                "completed_count": sum(1 for m in matches if m["is_final"]),
                "matches": matches,
            })
        return result

    def swiss_rounds(self, rows: list[dict[str, Any]], current_round: int) -> list[dict[str, Any]]:
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            number = as_int(row.get("round_number"))
            if number > 0:
                grouped[number].append(self.public_match(row, "swiss"))
        result = []
        for number in sorted(grouped):
            matches = sorted(grouped[number], key=lambda m: (m["table_number"], m["id"]))
            result.append({
                "number": number, "label": f"Ronde {number}", "is_current": number == current_round,
                "match_count": len(matches),
                "completed_count": sum(1 for m in matches if m["is_final"]),
                "matches": matches,
            })
        return result

    def standings(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = sorted(rows, key=lambda r: (-as_int(r.get("points")), as_int(r.get("double_losses")), -as_int(r.get("wins")), as_int(r.get("losses")), str(r.get("username") or r.get("player_name") or "")))
        result = []
        for index, row in enumerate(rows, start=1):
            name = row.get("username") or row.get("player_name") or row.get("display_name") or row.get("discord_id") or "Joueur"
            result.append({
                "rank": as_int(row.get("rank"), index), "name": str(name),
                "points": as_int(row.get("points")), "wins": as_int(row.get("wins")),
                "losses": as_int(row.get("losses")), "double_losses": as_int(row.get("double_losses")),
                "byes": as_int(row.get("byes")),
            })
        return result
