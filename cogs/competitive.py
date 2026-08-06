from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.competitive_service import CompetitiveService, MIN_OFFICIAL_GAMES
from services.expansion_database import init_expansion_schema, normalize_format
from utils.expansion_permissions import staff_only




def build_season_summary_embed(summary: dict[str, object]) -> discord.Embed:
    season = summary["season"]
    assert isinstance(season, dict)
    embed = discord.Embed(
        title=f"🏁 Fin de saison — {season['name']}",
        description=(
            f"**{summary['matches']}** match(s) classé(s) • "
            f"**{summary['players']}** joueur(s) actif(s) • "
            f"minimum officiel : **{summary['minimum_games']} matchs**"
        ),
        color=discord.Color.gold(),
    )
    podium = summary.get("podium") or []
    if podium:
        medals = ("🥇", "🥈", "🥉")
        embed.add_field(
            name="🏆 Podium général",
            value="\n".join(
                f"{medals[index]} **{row['player_name']}** — {row['rating']} ELO "
                f"({row['wins']}V/{row['losses']}D)"
                for index, row in enumerate(podium)
            ),
            inline=False,
        )
    else:
        embed.add_field(
            name="🏆 Podium général",
            value="Aucun joueur n'a atteint le minimum de matchs requis.",
            inline=False,
        )
    champions = summary.get("format_champions") or []
    if champions:
        embed.add_field(
            name="🎴 Champions par format",
            value="\n".join(
                f"**{row['format']}** : {row['player_name']} — {row['rating']} ELO"
                for row in champions[:15]
            ),
            inline=False,
        )
    embed.set_footer(text="Les classements finaux sont archivés et restent consultables.")
    return embed


