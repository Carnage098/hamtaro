from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


STATUS_LABELS = {
    "registration": "Inscriptions",
    "checkin": "Check-in",
    "check-in": "Check-in",
    "running": "En cours",
    "finished": "Terminé",
    "cancelled": "Annulé",
}


def _status_value(tournament) -> str:
    status = getattr(tournament, "status", "")
    return str(getattr(status, "value", status)).lower()


def _format_tournament(tournament) -> str:
    status = STATUS_LABELS.get(_status_value(tournament), _status_value(tournament))
    current_round = int(getattr(tournament, "current_round", 0) or 0)
    total_rounds = int(getattr(tournament, "total_rounds", 0) or 0)
    progression = f" — ronde {current_round}/{total_rounds}" if total_rounds > 0 else ""
    return (
        f"`{tournament.code}` — **{tournament.name}** "
        f"({getattr(tournament, 'format', 'Format inconnu')}) — {status}{progression}"
    )


class TournamentContextCog(commands.Cog):
    """Affiche les tournois du serveur.

    La sélection manuelle par salon a été retirée : les fils Hamtaro connaissent
    désormais automatiquement le tournoi auquel appartient leur match.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(
        name="tournament_list",
        description="Afficher les tournois du serveur",
    )
    @app_commands.describe(actifs_seulement="Masquer les tournois terminés et annulés")
    async def tournament_list(
        self,
        interaction: discord.Interaction,
        actifs_seulement: bool = True,
    ) -> None:
        await interaction.response.defer(ephemeral=False)

        if interaction.guild is None:
            await interaction.followup.send(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        tournaments = await self.db.list_tournaments(
            str(interaction.guild.id),
            include_finished=not actifs_seulement,
        )

        if not tournaments:
            await interaction.followup.send("📭 Aucun tournoi trouvé sur ce serveur.")
            return

        lines = ["🏆 **Tournois du serveur**", ""]
        lines.extend(_format_tournament(tournament) for tournament in tournaments[:30])
        await interaction.followup.send("\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentContextCog(bot))
