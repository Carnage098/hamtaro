from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from services.automation_service import AutomationService
from services.community_service import CommunityService
from services.competitive_service import CompetitiveService
from services.expansion_database import init_expansion_schema


LOGGER = logging.getLogger(__name__)


class ExpansionTasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.automation = AutomationService()
        self.community = CommunityService()
        self.competitive = CompetitiveService()

    async def cog_load(self) -> None:
        await init_expansion_schema()
        self.background_cycle.start()

    def cog_unload(self) -> None:
        self.background_cycle.cancel()

    @tasks.loop(seconds=60)
    async def background_cycle(self) -> None:
        try:
            closed_seasons = await self.competitive.close_expired_seasons()
            await self._send_season_summaries(closed_seasons)
            await self.competitive.sync_completed_matches()
            await self.automation.sync_deck_statistics()
            await self._send_schedule_events()
            await self._send_player_notifications()
            await self.community.close_expired()
        except Exception:
            LOGGER.exception("Erreur dans la boucle Hamtaro Expansion")

    @background_cycle.before_loop
    async def before_background_cycle(self) -> None:
        await self.bot.wait_until_ready()

    async def _send_season_summaries(self, seasons: list[dict[str, object]]) -> None:
        for season in seasons:
            summary = season.get("summary")
            if not isinstance(summary, dict):
                continue
            guild = self.bot.get_guild(int(season["guild_id"]))
            if guild is None:
                continue
            channel_id = await self.competitive.announcement_channel_id(str(guild.id))
            if not channel_id:
                LOGGER.warning(
                    "Saison %s clôturée sans salon d'annonce configuré",
                    season.get("id"),
                )
                continue
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                continue
            season_data = summary["season"]
            embed = discord.Embed(
                title=f"🏁 Fin de saison — {season_data['name']}",
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
                        f"{medals[index]} **{row['player_name']}** — {row['rating']} ELO"
                        for index, row in enumerate(podium)
                    ),
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
            await channel.send(embed=embed)
            await self.competitive.mark_season_summary_sent(int(season["id"]))

    async def _send_schedule_events(self) -> None:
        for event in await self.automation.due_schedule_events():
            channel = self.bot.get_channel(int(event["channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                LOGGER.warning(
                    "Salon introuvable pour la programmation %s",
                    event["id"],
                )
                continue
            name = (
                event.get("tournament_name")
                or event.get("template_tournament_name")
                or event.get("template_name")
                or "Tournoi Hamtaro"
            )
            format_name = event.get("format") or event.get("template_format") or "Format à préciser"
            code = event.get("code")
            event_type = event["event_type"]
            if event_type == "announcement":
                title = "📣 Nouveau tournoi Hamtaro"
                description = f"Les inscriptions ou préparatifs pour **{name}** peuvent commencer."
                color = discord.Color.gold()
            elif event_type == "reminder":
                title = "⏰ Rappel tournoi"
                description = f"**{name}** approche. Vérifiez votre inscription et vos disponibilités."
                color = discord.Color.orange()
            else:
                title = "🚦 Tournoi prêt à être lancé"
                description = (
                    f"**{name}** a atteint son heure de lancement prévue. "
                    "Le staff doit confirmer manuellement le démarrage dans Hamtaro."
                )
                color = discord.Color.green()
            embed = discord.Embed(title=title, description=description, color=color)
            embed.add_field(name="Format", value=str(format_name), inline=True)
            if code:
                embed.add_field(name="Code", value=f"`{code}`", inline=True)
            await channel.send(embed=embed)
            await self.automation.mark_schedule_event_sent(int(event["id"]), event_type)

    async def _send_player_notifications(self) -> None:
        for event in await self.automation.due_player_notifications():
            mark_as_processed = False
            try:
                user = self.bot.get_user(int(event["discord_id"]))
                if user is None:
                    user = await self.bot.fetch_user(int(event["discord_id"]))
                await user.send(
                    "🐹 **Notification Hamtaro**\n" + str(event["message"])
                )
                mark_as_processed = True
            except (discord.Forbidden, discord.NotFound):
                LOGGER.info(
                    "DM Hamtaro impossible pour %s",
                    event["discord_id"],
                )
                mark_as_processed = True
            except discord.HTTPException:
                LOGGER.exception(
                    "Erreur Discord pendant une notification Hamtaro"
                )

            if mark_as_processed:
                await self.automation.mark_player_notification_sent(
                    guild_id=str(event["guild_id"]),
                    discord_id=str(event["discord_id"]),
                    event_key=str(event["event_key"]),
                    event_type=str(event["event_type"]),
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ExpansionTasksCog(bot))
