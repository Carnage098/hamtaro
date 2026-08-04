from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import suppress
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config import TOKEN
from database import init_db
from services.database_service import DatabaseService
from utils.permissions import StaffOnly


# ==========================================================
# JOURNALISATION
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)

LOGGER = logging.getLogger("hamtaro")

BOT_BUILD_VERSION = "interaction-debug-2026-08-04-2154"

LOOP_WATCHDOG_INTERVAL = 1.0
LOOP_WATCHDOG_WARNING_THRESHOLD = 1.5


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


def _truthy(
    value: str | None,
    *,
    default: bool = False,
) -> bool:
    if value is None:
        return default

    return value.strip().lower() not in {
        "",
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }


class LoggingCommandTree(app_commands.CommandTree):
    """
    Arbre de commandes instrumenté.

    Le log COMMAND_TREE apparaît lorsque discord.py a reconnu
    l'interaction comme une commande chargée dans l'arbre local.
    """

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        command_name = (
            interaction.command.qualified_name
            if interaction.command is not None
            else "commande-inconnue"
        )

        LOGGER.warning(
            (
                "[COMMAND_TREE] interaction reçue "
                "id=%s commande=%s utilisateur=%s "
                "serveur=%s salon=%s"
            ),
            interaction.id,
            command_name,
            interaction.user.id,
            interaction.guild_id,
            interaction.channel_id,
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

            # Indispensable pour que on_socket_raw_receive()
            # soit réellement déclenché par discord.py.
            enable_debug_events=True,
        )

        self.db = DatabaseService()
        self._loop_watchdog_task: asyncio.Task[None] | None = None

    # ==========================================================
    # DÉMARRAGE
    # ==========================================================

    async def setup_hook(self) -> None:
        LOGGER.warning(
            "[BOOT] Hamtaro version=%s fichier=%s",
            BOT_BUILD_VERSION,
            __file__,
        )

        started = time.perf_counter()
        await init_db()
        LOGGER.info(
            "[BOOT] init_db terminé en %.3fs",
            time.perf_counter() - started,
        )

        started = time.perf_counter()
        await self.db.connect()
        LOGGER.info(
            "[BOOT] connexion DatabaseService terminée en %.3fs",
            time.perf_counter() - started,
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
                LOGGER.exception(
                    "❌ Erreur pendant le chargement du cog %s",
                    cog,
                )

        await self._sync_application_commands()

        if (
            self._loop_watchdog_task is None
            or self._loop_watchdog_task.done()
        ):
            self._loop_watchdog_task = asyncio.create_task(
                self._loop_watchdog(),
                name="hamtaro-loop-watchdog",
            )

    async def _sync_application_commands(self) -> None:
        """
        Synchronise les commandes globales.

        Par défaut, les anciennes commandes propres au serveur sont
        supprimées afin d'éviter deux versions de la même commande.

        Pour utiliser volontairement des commandes de serveur pendant
        les tests, configure dans Railway :
            SYNC_COMMANDS_TO_GUILD=true
        """

        try:
            started = time.perf_counter()
            global_synced = await self.tree.sync()

            LOGGER.warning(
                (
                    "[SYNC] %s commande(s) globale(s) "
                    "synchronisée(s) en %.3fs"
                ),
                len(global_synced),
                time.perf_counter() - started,
            )

        except Exception:
            LOGGER.exception(
                "[SYNC] Échec de la synchronisation globale"
            )
            return

        raw_guild_id = (
            os.getenv("GUILD_ID")
            or os.getenv("PUBLIC_GUILD_ID")
            or ""
        ).strip()

        if not raw_guild_id:
            LOGGER.info(
                "[SYNC] Aucun GUILD_ID configuré : "
                "aucun nettoyage serveur effectué."
            )
            return

        if not raw_guild_id.isdigit():
            LOGGER.error(
                "[SYNC] GUILD_ID invalide : %r",
                raw_guild_id,
            )
            return

        guild = discord.Object(id=int(raw_guild_id))
        sync_to_guild = _truthy(
            os.getenv("SYNC_COMMANDS_TO_GUILD"),
            default=False,
        )

        try:
            started = time.perf_counter()

            if sync_to_guild:
                # Copie les commandes globales dans le serveur pour
                # obtenir une mise à jour instantanée pendant les tests.
                self.tree.copy_global_to(guild=guild)
                guild_synced = await self.tree.sync(guild=guild)

                LOGGER.warning(
                    (
                        "[SYNC] %s commande(s) copiée(s) sur "
                        "le serveur %s en %.3fs"
                    ),
                    len(guild_synced),
                    raw_guild_id,
                    time.perf_counter() - started,
                )
            else:
                # Évite qu'une ancienne commande de serveur masque
                # ou double la commande globale du même nom.
                self.tree.clear_commands(guild=guild)
                guild_synced = await self.tree.sync(guild=guild)

                LOGGER.warning(
                    (
                        "[SYNC] commandes propres au serveur %s "
                        "nettoyées : %s restante(s) en %.3fs"
                    ),
                    raw_guild_id,
                    len(guild_synced),
                    time.perf_counter() - started,
                )

        except Exception:
            LOGGER.exception(
                "[SYNC] Échec de la synchronisation du serveur %s",
                raw_guild_id,
            )

    # ==========================================================
    # DIAGNOSTIC DE LA BOUCLE ASYNCIO
    # ==========================================================

    async def _loop_watchdog(self) -> None:
        """
        Signale dans Railway lorsqu'une opération synchrone bloque
        entièrement le bot pendant plus de 1,5 seconde.
        """

        loop = asyncio.get_running_loop()
        expected = loop.time() + LOOP_WATCHDOG_INTERVAL

        while not self.is_closed():
            await asyncio.sleep(LOOP_WATCHDOG_INTERVAL)

            now = loop.time()
            drift = now - expected

            if drift >= LOOP_WATCHDOG_WARNING_THRESHOLD:
                LOGGER.warning(
                    (
                        "[ASYNCIO_BLOCK] boucle bloquée ou retardée "
                        "pendant environ %.3fs"
                    ),
                    drift,
                )

            expected = now + LOOP_WATCHDOG_INTERVAL

    # ==========================================================
    # DIAGNOSTIC DES INTERACTIONS
    # ==========================================================

    async def on_socket_raw_receive(
        self,
        message: str | bytes,
    ) -> None:
        """
        Premier niveau du diagnostic.

        Ce log apparaît dès que le Gateway Discord transmet une
        interaction à cette instance du bot.
        """

        if isinstance(message, bytes):
            try:
                raw_message = message.decode(
                    "utf-8",
                    errors="replace",
                )
            except Exception:
                return
        else:
            raw_message = message

        try:
            payload: dict[str, Any] = json.loads(raw_message)
        except (TypeError, ValueError, json.JSONDecodeError):
            return

        if payload.get("t") != "INTERACTION_CREATE":
            return

        data = payload.get("d") or {}
        command_data = data.get("data") or {}

        LOGGER.warning(
            (
                "[GATEWAY_INTERACTION_CREATE] "
                "interaction_id=%s application_id=%s "
                "commande=%s type=%s serveur=%s salon=%s"
            ),
            data.get("id"),
            data.get("application_id"),
            command_data.get("name"),
            data.get("type"),
            data.get("guild_id"),
            data.get("channel_id"),
        )

    async def on_interaction(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Deuxième niveau du diagnostic.

        Ce log apparaît lorsque discord.py a transformé le paquet
        Gateway en objet Interaction.
        """

        command_name = None

        if interaction.data is not None:
            command_name = interaction.data.get("name")

        LOGGER.warning(
            (
                "[INTERACTION_EVENT] id=%s type=%s "
                "commande=%s application_id=%s "
                "utilisateur=%s serveur=%s salon=%s"
            ),
            interaction.id,
            interaction.type,
            command_name,
            interaction.application_id,
            interaction.user.id,
            interaction.guild_id,
            interaction.channel_id,
        )

    async def on_ready(self) -> None:
        guild_ids = [
            guild.id
            for guild in self.guilds
        ]

        LOGGER.warning("------------------------")
        LOGGER.warning("🐹 HAMTARO")
        LOGGER.warning("Utilisateur : %s", self.user)
        LOGGER.warning(
            "Latence Gateway : %.3fs",
            float(self.latency),
        )
        LOGGER.warning("Version : %s", BOT_BUILD_VERSION)

        # Identification essentielle pour vérifier que la commande
        # Discord appartient bien à l'application connectée à Railway.
        LOGGER.warning(
            (
                "[IDENTITE] bot_user_id=%s "
                "application_id=%s guilds=%s"
            ),
            self.user.id if self.user is not None else None,
            self.application_id,
            guild_ids,
        )

        LOGGER.warning("------------------------")

    # ==========================================================
    # FERMETURE
    # ==========================================================

    async def close(self) -> None:
        watchdog = self._loop_watchdog_task
        self._loop_watchdog_task = None

        if watchdog is not None:
            watchdog.cancel()

            with suppress(asyncio.CancelledError):
                await watchdog

        try:
            await self.db.close()
        finally:
            await super().close()


bot = HamtaroBot()


# ==========================================================
# RÉPONSE SÉCURISÉE AUX INTERACTIONS
# ==========================================================

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
                (
                    "Interaction expirée ou inconnue : "
                    "id=%s code=%s"
                ),
                interaction.id,
                error.code,
            )
            return False

        LOGGER.exception(
            "Erreur Discord pendant l'envoi"
        )
        return False

    except discord.HTTPException as error:
        if error.code in {
            10062,
            40060,
        }:
            LOGGER.warning(
                (
                    "Interaction déjà reconnue ou expirée : "
                    "id=%s code=%s"
                ),
                interaction.id,
                error.code,
            )
            return False

        LOGGER.exception(
            "Erreur HTTP Discord pendant l'envoi"
        )
        return False

    except Exception:
        LOGGER.exception(
            "Erreur inattendue pendant l'envoi"
        )
        return False


# ==========================================================
# GESTION GLOBALE DES ERREURS SLASH
# ==========================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    original_error = getattr(
        error,
        "original",
        error,
    )

    command_name = (
        interaction.command.qualified_name
        if interaction.command is not None
        else "commande-inconnue"
    )

    if isinstance(
        original_error,
        StaffOnly,
    ):
        await send_interaction_message(
            interaction,
            "⛔ Cette commande est réservée au staff.",
            ephemeral=True,
        )
        return

    if isinstance(
        original_error,
        discord.InteractionResponded,
    ):
        LOGGER.warning(
            (
                "La commande /%s a tenté de "
                "répondre deux fois."
            ),
            command_name,
        )
        return

    if (
        isinstance(
            original_error,
            discord.HTTPException,
        )
        and original_error.code in {
            10062,
            40060,
        }
    ):
        LOGGER.warning(
            (
                "Interaction Discord expirée ou déjà reconnue : "
                "commande=%s id=%s code=%s"
            ),
            command_name,
            interaction.id,
            original_error.code,
        )
        return

    LOGGER.error(
        "Erreur slash command /%s : %r",
        command_name,
        original_error,
        exc_info=(
            type(original_error),
            original_error,
            original_error.__traceback__,
        ),
    )

    await send_interaction_message(
        interaction,
        (
            "❌ Une erreur est survenue pendant "
            "l'exécution de la commande."
        ),
        ephemeral=True,
    )


# ==========================================================
# LANCEMENT
# ==========================================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN est introuvable dans "
        "les variables d'environnement."
    )


# log_handler=None évite que les lignes discord.py soient
# affichées deux fois lorsque logging.basicConfig est actif.
bot.run(
    TOKEN,
    log_handler=None,
)
