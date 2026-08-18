from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.boss_service import BossService
from utils.permissions import staff_only


LOGGER = logging.getLogger("hamtaro.boss")


class BossCog(commands.Cog):
    boss = app_commands.Group(
        name="boss",
        description="Gérer le format Boss Hamtaro",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = BossService()

    async def cog_load(self) -> None:
        await self.service.ensure_schema()

    @staticmethod
    def _guild_id(interaction: discord.Interaction) -> str:
        if interaction.guild is None:
            raise ValueError("Cette commande doit être utilisée sur un serveur Discord.")
        return str(interaction.guild.id)

    async def _channel(
        self,
        guild: discord.Guild,
        state: dict,
    ) -> discord.TextChannel | None:
        raw = str(state.get("announcement_channel_id") or "")
        if not raw.isdigit():
            return None
        channel = guild.get_channel(int(raw))
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _announce(
        self,
        interaction: discord.Interaction,
        *,
        title: str,
        description: str,
    ) -> bool:
        if interaction.guild is None:
            return False
        state = await self.service.state(str(interaction.guild.id))
        channel = await self._channel(interaction.guild, state)
        if channel is None:
            return False
        embed = discord.Embed(
            title=title,
            description=description,
            colour=discord.Colour.orange(),
        )
        embed.set_footer(text="Format Boss · Hamtaro")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            LOGGER.exception("Impossible d'envoyer l'annonce Boss.")
            return False
        return True

    @boss.command(name="status", description="Afficher le Boss et l'état de la semaine")
    async def status(self, interaction: discord.Interaction) -> None:
        try:
            guild_id = self._guild_id(interaction)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        state = await self.service.state(guild_id)
        challengers = await self.service.challengers(guild_id)
        if not state.get("boss_id"):
            await interaction.response.send_message(
                "👑 Aucun Boss n'est encore défini.",
                ephemeral=True,
            )
            return

        lines = [
            f"👑 **Boss actuel : <@{state['boss_id']}>**",
            f"🔥 Série : **{int(state.get('wins_current') or 0)} victoire(s)**",
            f"📅 Semaine Boss : **{int(state.get('week_number') or 1)}**",
            f"⚔️ Challengers : **{len(challengers)}**",
            (
                "📝 Inscriptions : **ouvertes**"
                if int(state.get("registrations_open") or 0)
                else "📝 Inscriptions : **fermées**"
            ),
        ]
        if state.get("successor_id"):
            lines.append(
                f"💀 Boss tombé · prochain Boss : <@{state['successor_id']}>"
            )
        await interaction.response.send_message("\n".join(lines))

    @boss.command(name="inscription", description="S'inscrire pour affronter le Boss")
    async def inscription(self, interaction: discord.Interaction) -> None:
        try:
            guild_id = self._guild_id(interaction)
            row = await self.service.register_challenger(
                guild_id,
                str(interaction.user.id),
                getattr(interaction.user, "display_name", interaction.user.name),
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"⚔️ Inscription confirmée ! Position actuelle : **#{row['position']}**.",
            ephemeral=True,
        )

    @boss.command(name="desinscription", description="Se retirer de la file du Boss")
    async def desinscription(self, interaction: discord.Interaction) -> None:
        try:
            guild_id = self._guild_id(interaction)
            await self.service.unregister_challenger(
                guild_id,
                str(interaction.user.id),
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            "✅ Tu as été retiré de la file du Boss.",
            ephemeral=True,
        )

    @boss.command(name="set", description="Définir le Boss actuel")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def set_boss(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
    ) -> None:
        guild_id = self._guild_id(interaction)
        state = await self.service.set_boss(
            guild_id,
            str(joueur.id),
            joueur.display_name,
        )
        await interaction.response.send_message(
            f"👑 {joueur.mention} devient le **Boss** de la semaine {state['week_number']}.",
            ephemeral=True,
        )
        await self._announce(
            interaction,
            title="👑 UN NOUVEAU BOSS PREND LE TRÔNE",
            description=(
                f"{joueur.mention} devient le Boss Hamtaro.\n\n"
                "Les challengers devront le faire tomber pour prendre sa place la semaine suivante."
            ),
        )

    @boss.command(name="inscriptions", description="Ouvrir ou fermer les inscriptions Boss")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def inscriptions(
        self,
        interaction: discord.Interaction,
        ouvertes: bool,
    ) -> None:
        guild_id = self._guild_id(interaction)
        await self.service.set_registrations(guild_id, ouvertes)
        label = "ouvertes" if ouvertes else "fermées"
        await interaction.response.send_message(
            f"📝 Inscriptions Boss **{label}**.",
            ephemeral=True,
        )
        if ouvertes:
            await self._announce(
                interaction,
                title="⚔️ LES INSCRIPTIONS BOSS SONT OUVERTES",
                description=(
                    "Inscris-toi avec **/boss inscription** ou depuis la page "
                    "**/formats/boss** pour tenter de faire tomber le Boss."
                ),
            )

    @boss.command(name="add", description="Ajouter manuellement un challenger")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def add(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
    ) -> None:
        guild_id = self._guild_id(interaction)
        try:
            row = await self.service.register_challenger(
                guild_id,
                str(joueur.id),
                joueur.display_name,
                force=True,
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ {joueur.mention} ajouté en position **#{row['position']}**.",
            ephemeral=True,
        )

    @boss.command(name="remove", description="Retirer un challenger")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def remove(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
    ) -> None:
        guild_id = self._guild_id(interaction)
        try:
            await self.service.unregister_challenger(
                guild_id,
                str(joueur.id),
                force=True,
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ {joueur.mention} a été retiré de la file.",
            ephemeral=True,
        )

    @boss.command(name="programme", description="Afficher l'ordre des duels du Boss")
    async def programme(self, interaction: discord.Interaction) -> None:
        guild_id = self._guild_id(interaction)
        state = await self.service.state(guild_id)
        rows = await self.service.challengers(guild_id)
        if not state.get("boss_id"):
            await interaction.response.send_message(
                "❌ Aucun Boss n'est défini.",
                ephemeral=True,
            )
            return
        if not rows:
            await interaction.response.send_message(
                "📅 Aucun challenger inscrit pour le moment."
            )
            return

        status_icon = {
            "registered": "⏳",
            "scheduled": "🗓️",
            "defeated": "✅",
            "boss_killer": "💀",
        }
        lines = []
        for row in rows:
            icon = status_icon.get(str(row["status"]), "•")
            when = f" — {row['scheduled_at']}" if row.get("scheduled_at") else ""
            lines.append(
                f"{icon} **#{row['position']}** <@{row['discord_id']}>{when}"
            )

        await interaction.response.send_message(
            f"👑 **Programme du Boss <@{state['boss_id']}>**\n\n"
            + "\n".join(lines)
        )

    @boss.command(name="planifier", description="Attribuer une date/heure à un challenger")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def planifier(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        date_heure: str,
    ) -> None:
        guild_id = self._guild_id(interaction)
        try:
            await self.service.schedule_challenger(
                guild_id,
                str(joueur.id),
                date_heure,
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🗓️ Duel de {joueur.mention} planifié : **{date_heure}**.",
            ephemeral=True,
        )

    @boss.command(name="move", description="Changer la position d'un challenger")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def move(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        position: app_commands.Range[int, 1, 200],
    ) -> None:
        guild_id = self._guild_id(interaction)
        try:
            await self.service.move_challenger(
                guild_id,
                str(joueur.id),
                int(position),
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"↕️ {joueur.mention} déplacé en position **#{position}**.",
            ephemeral=True,
        )

    @boss.command(name="swap", description="Échanger deux challengers dans le programme")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def swap(
        self,
        interaction: discord.Interaction,
        joueur_1: discord.Member,
        joueur_2: discord.Member,
    ) -> None:
        guild_id = self._guild_id(interaction)
        try:
            await self.service.swap_challengers(
                guild_id,
                str(joueur_1.id),
                str(joueur_2.id),
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🔁 {joueur_1.mention} et {joueur_2.mention} ont échangé leur place.",
            ephemeral=True,
        )

    @boss.command(name="resultat", description="Enregistrer le résultat d'un duel Boss")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def resultat(
        self,
        interaction: discord.Interaction,
        challenger: discord.Member,
        gagnant: discord.Member,
    ) -> None:
        guild_id = self._guild_id(interaction)
        try:
            result = await self.service.record_result(
                guild_id,
                str(challenger.id),
                str(gagnant.id),
                gagnant.display_name,
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        state = result["state"]
        if result["boss_won"]:
            await interaction.response.send_message(
                f"🔥 Victoire du Boss. Série actuelle : **{state['wins_current']}**.",
                ephemeral=True,
            )
            await self._announce(
                interaction,
                title="🔥 LE BOSS SURVIT",
                description=(
                    f"<@{state['boss_id']}> bat {challenger.mention}.\n"
                    f"Série actuelle : **{state['wins_current']} victoire(s)**."
                ),
            )
        else:
            await interaction.response.send_message(
                f"💀 {challenger.mention} a fait tomber le Boss et deviendra le prochain Boss.",
                ephemeral=True,
            )
            await self._announce(
                interaction,
                title="💀 LE BOSS EST TOMBÉ",
                description=(
                    f"{challenger.mention} vient de renverser <@{state['boss_id']}>.\n\n"
                    f"👑 **{challenger.mention} prendra le trône la semaine prochaine.**"
                ),
            )

    @boss.command(name="publier", description="Publier le programme Boss dans le salon d'annonces")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def publier(self, interaction: discord.Interaction) -> None:
        guild_id = self._guild_id(interaction)
        state = await self.service.state(guild_id)
        rows = await self.service.challengers(guild_id)

        if not state.get("boss_id"):
            await interaction.response.send_message(
                "❌ Aucun Boss n'est défini.",
                ephemeral=True,
            )
            return
        if not rows:
            await interaction.response.send_message(
                "❌ Le programme est vide.",
                ephemeral=True,
            )
            return

        lines = []
        for row in rows:
            when = row.get("scheduled_at") or "horaire à définir"
            lines.append(
                f"**#{row['position']}** <@{row['discord_id']}> — {when}"
            )

        sent = await self._announce(
            interaction,
            title="👑 PROGRAMME DU BOSS",
            description=(
                f"Boss actuel : <@{state['boss_id']}>\n\n"
                + "\n".join(lines)
                + "\n\n⚔️ Qui fera tomber le Boss ?"
            ),
        )
        if not sent:
            await interaction.response.send_message(
                "❌ Aucun salon d'annonces Boss n'est configuré. Utilise `/boss salon`.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "✅ Programme publié.",
            ephemeral=True,
        )

    @boss.command(name="salon", description="Choisir le salon des annonces Boss")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def salon(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
    ) -> None:
        guild_id = self._guild_id(interaction)
        await self.service.set_announcement_channel(
            guild_id,
            str(salon.id),
        )
        await interaction.response.send_message(
            f"📢 Les annonces Boss seront envoyées dans {salon.mention}.",
            ephemeral=True,
        )

    @boss.command(name="next_week", description="Passer à la semaine Boss suivante")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def next_week(self, interaction: discord.Interaction) -> None:
        guild_id = self._guild_id(interaction)
        before = await self.service.state(guild_id)
        try:
            after = await self.service.next_week(guild_id)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        changed = str(before.get("boss_id")) != str(after.get("boss_id"))
        await interaction.response.send_message(
            (
                f"✅ Semaine Boss **#{after['week_number']}** ouverte. "
                + (
                    f"Nouveau Boss : <@{after['boss_id']}>."
                    if changed
                    else f"<@{after['boss_id']}> conserve son trône."
                )
            ),
            ephemeral=True,
        )
        await self._announce(
            interaction,
            title="👑 NOUVELLE SEMAINE BOSS",
            description=(
                f"<@{after['boss_id']}> prend officiellement le trône."
                if changed
                else (
                    f"<@{after['boss_id']}> reste Boss après avoir survécu "
                    "à la semaine précédente."
                )
            ),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BossCog(bot))
