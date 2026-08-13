from __future__ import annotations

from typing import Any


MATCH_KIND_BRACKET = "bracket"
MATCH_KIND_SWISS = "swiss"


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    try:
        return obj[name]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, name, default)


def _round_number(match_kind: str, match: dict[str, Any]) -> int:
    if match_kind == MATCH_KIND_SWISS:
        return int(match.get("round_number") or 0)
    return int(match.get("round") or 0)


def _round_label(match_kind: str, match: dict[str, Any]) -> str:
    if match_kind == MATCH_KIND_SWISS:
        round_number = int(match.get("round_number") or 0)
        table_number = int(match.get("table_number") or 0)
        return f"Ronde {round_number} · Table {table_number}"

    round_number = int(match.get("round") or 0)
    match_number = int(match.get("match_number") or match.get("id") or 0)
    # Le numéro de ronde stocké dans `matches` part de la première ronde du
    # tableau : sans `total_rounds`, le convertir en "demi-finale/finale"
    # serait faux. On affiche donc une information exacte et stable.
    return f"Ronde {round_number} · Match {match_number}"


class MatchContextService:
    """Source de vérité du contexte d'un fil de match Hamtaro.

    Cette table ne remplace ni les matchs ni les sessions Match Center : elle
    mémorise uniquement l'identité du fil et les informations utiles à toutes
    les commandes. Ainsi les modules n'ont plus besoin d'un "tournoi courant".
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    async def ensure_table(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS match_thread_context (
                thread_id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER NOT NULL,
                tournament_code TEXT,
                tournament_name TEXT,
                tournament_format TEXT,
                tournament_type TEXT,
                match_kind TEXT NOT NULL,
                match_id INTEGER NOT NULL,
                round_number INTEGER NOT NULL DEFAULT 0,
                round_label TEXT,
                player1_id TEXT,
                player1_name TEXT,
                player2_id TEXT,
                player2_name TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(match_kind, match_id)
            )
            """
        )
        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_match_thread_context_tournament
            ON match_thread_context(tournament_id, match_kind, match_id)
            """
        )
        await self.db.commit()

    async def bind_thread(
        self,
        *,
        thread_id: str | int,
        tournament: Any,
        match_kind: str,
        match: dict[str, Any],
    ) -> None:
        await self.ensure_table()
        await self.db.execute(
            """
            INSERT INTO match_thread_context (
                thread_id, guild_id, tournament_id,
                tournament_code, tournament_name, tournament_format,
                tournament_type, match_kind, match_id,
                round_number, round_label,
                player1_id, player1_name, player2_id, player2_name,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(match_kind, match_id)
            DO UPDATE SET
                thread_id = excluded.thread_id,
                guild_id = excluded.guild_id,
                tournament_id = excluded.tournament_id,
                tournament_code = excluded.tournament_code,
                tournament_name = excluded.tournament_name,
                tournament_format = excluded.tournament_format,
                tournament_type = excluded.tournament_type,
                round_number = excluded.round_number,
                round_label = excluded.round_label,
                player1_id = excluded.player1_id,
                player1_name = excluded.player1_name,
                player2_id = excluded.player2_id,
                player2_name = excluded.player2_name,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                str(thread_id),
                str(_value(tournament, "guild_id", "")),
                int(_value(tournament, "id", 0)),
                str(_value(tournament, "code", "") or ""),
                str(_value(tournament, "name", "Tournoi Hamtaro") or "Tournoi Hamtaro"),
                str(_value(tournament, "format", "Format inconnu") or "Format inconnu"),
                str(_value(tournament, "tournament_type", "") or ""),
                str(match_kind),
                int(match["id"]),
                _round_number(match_kind, match),
                _round_label(match_kind, match),
                str(match.get("player1_id") or "") or None,
                str(match.get("player1_name") or "Joueur 1"),
                str(match.get("player2_id") or "") or None,
                str(match.get("player2_name") or "Joueur 2"),
            ),
        )
        await self.db.commit()

    async def by_thread(
        self,
        *,
        guild_id: str | int,
        thread_id: str | int,
    ) -> dict[str, Any] | None:
        await self.ensure_table()
        row = await self.db.fetchone(
            """
            SELECT *
            FROM match_thread_context
            WHERE guild_id = ? AND thread_id = ?
            LIMIT 1
            """,
            (str(guild_id), str(thread_id)),
        )
        return dict(row) if row is not None else None

    async def by_match(self, match_kind: str, match_id: int) -> dict[str, Any] | None:
        await self.ensure_table()
        row = await self.db.fetchone(
            """
            SELECT *
            FROM match_thread_context
            WHERE match_kind = ? AND match_id = ?
            LIMIT 1
            """,
            (str(match_kind), int(match_id)),
        )
        return dict(row) if row is not None else None

    async def tournament_threads(self, tournament_id: int) -> list[dict[str, Any]]:
        await self.ensure_table()
        rows = await self.db.fetchall(
            """
            SELECT *
            FROM match_thread_context
            WHERE tournament_id = ?
            ORDER BY round_number, match_kind, match_id
            """,
            (int(tournament_id),),
        )
        return [dict(row) for row in rows]
