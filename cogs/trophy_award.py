from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.trophy_manual_service import TrophyManualAwardService
from utils.permissions import staff_only


LOGGER = logging.getLogger("hamtaro.trophy_award")

KNOWN_TROPHIES: tuple[tuple[str, str], ...] = (
    ("HT-001", "Premier Champion"),
    ("HT-002", "Full Blue-Eyes"),
    ("HT-003", "Spiderman"),
)


class TrophyAwardCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = TrophyManualAwardService(bot)

    async def trophy_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        del interaction
        needle = str(current or "").strip().lower()
        choices: list[app_commands.Choice[str]] = []

        for trophy_id, label in KNOWN_TROPHIES:
            haystack = f"{trophy_id} {label}".lower()
            if not needle or needle in haystack:
                choices.append(
                    app_commands.Choice(
                        name=f"{trophy_id} — {label}",
                        value=trophy_id,
                    )
                )

        # Autorise aussi les futurs HT-004, HT-005, etc. sans modifier le cog.
        normalized = str(current or "").strip().upper()
        if normalized and all(normalized != item[0] for item in KNOWN_TROPHIES):
            try:
                normalized = self.service.normalize_trophy_id(normalized)
            except ValueError:
                pass
            else:
                choices.insert(
                    0,
                    app_commands.Choice(
                        name=f"Utiliser {normalized}",
                        value=normalized,
                    ),
                )

        return choices[:25]

    @app_commands.command(
        name="trophy_award",
        description="Attribuer manuellement un trophée Hamtaro à un joueur",
    )
    @app_commands.describe(
        trophy="Identifiant du trophée, par ex. HT-001",
        joueur="Joueur qui reçoit le trophée",
        tournoi_id="ID du tournoi auquel rattacher le trophée",
        remplacer="Remplacer une attribution déjà existante (correction staff)",
    )
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    @app_commands.autocomplete(trophy=trophy_autocomplete)
    async def trophy_award(
        self,
        interaction: discord.Interaction,
        trophy: str,
        joueur: discord.Member,
        tournoi_id: int,
        remplacer: bool = False,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur Discord.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            result = await self.service.award_trophy(
                trophy_id=trophy,
                player_id=str(joueur.id),
                player_name=joueur.display_name,
                guild_id=str(interaction.guild.id),
                tournament_id=tournoi_id,
                replace_existing=remplacer,
            )
        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return
        except Exception:
            LOGGER.exception(
                "Échec attribution manuelle trophée trophy=%s player=%s tournament=%s",
                trophy,
                joueur.id,
                tournoi_id,
            )
            await interaction.followup.send(
                "❌ Impossible d'attribuer le trophée. Le détail est dans les logs Hamtaro.",
                ephemeral=True,
            )
            return

        trophy_id = str(result.get("trophy_id") or trophy).upper()

        if result.get("blocked_existing"):
            holder_name = result.get("holder_name") or "propriétaire inconnu"
            previous_tournament = result.get("tournament_name") or "tournoi inconnu"
            await interaction.followup.send(
                (
                    f"⚠️ **{trophy_id} est déjà attribué** à **{holder_name}** "
                    f"pour **{previous_tournament}**.\n"
                    "Aucune donnée n'a été modifiée. Si c'est une correction volontaire, "
                    "relance la commande avec `remplacer:True`."
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🏆 Trophée attribué",
            description=(
                f"**{trophy_id}** appartient maintenant à {joueur.mention}."
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Joueur",
            value=f"{joueur.display_name} (`{joueur.id}`)",
            inline=False,
        )
        embed.add_field(
            name="Tournoi",
            value=f"{result.get('tournament_name', 'Inconnu')} (`#{result.get('tournament_id', tournoi_id)}`)",
            inline=False,
        )
        embed.add_field(
            name="Deck",
            value=result.get("deck") or "Non trouvé dans les inscriptions",
            inline=True,
        )
        embed.add_field(
            name="Format",
            value=result.get("format") or "Inconnu",
            inline=True,
        )

        if result.get("reassigned"):
            previous_holder = result.get("previous_holder_name") or "propriétaire précédent inconnu"
            embed.add_field(
                name="Correction staff",
                value=f"Ancien propriétaire : **{previous_holder}**",
                inline=False,
            )
            embed.set_footer(text="Attribution remplacée volontairement avec remplacer:True")
        else:
            embed.set_footer(text="Nouvelle attribution enregistrée dans trophy_awards")

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrophyAwardCog(bot))
