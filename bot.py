from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import traceback
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config import TOKEN
from database import init_db
from services.database_service import DatabaseService
from utils.permissions import StaffOnly


logging.basicConfig(
    level=getattr(
        logging,
        os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        logging.INFO,
    ),
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)

LOGGER = logging.getLogger("hamtaro")
BOT_BUILD = "interaction-fix-2026-08-04-2133"


COGS = [
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
    "cogs.graphics_preview",
    "cogs.swiss_graphics",
    "cogs.tournament_context",
    "cogs.tournament_undo",
    "cogs.match_center",
    "cogs.tournament_progression",
    "cogs.deck_stats",
    "cogs.tournament_export",
    "cogs.public_website",
    "cogs.hamtaro_hub",
]


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default

    return value.strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }


def _interaction_name(interaction: discord.Interaction) -> str:
    data = interaction.data
    if isinstance(data, dict):
        name = data.get("name")
        if name:
            return str(name)

    command = interaction.command
    if command is not None:
        return str(getattr(command, "qualified_name", command.name))

    return "interaction-inconnue"


class LoggingCommandTree(app_commands.CommandTree):
    """Journalise le passage d'une commande avant son callback."""

    async def interaction_check(
        self,
        interaction: discord.Interaction,
        /,
    ) -> bool:
        LOGGER.warning(
            (
                "[COMMAND_TREE] interaction reçue "
                "id=%s commande=%s guild=%s user=%s"
            ),
            interaction.id,
            _interaction_name(interaction),
            interaction.guild_id,
            interaction.user.id,
        )
        return True


class HamtaroBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            tree_cls=LoggingCommandTree,
        )

        self.db = DatabaseService()
        self._watchdog_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        LOGGER.warning(
            "[BOOT] Hamtaro version=%s fichier=%s",
            BOT_BUILD,
            __file__,
        )

        self._watchdog_task = asyncio.create_task(
            self._event_loop_watchdog(),
            name="hamtaro-event-loop-watchdog",
        )

        init_started = time.perf_counter()
        await init_db()
        LOGGER.info(
            "[BOOT] init_db terminé en %.3fs",
            time.perf_counter() - init_started,
        )

        db_started = time.perf_counter()
        await self.db.connect()
        LOGGER.info(
            "[BOOT] connexion DatabaseService terminée en %.3fs",
            time.perf_counter() - db_started,
        )

        for cog in COGS:
            cog_started = time.perf_counter()
            try:
                await self.load_extension(cog)
                LOGGER.info(
                    "✅ Cog chargé : %s en %.3fs",
                    cog,
                    time.perf_counter() - cog_started,
                )
            except Exception:
                LOGGER.exception("❌ Erreur chargement %s", cog)

        await self._sync_application_commands()

    async def _sync_application_commands(self) -> None:
        """
        Synchronise les commandes globales et, lorsqu'un identifiant de
        serveur est configuré, remplace les anciennes commandes de serveur
        par une copie exacte des commandes actuellement chargées.
        """

        try:
            started = time.perf_counter()
            global_synced = await self.tree.sync()
            LOGGER.warning(
                "[SYNC] %s commande(s) globale(s) synchronisée(s) en %.3fs",
                len(global_synced),
                time.perf_counter() - started,
            )
        except Exception:
            LOGGER.exception(
                "❌ Erreur lors de la synchronisation globale des commandes"
            )
            return

        guild_id = (
            os.getenv("GUILD_ID")
            or os.getenv("PUBLIC_GUILD_ID")
            or ""
        ).strip()

        sync_guild = _truthy(
            os.getenv("SYNC_GUILD_COMMANDS"),
            default=True,
        )

        if not sync_guild:
            LOGGER.info(
                "[SYNC] Synchronisation de serveur désactivée par "
                "SYNC_GUILD_COMMANDS."
            )
            return

        if not guild_id.isdigit():
            LOGGER.warning(
                "[SYNC] Aucun GUILD_ID/PUBLIC_GUILD_ID valide : "
                "les anciennes commandes propres au serveur ne peuvent "
                "pas être remplacées automatiquement."
            )
            return

        guild = discord.Object(id=int(guild_id))

        try:
            started = time.perf_counter()

            # Supprime de l'arbre local les anciennes définitions de serveur,
            # puis copie les commandes globales réellement chargées.
            self.tree.clear_commands(guild=guild)
            self.tree.copy_global_to(guild=guild)

            guild_synced = await self.tree.sync(guild=guild)

            LOGGER.warning(
                (
                    "[SYNC] %s commande(s) synchronisée(s) sur le serveur "
                    "%s en %.3fs"
                ),
                len(guild_synced),
                guild_id,
                time.perf_counter() - started,
            )
        except Exception:
            LOGGER.exception(
                "❌ Erreur lors de la synchronisation des commandes "
                "du serveur %s",
                guild_id,
            )

    async def _event_loop_watchdog(self) -> None:
        """Détecte les traitements synchrones qui figent tout le bot."""

        interval = max(
            0.5,
            float(os.getenv("EVENT_LOOP_WATCHDOG_INTERVAL", "1.0")),
        )
        warning_after = max(
            1.0,
            float(os.getenv("EVENT_LOOP_WARNING_SECONDS", "2.0")),
        )

        loop = asyncio.get_running_loop()
        expected = loop.time() + interval

        try:
            while not self.is_closed():
                await asyncio.sleep(interval)

                now = loop.time()
                delay = max(0.0, now - expected)
                expected = now + interval

                if delay < warning_after:
                    continue

                LOGGER.error(
                    (
                        "[EVENT_LOOP_BLOCKED] La boucle asyncio a été "
                        "bloquée pendant environ %.3fs. Une fonction "
                        "synchrone lourde s'exécute probablement dans un "
                        "async def."
                    ),
                    delay,
                )

                current = asyncio.current_task()
                reported = 0

                for task in asyncio.all_tasks(loop):
                    if task is current or task.done():
                        continue

                    frames = task.get_stack(limit=4)
                    if not frames:
                        continue

                    reported += 1
                    LOGGER.error(
                        "[EVENT_LOOP_TASK] nom=%s coroutine=%r",
                        task.get_name(),
                        task.get_coro(),
                    )

                    for frame in frames:
                        extracted = traceback.extract_stack(frame, limit=1)
                        if not extracted:
                            continue

                        info = extracted[0]
                        LOGGER.error(
                            "[EVENT_LOOP_STACK] %s:%s dans %s -> %s",
                            info.filename,
                            info.lineno,
                            info.name,
                            info.line or "",
                        )

                    if reported >= 12:
                        break

        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Le watchdog asyncio s'est arrêté anormalement.")

    async def on_interaction(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.type is discord.InteractionType.application_command:
            LOGGER.warning(
                (
                    "[INTERACTION_EVENT] id=%s commande=%s "
                    "guild=%s user=%s"
                ),
                interaction.id,
                _interaction_name(interaction),
                interaction.guild_id,
                interaction.user.id,
            )

    async def on_socket_raw_receive(self, msg: str | bytes) -> None:
        """
        Journalise INTERACTION_CREATE au niveau Gateway. Si ce log apparaît
        mais pas [COMMAND_TREE], Discord a bien envoyé l'interaction mais
        discord.py ne l'a pas associée à la commande chargée.
        """

        if isinstance(msg, bytes):
            try:
                text = msg.decode("utf-8")
            except UnicodeDecodeError:
                return
        else:
            text = msg

        if "INTERACTION_CREATE" not in text:
            return

        try:
            payload: dict[str, Any] = json.loads(text)
            data = payload.get("d") or {}
            command_data = data.get("data") or {}
            LOGGER.warning(
                (
                    "[GATEWAY_INTERACTION_CREATE] id=%s commande=%s "
                    "guild=%s application=%s"
                ),
                data.get("id"),
                command_data.get("name"),
                data.get("guild_id"),
                data.get("application_id"),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            LOGGER.warning(
                "[GATEWAY_INTERACTION_CREATE] interaction reçue, "
                "mais le payload n'a pas pu être décodé."
            )

    async def close(self) -> None:
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None

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
    """
    Envoie une réponse sans provoquer une seconde exception si
    l'interaction est déjà reconnue, expirée ou inconnue de Discord.

    Retourne True si le message a été envoyé, sinon False.
    """

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=ephemeral,
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=ephemeral,
            )

        return True

    except discord.InteractionResponded:
        try:
            await interaction.followup.send(
                message,
                ephemeral=ephemeral,
            )
            return True
        except (
            discord.NotFound,
            discord.HTTPException,
        ):
            return False

    except discord.NotFound as error:
        if error.code == 10062:
            LOGGER.warning(
                "Interaction expirée ou inconnue : %s",
                interaction.id,
            )
            return False

        LOGGER.exception(
            "Erreur Discord pendant l'envoi de l'interaction %s",
            interaction.id,
        )
        return False

    except discord.HTTPException as error:
        if error.code in {10062, 40060}:
            LOGGER.warning(
                "Interaction déjà reconnue ou expirée : %s code=%s",
                interaction.id,
                error.code,
            )
            return False

        LOGGER.exception(
            "Erreur HTTP Discord pendant l'envoi de l'interaction %s",
            interaction.id,
        )
        return False

    except Exception:
        LOGGER.exception(
            "Erreur inattendue pendant l'envoi de l'interaction %s",
            interaction.id,
        )
        return False


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    """
    Gestionnaire global des erreurs des commandes slash.

    Il vérifie toujours si l'interaction a déjà été reconnue avant
    d'essayer d'envoyer un message.
    """

    original_error = getattr(
        error,
        "original",
        error,
    )

    if isinstance(original_error, StaffOnly):
        await send_interaction_message(
            interaction,
            "⛔ Cette commande est réservée au staff.",
            ephemeral=True,
        )
        return

    if isinstance(original_error, discord.InteractionResponded):
        LOGGER.warning(
            "Une commande a tenté de répondre deux fois : %s",
            interaction.command.name
            if interaction.command
            else "commande inconnue",
        )
        return

    if (
        isinstance(original_error, discord.HTTPException)
        and original_error.code in {10062, 40060}
    ):
        LOGGER.warning(
            "Interaction Discord expirée ou déjà reconnue : %s code=%s",
            interaction.id,
            original_error.code,
        )
        return

    LOGGER.exception(
        "Erreur slash command : %r",
        original_error,
        exc_info=(
            type(original_error),
            original_error,
            original_error.__traceback__,
        ),
    )

    await send_interaction_message(
        interaction,
        "❌ Une erreur est survenue pendant l'exécution de la commande.",
        ephemeral=True,
    )


@bot.event
async def on_ready() -> None:
    LOGGER.warning("------------------------")
    LOGGER.warning("🐹 HAMTARO")
    LOGGER.warning("Utilisateur : %s", bot.user)
    LOGGER.warning("Latence Gateway : %.3fs", bot.latency)
    LOGGER.warning("Version : %s", BOT_BUILD)
    LOGGER.warning("------------------------")


if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN est introuvable dans les variables d'environnement."
    )


bot.run(TOKEN)