class CompetitiveCog(commands.Cog):
    competitive = app_commands.Group(
        name="competitive",
        description="Classement ELO, saisons et comparaisons Hamtaro",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = CompetitiveService()

    async def cog_load(self) -> None:
        await init_expansion_schema()

    @competitive.command(name="ranking", description="Afficher le classement ELO officiel d'un format")
    @app_commands.describe(format="Format Yu-Gi-Oh!", visible="Afficher publiquement")
    async def ranking(
        self,
        interaction: discord.Interaction,
        format: str = "Général",
        visible: bool = False,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=not visible)
        guild_id = str(interaction.guild.id)
        season = await self.service.display_season(guild_id)
        rows = await self.service.ranking(guild_id, format, limit=20)
        embed = discord.Embed(
            title=f"🏆 Classement ELO — {normalize_format(format)}",
            description=None,
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Saison affichée",
            value=f"**{season['name']}** — {str(season['status']).title()}",
            inline=False,
        )
        if not rows:
            embed.description = (
                f"Aucun joueur n'a encore atteint les **{MIN_OFFICIAL_GAMES} matchs classés** "
                "requis pour apparaître officiellement."
            )
        else:
            lines = []
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            for index, row in enumerate(rows, start=1):
                label = medals.get(index, f"`#{index}`")
                lines.append(
                    f"{label} **{row['player_name']}** — **{row['rating']}** ELO "
                    f"({row['wins']}V/{row['losses']}D, {row['games']} matchs)"
                )
            embed.description = "\n".join(lines)
        embed.set_footer(
            text=f"Minimum : {MIN_OFFICIAL_GAMES} matchs • Les BYE et Double Loss ne modifient pas l'ELO."
        )
        await interaction.followup.send(embed=embed, ephemeral=not visible)

    @competitive.command(name="elo", description="Afficher la cote ELO d'un joueur")
    async def elo(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member | None = None,
        format: str = "Général",
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        target = joueur or interaction.user
        row = await self.service.player_rating(
            str(interaction.guild.id), str(target.id), format
        )
        games = int(row["games"])
        win_rate = int(row["wins"]) / games * 100 if games else 0.0
        embed = discord.Embed(
            title=f"📈 ELO de {target.display_name}",
            description=f"Format : **{normalize_format(format)}**",
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        rank_value = (
            f"**#{row['rank']}**"
            if row.get("official") and row.get("rank") is not None
            else f"**Provisoire** ({row['games']}/{MIN_OFFICIAL_GAMES})"
        )
        embed.add_field(name="Classement", value=rank_value, inline=True)
        embed.add_field(name="Cote", value=f"**{row['rating']}**", inline=True)
        embed.add_field(name="Record", value=f"**{row['peak_rating']}**", inline=True)
        embed.add_field(name="Saison", value=f"**{row.get('season_name', 'Classement permanent')}**", inline=False)
        embed.add_field(
            name="Bilan",
            value=f"{row['wins']} victoire(s) • {row['losses']} défaite(s)\n{win_rate:.1f} % de victoire",
            inline=False,
        )
        embed.add_field(
            name="Séries",
            value=f"Actuelle : **{row['current_streak']}** • Record : **{row['best_streak']}**",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @competitive.command(name="history", description="Afficher les dernières variations ELO")
    async def history(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member | None = None,
        format: str = "Général",
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        target = joueur or interaction.user
        rows = await self.service.history(
            str(interaction.guild.id), str(target.id), normalize_format(format)
        )
        embed = discord.Embed(
            title=f"📊 Historique ELO — {target.display_name}",
            color=discord.Color.blurple(),
        )
        if not rows:
            embed.description = "Aucune variation enregistrée."
        else:
            embed.description = "\n".join(
                f"{'✅' if row['result']=='win' else '❌'} **{row['format']}** `{row['source_key']}` : "
                f"**{row['old_rating']} → {row['new_rating']}** "
                f"({int(row['delta']):+d})"
                for row in rows
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @competitive.command(name="compare", description="Comparer les confrontations de deux joueurs")
    async def compare(
        self,
        interaction: discord.Interaction,
        joueur_1: discord.Member,
        joueur_2: discord.Member,
        format: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        if joueur_1.id == joueur_2.id:
            await interaction.response.send_message("❌ Choisis deux joueurs différents.", ephemeral=True)
            return
        data = await self.service.head_to_head(
            str(interaction.guild.id), str(joueur_1.id), str(joueur_2.id), format
        )
        scope = normalize_format(format) if format else "Tous les formats"
        embed = discord.Embed(
            title="⚔️ Face-à-face",
            description=f"**{joueur_1.display_name}** contre **{joueur_2.display_name}**\nPortée : **{scope}**",
            color=discord.Color.red(),
        )
        embed.add_field(name=joueur_1.display_name, value=f"**{data['player1_wins']}** victoire(s)", inline=True)
        embed.add_field(name="Matchs", value=f"**{data['matches']}**", inline=True)
        embed.add_field(name=joueur_2.display_name, value=f"**{data['player2_wins']}** victoire(s)", inline=True)
        if data["last"]:
            last = data["last"]
            winner = joueur_1.display_name if str(last["winner_id"]) == str(joueur_1.id) else joueur_2.display_name
            embed.add_field(
                name="Dernier affrontement",
                value=f"Vainqueur : **{winner}** • {last['format']} • `{last['source_key']}`",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @competitive.command(name="sync", description="Synchroniser les nouveaux résultats avec le classement")
    @staff_only()
    async def sync(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        count = await self.service.sync_completed_matches(str(interaction.guild.id))
        await interaction.followup.send(f"✅ **{count}** nouveau(x) match(s) ajouté(s) au classement.", ephemeral=True)

    @competitive.command(name="rebuild", description="Reconstruire entièrement le classement du serveur")
    @staff_only()
    async def rebuild(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        count = await self.service.reset_and_rebuild(str(interaction.guild.id))
        await interaction.followup.send(
            f"✅ Classement reconstruit à partir de **{count}** match(s) validé(s).",
            ephemeral=True,
        )

    @competitive.command(name="season_create", description="Créer une nouvelle saison compétitive")
    @staff_only()
    async def season_create(
        self,
        interaction: discord.Interaction,
        nom: str,
        facteur_reset: app_commands.Range[float, 0.0, 1.0] = 0.50,
        fin_iso: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            season_id = await self.service.create_season(
                guild_id=str(interaction.guild.id),
                name=nom,
                created_by=str(interaction.user.id),
                ends_at=fin_iso,
                soft_reset_factor=float(facteur_reset),
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ Saison **{nom}** créée (`#{season_id}`). Reset progressif : **{facteur_reset:.0%}**. "
            f"Le classement officiel demandera **{MIN_OFFICIAL_GAMES} matchs**.",
            ephemeral=True,
        )

    @competitive.command(name="season_close", description="Clore la saison et publier son bilan final")
    @staff_only()
    async def season_close(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            season = await self.service.close_season(str(interaction.guild.id))
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return
        summary = season["summary"]
        embed = build_season_summary_embed(summary)
        channel = None
        channel_id = await self.service.announcement_channel_id(str(interaction.guild.id))
        if channel_id:
            candidate = interaction.guild.get_channel(int(channel_id))
            if isinstance(candidate, discord.TextChannel):
                channel = candidate
        if channel is None and isinstance(interaction.channel, discord.TextChannel):
            channel = interaction.channel
        if channel is not None:
            message = await channel.send(embed=embed)
            await self.service.mark_season_summary_sent(int(season["id"]))
            await interaction.followup.send(
                f"✅ Saison **{season['name']}** clôturée. Bilan publié : {message.jump_url}",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                content=f"✅ Saison **{season['name']}** clôturée, mais aucun salon d'annonce valide n'a été trouvé.",
                embed=embed,
                ephemeral=True,
            )

    @competitive.command(name="season_ranking", description="Revoir le classement final d'une ancienne saison")
    async def season_ranking(
        self,
        interaction: discord.Interaction,
        saison_id: int,
        format: str = "Général",
        visible: bool = False,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=not visible)
        try:
            rows = await self.service.season_ranking(
                str(interaction.guild.id), saison_id, format, limit=20
            )
            summary = await self.service.season_summary(str(interaction.guild.id), saison_id)
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return
        season = summary["season"]
        embed = discord.Embed(
            title=f"📜 {season['name']} — {normalize_format(format)}",
            color=discord.Color.gold(),
        )
        if rows:
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            embed.description = "\n".join(
                f"{medals.get(index, f'`#{index}`')} **{row['player_name']}** — "
                f"**{row['rating']}** ELO ({row['wins']}V/{row['losses']}D)"
                for index, row in enumerate(rows, start=1)
            )
        else:
            embed.description = "Aucun joueur officiellement classé dans ce format."
        embed.set_footer(text=f"Archive de saison • minimum {MIN_OFFICIAL_GAMES} matchs")
        await interaction.followup.send(embed=embed, ephemeral=not visible)

    @competitive.command(name="season_status", description="Afficher la saison compétitive actuelle")
    async def season_status(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        season = await self.service.season_status(str(interaction.guild.id))
        if season is None:
            await interaction.response.send_message(
                "ℹ️ Aucun découpage saisonnier actif : Hamtaro utilise le classement permanent.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(title=f"🗓️ Saison — {season['name']}", color=discord.Color.gold())
        embed.add_field(name="Statut", value=str(season["status"]).title(), inline=True)
        embed.add_field(name="Début", value=str(season["starts_at"]), inline=True)
        embed.add_field(name="Fin", value=str(season["ends_at"] or "Non définie"), inline=True)
        embed.add_field(name="Reset progressif", value=f"{float(season['soft_reset_factor']):.0%}", inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CompetitiveCog(bot))
