from __future__ import annotations

import asyncio
import logging
import math
import os
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from services.bracket_service import BracketService
from services.swiss_service import SwissService
from services.tournament_schedule_service import get_schedule_slot, load_schedule


LOGGER = logging.getLogger("hamtaro.tournament_auto_start")
SCAN_INTERVAL_SECONDS = 30
DEFAULT_MIN_PLAYERS = 4


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "non"}


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        LOGGER.warning("%s invalide (%r), valeur par defaut=%s", name, raw, default)
        return default


def _status(tournament: Any) -> str:
    raw = getattr(tournament, "status", "")
    return str(getattr(raw, "value", raw) or "").lower().strip()


class TournamentAutoStartCog(commands.Cog):
    """Demarre ou annule automatiquement les tournois du planning Hamtaro."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db
        self.brackets = BracketService(self.db)
        self.swiss = SwissService(self.db)
        self.enabled = _env_bool("HAMTARO_AUTO_START_ENABLED", True)
        self.minimum_players = max(
            2,
            _env_int("HAMTARO_AUTO_START_MIN_PLAYERS", DEFAULT_MIN_PLAYERS),
        )
        self.forced_channel_id = (
            os.getenv("HAMTARO_TOURNAMENT_ANNOUNCEMENT_CHANNEL_ID", "").strip()
        )
        self._locks: dict[int, asyncio.Lock] = {}

    async def cog_load(self) -> None:
        if not self.enabled:
            LOGGER.info("Auto-start des tournois desactive.")
            return

        if not self.auto_start_scan.is_running():
            self.auto_start_scan.start()

        LOGGER.info(
            "Auto-start actif : minimum=%s, scan=%ss.",
            self.minimum_players,
            SCAN_INTERVAL_SECONDS,
        )
        if self.forced_channel_id:
            LOGGER.info(
                "Salon d'annonce impose par Railway : ID=%s.",
                self.forced_channel_id,
            )
        else:
            LOGGER.info(
                "Salon d'annonce : progression_setup, contexte tournoi, "
                "salon systeme, puis premier salon textuel disponible."
            )

    async def cog_unload(self) -> None:
        if self.auto_start_scan.is_running():
            self.auto_start_scan.cancel()

    @staticmethod
    def _timezone() -> ZoneInfo:
        try:
            name = str(load_schedule().get("timezone") or "Europe/Paris")
            return ZoneInfo(name)
        except Exception:
            LOGGER.exception("Timezone du planning invalide ; Europe/Paris utilise.")
            return ZoneInfo("Europe/Paris")

    @classmethod
    def _slot_start(cls, slot: dict[str, Any]) -> datetime:
        value = f"{slot['date']} {slot['start']}"
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(
            tzinfo=cls._timezone()
        )

    def _minimum_for(self, tournament: Any, slot: dict[str, Any]) -> int:
        raw = slot.get("min_players", self.minimum_players)
        try:
            minimum = int(raw)
        except (TypeError, ValueError):
            minimum = self.minimum_players

        maximum = max(
            2,
            int(getattr(tournament, "max_players", minimum) or minimum),
        )
        return max(2, min(minimum, maximum))

    async def _active_players(self, tournament_id: int) -> int:
        value = await self.db.fetchval(
            """
            SELECT COUNT(*)
            FROM registrations
            WHERE tournament_id = ?
              AND COALESCE(dropped, 0) = 0
              AND COALESCE(disqualified, 0) = 0
            """,
            (tournament_id,),
        )
        return int(value or 0)

    async def _claim(self, tournament_id: int) -> bool:
        changed = await self.db.update(
            """
            UPDATE tournaments
            SET auto_start_attempted_at = CURRENT_TIMESTAMP,
                auto_start_result = 'processing'
            WHERE id = ?
              AND status = 'registration'
              AND auto_start_attempted_at IS NULL
            """,
            (tournament_id,),
        )
        return changed == 1

    async def _set_result(self, tournament_id: int, result: str) -> None:
        await self.db.update(
            """
            UPDATE tournaments
            SET auto_start_result = ?
            WHERE id = ?
            """,
            (result[:250], tournament_id),
        )

    async def _channel_from_id(self, channel_id: Any) -> Any | None:
        if channel_id is None:
            return None
        try:
            numeric_id = int(str(channel_id))
        except (TypeError, ValueError):
            return None

        channel = self.bot.get_channel(numeric_id)
        if channel is not None:
            return channel

        try:
            return await self.bot.fetch_channel(numeric_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _announcement_channel(self, tournament: Any) -> Any | None:
        # 1. Variable Railway explicite.
        channel = await self._channel_from_id(self.forced_channel_id)
        if channel is not None:
            return channel

        guild_id = str(getattr(tournament, "guild_id", "") or "")
        tournament_id = int(getattr(tournament, "id"))

        # 2. Salon des matchs configure avec /progression_setup.
        try:
            row = await self.db.fetchone(
                """
                SELECT matches_channel_id
                FROM progression_settings
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            if row is not None:
                channel = await self._channel_from_id(row["matches_channel_id"])
                if channel is not None:
                    return channel
        except Exception:
            LOGGER.debug("progression_settings indisponible.", exc_info=True)

        # 3. Dernier salon ayant selectionne le tournoi.
        try:
            row = await self.db.fetchone(
                """
                SELECT channel_id
                FROM tournament_contexts
                WHERE tournament_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (tournament_id,),
            )
            if row is not None:
                channel = await self._channel_from_id(row["channel_id"])
                if channel is not None:
                    return channel
        except Exception:
            LOGGER.debug("tournament_contexts indisponible.", exc_info=True)

        # 4. Salon systeme puis premier salon textuel accessible.
        try:
            guild = self.bot.get_guild(int(guild_id))
        except (TypeError, ValueError):
            guild = None

        if guild is None:
            return None

        me = guild.me
        if guild.system_channel is not None:
            if me is None or guild.system_channel.permissions_for(me).send_messages:
                return guild.system_channel

        for text_channel in guild.text_channels:
            if me is None or text_channel.permissions_for(me).send_messages:
                return text_channel

        return None

    async def _send_announcement(
        self,
        tournament: Any,
        embed: discord.Embed,
    ) -> str | None:
        channel = await self._announcement_channel(tournament)
        if channel is None:
            LOGGER.warning(
                "Aucun salon d'annonce trouve pour le tournoi %s.",
                getattr(tournament, "id", "?"),
            )
            return None

        channel_id = str(getattr(channel, "id", "") or "")
        channel_name = str(
            getattr(channel, "name", "salon-inconnu") or "salon-inconnu"
        )

        try:
            await channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.exception(
                "Echec annonce tournoi %s dans #%s (ID=%s).",
                getattr(tournament, "id", "?"),
                channel_name,
                channel_id or "?",
            )
            return None

        LOGGER.info(
            "Annonce auto-start tournoi %s envoyee dans #%s (ID=%s).",
            getattr(tournament, "id", "?"),
            channel_name,
            channel_id or "?",
        )
        return channel_id or None

    async def _announce_cancelled(
        self,
        tournament: Any,
        *,
        registered: int,
        minimum: int,
        past_due: bool,
    ) -> str | None:
        if past_due:
            description = (
                "Ce tournoi correspond a un creneau du planning deja passe. "
                "Hamtaro l'a ferme automatiquement afin qu'un ancien tournoi "
                "ne reste pas ouvert et ne demarre pas en retard."
            )
            participants = f"{registered} inscrit(s) lors de la fermeture"
        else:
            description = (
                "L'heure de debut est arrivee mais le nombre minimum de "
                "participants n'a pas ete atteint."
            )
            participants = f"{registered}/{minimum} minimum requis"

        embed = discord.Embed(
            title="Tournoi annule automatiquement",
            description=description,
            colour=discord.Colour.red(),
        )
        embed.add_field(name="Tournoi", value=str(tournament.name), inline=False)
        embed.add_field(name="Code", value=str(tournament.code), inline=True)
        embed.add_field(name="Participants", value=participants, inline=True)
        embed.add_field(
            name="Statut",
            value="Annule - inscriptions fermees",
            inline=False,
        )
        embed.set_footer(text="Hamtaro - gestion automatique des tournois")
        return await self._send_announcement(tournament, embed)

    async def _announce_started(
        self,
        tournament: Any,
        *,
        registered: int,
        structure: str,
    ) -> str | None:
        structure_label = (
            "Rondes suisses"
            if structure == "swiss"
            else "Elimination directe"
        )
        embed = discord.Embed(
            title="Tournoi lance automatiquement",
            description=(
                "Le nombre minimum de participants est atteint. "
                "Le tournoi commence."
            ),
            colour=discord.Colour.green(),
        )
        embed.add_field(name="Tournoi", value=str(tournament.name), inline=False)
        embed.add_field(name="Code", value=str(tournament.code), inline=True)
        embed.add_field(name="Participants", value=str(registered), inline=True)
        embed.add_field(name="Structure", value=structure_label, inline=True)
        embed.add_field(
            name="Statut",
            value="En cours - inscriptions fermees",
            inline=False,
        )
        embed.set_footer(
            text="Les matchs sont publies par la progression automatique Hamtaro."
        )
        return await self._send_announcement(tournament, embed)

    async def _cancel(
        self,
        tournament: Any,
        *,
        registered: int,
        minimum: int,
        past_due: bool,
    ) -> None:
        tournament_id = int(tournament.id)
        result = (
            f"cancelled:past_due:{registered}"
            if past_due
            else f"cancelled:not_enough_players:{registered}/{minimum}"
        )

        changed = await self.db.update(
            """
            UPDATE tournaments
            SET status = 'cancelled',
                finished_at = CURRENT_TIMESTAMP,
                auto_start_result = ?
            WHERE id = ?
              AND status = 'registration'
            """,
            (result, tournament_id),
        )
        if changed != 1:
            return

        channel_id = await self._announce_cancelled(
            tournament,
            registered=registered,
            minimum=minimum,
            past_due=past_due,
        )
        if channel_id:
            await self._set_result(
                tournament_id,
                f"{result}:channel:{channel_id}",
            )

        LOGGER.info(
            "Tournoi %s annule automatiquement (past_due=%s, inscrits=%s, min=%s).",
            tournament_id,
            past_due,
            registered,
            minimum,
        )

    async def _launch(
        self,
        tournament: Any,
        slot: dict[str, Any],
        *,
        registered: int,
    ) -> None:
        tournament_id = int(tournament.id)
        slot_structure = str(slot.get("structure") or "").strip().lower()
        format_name = str(
            getattr(tournament, "format", "") or ""
        ).strip().casefold()

        if slot_structure == "swiss" or format_name == "suisse":
            rounds = max(3, math.ceil(math.log2(max(2, registered))))
            await self.swiss.start(
                tournament_id,
                rounds,
                shuffle_first_round=True,
            )
            structure = "swiss"
        else:
            await self.brackets.generate_bracket(
                tournament_id,
                shuffle=True,
                force=False,
            )
            structure = "single_elimination"

        await self._set_result(
            tournament_id,
            f"started:{structure}:{registered}",
        )

        updated = await self.db.get_tournament(tournament_id)
        message_tournament = updated or tournament

        progression = self.bot.get_cog("TournamentProgressionCog")
        if progression is not None and hasattr(progression, "publish_tournament"):
            try:
                await progression.publish_tournament(message_tournament)
            except Exception:
                LOGGER.exception(
                    "Tournoi %s lance mais publication immediate echouee.",
                    tournament_id,
                )

        channel_id = await self._announce_started(
            message_tournament,
            registered=registered,
            structure=structure,
        )
        if channel_id:
            await self._set_result(
                tournament_id,
                f"started:{structure}:{registered}:channel:{channel_id}",
            )

        LOGGER.info(
            "Tournoi %s demarre automatiquement (%s, %s participants).",
            tournament_id,
            structure,
            registered,
        )

    async def _process_current(
        self,
        tournament_id: int,
        slot: dict[str, Any],
    ) -> None:
        lock = self._locks.setdefault(tournament_id, asyncio.Lock())
        async with lock:
            tournament = await self.db.get_tournament(tournament_id)
            if tournament is None or _status(tournament) != "registration":
                return

            row = await self.db.fetchone(
                """
                SELECT auto_start_attempted_at
                FROM tournaments
                WHERE id = ?
                """,
                (tournament_id,),
            )
            if row is None or row["auto_start_attempted_at"] is not None:
                return

            if not await self._claim(tournament_id):
                return

            registered = await self._active_players(tournament_id)
            minimum = self._minimum_for(tournament, slot)

            if registered < minimum:
                await self._cancel(
                    tournament,
                    registered=registered,
                    minimum=minimum,
                    past_due=False,
                )
                return

            try:
                await self._launch(
                    tournament,
                    slot,
                    registered=registered,
                )
            except Exception as error:
                await self._set_result(
                    tournament_id,
                    f"error:{type(error).__name__}:{str(error)[:180]}",
                )
                LOGGER.exception(
                    "Echec du demarrage automatique du tournoi %s.",
                    tournament_id,
                )

    async def _process_past(
        self,
        tournament_id: int,
        slot: dict[str, Any],
    ) -> None:
        lock = self._locks.setdefault(tournament_id, asyncio.Lock())
        async with lock:
            tournament = await self.db.get_tournament(tournament_id)
            if tournament is None or _status(tournament) != "registration":
                return

            row = await self.db.fetchone(
                """
                SELECT auto_start_attempted_at
                FROM tournaments
                WHERE id = ?
                """,
                (tournament_id,),
            )
            if row is None or row["auto_start_attempted_at"] is not None:
                return

            if not await self._claim(tournament_id):
                return

            registered = await self._active_players(tournament_id)
            minimum = self._minimum_for(tournament, slot)
            await self._cancel(
                tournament,
                registered=registered,
                minimum=minimum,
                past_due=True,
            )

    @tasks.loop(seconds=SCAN_INTERVAL_SECONDS)
    async def auto_start_scan(self) -> None:
        try:
            now = datetime.now(self._timezone())
            today = now.date()

            rows = await self.db.fetchall(
                """
                SELECT id, scheduled_slot_id
                FROM tournaments
                WHERE status = 'registration'
                  AND scheduled_slot_id IS NOT NULL
                  AND auto_start_attempted_at IS NULL
                ORDER BY id ASC
                """
            )

            for row in rows:
                slot_id = str(row["scheduled_slot_id"] or "").strip()
                slot = get_schedule_slot(slot_id)
                if slot is None:
                    continue

                try:
                    slot_date = date.fromisoformat(
                        str(slot.get("date") or "")
                    )
                    start_at = self._slot_start(slot)
                except (KeyError, TypeError, ValueError):
                    LOGGER.exception("Creneau invalide : %s", slot_id)
                    continue

                if slot_date > today:
                    continue

                if slot_date < today:
                    await self._process_past(int(row["id"]), slot)
                    continue

                if now < start_at:
                    continue

                await self._process_current(int(row["id"]), slot)

        except Exception:
            LOGGER.exception("Erreur pendant le scan automatique des tournois.")

    @auto_start_scan.before_loop
    async def before_auto_start_scan(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentAutoStartCog(bot))
