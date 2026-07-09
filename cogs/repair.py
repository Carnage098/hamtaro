from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from services.bracket_service import BracketService

from utils.embeds import success_embed, error_embed, info_embed
from utils.permissions import staff_only


class RepairCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.db = bot.db
        self.brackets = BracketService(self.db)

    # ==========================================================
    # OUTILS INTERNES
    # ==========================================================

    def _guild_id(
        self,
        interaction: discord.Interaction,
    ) -> str:
        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(interaction.guild.id)

    async def _send_error(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        ephemeral: bool = True,
    ):
        embed = error_embed(
            title=title,
            description=description,
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                embed=embed,
                ephemeral=ephemeral,
            )
        else:
            await interaction.response.send_message(
                embed=embed,
                ephemeral=ephemeral,
            )

    async def _get_tournament(
        self,
        interaction: discord.Interaction,
        tournament_id: int | None,
    ):
        if tournament_id is not None:
            tournament = await self.db.get_tournament(
                tournament_id
            )

            return tournament

        guild_id = self._guild_id(interaction)

        tournament = await self.db.get_active_tournament(
            guild_id
        )

        return tournament

    # ==========================================================
    # REPAIR TOURNAMENT
    # ==========================================================

    @app_commands.command(
        name="repair_tournament",
        description="Réparer ou resynchroniser un tournoi bloqué"
    )
    @app_commands.describe(
        tournament_id="ID du tournoi à réparer, facultatif si un tournoi est actif"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def repair_tournament(
        self,
        interaction: discord.Interaction,
        tournament_id: int | None = None,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        actions = []
        warnings = []

        try:
            tournament = await self._get_tournament(
                interaction=interaction,
                tournament_id=tournament_id,
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi trouvé",
                    description=(
                        "Aucun tournoi actif n'a été trouvé.\n\n"
                        "Tu peux aussi préciser un `tournament_id`."
                    ),
                )
                return

            actions.append(
                "✅ Tournoi trouvé."
            )

            current_round = await self.brackets.sync_current_round(
                tournament.id
            )

            if current_round is not None:
                actions.append(
                    f"✅ Round actuel resynchronisé : `{current_round}`."
                )
            else:
                warnings.append(
                    "⚠️ Aucun round actuel détecté."
                )

            winner = await self.brackets.get_winner(
                tournament.id
            )

            if winner is not None:
                _, winner_name = winner

                actions.append(
                    f"🏆 Champion détecté : **{winner_name}**."
                )
            else:
                actions.append(
                    "✅ Aucun champion détecté pour le moment."
                )

            registrations = await self.db.list_registrations(
                tournament.id
            )

            actions.append(
                f"👥 Joueurs inscrits détectés : **{len(registrations)}**."
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Réparation impossible",
                description=str(error),
            )
            return

        except Exception as error:
            await self._send_error(
                interaction=interaction,
                title="Erreur inattendue",
                description=(
                    "Hamtaro n'a pas pu terminer la réparation.\n\n"
                    f"Erreur : `{error}`"
                ),
            )
            return

        description_parts = []

        if actions:
            description_parts.append(
                "\n".join(actions)
            )

        if warnings:
            description_parts.append(
                "\n".join(warnings)
            )

        embed = success_embed(
            title="Tournoi réparé",
            description="\n\n".join(description_parts),
        )

        embed.add_field(
            name="🏆 Tournoi",
            value=f"**{tournament.name}**",
            inline=False,
        )

        embed.add_field(
            name="🆔 ID",
            value=f"`{tournament.id}`",
            inline=True,
        )

        embed.set_footer(
            text="Diagnostic Hamtaro terminé"
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        RepairCog(bot)
    )
