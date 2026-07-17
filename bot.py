from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import TOKEN
from database import init_db
from services.database_service import DatabaseService
from utils.permissions import StaffOnly


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
]


class HamtaroBot(commands.Bot):

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
        )

        self.db = DatabaseService()

    async def setup_hook(self) -> None:
        await init_db()
        await self.db.connect()

        for cog in COGS:
            try:
                await self.load_extension(cog)
                print(f"✅ Cog chargé : {cog}")

            except Exception as error:
                print(
                    f"❌ Erreur chargement {cog} : "
                    f"{type(error).__name__}: {error}"
                )

        try:
            synced = await self.tree.sync()
            print(f"✅ {len(synced)} commandes synchronisées")

        except Exception as error:
            print(
                "❌ Erreur synchronisation des commandes : "
                f"{type(error).__name__}: {error}"
            )

    async def close(self) -> None:
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
            print(
                "⚠️ Interaction expirée ou inconnue :",
                interaction.id,
            )
            return False

        print(
            "❌ Erreur Discord pendant l'envoi :",
            repr(error),
        )
        return False

    except discord.HTTPException as error:
        if error.code in {
            10062,
            40060,
        }:
            print(
                "⚠️ Interaction déjà reconnue ou expirée :",
                interaction.id,
                f"code={error.code}",
            )
            return False

        print(
            "❌ Erreur HTTP Discord pendant l'envoi :",
            repr(error),
        )
        return False

    except Exception as error:
        print(
            "❌ Erreur inattendue pendant l'envoi :",
            repr(error),
        )
        return False


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    """
    Gestionnaire global des erreurs des commandes slash.

    Il vérifie toujours si l'interaction a déjà été reconnue
    avant d'essayer d'envoyer un message.
    """

    original_error = getattr(
        error,
        "original",
        error,
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
        print(
            "⚠️ Une commande a tenté de répondre deux fois :",
            interaction.command.name
            if interaction.command
            else "commande inconnue",
        )
        return

    if isinstance(
        original_error,
        discord.HTTPException,
    ) and original_error.code in {
        10062,
        40060,
    }:
        print(
            "⚠️ Interaction Discord expirée ou déjà reconnue :",
            interaction.id,
            f"code={original_error.code}",
        )
        return

    print(
        "❌ Erreur slash command :",
        repr(original_error),
    )

    await send_interaction_message(
        interaction,
        (
            "❌ Une erreur est survenue pendant "
            "l'exécution de la commande."
        ),
        ephemeral=True,
    )


@bot.event
async def on_ready() -> None:
    print("------------------------")
    print("🐹 HAMTARO")
    print(bot.user)
    print("------------------------")


if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN est introuvable dans "
        "les variables d'environnement."
    )


bot.run(TOKEN)
