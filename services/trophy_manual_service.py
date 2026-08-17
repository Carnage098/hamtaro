from __future__ import annotations

import re
from typing import Any

from services.trophy_award_service import TrophyAwardService


_TROPHY_ID_RE = re.compile(r"^HT-\d{3,}$", re.IGNORECASE)


class TrophyManualAwardService(TrophyAwardService):
    """Service staff pour attribuer/corriger manuellement un trophée.

    Il réutilise exactement la table ``trophy_awards`` déjà consommée par
    la page /trophies. Aucun schéma parallèle n'est créé.
    """

    @staticmethod
    def normalize_trophy_id(trophy_id: str) -> str:
        normalized = str(trophy_id or "").strip().upper()
        if not _TROPHY_ID_RE.fullmatch(normalized):
            raise ValueError(
                "Identifiant de trophée invalide. Format attendu : HT-001, HT-002, etc."
            )
        return normalized

    async def award_trophy(
        self,
        *,
        trophy_id: str,
        player_id: str,
        player_name: str,
        guild_id: str,
        tournament_id: int,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        trophy_id = self.normalize_trophy_id(trophy_id)
        player_id = str(player_id or "").strip()
        player_name = str(player_name or "").strip()
        guild_id = str(guild_id or "").strip()

        if not player_id or not player_name:
            raise ValueError("Le joueur sélectionné est invalide.")
        if not guild_id:
            raise ValueError("Cette commande doit être utilisée dans un serveur Discord.")
        if int(tournament_id) <= 0:
            raise ValueError("L'identifiant du tournoi doit être supérieur à 0.")

        await self.ensure_schema()
        db = await self._connect()

        try:
            await db.execute("BEGIN IMMEDIATE")

            tournament_cursor = await db.execute(
                """
                SELECT id, guild_id, name, format, finished_at
                FROM tournaments
                WHERE id = ?
                LIMIT 1
                """,
                (int(tournament_id),),
            )
            tournament = await tournament_cursor.fetchone()

            if tournament is None:
                await db.rollback()
                raise ValueError(f"Tournoi {tournament_id} introuvable.")

            tournament_guild_id = str(tournament["guild_id"])
            if tournament_guild_id != guild_id:
                await db.rollback()
                raise ValueError(
                    "Ce tournoi n'appartient pas au serveur Discord où la commande est utilisée."
                )

            existing_cursor = await db.execute(
                """
                SELECT *
                FROM trophy_awards
                WHERE UPPER(trophy_id) = UPPER(?)
                LIMIT 1
                """,
                (trophy_id,),
            )
            existing = await existing_cursor.fetchone()

            if existing is not None and not replace_existing:
                await db.commit()
                result = self._row_to_dict(existing) or {}
                result["newly_awarded"] = False
                result["reassigned"] = False
                result["blocked_existing"] = True
                return result

            deck_cursor = await db.execute(
                """
                SELECT deck
                FROM registrations
                WHERE tournament_id = ?
                  AND discord_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(tournament_id), player_id),
            )
            deck_row = await deck_cursor.fetchone()
            deck = None
            if deck_row is not None and deck_row["deck"] is not None:
                deck = str(deck_row["deck"]).strip() or None

            previous_holder_name = None
            previous_discord_id = None
            if existing is not None:
                previous_holder_name = str(existing["holder_name"])
                previous_discord_id = str(existing["discord_id"])

                await db.execute(
                    """
                    UPDATE trophy_awards
                    SET discord_id = ?,
                        holder_name = ?,
                        guild_id = ?,
                        tournament_id = ?,
                        tournament_name = ?,
                        deck = ?,
                        format = ?,
                        awarded_at = COALESCE(?, CURRENT_TIMESTAMP)
                    WHERE UPPER(trophy_id) = UPPER(?)
                    """,
                    (
                        player_id,
                        player_name,
                        tournament_guild_id,
                        int(tournament["id"]),
                        str(tournament["name"]),
                        deck,
                        str(tournament["format"]),
                        tournament["finished_at"],
                        trophy_id,
                    ),
                )
                newly_awarded = False
                reassigned = True
            else:
                await db.execute(
                    """
                    INSERT INTO trophy_awards (
                        trophy_id,
                        discord_id,
                        holder_name,
                        guild_id,
                        tournament_id,
                        tournament_name,
                        deck,
                        format,
                        awarded_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                    """,
                    (
                        trophy_id,
                        player_id,
                        player_name,
                        tournament_guild_id,
                        int(tournament["id"]),
                        str(tournament["name"]),
                        deck,
                        str(tournament["format"]),
                        tournament["finished_at"],
                    ),
                )
                newly_awarded = True
                reassigned = False

            final_cursor = await db.execute(
                """
                SELECT *
                FROM trophy_awards
                WHERE UPPER(trophy_id) = UPPER(?)
                LIMIT 1
                """,
                (trophy_id,),
            )
            final_row = await final_cursor.fetchone()
            await db.commit()

            result = self._row_to_dict(final_row) or {}
            result["newly_awarded"] = newly_awarded
            result["reassigned"] = reassigned
            result["blocked_existing"] = False
            result["previous_holder_name"] = previous_holder_name
            result["previous_discord_id"] = previous_discord_id
            return result

        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass
            raise
        finally:
            await db.close()
