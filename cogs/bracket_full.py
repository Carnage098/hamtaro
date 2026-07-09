from __future__ import annotations

import aiosqlite
import discord

from discord.ext import commands
from discord import app_commands

from config import DATABASE

from utils.embeds import info_embed, error_embed


class BracketFullCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.db = bot.db

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

    async def _get_tournament(
        self,
        interaction: discord.Interaction,
        tournament_id: int | None,
    ):
        if tournament_id is not None:
            return await self.db.get_tournament(
                tournament_id
            )

        guild_id = self._guild_id(
            interaction
        )

        return await self.db.get_active_tournament(
            guild_id
        )

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

    def _row_value(
        self,
        row,
        *names: str,
        default=None,
    ):
        for name in names:
            try:
                value = row[name]

                if value is not None:
                    return value

            except Exception:
                continue

        return default

    def _status_icon(
        self,
        status: str | None,
    ) -> str:
        status = str(status or "").lower()

        if status in {
            "approved",
            "finished",
            "completed",
        }:
            return "✅"

        if status in {
            "pending",
            "reported",
        }:
            return "⏳"

        if status in {
            "refused",
            "rejected",
        }:
            return "❌"

        if status in {
            "waiting",
            "created",
        }:
            return "⚔️"

        return "•"

    def _round_title(
        self,
        round_number: int | str,
        max_round: int | None = None,
    ) -> str:
        try:
            round_int = int(round_number)

        except Exception:
            return f"Round {round_number}"

        if max_round is not None:
            if round_int == max_round:
                return "Finale"

            if round_int == max_round - 1:
                return "Demi-finales"

            if round_int == max_round - 2:
                return "Quarts de finale"

        return f"Round {round_int}"

    def _format_match_line(
        self,
        row,
    ) -> str:
        match_id = self._row_value(
            row,
            "id",
            "match_id",
            default="?",
        )

        player1 = self._row_value(
            row,
            "player1_name",
            "p1_name",
            default="Joueur 1",
        )

        player2 = self._row_value(
            row,
            "player2_name",
            "p2_name",
            default="Joueur 2",
        )

        score = self._row_value(
            row,
            "score",
            default=None,
        )

        winner = self._row_value(
            row,
            "winner_name",
            default=None,
        )

        status = self._row_value(
            row,
            "status",
            default="waiting",
        )

        icon = self._status_icon(
            status
        )

        if score:
            score_text = f" — `{score}`"
        else:
            score_text = ""

        if winner:
            winner_text = f"\n🏆 Vainqueur : **{winner}**"
        else:
            winner_text = ""

        return (
            f"{icon} **Match #{match_id}**\n"
            f"**{player1}** vs **{player2}**{score_text}"
            f"{winner_text}"
        )

    async def _fetch_matches(
        self,
        tournament_id: int,
    ):
        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT *
                FROM matches
                WHERE tournament_id = ?
                ORDER BY
                    COALESCE(round_number, round, 0) ASC,
                    id ASC
            """, (
                tournament_id,
            ))

            return await cursor.fetchall()

    def _group_matches_by_round(
        self,
        rows,
    ) -> dict:
        grouped = {}

        for row in rows:
            round_number = self._row_value(
                row,
                "round_number",
                "round",
                default="?",
            )

            grouped.setdefault(
                round_number,
                [],
            ).append(row)

        return grouped

    # ==========================================================
    # BRACKET FULL
    # ==========================================================

    @app_commands.command(
        name="bracket_full",
        description="Afficher le bracket complet du tournoi actif"
    )
    @app_commands.describe(
        tournament_id="ID du tournoi, optionnel si un tournoi est actif"
    )
    async def bracket_full(
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

            matches = await self._fetch_matches(
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

        except Exception as error:
            await self._send_error(
                interaction=interaction,
                title="Bracket indisponible",
                description=(
                    "Hamtaro n'a pas réussi à lire le bracket.\n\n"
                    f"Erreur : `{error}`"
                ),
                ephemeral=True,
            )
            return

        if not matches:
            embed = info_embed(
                title=f"Bracket — {tournament.name}",
                description=(
                    "Aucun match n'a encore été généré pour ce tournoi.\n\n"
                    "Le bracket apparaîtra après le lancement du tournoi."
                ),
            )

            embed.set_footer(
                text="Hamtaro Tournament Manager"
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=False,
            )
            return

        grouped = self._group_matches_by_round(
            matches
        )

        numeric_rounds = []

        for round_key in grouped.keys():
            try:
                numeric_rounds.append(
                    int(round_key)
                )

            except Exception:
                pass

        max_round = max(numeric_rounds) if numeric_rounds else None

        embed = info_embed(
            title=f"Bracket complet — {tournament.name}",
            description=(
                "Voici l'état actuel du bracket.\n\n"
                "✅ terminé • ⏳ en attente de validation • ⚔️ à jouer"
            ),
        )

        for round_number, round_matches in sorted(
            grouped.items(),
            key=lambda item: int(item[0]) if str(item[0]).isdigit() else 999,
        ):
            title = self._round_title(
                round_number=round_number,
                max_round=max_round,
            )

            lines = [
                self._format_match_line(row)
                for row in round_matches
            ]

            value = "\n\n".join(lines)

            if len(value) > 1024:
                value = value[:1000] + "\n\n…"

            embed.add_field(
                name=f"🔄 {title}",
                value=value,
                inline=False,
            )

        embed.set_footer(
            text=f"{len(matches)} match(s) affiché(s)"
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=False,
        )


async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        BracketFullCog(bot)
    )
