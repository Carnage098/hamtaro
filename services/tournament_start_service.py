from __future__ import annotations

import asyncio
import math
import random
import re
from dataclasses import dataclass
from typing import Any, Iterable

from services.bracket_service import BracketService
from services.expansion_database import expansion_connection, utcnow_iso


SINGLE_ELIMINATION = "single_elimination"
SWISS = "swiss"
MIN_ELIMINATION_PLAYERS = 2
MAX_ELIMINATION_PLAYERS = 128


@dataclass(slots=True, frozen=True)
class PreviewPlayer:
    discord_id: str
    username: str
    seed: int


@dataclass(slots=True, frozen=True)
class PreviewPairing:
    round_number: int
    table_number: int
    player1_id: str
    player1_name: str
    player2_id: str | None
    player2_name: str | None
    is_bye: bool = False


class TournamentStartService:
    """Prépare puis confirme le démarrage d'un tournoi sans effet immédiat."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.db = bot.db
        self.brackets = BracketService(self.db)
        self._locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def value(item: Any, name: str, default: Any = None) -> Any:
        if item is None:
            return default
        if isinstance(item, dict):
            return item.get(name, default)
        try:
            return item[name]
        except (KeyError, TypeError, IndexError):
            return getattr(item, name, default)

    @classmethod
    def tournament_type(cls, tournament: Any) -> str:
        raw = str(cls.value(tournament, "tournament_type", "") or "")
        if raw == SWISS or bool(cls.value(tournament, "is_swiss", False)):
            return SWISS
        return SINGLE_ELIMINATION

    @classmethod
    def status_value(cls, tournament: Any) -> str:
        raw = cls.value(tournament, "status", "")
        return str(getattr(raw, "value", raw) or "").lower().strip()

    @staticmethod
    def default_swiss_rounds(player_count: int) -> int:
        if player_count < 2:
            return 1
        # Trois rondes minimum donnent un vrai classement, puis une ronde
        # supplémentaire à chaque doublement du nombre de joueurs.
        return max(3, math.ceil(math.log2(player_count)))

    @staticmethod
    def bracket_size(player_count: int) -> int:
        if not MIN_ELIMINATION_PLAYERS <= player_count <= MAX_ELIMINATION_PLAYERS:
            raise ValueError(
                "Un tournoi à élimination directe doit contenir entre "
                "2 et 128 joueurs actifs."
            )
        return 1 << math.ceil(math.log2(player_count))

    @classmethod
    def elimination_rounds(cls, player_count: int) -> int:
        return int(math.log2(cls.bracket_size(player_count)))

    @staticmethod
    def bracket_seed_order(bracket_size: int) -> list[int]:
        """Ordre classique des seeds dans un bracket équilibré."""
        if bracket_size < 2 or bracket_size > MAX_ELIMINATION_PLAYERS:
            raise ValueError("Taille de bracket non prise en charge.")
        if bracket_size & (bracket_size - 1):
            raise ValueError("La taille du bracket doit être une puissance de deux.")
        if bracket_size == 2:
            return [1, 2]

        order = [1, 2]
        while len(order) < bracket_size:
            next_size = len(order) * 2
            next_order: list[int] = []
            for seed in order:
                next_order.extend((seed, next_size + 1 - seed))
            order = next_order
        return order

    @staticmethod
    def parse_seed_order(
        raw_text: str,
        participant_ids: Iterable[str],
    ) -> list[str]:
        """
        Accepte une liste d'identifiants, avec ou sans numéro de seed.

        Exemples :
        1 = 123456789
        2 = <@987654321>
        ou simplement un identifiant par ligne.
        """
        expected = {str(value) for value in participant_ids}
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if len(lines) != len(expected):
            raise ValueError(
                f"Il faut exactement {len(expected)} ligne(s), une par joueur."
            )

        explicit: dict[int, str] = {}
        sequential: list[str] = []
        saw_explicit = False
        saw_sequential = False

        for line in lines:
            mention_match = re.search(r"(?:<@!?)?(\d{5,25})(?:>)?", line)
            if mention_match is None:
                raise ValueError(f"Identifiant Discord introuvable dans : {line}")
            discord_id = mention_match.group(1)

            seed_match = re.match(r"^\s*(\d{1,3})\s*(?:=|:|-|>)", line)
            if seed_match is not None:
                saw_explicit = True
                seed = int(seed_match.group(1))
                if seed in explicit:
                    raise ValueError(f"Le seed {seed} est utilisé plusieurs fois.")
                explicit[seed] = discord_id
            else:
                saw_sequential = True
                sequential.append(discord_id)

        if saw_explicit and saw_sequential:
            raise ValueError(
                "Utilise soit `seed = identifiant` sur toutes les lignes, "
                "soit seulement un identifiant par ligne."
            )

        if saw_explicit:
            required_seeds = set(range(1, len(expected) + 1))
            if set(explicit) != required_seeds:
                raise ValueError(
                    "Les seeds doivent former une suite complète de 1 à "
                    f"{len(expected)}."
                )
            ordered = [explicit[index] for index in range(1, len(expected) + 1)]
        else:
            ordered = sequential

        if len(set(ordered)) != len(ordered):
            raise ValueError("Un joueur apparaît plusieurs fois dans la liste.")
        missing = expected - set(ordered)
        unknown = set(ordered) - expected
        if missing or unknown:
            details: list[str] = []
            if missing:
                details.append("joueurs manquants : " + ", ".join(sorted(missing)))
            if unknown:
                details.append("identifiants inconnus : " + ", ".join(sorted(unknown)))
            raise ValueError("Liste de seeds invalide — " + " ; ".join(details))
        return ordered

    async def _active_registrations(self, tournament_id: int) -> list[dict[str, Any]]:
        async with expansion_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT discord_id, username, seed
                    FROM registrations
                    WHERE tournament_id=?
                      AND COALESCE(dropped, 0)=0
                      AND COALESCE(disqualified, 0)=0
                    ORDER BY
                        CASE WHEN seed IS NULL THEN 1 ELSE 0 END,
                        seed ASC,
                        username COLLATE NOCASE ASC,
                        discord_id ASC
                    """,
                    (tournament_id,),
                )
            ).fetchall()
        return [dict(row) for row in rows]

    async def _has_real_matches(self, tournament_id: int) -> bool:
        async with expansion_connection() as db:
            bracket_count = await (
                await db.execute(
                    "SELECT COUNT(*) FROM matches WHERE tournament_id=?",
                    (tournament_id,),
                )
            ).fetchone()
            swiss_count = await (
                await db.execute(
                    "SELECT COUNT(*) FROM swiss_matches WHERE tournament_id=?",
                    (tournament_id,),
                )
            ).fetchone()
        return bool(int(bracket_count[0] or 0) or int(swiss_count[0] or 0))

    @staticmethod
    def _ordered_players(
        registrations: list[dict[str, Any]],
        *,
        preserve_complete_seeds: bool,
        random_source: random.Random,
    ) -> list[PreviewPlayer]:
        count = len(registrations)
        seed_values = [row.get("seed") for row in registrations]
        complete_seeds = (
            preserve_complete_seeds
            and all(value is not None for value in seed_values)
            and {int(value) for value in seed_values} == set(range(1, count + 1))
        )

        source = list(registrations)
        if complete_seeds:
            source.sort(key=lambda row: int(row["seed"]))
        else:
            random_source.shuffle(source)

        return [
            PreviewPlayer(
                discord_id=str(row["discord_id"]),
                username=str(row["username"]),
                seed=index,
            )
            for index, row in enumerate(source, start=1)
        ]

    @classmethod
    def _elimination_pairings(
        cls,
        players: list[PreviewPlayer],
    ) -> list[PreviewPairing]:
        by_seed = {player.seed: player for player in players}
        bracket_size = cls.bracket_size(len(players))
        positions = cls.bracket_seed_order(bracket_size)
        pairings: list[PreviewPairing] = []
        for offset in range(0, len(positions), 2):
            first = by_seed.get(positions[offset])
            second = by_seed.get(positions[offset + 1])

            # Dans un bracket incomplet, un seed peut faire face à un slot vide.
            # On garde toujours le joueur réel dans player1 pour rester compatible
            # avec les tables actuelles de Hamtaro.
            player1 = first or second
            player2 = second if first is not None else None
            if player1 is None:
                continue

            pairings.append(
                PreviewPairing(
                    round_number=cls.elimination_rounds(len(players)),
                    table_number=(offset // 2) + 1,
                    player1_id=player1.discord_id,
                    player1_name=player1.username,
                    player2_id=player2.discord_id if player2 else None,
                    player2_name=player2.username if player2 else None,
                    is_bye=player2 is None,
                )
            )
        return pairings

    @staticmethod
    def _swiss_pairings(players: list[PreviewPlayer]) -> list[PreviewPairing]:
        pairings: list[PreviewPairing] = []
        table_number = 1
        for offset in range(0, len(players), 2):
            player1 = players[offset]
            player2 = players[offset + 1] if offset + 1 < len(players) else None
            pairings.append(
                PreviewPairing(
                    round_number=1,
                    table_number=table_number,
                    player1_id=player1.discord_id,
                    player1_name=player1.username,
                    player2_id=player2.discord_id if player2 else None,
                    player2_name=player2.username if player2 else None,
                    is_bye=player2 is None,
                )
            )
            table_number += 1
        return pairings

    async def _store_preview(
        self,
        *,
        guild_id: str,
        tournament: Any,
        tournament_type: str,
        total_rounds: int,
        players: list[PreviewPlayer],
        pairings: list[PreviewPairing],
        actor_id: str,
        channel_id: str | None,
    ) -> int:
        tournament_id = int(self.value(tournament, "id"))
        now = utcnow_iso()
        async with expansion_connection() as db:
            await db.execute(
                """
                UPDATE pending_tournament_starts
                SET status='cancelled', updated_at=?
                WHERE tournament_id=? AND status='pending'
                """,
                (now, tournament_id),
            )
            cursor = await db.execute(
                """
                INSERT INTO pending_tournament_starts(
                    guild_id, tournament_id, tournament_type, total_rounds,
                    status, created_by, channel_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    tournament_id,
                    tournament_type,
                    total_rounds,
                    actor_id,
                    channel_id,
                    now,
                    now,
                ),
            )
            preview_id = int(cursor.lastrowid)
            await db.executemany(
                """
                INSERT INTO pending_tournament_players(
                    pending_id, seed, discord_id, username
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (preview_id, player.seed, player.discord_id, player.username)
                    for player in players
                ],
            )
            await db.executemany(
                """
                INSERT INTO pending_tournament_pairings(
                    pending_id, round_number, table_number,
                    player1_id, player1_name, player2_id, player2_name, is_bye
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        preview_id,
                        pairing.round_number,
                        pairing.table_number,
                        pairing.player1_id,
                        pairing.player1_name,
                        pairing.player2_id,
                        pairing.player2_name,
                        int(pairing.is_bye),
                    )
                    for pairing in pairings
                ],
            )
            await db.commit()
        return preview_id

    async def create_preview(
        self,
        *,
        guild_id: str,
        tournament: Any,
        total_rounds: int | None,
        actor_id: str,
        channel_id: str | None,
        force_new_draw: bool = False,
    ) -> dict[str, Any]:
        tournament_id = int(self.value(tournament, "id"))
        if self.status_value(tournament) != "registration":
            raise ValueError(
                "Le tournoi doit être dans la phase d'inscription pour préparer son démarrage."
            )
        if await self._has_real_matches(tournament_id):
            raise ValueError(
                "Des matchs existent déjà pour ce tournoi : le démarrage ne peut plus être préparé."
            )

        if not force_new_draw:
            existing = await self.pending_for_tournament(tournament_id)
            if existing is not None:
                return existing

        registrations = await self._active_registrations(tournament_id)
        tournament_type = self.tournament_type(tournament)
        if tournament_type == SINGLE_ELIMINATION:
            rounds = self.elimination_rounds(len(registrations))
        else:
            if len(registrations) < 2:
                raise ValueError("Il faut au moins deux joueurs actifs.")
            rounds = total_rounds or self.default_swiss_rounds(len(registrations))
            if rounds < 1 or rounds > 30:
                raise ValueError("Le nombre de rondes suisses doit être compris entre 1 et 30.")

        seed = random.SystemRandom().randrange(0, 2**63)
        random_source = random.Random(seed)
        players = self._ordered_players(
            registrations,
            preserve_complete_seeds=(tournament_type == SINGLE_ELIMINATION),
            random_source=random_source,
        )
        pairings = (
            self._elimination_pairings(players)
            if tournament_type == SINGLE_ELIMINATION
            else self._swiss_pairings(players)
        )
        preview_id = await self._store_preview(
            guild_id=guild_id,
            tournament=tournament,
            tournament_type=tournament_type,
            total_rounds=rounds,
            players=players,
            pairings=pairings,
            actor_id=actor_id,
            channel_id=channel_id,
        )
        preview = await self.get_preview(preview_id)
        if preview is None:
            raise RuntimeError("Le brouillon a été créé mais ne peut pas être relu.")
        return preview

    async def get_preview(self, preview_id: int) -> dict[str, Any] | None:
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    """
                    SELECT p.*, t.name AS tournament_name, t.code AS tournament_code,
                           t.format AS tournament_format, t.status AS tournament_status
                    FROM pending_tournament_starts p
                    JOIN tournaments t ON t.id=p.tournament_id
                    WHERE p.id=?
                    """,
                    (preview_id,),
                )
            ).fetchone()
            if row is None:
                return None
            players = await (
                await db.execute(
                    """
                    SELECT seed, discord_id, username
                    FROM pending_tournament_players
                    WHERE pending_id=? ORDER BY seed ASC
                    """,
                    (preview_id,),
                )
            ).fetchall()
            pairings = await (
                await db.execute(
                    """
                    SELECT * FROM pending_tournament_pairings
                    WHERE pending_id=?
                    ORDER BY round_number DESC, table_number ASC
                    """,
                    (preview_id,),
                )
            ).fetchall()
        result = dict(row)
        result["players"] = [dict(player) for player in players]
        result["pairings"] = [dict(pairing) for pairing in pairings]
        return result

    async def pending_for_tournament(self, tournament_id: int) -> dict[str, Any] | None:
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    """
                    SELECT id FROM pending_tournament_starts
                    WHERE tournament_id=? AND status='pending'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (tournament_id,),
                )
            ).fetchone()
        return await self.get_preview(int(row["id"])) if row else None

    async def reshuffle(self, preview_id: int) -> dict[str, Any]:
        preview = await self.get_preview(preview_id)
        if preview is None or preview["status"] != "pending":
            raise ValueError("Ce brouillon n'est plus disponible.")
        if preview["tournament_type"] != SINGLE_ELIMINATION:
            raise ValueError("Le remélange est réservé aux brackets à élimination directe.")

        player_rows = list(preview["players"])
        random.SystemRandom().shuffle(player_rows)
        ordered = [
            PreviewPlayer(
                discord_id=str(row["discord_id"]),
                username=str(row["username"]),
                seed=index,
            )
            for index, row in enumerate(player_rows, start=1)
        ]
        await self._replace_players_and_pairings(
            preview_id,
            ordered,
            self._elimination_pairings(ordered),
        )
        updated = await self.get_preview(preview_id)
        if updated is None:
            raise RuntimeError("Le nouveau tirage est introuvable.")
        return updated

    async def update_seed_order(
        self,
        preview_id: int,
        ordered_ids: list[str],
    ) -> dict[str, Any]:
        preview = await self.get_preview(preview_id)
        if preview is None or preview["status"] != "pending":
            raise ValueError("Ce brouillon n'est plus disponible.")
        if preview["tournament_type"] != SINGLE_ELIMINATION:
            raise ValueError("Les seeds ne sont modifiables qu'en élimination directe.")

        current = {str(row["discord_id"]): str(row["username"]) for row in preview["players"]}
        if len(ordered_ids) != len(current) or set(ordered_ids) != set(current):
            raise ValueError("La nouvelle liste doit contenir exactement tous les joueurs.")
        ordered = [
            PreviewPlayer(discord_id=value, username=current[value], seed=index)
            for index, value in enumerate(ordered_ids, start=1)
        ]
        await self._replace_players_and_pairings(
            preview_id,
            ordered,
            self._elimination_pairings(ordered),
        )
        updated = await self.get_preview(preview_id)
        if updated is None:
            raise RuntimeError("Le brouillon modifié est introuvable.")
        return updated

    async def _replace_players_and_pairings(
        self,
        preview_id: int,
        players: list[PreviewPlayer],
        pairings: list[PreviewPairing],
    ) -> None:
        now = utcnow_iso()
        async with expansion_connection() as db:
            await db.execute(
                "DELETE FROM pending_tournament_players WHERE pending_id=?",
                (preview_id,),
            )
            await db.execute(
                "DELETE FROM pending_tournament_pairings WHERE pending_id=?",
                (preview_id,),
            )
            await db.executemany(
                """
                INSERT INTO pending_tournament_players(
                    pending_id, seed, discord_id, username
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (preview_id, player.seed, player.discord_id, player.username)
                    for player in players
                ],
            )
            await db.executemany(
                """
                INSERT INTO pending_tournament_pairings(
                    pending_id, round_number, table_number,
                    player1_id, player1_name, player2_id, player2_name, is_bye
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        preview_id,
                        pairing.round_number,
                        pairing.table_number,
                        pairing.player1_id,
                        pairing.player1_name,
                        pairing.player2_id,
                        pairing.player2_name,
                        int(pairing.is_bye),
                    )
                    for pairing in pairings
                ],
            )
            await db.execute(
                """
                UPDATE pending_tournament_starts
                SET version=version+1, updated_at=? WHERE id=?
                """,
                (now, preview_id),
            )
            await db.commit()

    async def cancel_preview(self, preview_id: int, actor_id: str) -> dict[str, Any]:
        now = utcnow_iso()
        async with expansion_connection() as db:
            await db.execute(
                """
                UPDATE pending_tournament_starts
                SET status='cancelled', updated_at=?, confirmed_by=?
                WHERE id=? AND status='pending'
                """,
                (now, actor_id, preview_id),
            )
            await db.commit()
        preview = await self.get_preview(preview_id)
        if preview is None:
            raise ValueError("Brouillon introuvable.")
        return preview

    async def _commit_core_db(self) -> None:
        commit = getattr(self.db, "commit", None)
        if callable(commit):
            await commit()

    async def _cleanup_failed_launch(self, tournament_id: int, tournament_type: str) -> None:
        async with expansion_connection() as db:
            if tournament_type == SWISS:
                await db.execute(
                    "DELETE FROM swiss_matches WHERE tournament_id=?",
                    (tournament_id,),
                )
                await db.execute(
                    "DELETE FROM swiss_settings WHERE tournament_id=?",
                    (tournament_id,),
                )
            else:
                await db.execute(
                    "DELETE FROM matches WHERE tournament_id=?",
                    (tournament_id,),
                )
            await db.execute(
                """
                UPDATE tournaments
                SET status='registration', current_round=0,
                    total_rounds=0, started_at=NULL
                WHERE id=?
                """,
                (tournament_id,),
            )
            await db.commit()

    async def _assert_generated_pairings(
        self,
        tournament_id: int,
        expected_pairings: list[dict[str, Any]],
    ) -> None:
        expected = {
            frozenset((str(row["player1_id"]), str(row["player2_id"])))
            for row in expected_pairings
            if row.get("player2_id")
        }
        async with expansion_connection() as db:
            max_round_row = await (
                await db.execute(
                    "SELECT MAX(round) FROM matches WHERE tournament_id=?",
                    (tournament_id,),
                )
            ).fetchone()
            max_round = int(max_round_row[0] or 0)
            rows = await (
                await db.execute(
                    """
                    SELECT player1_id, player2_id
                    FROM matches
                    WHERE tournament_id=? AND round=? AND COALESCE(is_bye,0)=0
                    """,
                    (tournament_id, max_round),
                )
            ).fetchall()
        actual = {
            frozenset((str(row["player1_id"]), str(row["player2_id"])))
            for row in rows
            if row["player1_id"] and row["player2_id"]
        }
        if expected != actual:
            raise RuntimeError(
                "Le générateur de bracket installé n'a pas respecté le tirage "
                "prévisualisé. Le lancement a été annulé sans conserver les matchs."
            )

    async def confirm_preview(self, preview_id: int, actor_id: str) -> dict[str, Any]:
        preview = await self.get_preview(preview_id)
        if preview is None:
            raise ValueError("Brouillon introuvable.")
        tournament_id = int(preview["tournament_id"])
        lock = self._locks.setdefault(tournament_id, asyncio.Lock())

        async with lock:
            preview = await self.get_preview(preview_id)
            if preview is None or preview["status"] != "pending":
                raise ValueError("Ce brouillon a déjà été traité.")
            tournament = await self.db.get_tournament(tournament_id)
            if tournament is None:
                raise ValueError("Tournoi introuvable.")
            if self.status_value(tournament) != "registration":
                raise ValueError("Le tournoi n'est plus dans la phase d'inscription.")
            if await self._has_real_matches(tournament_id):
                raise ValueError("Des matchs existent déjà pour ce tournoi.")

            tournament_type = str(preview["tournament_type"])
            try:
                if tournament_type == SINGLE_ELIMINATION:
                    for player in preview["players"]:
                        await self.db.set_registration_seed(
                            tournament_id,
                            str(player["discord_id"]),
                            int(player["seed"]),
                        )
                    await self._commit_core_db()
                    await self.brackets.generate_bracket(tournament_id)
                    await self._assert_generated_pairings(
                        tournament_id,
                        list(preview["pairings"]),
                    )
                else:
                    await self.db.start_swiss_tournament(
                        tournament_id,
                        int(preview["total_rounds"]),
                    )
                    for pairing in preview["pairings"]:
                        await self.db.create_swiss_match(
                            tournament_id=tournament_id,
                            round_number=1,
                            table_number=int(pairing["table_number"]),
                            player1_id=str(pairing["player1_id"]),
                            player1_name=str(pairing["player1_name"]),
                            player2_id=(
                                str(pairing["player2_id"])
                                if pairing.get("player2_id")
                                else None
                            ),
                            player2_name=(
                                str(pairing["player2_name"])
                                if pairing.get("player2_name")
                                else None
                            ),
                            is_bye=bool(pairing.get("is_bye")),
                        )
                    await self.db.set_swiss_current_round(tournament_id, 1)
                    await self._commit_core_db()
            except Exception:
                await self._cleanup_failed_launch(tournament_id, tournament_type)
                raise

            now = utcnow_iso()
            async with expansion_connection() as db:
                await db.execute(
                    """
                    UPDATE pending_tournament_starts
                    SET status='confirmed', confirmed_at=?, confirmed_by=?,
                        updated_at=?
                    WHERE id=? AND status='pending'
                    """,
                    (now, actor_id, now, preview_id),
                )
                await db.commit()

        confirmed = await self.get_preview(preview_id)
        if confirmed is None:
            raise RuntimeError("Le démarrage est confirmé mais son historique est introuvable.")
        return confirmed
