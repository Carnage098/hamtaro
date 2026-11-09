from __future__ import annotations

import asyncio
import io
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.weekly_program_service import (
    get_week_program, init_weekly_schema, program_description,
    publication_due, render_weekly_poster,
)
from utils.permissions import staff_only

LOGGER = logging.getLogger("hamtaro.weekly_program")


class WeeklyProgramCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot, self.db = bot, bot.db
        self.lock = asyncio.Lock()

    async def cog_load(self):
        await init_weekly_schema(self.db)
        self.weekly_scan.start()

    def cog_unload(self):
        self.weekly_scan.cancel()

    @staticmethod
    def publication_authorized() -> bool:
        return os.getenv("HAMTARO_WEEKLY_ENABLED", "false").lower() in {"true", "1", "yes"}

    async def initialize_from_environment(self):
        """Configuration initiale facultative, sans modifier un réglage du staff."""
        channel_id = os.getenv("HAMTARO_WEEKLY_CHANNEL_ID", "").strip()
        if not channel_id:
            return
        guild_id = (os.getenv("GUILD_ID") or os.getenv("PUBLIC_GUILD_ID") or "").strip()
        if not guild_id.isdecimal() or not channel_id.isdecimal():
            LOGGER.error("Configuration affiche refusée : identifiants de serveur/salon invalides.")
            return
        guild = self.bot.get_guild(int(guild_id))
        channel = guild.get_channel(int(channel_id)) if guild else None
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != int(guild_id):
            LOGGER.error("Configuration affiche refusée : salon=%s absent du serveur=%s. Aucun autre salon utilisé.", channel_id, guild_id)
            return
        automatic = os.getenv("HAMTARO_WEEKLY_AUTOMATIC", "false").strip().lower() in {"true", "1", "yes"}
        changed = await self.db.update("""INSERT INTO weekly_program_settings
            (guild_id,channel_id,weekday,hour,minute,enabled) VALUES (?,?,2,18,0,?)
            ON CONFLICT(guild_id) DO NOTHING""", (guild_id, channel_id, int(automatic)))
        if changed:
            LOGGER.info("Configuration affiche initialisée : serveur=%s (%s), salon=#%s (%s), mercredi 18:00 Paris, automatique=%s, publication autorisée=%s. Aucun message envoyé par l’initialisation.",
                        guild.name, guild_id, channel.name, channel_id, automatic, self.publication_authorized())
        else:
            LOGGER.info("Configuration affiche existante conservée pour serveur=%s ; variables initiales non réappliquées.", guild_id)

    async def publish(self, guild_id: str, *, refresh: bool = False) -> str:
        if not self.publication_authorized():
            raise ValueError("Publication désactivée : activation Railway requise après accord du propriétaire.")
        async with self.lock:
            settings = await self.db.fetchone("SELECT * FROM weekly_program_settings WHERE guild_id=?", (guild_id,))
            if settings is None:
                raise ValueError("Configure d’abord le salon avec la commande staff de configuration de l’annonce.")
            guild = self.bot.get_guild(int(guild_id))
            channel = guild.get_channel(int(settings["channel_id"])) if guild else None
            if not isinstance(channel, discord.TextChannel):
                raise ValueError("Le salon configuré est introuvable dans ce serveur. Aucun autre salon ne sera utilisé.")
            permissions = channel.permissions_for(guild.me)
            if not all((permissions.view_channel, permissions.send_messages, permissions.attach_files, permissions.embed_links, permissions.read_message_history)):
                raise ValueError("Hamtaro doit pouvoir voir le salon, envoyer des messages, joindre des fichiers, intégrer des liens et lire l’historique.")
            program = await get_week_program(self.db, guild_id)
            key = program["key"]
            previous = await self.db.fetchone("SELECT * FROM weekly_program_publications WHERE guild_id=? AND week_key=?", (guild_id, key))
            marker = f"Hamtaro · programme {key}"
            if previous and previous["status"] == "pending":
                # Une panne entre l’envoi et l’enregistrement ne doit jamais doubler le message.
                previous_channel = guild.get_channel(int(previous["channel_id"]))
                if not isinstance(previous_channel, discord.TextChannel):
                    raise ValueError("Envoi précédent incertain : ancien salon inaccessible, vérification staff requise.")
                async for message in previous_channel.history(limit=100):
                    if message.author.id == self.bot.user.id and any(embed.footer.text == marker for embed in message.embeds):
                        await self._mark_sent(guild_id, key, message.id)
                        return message.jump_url
                raise ValueError("Envoi précédent incertain : vérifie le salon et les logs. Aucun renvoi automatique pour éviter un doublon.")
            if previous and previous["status"] == "sent" and not refresh:
                return f"https://discord.com/channels/{guild_id}/{previous['channel_id']}/{previous['message_id']}"
            image = await asyncio.to_thread(render_weekly_poster, program)
            file = discord.File(io.BytesIO(image), filename=f"hamtaro-{key}.png")
            embed = discord.Embed(title="Le programme Hamtaro de la semaine", description=program_description(program), color=0xF4C66A)
            embed.set_image(url=f"attachment://hamtaro-{key}.png")
            embed.set_footer(text=marker)
            if previous and previous["status"] == "sent":
                # Une commande manuelle actualise le message existant, sans spam.
                old_channel = guild.get_channel(int(previous["channel_id"]))
                if not isinstance(old_channel, discord.TextChannel):
                    raise ValueError("Le salon du message existant est inaccessible.")
                message = await old_channel.fetch_message(int(previous["message_id"]))
                await message.edit(embed=embed, attachments=[file], allowed_mentions=discord.AllowedMentions.none())
                return message.jump_url
            changed = await self.db.update("""INSERT INTO weekly_program_publications
                (guild_id,week_key,channel_id,status) VALUES (?,?,?,'pending')
                ON CONFLICT(guild_id,week_key) DO UPDATE SET status='pending', error=NULL,
                channel_id=excluded.channel_id, updated_at=CURRENT_TIMESTAMP
                WHERE weekly_program_publications.status='failed'""", (guild_id, key, str(channel.id)))
            if changed != 1:
                raise ValueError("Une publication est déjà en cours ou enregistrée pour cette semaine.")
            try:
                message = await channel.send(embed=embed, file=file, allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.NotFound) as error:
                await self.db.update("UPDATE weekly_program_publications SET status='failed',error=? WHERE guild_id=? AND week_key=?", (type(error).__name__, guild_id, key))
                raise
            # Tout autre échec reste pending : l’envoi a pu arriver chez Discord.
            await self._mark_sent(guild_id, key, message.id)
            LOGGER.info("Affiche semaine=%s envoyée dans #%s (ID=%s), message=%s", key, channel.name, channel.id, message.id)
            return message.jump_url

    async def _mark_sent(self, guild_id: str, key: str, message_id: int):
        await self.db.update("""UPDATE weekly_program_publications SET status='sent',message_id=?,error=NULL,
            updated_at=CURRENT_TIMESTAMP WHERE guild_id=? AND week_key=?""", (str(message_id), guild_id, key))

    @tasks.loop(minutes=5)
    async def weekly_scan(self):
        if not self.publication_authorized():
            return
        for row in await self.db.fetchall("SELECT * FROM weekly_program_settings WHERE enabled=1"):
            if publication_due(dict(row)):
                try:
                    await self.publish(str(row["guild_id"]))
                except Exception:
                    LOGGER.exception("Publication hebdomadaire impossible pour serveur=%s", row["guild_id"])

    @weekly_scan.before_loop
    async def before_scan(self):
        await self.bot.wait_until_ready()
        try:
            await self.initialize_from_environment()
        except Exception:
            LOGGER.exception("Initialisation du salon hebdomadaire impossible ; aucun réglage de remplacement appliqué.")

    @app_commands.command(name="schedule_poster", description="Générer en privé l’affiche des tournois de la semaine.")
    @app_commands.guild_only()
    @staff_only()
    @app_commands.describe(semaine_suivante="Afficher la semaine suivante plutôt que la semaine actuelle.")
    async def poster(self, interaction: discord.Interaction, semaine_suivante: bool = False):
        await interaction.response.defer(ephemeral=True)
        program = await get_week_program(self.db, str(interaction.guild_id), week_offset=int(semaine_suivante))
        image = await asyncio.to_thread(render_weekly_poster, program)
        await interaction.followup.send(content=program_description(program), file=discord.File(io.BytesIO(image), filename=f"hamtaro-{program['key']}.png"), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="schedule_publish", description="Publier l’affiche dans le salon configuré, ou actualiser celle déjà publiée.")
    @app_commands.guild_only()
    @staff_only()
    async def publish_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            url = await self.publish(str(interaction.guild_id), refresh=True)
            await interaction.followup.send(f"Programme publié : {url}", ephemeral=True)
        except (ValueError, discord.HTTPException) as error:
            await interaction.followup.send(str(error), ephemeral=True)

    @app_commands.command(name="schedule_settings", description="Choisir le salon et l’heure de publication de l’affiche hebdomadaire.")
    @app_commands.guild_only()
    @staff_only()
    @app_commands.describe(salon="Salon exact de publication", automatique="Activer la publication récurrente", jour="Lundi=0, mardi=1, mercredi=2, jeudi=3, vendredi=4", heure="Heure de Paris", minute="Minute de publication")
    async def settings(self, interaction: discord.Interaction, salon: discord.TextChannel,
                       automatique: bool = False, jour: app_commands.Range[int, 0, 4] = 2,
                       heure: app_commands.Range[int, 0, 23] = 18, minute: app_commands.Range[int, 0, 59] = 0):
        if salon.guild.id != interaction.guild_id:
            await interaction.response.send_message("Choisis un salon de ce serveur.", ephemeral=True)
            return
        await self.db.update("""INSERT INTO weekly_program_settings(guild_id,channel_id,weekday,hour,minute,enabled)
            VALUES (?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,
            weekday=excluded.weekday,hour=excluded.hour,minute=excluded.minute,enabled=excluded.enabled""",
            (str(interaction.guild_id), str(salon.id), jour, heure, minute, int(automatique)))
        days = ("lundi", "mardi", "mercredi", "jeudi", "vendredi")
        await interaction.response.send_message(f"Salon : {salon.mention} (`{salon.id}`) · {days[jour]} {heure:02d}:{minute:02d}, Paris. Automatique : {'oui' if automatique else 'non'}. Activation Railway : {'oui' if self.publication_authorized() else 'en attente'}. Aucun message publié par cette configuration.", ephemeral=True)

    @app_commands.command(name="schedule_status", description="Vérifier le salon, la programmation et le dernier envoi de l’affiche.")
    @app_commands.guild_only()
    @staff_only()
    async def status(self, interaction: discord.Interaction):
        settings = await self.db.fetchone("SELECT * FROM weekly_program_settings WHERE guild_id=?", (str(interaction.guild_id),))
        last = await self.db.fetchone("SELECT * FROM weekly_program_publications WHERE guild_id=? ORDER BY week_key DESC LIMIT 1", (str(interaction.guild_id),))
        text = "Aucun salon configuré." if settings is None else f"Salon : <#{settings['channel_id']}> (`{settings['channel_id']}`) · jour {settings['weekday']} (lundi=0) à {settings['hour']:02d}:{settings['minute']:02d} Paris · automatique : {bool(settings['enabled'])}."
        text += f"\nActivation Railway : {self.publication_authorized()}."
        if last:
            text += f"\nDernière semaine : {last['week_key']} · état : {last['status']} · message : {last['message_id'] or 'non confirmé'}."
        await interaction.response.send_message(text, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(WeeklyProgramCog(bot))
