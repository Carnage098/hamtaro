from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.expansion_database import expansion_connection, utcnow_iso


@dataclass(slots=True)
class SwissPlayer:
    discord_id: str
    username: str
    points: int
    wins: int
    losses: int
    byes: int
    buchholz: int = 0
    opponent_win_rate: float = 0.0


class SwissPairingService:
    """Appariements suisses avec prévention des rematches et départages lisibles."""

    async def standings(self, tournament_id: int) -> list[dict[str, Any]]:
        async with expansion_connection() as db:
            registrations = await (
                await db.execute(
                    """
                    SELECT discord_id, username
                    FROM registrations
                    WHERE tournament_id=? AND dropped=0 AND disqualified=0
                    ORDER BY registered_at, id
                    """,
                    (tournament_id,),
                )
            ).fetchall()
            matches = await (
                await db.execute(
                    """
                    SELECT * FROM swiss_matches
                    WHERE tournament_id=? AND status='completed'
                    ORDER BY round_number, table_number
                    """,
                    (tournament_id,),
                )
            ).fetchall()

        players: dict[str, SwissPlayer] = {
            str(row["discord_id"]): SwissPlayer(
                discord_id=str(row["discord_id"]),
                username=str(row["username"]),
                points=0,
                wins=0,
                losses=0,
                byes=0,
            )
            for row in registrations
        }
        opponents: dict[str, list[str]] = {player_id: [] for player_id in players}

        for row in matches:
            p1 = str(row["player1_id"])
            p2 = str(row["player2_id"]) if row["player2_id"] is not None else None
            if p1 not in players:
                continue
            if int(row["is_bye"] or 0) == 1 or p2 is None:
                players[p1].points += 3
                players[p1].wins += 1
                players[p1].byes += 1
                continue
            if p2 not in players:
                continue
            opponents[p1].append(p2)
            opponents[p2].append(p1)
            winner = str(row["winner_id"]) if row["winner_id"] else None
            double_loss = int(row["is_double_loss"] or 0) == 1
            if double_loss or winner is None:
                players[p1].losses += 1
                players[p2].losses += 1
            elif winner == p1:
                players[p1].points += 3
                players[p1].wins += 1
                players[p2].losses += 1
            elif winner == p2:
                players[p2].points += 3
                players[p2].wins += 1
                players[p1].losses += 1

        for player_id, player in players.items():
            opponent_ids = opponents[player_id]
            player.buchholz = sum(players[opponent_id].points for opponent_id in opponent_ids)
            opponent_games = sum(
                players[opponent_id].wins + players[opponent_id].losses
                for opponent_id in opponent_ids
            )
            opponent_wins = sum(players[opponent_id].wins for opponent_id in opponent_ids)
            player.opponent_win_rate = (
                opponent_wins / opponent_games * 100.0 if opponent_games else 0.0
            )

        ordered = sorted(
            players.values(),
            key=lambda player: (
                -player.points,
                -player.buchholz,
                -player.opponent_win_rate,
                -player.wins,
                player.losses,
                player.username.casefold(),
            ),
        )
        result: list[dict[str, Any]] = []
        for rank, player in enumerate(ordered, start=1):
            result.append(
                {
                    "rank": rank,
                    "discord_id": player.discord_id,
                    "username": player.username,
                    "points": player.points,
                    "wins": player.wins,
                    "losses": player.losses,
                    "byes": player.byes,
                    "buchholz": player.buchholz,
                    "opponent_win_rate": player.opponent_win_rate,
                }
            )
        return result

    async def generate_next_round(self, tournament_id: int) -> dict[str, Any]:
        standings = await self.standings(tournament_id)
        if len(standings) < 2:
            raise ValueError("Il faut au moins deux joueurs pour générer une ronde.")

        async with expansion_connection() as db:
            tournament = await (
                await db.execute("SELECT * FROM tournaments WHERE id=?", (tournament_id,))
            ).fetchone()
            if tournament is None:
                raise ValueError("Tournoi introuvable.")
            settings = await (
                await db.execute(
                    "SELECT * FROM swiss_settings WHERE tournament_id=?",
                    (tournament_id,),
                )
            ).fetchone()
            if settings is None:
                raise ValueError("Ce tournoi n'est pas configuré en rondes suisses.")
            current_round = int(settings["current_round"] or 0)
            next_round = current_round + 1
            total_rounds = int(settings["total_rounds"] or 0)
            if total_rounds and next_round > total_rounds:
                raise ValueError("Toutes les rondes prévues ont déjà été générées.")
            existing = await (
                await db.execute(
                    """
                    SELECT COUNT(*) AS total FROM swiss_matches
                    WHERE tournament_id=? AND round_number=?
                    """,
                    (tournament_id, next_round),
                )
            ).fetchone()
            if int(existing["total"]) > 0:
                raise ValueError("Cette ronde existe déjà.")
            if current_round > 0:
                unfinished = await (
                    await db.execute(
                        """
                        SELECT COUNT(*) AS total FROM swiss_matches
                        WHERE tournament_id=? AND round_number=? AND status<>'completed'
                        """,
                        (tournament_id, current_round),
                    )
                ).fetchone()
                if int(unfinished["total"]) > 0:
                    raise ValueError("La ronde actuelle contient encore des matchs non terminés.")
            history_rows = await (
                await db.execute(
                    """
                    SELECT player1_id, player2_id
                    FROM swiss_matches
                    WHERE tournament_id=? AND player2_id IS NOT NULL
                    """,
                    (tournament_id,),
                )
            ).fetchall()

        played_pairs = {
            frozenset((str(row["player1_id"]), str(row["player2_id"])))
            for row in history_rows
        }
        player_by_id = {str(player["discord_id"]): player for player in standings}
        ordered_ids = [str(player["discord_id"]) for player in standings]
        bye_player: str | None = None
        if len(ordered_ids) % 2 == 1:
            bye_candidates = sorted(
                ordered_ids,
                key=lambda player_id: (
                    int(player_by_id[player_id]["byes"]),
                    int(player_by_id[player_id]["points"]),
                    int(player_by_id[player_id]["buchholz"]),
                    player_by_id[player_id]["username"].casefold(),
                ),
            )
            bye_player = bye_candidates[0]
            ordered_ids.remove(bye_player)

        pairs = self._pair_players(ordered_ids, player_by_id, played_pairs)
        if pairs is None:
            raise ValueError("Impossible de générer des appariements cohérents.")

        async with expansion_connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            table_number = 1
            created: list[dict[str, Any]] = []
            for player1_id, player2_id, rematch in pairs:
                p1 = player_by_id[player1_id]
                p2 = player_by_id[player2_id]
                cursor = await db.execute(
                    """
                    INSERT INTO swiss_matches(
                        tournament_id, round_number, table_number,
                        player1_id, player1_name, player2_id, player2_name,
                        status, result, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 'none', ?)
                    """,
                    (
                        tournament_id,
                        next_round,
                        table_number,
                        player1_id,
                        p1["username"],
                        player2_id,
                        p2["username"],
                        utcnow_iso(),
                    ),
                )
                created.append(
                    {
                        "id": int(cursor.lastrowid),
                        "table_number": table_number,
                        "player1_id": player1_id,
                        "player1_name": p1["username"],
                        "player2_id": player2_id,
                        "player2_name": p2["username"],
                        "rematch": rematch,
                    }
                )
                table_number += 1

            if bye_player is not None:
                player = player_by_id[bye_player]
                cursor = await db.execute(
                    """
                    INSERT INTO swiss_matches(
                        tournament_id, round_number, table_number,
                        player1_id, player1_name, player2_id, player2_name,
                        player1_score, player2_score, winner_id, winner_name,
                        is_bye, result, status, finished_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 2, 0, ?, ?, 1,
                              'player1', 'completed', ?, ?)
                    """,
                    (
                        tournament_id,
                        next_round,
                        table_number,
                        bye_player,
                        player["username"],
                        bye_player,
                        player["username"],
                        utcnow_iso(),
                        utcnow_iso(),
                    ),
                )
                created.append(
                    {
                        "id": int(cursor.lastrowid),
                        "table_number": table_number,
                        "player1_id": bye_player,
                        "player1_name": player["username"],
                        "player2_id": None,
                        "player2_name": "BYE",
                        "rematch": False,
                        "bye": True,
                    }
                )

            await db.execute(
                "UPDATE swiss_settings SET current_round=? WHERE tournament_id=?",
                (next_round, tournament_id),
            )
            await db.execute(
                "UPDATE tournaments SET current_round=? WHERE id=?",
                (next_round, tournament_id),
            )
            await db.commit()

        return {
            "round_number": next_round,
            "matches": created,
            "forced_rematches": sum(1 for pair in created if pair.get("rematch")),
        }

    def _pair_players(
        self,
        player_ids: list[str],
        players: dict[str, dict[str, Any]],
        played_pairs: set[frozenset[str]],
    ) -> list[tuple[str, str, bool]] | None:
        best: tuple[int, list[tuple[str, str, bool]]] | None = None

        def cost(player1_id: str, player2_id: str) -> int:
            score_gap = abs(
                int(players[player1_id]["points"]) - int(players[player2_id]["points"])
            )
            rank_gap = abs(
                int(players[player1_id]["rank"]) - int(players[player2_id]["rank"])
            )
            rematch = frozenset((player1_id, player2_id)) in played_pairs
            return score_gap * 100 + rank_gap + (10000 if rematch else 0)

        def search(
            remaining: list[str],
            current: list[tuple[str, str, bool]],
            current_cost: int,
        ) -> None:
            nonlocal best
            if not remaining:
                if best is None or current_cost < best[0]:
                    best = (current_cost, list(current))
                return
            if best is not None and current_cost >= best[0]:
                return
            first = remaining[0]
            candidates = sorted(remaining[1:], key=lambda candidate: cost(first, candidate))
            for candidate in candidates:
                pair_cost = cost(first, candidate)
                next_remaining = [
                    player_id
                    for player_id in remaining[1:]
                    if player_id != candidate
                ]
                current.append(
                    (
                        first,
                        candidate,
                        frozenset((first, candidate)) in played_pairs,
                    )
                )
                search(next_remaining, current, current_cost + pair_cost)
                current.pop()

        search(list(player_ids), [], 0)
        return best[1] if best else None
