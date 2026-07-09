from __future__ import annotations

import aiosqlite
import discord

from discord.ext import commands
from discord import app_commands

from config import DATABASE

from services.bracket_service import BracketService

from utils.embeds import info_embed, error_embed


class TournamentStatusCog(commands.Cog):

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
            return await self.db.get_tournament(
                tournament_id
            )

        guild_id = self._guild_id(interaction)

        return await self.db.get_active_tournament(
            guild_id
        )

    def _status_value(
        self,
        tournament,
    ) -> str:
        status = getattr(
            tournament,
            "status",
            "unknown",
        )

        return getattr(
            status,
            "value",
            str(status),
        )

    def _pretty_status(
        self,
        status: str,
    ) -> str:
        labels = {
            "registration": "🟢 Inscriptions ouvertes",
            "check_in": "🟡 Check-in désactivé",
            "running": "🔵 En cours",
            "finished": "🏁 Terminé",
            "cancelled": "🔴 Annulé",
        }

        return labels.get(
            status,
            f"`{status}`",
        )

    async def _count_players(
        self,
        tournament_id: int,
    ) -> int:
        try:
            return await self.db.count_registrations(
                tournament_id
            )

        except Exception:
            registrations = await self.db.list_registrations(
                tournament_id
            )

            return len(registrations)

    async def _match_stats(
        self,
        tournament_id: int,
    ) -> dict[str, int | None]:
        """
        Récupère les statistiques des matchs.

        Si la table ou les colonnes ne correspondent pas,
        Hamtaro continue quand même avec des valeurs inconnues.
        """

        stats: dict[str, int | None] = {
            "total": None,
            "waiting": None,
            "pending": None,
            "finished": None,
        }

        try:
            async with aiosqlite.connect(DATABASE) as db:
                cursor = await db.execute("""
                    SELECT
                        COUNT(*) AS total,

                        SUM(
                            CASE
                                WHEN LOWER(COALESCE(status, '')) IN (
                                    'waiting',
                                    'pending',
                                    'reported'
                                )
                                THEN 1
                                ELSE 0
                            END
                        ) AS waiting,

                        SUM(
                            CASE
                                WHEN LOWER(COALESCE(status, '')) IN (
                                    'pending',
                                    'reported'
                                )
                                THEN 1
                                ELSE 0
                            END
                        ) AS pending,

                        SUM(
                            CASE
                                WHEN LOWER(COALESCE(status, '')) IN (
                                    'approved',
                                    'finished'
                                )
                                THEN 1
                                ELSE 0
                            END
                        ) AS finished

                    FROM matches
                    WHERE tournament_id = ?
                """, (
                    tournament_id,
                ))

                row = await cursor.fetchone()

                if row is None:
                    return stats

                stats["total"] = int(row[0] or 0)
                stats["waiting"] = int(row[1] or 0)
                stats["pending"] = int(row[2] or 0)
                stats["finished"] = int(row[3] or 0)

        except Exception:
            return stats

        return stats

    async def _safe_current_round(
        self,
        tournament_id: int,
    ) -> int | None:
        try:
            return await self.brackets.sync_current_round(
                tournament_id
            )

        except Exception:
            return None

    async def _safe_winner(
        self,
        tournament_id: int,
    ):
        try:
            return await self.brackets.get_winner(
                tournament_id
            )

        except Exception:
            return None

    async def _safe_round_text(
        self,
        tournament_id: int,
    ) -> str | None:
        try:
            text = await self.brackets.format_current_round(
                tournament_id
            )

            if not text:
                return None

            return text

        except Exception:
            return None

    # ==========================================================
    # TOURNAMENT STATUS
    # ==========================================================

    @app_commands.command(
        name="tournament_status",
        description="Voir l'état complet du tournoi actif"
    )
    @app_commands.describe(
        tournament_id="ID du tournoi, optionnel si un tournoi est actif"
    )
    async def tournament_status(
        self,
        interaction: discord.Interaction,
        tournament_id: int | None = None,
    ):
        await interaction.response.defer(
            ephemeral=False
        )

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
                    ephemeral=True,
                )
                return

            player_count = await self._count_players(
                tournament.id
            )

            current_round = await self._safe_current_round(
                tournament.id
            )

            winner = await self._safe_winner(
                tournament.id
            )

            round_text = await self._safe_round_text(
                tournament.id
            )

            match_stats = await self._match_stats(
                tournament.id
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Erreur",
                description=str(error),
                ephemeral=True,
            )
            return

        status = self._status_value(
            tournament
        )

        max_players = getattr(
            tournament,
            "max_players",
            "?",
        )

        tournament_format = getattr(
            tournament,
            "format",
            None,
        ) or getattr(
            tournament,
            "format_name",
            None,
        ) or "Non renseigné"

        embed = info_embed(
            title=f"État du tournoi — {tournament.name}",
            description="Voici le résumé actuel du tournoi Hamtaro.",
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

        embed.add_field(
            name="🎮 Format",
            value=f"`{tournament_format}`",
            inline=True,
        )

        embed.add_field(
            name="📌 Statut",
            value=self._pretty_status(status),
            inline=True,
        )

        embed.add_field(
            name="👥 Joueurs",
            value=f"**{player_count}/{max_players}**",
            inline=True,
        )

        if current_round is not None:
            embed.add_field(
                name="🔄 Round actuel",
                value=f"`{current_round}`",
                inline=True,
            )
        else:
            embed.add_field(
                name="🔄 Round actuel",
                value="Non détecté",
                inline=True,
            )

        if match_stats["total"] is not None:
            embed.add_field(
                name="⚔️ Matchs totaux",
                value=str(match_stats["total"]),
                inline=True,
            )

            embed.add_field(
                name="⏳ Matchs en attente",
                value=str(match_stats["waiting"]),
                inline=True,
            )

            embed.add_field(
                name="✅ Matchs terminés",
                value=str(match_stats["finished"]),
                inline=True,
            )

            embed.add_field(
                name="🧾 Résultats à valider",
                value=str(match_stats["pending"]),
                inline=True,
            )

        else:
            embed.add_field(
                name="⚔️ Matchs",
                value="Statistiques indisponibles.",
                inline=False,
            )

        if winner is not None:
            _, winner_name = winner

            embed.add_field(
                name="👑 Champion",
                value=f"**{winner_name}**",
                inline=False,
            )

        if round_text:
            embed.add_field(
                name="📋 Round en cours",
                value=round_text[:1024],
                inline=False,
            )

        embed.set_footer(
            text="Hamtaro Tournament Manager"
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=False,
        )


async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        TournamentStatusCog(bot)
    )
