from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.casual_result_service import CasualResultService
from services.expansion_database import init_expansion_schema
from services.tournament_extensions_service import TournamentExtensionsService


class CasualResultsPlusCog(commands.Cog):
    casual_result = app_commands.Group(
        name="casual_result",
        description="Double confirmation des résultats de matchs casuels",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = CasualResultService()
        self.settings_service = TournamentExtensionsService()

    async def cog_load(self) -> None:
        await init_expansion_schema()

    @casual_result.command(name="report", description="Déclarer un résultat casual à faire confirmer")
    async def report(
        self,
        interaction: discord.Interaction,
        gagnant: discord.Member,
        score: str,
        match_id: int | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            result = await self.service.report(
                guild_id=str(interaction.guild.id),
                reporter_id=str(interaction.user.id),
                winner_id=str(gagnant.id),
                score=score,
                match_id=match_id,
                channel_id=str(interaction.channel_id) if interaction.channel_id else None,
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        opponent_id = (
            result["loser_id"]
            if str(interaction.user.id) == result["winner_id"]
            else result["winner_id"]
        )
        embed = discord.Embed(
            title="⚔️ Résultat casual à confirmer",
            description=(
                f"Gagnant : <@{result['winner_id']}>\n"
                f"Score : **{result['score']}**\n"
                f"Demande : `#{result['request_id']}`"
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="Validation",
            value=(
                f"<@{opponent_id}> doit utiliser "
                f"`/casual_result confirm demande_id:{result['request_id']}`.\n"
                "En cas de désaccord : `/casual_result contest`."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @casual_result.command(name="confirm", description="Confirmer le résultat déclaré par l'autre joueur")
    async def confirm(
        self,
        interaction: discord.Interaction,
        demande_id: int,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=False)
        try:
            result = await self.service.confirm(
                guild_id=str(interaction.guild.id),
                request_id=demande_id,
                confirmer_id=str(interaction.user.id),
            )
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return
        rated = " • ELO mis à jour" if result["rated"] else ""
        await interaction.followup.send(
            f"✅ Résultat casual confirmé : <@{result['request']['winner_id']}> "
            f"gagne **{result['request']['score']}**{rated}."
        )
        channel = interaction.channel
        if isinstance(channel, discord.Thread):
            for player_id in (result["player1_id"], result["player2_id"]):
                try:
                    member = interaction.guild.get_member(int(player_id))
                    if member is not None:
                        await channel.remove_user(member)
                except (discord.Forbidden, discord.HTTPException):
                    pass
            try:
                await channel.edit(archived=True, locked=True)
            except (discord.Forbidden, discord.HTTPException):
                pass

    @casual_result.command(name="contest", description="Contester un résultat casual déclaré")
    async def contest(
        self,
        interaction: discord.Interaction,
        demande_id: int,
        raison: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            request = await self.service.contest(
                guild_id=str(interaction.guild.id),
                request_id=demande_id,
                contester_id=str(interaction.user.id),
                reason=raison,
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            "⚠️ Le résultat est contesté. Le fil reste ouvert et le staff a été prévenu."
        )
        settings = await self.settings_service.settings(str(interaction.guild.id))
        channel_id = settings.get("judge_channel_id")
        if channel_id and str(channel_id).isdigit():
            channel = self.bot.get_channel(int(channel_id))
            if isinstance(channel, discord.TextChannel):
                embed = discord.Embed(
                    title="⚖️ Résultat casual contesté",
                    description=(
                        f"Demande `#{demande_id}` • match casual `#{request['casual_match_id']}`\n"
                        f"Contesté par {interaction.user.mention}\n"
                        f"Raison : {raison[:1000]}"
                    ),
                    color=discord.Color.red(),
                )
                await channel.send(embed=embed)

    @casual_result.command(name="cancel", description="Annuler ta demande encore en attente")
    async def cancel(self, interaction: discord.Interaction, demande_id: int) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            await self.service.cancel(
                guild_id=str(interaction.guild.id),
                request_id=demande_id,
                reporter_id=str(interaction.user.id),
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message("✅ Demande de résultat annulée.", ephemeral=True)

    @casual_result.command(name="status", description="Afficher l'état d'une demande de résultat casual")
    async def status(self, interaction: discord.Interaction, demande_id: int) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            row = await self.service.pending_request(
                guild_id=str(interaction.guild.id),
                request_id=demande_id,
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"⚔️ Résultat casual #{demande_id}",
            description=(
                f"Statut : **{str(row['status']).title()}**\n"
                f"Gagnant : <@{row['winner_id']}>\n"
                f"Score : **{row['score']}**"
            ),
            color=discord.Color.blurple(),
        )
        if row.get("contest_reason"):
            embed.add_field(name="Contestation", value=str(row["contest_reason"]), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CasualResultsPlusCog(bot))
