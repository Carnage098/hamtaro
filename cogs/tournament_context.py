from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.tournament_resolver import active_tournament_code_autocomplete


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
    """Sélectionne le tournoi utilisé par les commandes dans chaque salon."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    def _ids(self, interaction: discord.Interaction) -> tuple[str, str]:
        if interaction.guild is None or interaction.channel_id is None:
            raise ValueError("Cette commande doit être utilisée dans un salon de serveur.")
        return str(interaction.guild.id), str(interaction.channel_id)

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

        try:
            guild_id, _ = self._ids(interaction)
            tournaments = await self.db.list_tournaments(
                guild_id,
                include_finished=not actifs_seulement,
            )
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        if not tournaments:
            await interaction.followup.send("📭 Aucun tournoi trouvé sur ce serveur.")
            return

        lines = ["🏆 **Tournois du serveur**", ""]
        lines.extend(_format_tournament(tournament) for tournament in tournaments[:30])
        await interaction.followup.send("\n".join(lines))

    @app_commands.command(
        name="tournament_select",
        description="Sélectionner le tournoi utilisé dans ce salon",
    )
    @app_commands.describe(code="Code du tournoi, par exemple TCG-1234")
    @app_commands.autocomplete(code=active_tournament_code_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def tournament_select(
        self,
        interaction: discord.Interaction,
        code: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            guild_id, channel_id = self._ids(interaction)
            tournament = await self.db.get_guild_tournament_by_code(guild_id, code)
            if tournament is None:
                raise ValueError(f"Aucun tournoi trouvé avec le code `{code.upper()}`.")

            await self.db.select_tournament_for_channel(
                guild_id=guild_id,
                channel_id=channel_id,
                tournament_id=int(tournament.id),
                selected_by=str(interaction.user.id),
            )
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        await interaction.followup.send(
            "✅ Tournoi sélectionné dans ce salon :\n"
            f"{_format_tournament(tournament)}",
            ephemeral=True,
        )

    @app_commands.command(
        name="tournament_current",
        description="Afficher le tournoi sélectionné dans ce salon",
    )
    async def tournament_current(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            guild_id, channel_id = self._ids(interaction)
            tournament = await self.db.get_selected_tournament(guild_id, channel_id)
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        if tournament is None:
            await interaction.followup.send(
                "📭 Aucun tournoi n'est sélectionné dans ce salon.\n"
                "Utilise `/tournament_select`.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "🎯 **Tournoi sélectionné dans ce salon**\n"
            f"{_format_tournament(tournament)}",
            ephemeral=True,
        )

    @app_commands.command(
        name="tournament_unselect",
        description="Retirer la sélection de tournoi de ce salon",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def tournament_unselect(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            guild_id, channel_id = self._ids(interaction)
            removed = await self.db.unselect_tournament_for_channel(guild_id, channel_id)
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        message = (
            "✅ La sélection de tournoi a été retirée de ce salon."
            if removed
            else "📭 Aucun tournoi n'était sélectionné dans ce salon."
        )
        await interaction.followup.send(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentContextCog(bot))
