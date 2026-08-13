from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from contextlib import suppress
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config import (
    BOT_BUILD,
    DATABASE_BACKUP_INTERVAL_HOURS,
    DATABASE_BACKUPS_ENABLED,
    DEBUG_INTERACTIONS,
    ENABLE_MESSAGE_CONTENT,
    ENABLE_WATCHDOG,
    EVENT_LOOP_WARNING_SECONDS,
    EVENT_LOOP_WATCHDOG_INTERVAL,
    FAIL_ON_COG_ERROR,
    GUILD_ID,
    INSTANCE_LOCK_PATH,
    LOG_LEVEL,
    SYNC_GLOBAL_COMMANDS,
    SYNC_GUILD_COMMANDS,
    TOKEN,
)
from database import init_db
from services.database_maintenance import (
    checkpoint_wal,
    create_backup,
    prepare_database,
)
from services.database_service import DatabaseService
from utils.permissions import StaffOnly
from utils.runtime_lock import AlreadyRunningError, RuntimeLock


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
LOGGER = logging.getLogger("hamtaro")

# Un échec sur un module essentiel empêche un bot partiellement cassé
# d'apparaître en ligne. Les modules graphiques restent facultatifs.
REQUIRED_COGS = (
    "cogs.registration",
    "cogs.tournament",
    "cogs.bracket",
    "cogs.results",
    "cogs.profile",
    "cogs.admin",
    "cogs.swiss",
    "cogs.match_history",
    "cogs.repair",
    "cogs.staff_logs",
    "cogs.tournament_status",
    "cogs.nextmatch",
    "cogs.bracket_full",
    "cogs.end_tournament",
    "cogs.help",
    "cogs.tournament_context",
    "cogs.tournament_undo",
    "cogs.match_center",
    "cogs.casual_matches",
    "cogs.tournament_progression",
    "cogs.deck_stats",
    "cogs.tournament_export",
    "cogs.hamtaro_hub",
    "cogs.system_health",
    "cogs.professional_tools",
    "cogs.public_website",
    "cogs.competitive",
    "cogs.player_experience",
    "cogs.tournament_extensions",
    "cogs.setup_assistant",
    "cogs.expansion_tasks",
    "cogs.expansion_hub",
    "cogs.casual_results_plus",
    "cogs.community_tools",
    "cogs.tournament_start_preview",
    "cogs.archetype_artworks",
)

OPTIONAL_COGS = (
    "cogs.graphics_preview",
    "cogs.swiss_graphics",
)


def interaction_name(interaction: discord.Interaction) -> str:
    data = interaction.data
    if isinstance(data, dict) and data.get("name"):
        return str(data["name"])
    command = interaction.command
    return (
        str(getattr(command, "qualified_name", command.name))
        if command is not None
        else "interaction-inconnue"
    )


class HamtaroCommandTree(app_commands.CommandTree):
    async def interaction_check(
        self,
        interaction: discord.Interaction,
        /,
    ) -> bool:
        if DEBUG_INTERACTIONS:
            LOGGER.info(
                "[COMMAND] id=%s name=%s guild=%s user=%s",
                interaction.id,
                interaction_name(interaction),
                interaction.guild_id,
                interaction.user.id,
            )
        return True


class HamtaroBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        # Nécessaire pour suivre les joueurs présents dans le vocal Streaming
        # et lire leur état de partage d'écran pendant les matchs vedettes.
        intents.voice_states = True
        intents.message_content = ENABLE_MESSAGE_CONTENT

        super().__init__(
            command_prefix="!",
            intents=intents,
            tree_cls=HamtaroCommandTree,
            allowed_mentions=discord.AllowedMentions.none(),
            chunk_guilds_at_startup=False,
        )

        self.db = DatabaseService()
        self.started_at_monotonic = time.monotonic()
        self.failed_extensions: dict[str, str] = {}
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._ready_logged = False

    def create_background_task(
        self,
        coroutine,
        *,
        name: str,
    ) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine, name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def setup_hook(self) -> None:
        LOGGER.info("Démarrage Hamtaro build=%s", BOT_BUILD)

        # Le contrôle et la sauvegarde ont lieu avant toute migration.
        await prepare_database()
        await init_db()
        await self.db.connect()

        await self._load_extensions()
        await self._sync_application_commands()

        if ENABLE_WATCHDOG:
            self.create_background_task(
                self._event_loop_watchdog(),
                name="hamtaro-event-loop-watchdog",
            )

        if DATABASE_BACKUPS_ENABLED:
            self.create_background_task(
                self._database_backup_loop(),
                name="hamtaro-database-backups",
            )

    async def _load_extensions(self) -> None:
        required_failures: list[str] = []

        for extension in (*REQUIRED_COGS, *OPTIONAL_COGS):
            started = time.perf_counter()
            try:
                await self.load_extension(extension)
            except Exception as error:
                self.failed_extensions[extension] = repr(error)
                LOGGER.exception("Échec du chargement de %s", extension)
                if extension in REQUIRED_COGS:
                    required_failures.append(extension)
            else:
                LOGGER.info(
                    "Cog chargé : %s en %.3fs",
                    extension,
                    time.perf_counter() - started,
                )

        if required_failures and FAIL_ON_COG_ERROR:
            raise RuntimeError(
                "Modules essentiels non chargés : "
                + ", ".join(required_failures)
            )

        if required_failures:
            LOGGER.error(
                "Hamtaro démarre en mode dégradé. Modules essentiels absents : %s",
                ", ".join(required_failures),
            )

    async def _sync_application_commands(self) -> None:
        performed = False

        if SYNC_GUILD_COMMANDS:
            if GUILD_ID.isdigit():
                guild = discord.Object(id=int(GUILD_ID))
                started = time.perf_counter()
                self.tree.clear_commands(guild=guild)
                self.tree.copy_global_to(guild=guild)
                commands_synced = await self.tree.sync(guild=guild)
                LOGGER.info(
                    "%s commandes synchronisées sur le serveur %s en %.3fs",
                    len(commands_synced),
                    GUILD_ID,
                    time.perf_counter() - started,
                )
                performed = True
            else:
                LOGGER.warning(
                    "SYNC_GUILD_COMMANDS est actif, mais GUILD_ID est absent ou invalide."
                )

        if SYNC_GLOBAL_COMMANDS:
            started = time.perf_counter()
            commands_synced = await self.tree.sync()
            LOGGER.info(
                "%s commandes globales synchronisées en %.3fs",
                len(commands_synced),
                time.perf_counter() - started,
            )
            performed = True

        if not performed:
            LOGGER.info(
                "Synchronisation Discord ignorée. Les commandes déjà publiées restent actives."
            )

    async def _database_backup_loop(self) -> None:
        interval = DATABASE_BACKUP_INTERVAL_HOURS * 3600
        try:
            while not self.is_closed():
                await asyncio.sleep(interval)
                await create_backup(reason="scheduled")
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("La boucle de sauvegarde SQLite s'est arrêtée.")

    async def _event_loop_watchdog(self) -> None:
        loop = asyncio.get_running_loop()
        expected = loop.time() + EVENT_LOOP_WATCHDOG_INTERVAL

        try:
            while not self.is_closed():
                await asyncio.sleep(EVENT_LOOP_WATCHDOG_INTERVAL)
                now = loop.time()
                delay = max(0.0, now - expected)
                expected = now + EVENT_LOOP_WATCHDOG_INTERVAL

                if delay < EVENT_LOOP_WARNING_SECONDS:
                    continue

                LOGGER.error(
                    "La boucle asyncio a été bloquée pendant environ %.3fs.",
                    delay,
                )
                current = asyncio.current_task()
                reported = 0

                for task in asyncio.all_tasks(loop):
                    if task is current or task.done():
                        continue
                    frames = task.get_stack(limit=3)
                    if not frames:
                        continue

                    LOGGER.error(
                        "Tâche potentiellement bloquante : %s (%r)",
                        task.get_name(),
                        task.get_coro(),
                    )
                    for frame in frames:
                        extracted = traceback.extract_stack(frame, limit=1)
                        if extracted:
                            info = extracted[0]
                            LOGGER.error(
                                "%s:%s dans %s -> %s",
                                info.filename,
                                info.lineno,
                                info.name,
                                info.line or "",
                            )
                    reported += 1
                    if reported >= 8:
                        break
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Le watchdog asyncio s'est arrêté.")

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if (
            DEBUG_INTERACTIONS
            and interaction.type is discord.InteractionType.application_command
        ):
            LOGGER.info(
                "[INTERACTION] id=%s name=%s guild=%s user=%s",
                interaction.id,
                interaction_name(interaction),
                interaction.guild_id,
                interaction.user.id,
            )

    async def on_socket_raw_receive(self, message: str | bytes) -> None:
        if not DEBUG_INTERACTIONS:
            return

        text = (
            message.decode("utf-8", errors="ignore")
            if isinstance(message, bytes)
            else message
        )
        if "INTERACTION_CREATE" not in text:
            return

        try:
            payload: dict[str, Any] = json.loads(text)
            data = payload.get("d") or {}
            command_data = data.get("data") or {}
            LOGGER.debug(
                "[GATEWAY] id=%s command=%s guild=%s application=%s",
                data.get("id"),
                command_data.get("name"),
                data.get("guild_id"),
                data.get("application_id"),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            LOGGER.debug("Payload INTERACTION_CREATE illisible.")

    async def close(self) -> None:
        LOGGER.info("Arrêt propre de Hamtaro.")

        for task in tuple(self._background_tasks):
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(
                *tuple(self._background_tasks),
                return_exceptions=True,
            )
        self._background_tasks.clear()

        connection = getattr(self.db, "conn", None)
        await checkpoint_wal(connection)

        if DATABASE_BACKUPS_ENABLED:
            with suppress(Exception):
                await create_backup(reason="shutdown")

        try:
            await self.db.close()
        finally:
            await super().close()


bot = HamtaroBot()


async def send_interaction_message(
    interaction: discord.Interaction,
    message: str,
    *,
    ephemeral: bool = True,
) -> bool:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(
                message,
                ephemeral=ephemeral,
            )
        return True
    except discord.InteractionResponded:
        try:
            await interaction.followup.send(message, ephemeral=ephemeral)
            return True
        except (discord.NotFound, discord.HTTPException):
            return False
    except discord.NotFound as error:
        if error.code == 10062:
            LOGGER.warning("Interaction expirée : %s", interaction.id)
            return False
        LOGGER.exception("Erreur Discord sur l'interaction %s", interaction.id)
        return False
    except discord.HTTPException as error:
        if error.code in {10062, 40060}:
            LOGGER.warning(
                "Interaction expirée ou déjà reconnue : %s code=%s",
                interaction.id,
                error.code,
            )
            return False
        LOGGER.exception("Erreur HTTP Discord sur %s", interaction.id)
        return False
    except Exception:
        LOGGER.exception("Erreur inattendue sur %s", interaction.id)
        return False


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    original = getattr(error, "original", error)

    if isinstance(original, StaffOnly):
        await send_interaction_message(
            interaction,
            "⛔ Cette commande est réservée au staff.",
        )
        return

    if isinstance(original, app_commands.CommandOnCooldown):
        await send_interaction_message(
            interaction,
            f"⏳ Réessaie dans {original.retry_after:.1f} seconde(s).",
        )
        return

    if isinstance(original, discord.InteractionResponded):
        LOGGER.warning("Double réponse évitée pour %s", interaction_name(interaction))
        return

    if (
        isinstance(original, discord.HTTPException)
        and original.code in {10062, 40060}
    ):
        LOGGER.warning(
            "Interaction Discord expirée ou déjà reconnue : %s code=%s",
            interaction.id,
            original.code,
        )
        return

    LOGGER.error(
        "Erreur slash command %s : %r",
        interaction_name(interaction),
        original,
        exc_info=(type(original), original, original.__traceback__),
    )
    await send_interaction_message(
        interaction,
        "❌ Une erreur est survenue. Le problème a été enregistré dans les logs.",
    )


@bot.event
async def on_ready() -> None:
    if bot._ready_logged:
        LOGGER.info("Hamtaro reconnecté à Discord.")
        return

    bot._ready_logged = True
    LOGGER.info("----------------------------------------")
    LOGGER.info("HAMTARO prêt : %s", bot.user)
    LOGGER.info("Latence Gateway : %.0f ms", bot.latency * 1000)
    LOGGER.info("Build : %s", BOT_BUILD)
    LOGGER.info("Cogs chargés : %s", len(bot.extensions))
    LOGGER.info("----------------------------------------")


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN est introuvable dans les variables d'environnement."
        )

    runtime_lock = RuntimeLock(INSTANCE_LOCK_PATH)
    try:
        runtime_lock.acquire()
    except AlreadyRunningError as error:
        raise RuntimeError(
            "Une autre instance Hamtaro utilise déjà le même volume. "
            "Conserve un seul service et un seul réplica Railway."
        ) from error

    try:
        bot.run(TOKEN, log_handler=None)
    finally:
        runtime_lock.release()


if __name__ == "__main__":
    main()
