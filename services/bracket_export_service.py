from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from services.bracket_image_service import BracketImageService
from services.bracket_service import BracketService


FINISHED_STATUSES = {
    "finished",
    "completed",
    "ended",
    "closed",
    "archived",
}


class BracketExportService:
    """
    Service partagé entre Discord et le site public.

    Il relit le tournoi et son bracket, fabrique une empreinte de leur état,
    puis utilise exactement le BracketImageService déjà présent dans Hamtaro.
    Aucune seconde maquette de bracket n'est créée.
    """

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.db = bot.db
        self.brackets = BracketService(self.db)
        self.renderer = BracketImageService(self.db)

        cache_directory = os.getenv(
            "BRACKET_CACHE_DIR",
            "cache/brackets",
        )
        self.cache_directory = Path(cache_directory)
        self.cache_directory.mkdir(parents=True, exist_ok=True)

        self._locks: dict[int, asyncio.Lock] = {}

    # ==========================================================
    # OUTILS DE BASE DE DONNÉES
    # ==========================================================

    @staticmethod
    def _to_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}

        if isinstance(value, dict):
            return dict(value)

        keys = getattr(value, "keys", None)
        if callable(keys):
            try:
                return {key: value[key] for key in keys()}
            except (KeyError, TypeError):
                pass

        try:
            return vars(value).copy()
        except TypeError:
            result: dict[str, Any] = {}
            for name in dir(value):
                if name.startswith("_"):
                    continue
                try:
                    item = getattr(value, name)
                except Exception:
                    continue
                if not callable(item):
                    result[name] = item
            return result

    async def _fetchone(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> Any | None:
        method = getattr(self.db, "fetchone", None)
        if callable(method):
            return await method(query, parameters)

        connection = getattr(self.db, "conn", None)
        if connection is None:
            connection = getattr(self.db, "connection", None)

        if connection is None:
            raise RuntimeError(
                "La base de données de Hamtaro ne fournit ni fetchone() "
                "ni connexion SQL accessible."
            )

        cursor = await connection.execute(query, parameters)
        return await cursor.fetchone()

    async def _fetchall(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> list[Any]:
        method = getattr(self.db, "fetchall", None)
        if callable(method):
            rows = await method(query, parameters)
            return list(rows or [])

        connection = getattr(self.db, "conn", None)
        if connection is None:
            connection = getattr(self.db, "connection", None)

        if connection is None:
            raise RuntimeError(
                "La base de données de Hamtaro ne fournit ni fetchall() "
                "ni connexion SQL accessible."
            )

        cursor = await connection.execute(query, parameters)
        return list(await cursor.fetchall())

    async def _safe_fetchall(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        try:
            rows = await self._fetchall(query, parameters)
        except Exception:
            return []

        return [self._to_dict(row) for row in rows]

    async def _safe_fetchone(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> dict[str, Any] | None:
        try:
            row = await self._fetchone(query, parameters)
        except Exception:
            return None

        if row is None:
            return None

        return self._to_dict(row)

    # ==========================================================
    # TOURNOIS
    # ==========================================================

    async def get_tournament_object(self, tournament_id: int) -> Any:
        getter = getattr(self.db, "get_tournament", None)

        if callable(getter):
            tournament = await getter(tournament_id)
            if tournament is not None:
                return tournament

        row = await self._fetchone(
            """
            SELECT *
            FROM tournaments
            WHERE id = ?
            """,
            (tournament_id,),
        )

        if row is None:
            raise ValueError("Tournoi introuvable.")

        return SimpleNamespace(**self._to_dict(row))

    async def get_tournament_dict(
        self,
        tournament_id: int,
    ) -> dict[str, Any]:
        tournament = await self.get_tournament_object(tournament_id)
        return self._to_dict(tournament)

    async def list_tournaments(
        self,
        *,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(200, int(limit)))

        return await self._safe_fetchall(
            """
            SELECT
                t.*,
                (
                    SELECT COUNT(*)
                    FROM registrations r
                    WHERE r.tournament_id = t.id
                ) AS participant_count
            FROM tournaments t
            WHERE LOWER(COALESCE(t.status, '')) != 'cancelled'
            ORDER BY t.id DESC
            LIMIT ?
            """,
            (limit,),
        )

    async def list_archives(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(300, int(limit)))

        status_placeholders = ",".join("?" for _ in FINISHED_STATUSES)

        return await self._safe_fetchall(
            f"""
            SELECT
                t.*,
                (
                    SELECT COUNT(*)
                    FROM registrations r
                    WHERE r.tournament_id = t.id
                ) AS participant_count
            FROM tournaments t
            WHERE LOWER(COALESCE(t.status, '')) IN ({status_placeholders})
            ORDER BY COALESCE(t.finished_at, t.created_at) DESC, t.id DESC
            LIMIT ?
            """,
            (*sorted(FINISHED_STATUSES), limit),
        )

    async def get_tournament_page_data(
        self,
        tournament_id: int,
    ) -> dict[str, Any]:
        tournament = await self.get_tournament_dict(tournament_id)

        participants = await self._safe_fetchall(
            """
            SELECT
                discord_id,
                username,
                deck,
                seed,
                final_rank,
                dropped,
                disqualified,
                registered_at
            FROM registrations
            WHERE tournament_id = ?
            ORDER BY
                CASE WHEN seed IS NULL THEN 1 ELSE 0 END,
                seed ASC,
                registered_at ASC
            """,
            (tournament_id,),
        )

        results = await self._safe_fetchall(
            """
            SELECT
                id,
                round,
                match_number,
                player1_id,
                player1_name,
                player2_id,
                player2_name,
                player1_score,
                player2_score,
                winner_id,
                winner_name,
                score,
                status,
                validated_at
            FROM matches
            WHERE tournament_id = ?
              AND LOWER(COALESCE(status, '')) IN (
                  'validated',
                  'completed',
                  'finished',
                  'approved'
              )
            ORDER BY COALESCE(validated_at, created_at) DESC, id DESC
            LIMIT 20
            """,
            (tournament_id,),
        )

        tournament["participants"] = participants
        tournament["results"] = results
        tournament["participant_count"] = len(participants)
        return tournament

    # ==========================================================
    # DONNÉES PUBLIQUES COMPLÉMENTAIRES
    # ==========================================================

    async def list_recent_results(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(300, int(limit)))

        return await self._safe_fetchall(
            """
            SELECT
                m.id,
                m.tournament_id,
                m.round,
                m.match_number,
                m.player1_id,
                m.player1_name,
                m.player2_id,
                m.player2_name,
                m.player1_score,
                m.player2_score,
                m.winner_id,
                m.winner_name,
                m.score,
                m.status,
                m.validated_at,
                t.name AS tournament_name,
                t.code AS tournament_code,
                t.format AS tournament_format
            FROM matches m
            JOIN tournaments t ON t.id = m.tournament_id
            WHERE LOWER(COALESCE(m.status, '')) IN (
                'validated',
                'completed',
                'finished',
                'approved'
            )
            ORDER BY COALESCE(m.validated_at, m.created_at) DESC, m.id DESC
            LIMIT ?
            """,
            (limit,),
        )

    async def list_deck_statistics(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(300, int(limit)))

        return await self._safe_fetchall(
            """
            SELECT
                TRIM(deck) AS deck,
                COUNT(*) AS appearances,
                COUNT(DISTINCT tournament_id) AS tournaments,
                SUM(
                    CASE
                        WHEN final_rank = 1 THEN 1
                        ELSE 0
                    END
                ) AS tournament_wins,
                SUM(
                    CASE
                        WHEN final_rank IS NOT NULL
                         AND final_rank <= 4 THEN 1
                        ELSE 0
                    END
                ) AS top_four
            FROM registrations
            WHERE deck IS NOT NULL
              AND TRIM(deck) != ''
            GROUP BY LOWER(TRIM(deck))
            ORDER BY appearances DESC, tournament_wins DESC, deck ASC
            LIMIT ?
            """,
            (limit,),
        )

    async def get_player_profile(
        self,
        discord_id: str,
    ) -> dict[str, Any] | None:
        player = await self._safe_fetchone(
            """
            SELECT *
            FROM players
            WHERE discord_id = ?
            ORDER BY joined_at DESC
            LIMIT 1
            """,
            (discord_id,),
        )

        registrations = await self._safe_fetchall(
            """
            SELECT
                r.tournament_id,
                r.username,
                r.deck,
                r.seed,
                r.final_rank,
                r.dropped,
                r.disqualified,
                t.name AS tournament_name,
                t.code AS tournament_code,
                t.format AS tournament_format,
                t.status AS tournament_status
            FROM registrations r
            JOIN tournaments t ON t.id = r.tournament_id
            WHERE r.discord_id = ?
            ORDER BY r.tournament_id DESC
            LIMIT 50
            """,
            (discord_id,),
        )

        matches = await self._safe_fetchall(
            """
            SELECT
                m.*,
                t.name AS tournament_name,
                t.code AS tournament_code
            FROM matches m
            JOIN tournaments t ON t.id = m.tournament_id
            WHERE m.player1_id = ? OR m.player2_id = ?
            ORDER BY COALESCE(m.validated_at, m.created_at) DESC, m.id DESC
            LIMIT 50
            """,
            (discord_id, discord_id),
        )

        if player is None and not registrations and not matches:
            return None

        if player is None:
            fallback_name = (
                registrations[0].get("username")
                if registrations
                else "Joueur Hamtaro"
            )
            player = {
                "discord_id": discord_id,
                "username": fallback_name,
                "display_name": fallback_name,
            }

        victories = 0
        defeats = 0
        for match in matches:
            status = str(match.get("status") or "").lower()
            if status not in {
                "validated",
                "completed",
                "finished",
                "approved",
            }:
                continue

            winner_id = str(match.get("winner_id") or "")
            if not winner_id:
                continue

            if winner_id == str(discord_id):
                victories += 1
            else:
                defeats += 1

        player["registrations"] = registrations
        player["matches"] = matches
        player["calculated_wins"] = victories
        player["calculated_losses"] = defeats
        player["calculated_played"] = victories + defeats
        return player

    # ==========================================================
    # BRACKET ET CACHE
    # ==========================================================

    @staticmethod
    def _value(item: Any, name: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(name, default)
        return getattr(item, name, default)

    @classmethod
    def _normalised_status(cls, tournament: Any) -> str:
        return str(
            cls._value(tournament, "status", "") or ""
        ).lower().strip()

    @classmethod
    def _is_final_mode(cls, tournament: Any) -> bool:
        return cls._normalised_status(tournament) in FINISHED_STATUSES

    @classmethod
    def _signature_payload(
        cls,
        tournament: Any,
        bracket: dict[int, list[Any]],
        *,
        final_mode: bool,
    ) -> dict[str, Any]:
        tournament_fields = (
            "id",
            "code",
            "name",
            "format",
            "status",
            "current_round",
            "total_rounds",
            "winner_id",
            "winner_name",
            "started_at",
            "finished_at",
        )

        match_fields = (
            "id",
            "tournament_id",
            "round",
            "round_number",
            "match_number",
            "bracket_position",
            "next_match_id",
            "next_slot",
            "player1_id",
            "player1_name",
            "player1_score",
            "player2_id",
            "player2_name",
            "player2_score",
            "winner_id",
            "winner_name",
            "score",
            "status",
            "is_bye",
            "validated_at",
        )

        tournament_payload = {
            field: str(cls._value(tournament, field, "") or "")
            for field in tournament_fields
        }

        matches_payload: list[dict[str, str]] = []

        for round_number in sorted(bracket):
            matches = bracket.get(round_number) or []
            for match in sorted(
                matches,
                key=lambda value: (
                    int(cls._value(value, "match_number", 0) or 0),
                    int(cls._value(value, "id", 0) or 0),
                ),
            ):
                data = {
                    field: str(cls._value(match, field, "") or "")
                    for field in match_fields
                }
                data["_group_round"] = str(round_number)
                matches_payload.append(data)

        return {
            "final_mode": final_mode,
            "tournament": tournament_payload,
            "matches": matches_payload,
        }

    @classmethod
    def _signature(
        cls,
        tournament: Any,
        bracket: dict[int, list[Any]],
        *,
        final_mode: bool,
    ) -> str:
        payload = cls._signature_payload(
            tournament,
            bracket,
            final_mode=final_mode,
        )

        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        return hashlib.sha256(encoded).hexdigest()[:20]

    async def _avatar_urls(
        self,
        tournament: Any,
        bracket: dict[int, list[Any]],
    ) -> dict[str, str]:
        player_ids: set[str] = set()

        for matches in bracket.values():
            for match in matches:
                for slot in (1, 2):
                    player_id = self._value(
                        match,
                        f"player{slot}_id",
                        None,
                    )
                    if player_id not in (None, ""):
                        player_ids.add(str(player_id))

        if not player_ids:
            return {}

        result: dict[str, str] = {}

        guild_id = self._value(tournament, "guild_id", None)
        guild = None

        if guild_id not in (None, ""):
            try:
                guild = self.bot.get_guild(int(guild_id))
            except (TypeError, ValueError):
                guild = None

        if guild is not None:
            for player_id in player_ids:
                try:
                    numeric_id = int(player_id)
                except ValueError:
                    continue

                member = guild.get_member(numeric_id)
                if member is None:
                    continue

                result[player_id] = member.display_avatar.replace(
                    size=256,
                    static_format="png",
                ).url

        missing = sorted(player_ids.difference(result))
        if not missing:
            return result

        placeholders = ",".join("?" for _ in missing)

        rows = await self._safe_fetchall(
            f"""
            SELECT discord_id, avatar_url
            FROM players
            WHERE discord_id IN ({placeholders})
              AND avatar_url IS NOT NULL
              AND TRIM(avatar_url) != ''
            """,
            tuple(missing),
        )

        for row in rows:
            player_id = str(row.get("discord_id") or "")
            avatar_url = str(row.get("avatar_url") or "")
            if player_id and avatar_url:
                result[player_id] = avatar_url

        return result

    async def get_state(
        self,
        tournament_id: int,
        *,
        final_mode: bool | None = None,
    ) -> tuple[Any, dict[int, list[Any]], bool, str]:
        tournament = await self.get_tournament_object(tournament_id)
        bracket = await self.brackets.get_bracket(tournament_id)

        if not bracket:
            raise ValueError(
                "Aucun bracket n'a encore été généré pour ce tournoi."
            )

        if final_mode is None:
            final_mode = self._is_final_mode(tournament)

        signature = self._signature(
            tournament,
            bracket,
            final_mode=final_mode,
        )

        return tournament, bracket, final_mode, signature

    async def get_version(
        self,
        tournament_id: int,
    ) -> str:
        _, _, _, signature = await self.get_state(tournament_id)
        return signature

    async def get_or_generate(
        self,
        tournament_id: int,
        *,
        final_mode: bool | None = None,
        force: bool = False,
    ) -> tuple[Path, str]:
        (
            tournament,
            bracket,
            resolved_final_mode,
            signature,
        ) = await self.get_state(
            tournament_id,
            final_mode=final_mode,
        )

        mode = "final" if resolved_final_mode else "live"
        image_path = (
            self.cache_directory
            / f"tournament_{tournament_id}_{mode}_{signature}.png"
        )

        if image_path.exists() and not force:
            return image_path, signature

        lock = self._locks.setdefault(
            tournament_id,
            asyncio.Lock(),
        )

        async with lock:
            if image_path.exists() and not force:
                return image_path, signature

            avatar_urls = await self._avatar_urls(
                tournament,
                bracket,
            )

            image_buffer = await self.renderer.render(
                tournament,
                bracket,
                avatar_urls=avatar_urls,
                final_mode=resolved_final_mode,
            )

            if isinstance(image_buffer, io.BytesIO):
                payload = image_buffer.getvalue()
            elif isinstance(image_buffer, (bytes, bytearray)):
                payload = bytes(image_buffer)
            else:
                raise RuntimeError(
                    "Le moteur graphique n'a pas renvoyé un PNG valide."
                )

            if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError(
                    "Le moteur graphique n'a pas produit un fichier PNG."
                )

            temporary_path = image_path.with_suffix(".tmp.png")
            temporary_path.write_bytes(payload)
            os.replace(temporary_path, image_path)

            self._remove_old_versions(
                tournament_id=tournament_id,
                mode=mode,
                keep=image_path,
            )

            return image_path, signature

    def _remove_old_versions(
        self,
        *,
        tournament_id: int,
        mode: str,
        keep: Path,
    ) -> None:
        pattern = f"tournament_{tournament_id}_{mode}_*.png"

        for path in self.cache_directory.glob(pattern):
            if path == keep:
                continue
            try:
                path.unlink()
            except OSError:
                pass
