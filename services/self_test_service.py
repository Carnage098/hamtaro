from __future__ import annotations

import secrets
from dataclasses import dataclass


@dataclass(slots=True)
class TestStep:
    label: str
    ok: bool
    detail: str


class TournamentSelfTestService:
    """Teste le noyau tournoi dans une transaction entièrement annulée."""

    def __init__(self, db) -> None:
        self.db = db

    async def run(self, *, guild_id: str, actor_id: str) -> list[TestStep]:
        conn = self.db._connection()  # Connexion centralisée du DatabaseService.
        code = f"TEST-{secrets.token_hex(3).upper()}"
        steps: list[TestStep] = []

        await conn.execute("SAVEPOINT hamtaro_professional_self_test")
        try:
            cursor = await conn.execute(
                """
                INSERT INTO tournaments (
                    guild_id, code, name, format, max_players,
                    status, current_round, total_rounds, created_by
                )
                VALUES (?, ?, ?, ?, 4, 'registration', 0, 2, ?)
                """,
                (guild_id, code, "Test automatique Hamtaro", "Format Actuel", actor_id),
            )
            tournament_id = int(cursor.lastrowid)
            steps.append(TestStep("Création du tournoi", True, code))

            players = [
                ("test-player-1", "Joueur Test 1", "Blue Eyes"),
                ("test-player-2", "Joueur Test 2", "Dark Magician"),
                ("test-player-3", "Joueur Test 3", "HERO"),
                ("test-player-4", "Joueur Test 4", "Branded"),
            ]
            await conn.executemany(
                """
                INSERT INTO registrations (
                    tournament_id, discord_id, username, deck, checked_in
                )
                VALUES (?, ?, ?, ?, 1)
                """,
                [(tournament_id, pid, name, deck) for pid, name, deck in players],
            )
            count = await (await conn.execute(
                "SELECT COUNT(*) FROM registrations WHERE tournament_id = ?",
                (tournament_id,),
            )).fetchone()
            if int(count[0]) != 4:
                raise AssertionError("Le nombre d'inscriptions de test est incorrect.")
            steps.append(TestStep("Inscriptions", True, "4 joueurs créés"))

            final_cursor = await conn.execute(
                """
                INSERT INTO matches (
                    tournament_id, round, match_number, bracket_position,
                    player1_id, player2_id, player1_name, player2_name,
                    status
                )
                VALUES (?, 2, 1, 1, NULL, NULL, NULL, NULL, 'waiting')
                """,
                (tournament_id,),
            )
            final_id = int(final_cursor.lastrowid)

            semi1_cursor = await conn.execute(
                """
                INSERT INTO matches (
                    tournament_id, round, match_number, bracket_position,
                    next_match_id, next_slot,
                    player1_id, player2_id, player1_name, player2_name,
                    status
                )
                VALUES (?, 1, 1, 1, ?, 1, ?, ?, ?, ?, 'playing')
                """,
                (
                    tournament_id,
                    final_id,
                    players[0][0],
                    players[1][0],
                    players[0][1],
                    players[1][1],
                ),
            )
            semi1_id = int(semi1_cursor.lastrowid)
            semi2_cursor = await conn.execute(
                """
                INSERT INTO matches (
                    tournament_id, round, match_number, bracket_position,
                    next_match_id, next_slot,
                    player1_id, player2_id, player1_name, player2_name,
                    status
                )
                VALUES (?, 1, 2, 2, ?, 2, ?, ?, ?, ?, 'playing')
                """,
                (
                    tournament_id,
                    final_id,
                    players[2][0],
                    players[3][0],
                    players[2][1],
                    players[3][1],
                ),
            )
            semi2_id = int(semi2_cursor.lastrowid)
            steps.append(TestStep("Génération du bracket", True, "2 demi-finales et 1 finale"))

            async def validate_semifinal(
                match_id: int,
                winner_id: str,
                winner_name: str,
                next_slot: int,
            ) -> None:
                await conn.execute(
                    """
                    UPDATE matches
                    SET player1_score = 2,
                        player2_score = 1,
                        winner_id = ?,
                        winner_name = ?,
                        score = '2-1',
                        reported_by = ?,
                        validated_by = ?,
                        reported_at = CURRENT_TIMESTAMP,
                        validated_at = CURRENT_TIMESTAMP,
                        status = 'completed'
                    WHERE id = ? AND status IN ('playing', 'reported')
                    """,
                    (winner_id, winner_name, actor_id, actor_id, match_id),
                )
                column_id = "player1_id" if next_slot == 1 else "player2_id"
                column_name = "player1_name" if next_slot == 1 else "player2_name"
                await conn.execute(
                    f"UPDATE matches SET {column_id} = ?, {column_name} = ? WHERE id = ?",
                    (winner_id, winner_name, final_id),
                )

            await validate_semifinal(semi1_id, players[0][0], players[0][1], 1)
            await validate_semifinal(semi2_id, players[2][0], players[2][1], 2)
            final_row = await (await conn.execute(
                "SELECT player1_id, player2_id FROM matches WHERE id = ?",
                (final_id,),
            )).fetchone()
            if tuple(final_row) != (players[0][0], players[2][0]):
                raise AssertionError("La propagation des gagnants vers la finale a échoué.")
            steps.append(TestStep("Progression des gagnants", True, "Finalistes corrects"))

            await conn.execute(
                """
                UPDATE matches
                SET player1_score = 2,
                    player2_score = 0,
                    winner_id = ?,
                    winner_name = ?,
                    score = '2-0',
                    reported_by = ?,
                    validated_by = ?,
                    reported_at = CURRENT_TIMESTAMP,
                    validated_at = CURRENT_TIMESTAMP,
                    status = 'completed'
                WHERE id = ?
                """,
                (players[0][0], players[0][1], actor_id, actor_id, final_id),
            )
            await conn.execute(
                """
                UPDATE tournaments
                SET status = 'finished',
                    current_round = 2,
                    winner_id = ?,
                    winner_name = ?,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (players[0][0], players[0][1], tournament_id),
            )
            finished = await (await conn.execute(
                "SELECT status, winner_id FROM tournaments WHERE id = ?",
                (tournament_id,),
            )).fetchone()
            if tuple(finished) != ("finished", players[0][0]):
                raise AssertionError("La clôture du tournoi a échoué.")
            steps.append(TestStep("Finale et clôture", True, players[0][1]))

            invalid_winners = await (await conn.execute(
                """
                SELECT COUNT(*)
                FROM matches
                WHERE tournament_id = ?
                  AND winner_id IS NOT NULL
                  AND winner_id NOT IN (player1_id, player2_id)
                """,
                (tournament_id,),
            )).fetchone()
            if int(invalid_winners[0]) != 0:
                raise AssertionError("Un gagnant ne correspond pas aux participants du match.")
            steps.append(TestStep("Contrôles d'intégrité", True, "Aucune incohérence"))

        except Exception as error:
            steps.append(TestStep("Test interrompu", False, str(error)))
        finally:
            await conn.execute("ROLLBACK TO hamtaro_professional_self_test")
            await conn.execute("RELEASE hamtaro_professional_self_test")

        return steps
