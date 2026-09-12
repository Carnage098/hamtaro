from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.boss_service import BossService
from cogs.boss_arena_support import BossArenaCoordinator
# HAMTARO BOSS ARENA V1
from utils.permissions import staff_only


LOGGER = logging.getLogger("hamtaro.boss")

PLATFORM_CHOICES = [
    app_commands.Choice(name="Master Duel", value="master_duel"),
    app_commands.Choice(name="Remote Duel", value="remote"),
    app_commands.Choice(name="YGO Omega", value="omega"),
]

FORMAT_CHOICES = [
    app_commands.Choice(name="Format classique", value="classique"),
    app_commands.Choice(name="Format animé", value="anime"),
    app_commands.Choice(name="Deck de structure boutique", value="structure_boutique"),
    app_commands.Choice(name="GOAT", value="goat"),
    app_commands.Choice(name="Edison", value="edison"),
]


class BossCog(commands.Cog):
    boss = app_commands.Group(
        name="boss",
        description="Gérer le format Boss Hamtaro",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = BossService()
        self.arena = BossArenaCoordinator(bot, self.service)

    async def cog_load(self) -> None:
        await self.service.ensure_schema()
        await self.arena.cog_load()

    def cog_unload(self) -> None:
        self.arena.cog_unload()

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

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Récupération idempotente : aucun nouveau fil n'est créé si un match
        # actif existe déjà. Un fil réellement disparu est seulement réparé.
        for guild in self.bot.guilds:
            try:
                await self.arena.recover_and_start(guild)
            except Exception:
                LOGGER.exception("Récupération de l'arène Boss impossible pour %s", guild.id)

    @boss.command(name="status", description="Afficher le Boss et l'état du trône")
    async def status(self, interaction: discord.Interaction) -> None:
        try:
            guild_id = self._guild_id(interaction)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        state = await self.service.state(guild_id)
        challengers = await self.service.challengers(guild_id)
        arena_settings = await self.arena.settings(guild_id)
        if not state.get("boss_id"):
            await interaction.response.send_message(
                "👑 Aucun Boss n'est encore défini.",
                ephemeral=True,
            )
            return

        lines = [
            f"👑 **Boss actuel : <@{state['boss_id']}>**",
            f"🔥 Série : **{int(state.get('wins_current') or 0)} victoire(s)**",
            f"👑 Règne Boss : **#{int(state.get('week_number') or 1)}**",
            f"⚔️ Challengers : **{len(challengers)}**",
            (
                "📝 Inscriptions : **ouvertes**"
                if int(state.get("registrations_open") or 0)
                else "📝 Inscriptions : **fermées**"
            ),
        ]
        if str(arena_settings.get("configured_boss_id") or "") == str(state.get("boss_id")):
            lines.append(
                f"🎮 Plateforme : **{self.arena.platform_label(arena_settings.get('platform_key'))}**"
            )
            lines.append(
                f"🎴 Format : **{self.arena.format_label(arena_settings.get('format_key'))}**"
            )
        else:
            lines.append("⚙️ Configuration : **à choisir avec `/joueur formats config`**")
        if state.get("successor_id"):
            lines.append(
                f"💀 Boss tombé · prochain Boss : <@{state['successor_id']}>"
            )
        await interaction.response.send_message("\n".join(lines))

    @boss.command(name="inscription", description="S'inscrire pour affronter le Boss")
    @app_commands.describe(
        plateforme="Ta plateforme préférée (facultatif)",
        format_jeu="Ton format préféré (facultatif)",
        disponibilite="Tes disponibilités, par ex. samedi 18 h–21 h",
    )
    @app_commands.choices(
        plateforme=PLATFORM_CHOICES,
        format_jeu=FORMAT_CHOICES,
    )
    async def inscription(
        self,
        interaction: discord.Interaction,
        plateforme: app_commands.Choice[str] | None = None,
        format_jeu: app_commands.Choice[str] | None = None,
        disponibilite: app_commands.Range[str, 0, 120] | None = None,
    ) -> None:
        try:
            guild_id = self._guild_id(interaction)
            row = await self.service.register_challenger(
                guild_id,
                str(interaction.user.id),
                getattr(interaction.user, "display_name", interaction.user.name),
                platform_key=plateforme.value if plateforme else None,
                format_key=format_jeu.value if format_jeu else None,
                availability=disponibilite,
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            (
                f"⚔️ Inscription confirmée ! Position actuelle : **#{row['position']}**."
                + (
                    f"\n🎮 Choix : **{self.arena.platform_label(row.get('preferred_platform_key'))}** · "
                    f"**{self.arena.format_label(row.get('preferred_format_key'))}**."
                    if row.get("preferred_platform_key")
                    else "\n🎮 Les choix par défaut du Boss seront utilisés."
                )
            ),
            ephemeral=True,
        )
        if interaction.guild is not None:
            await self.arena.maybe_start_next(interaction.guild)

    @boss.command(name="choix", description="Modifier ses choix de match Boss")
    @app_commands.describe(
        plateforme="Ta plateforme pour le prochain duel",
        format_jeu="Ton format pour le prochain duel",
        disponibilite="Tes disponibilités, par ex. samedi 18 h–21 h",
    )
    @app_commands.choices(
        plateforme=PLATFORM_CHOICES,
        format_jeu=FORMAT_CHOICES,
    )
    async def choix(
        self,
        interaction: discord.Interaction,
        plateforme: app_commands.Choice[str],
        format_jeu: app_commands.Choice[str],
        disponibilite: app_commands.Range[str, 0, 120] | None = None,
    ) -> None:
        try:
            guild_id = self._guild_id(interaction)
            row = await self.service.update_preferences(
                guild_id,
                str(interaction.user.id),
                platform_key=plateforme.value,
                format_key=format_jeu.value,
                availability=disponibilite,
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            (
                "✅ Tes choix Boss ont été mis à jour : "
                f"**{self.arena.platform_label(row['preferred_platform_key'])}** · "
                f"**{self.arena.format_label(row['preferred_format_key'])}**."
            ),
            ephemeral=True,
        )

    @boss.command(name="desinscription", description="Se retirer de la file du Boss")
    async def desinscription(self, interaction: discord.Interaction) -> None:
        try:
            guild_id = self._guild_id(interaction)
            if await self.arena.challenger_has_active_match(
                guild_id, str(interaction.user.id)
            ):
                raise ValueError(
                    "Impossible de quitter la file pendant ton match Boss actif."
                )
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
        before_set = await self.service.state(guild_id)
        state = await self.service.set_boss(
            guild_id,
            str(joueur.id),
            joueur.display_name,
        )
        if interaction.guild is not None:
            await self.arena.on_manual_boss_change(
                interaction.guild,
                old_boss_id=str(before_set.get('boss_id') or '') or None,
                new_boss_id=str(joueur.id),
            )
        else:
            await self.arena.reset_for_new_boss(guild_id)
        await interaction.response.send_message(
            f"👑 {joueur.mention} devient immédiatement le **Boss** (règne #{state['week_number']}).",
            ephemeral=True,
        )
        await self._announce(
            interaction,
            title="👑 UN NOUVEAU BOSS PREND LE TRÔNE",
            description=(
                f"{joueur.mention} devient le Boss Hamtaro.\n\n"
                "Les challengers devront le faire tomber pour prendre immédiatement sa place."
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
        if ouvertes and interaction.guild is not None:
            await self.arena.maybe_start_next(interaction.guild)
        if ouvertes:
            await self._announce(
                interaction,
                title="⚔️ LES INSCRIPTIONS BOSS SONT OUVERTES",
                description=(
                    "Inscris-toi avec **/joueur formats inscription** ou depuis la page "
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
        if interaction.guild is not None:
            await self.arena.maybe_start_next(interaction.guild)

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
            "in_match": "🔴",
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
        if interaction.guild is None:
            await interaction.response.send_message("❌ Serveur introuvable.", ephemeral=True)
            return
        try:
            result = await self.arena.finalize_manual(
                interaction.guild,
                challenger_id=str(challenger.id),
                winner_id=str(gagnant.id),
                winner_name=gagnant.display_name,
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        if result["boss_won"]:
            state = result["state"]
            await interaction.response.send_message(
                f"🔥 Victoire du Boss. Série actuelle : **{state['wins_current']}**.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"⚔️ {challenger.mention} a fait tomber le Boss et devient **immédiatement** le nouveau Boss. "
                f"File conservée : **{result.get('migrated', 0)}** challenger(s).",
                ephemeral=True,
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
                "❌ Aucun salon d'annonces Boss n'est configuré. Utilise `/staff formats salon`.",
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

    @boss.command(name="config", description="Choisir la plateforme et le format du Boss")
    @app_commands.choices(
        plateforme=PLATFORM_CHOICES,
        format_jeu=FORMAT_CHOICES,
    )
    async def config(
        self,
        interaction: discord.Interaction,
        plateforme: app_commands.Choice[str],
        format_jeu: app_commands.Choice[str],
    ) -> None:
        guild_id = self._guild_id(interaction)
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Serveur introuvable.", ephemeral=True)
            return
        state = await self.service.state(guild_id)
        if not state.get("boss_id"):
            await interaction.response.send_message(
                "❌ Aucun Boss n'est actuellement défini.", ephemeral=True
            )
            return
        is_boss = str(state.get("boss_id") or "") == str(interaction.user.id)
        is_manager = interaction.user.guild_permissions.manage_guild
        if not is_boss and not is_manager:
            await interaction.response.send_message(
                "❌ Seul le Boss actuel (ou un administrateur) peut choisir ces règles.",
                ephemeral=True,
            )
            return
        try:
            settings = await self.arena.configure(
                interaction.guild,
                boss_id=str(state.get("boss_id") or interaction.user.id),
                platform_key=plateforme.value,
                format_key=format_jeu.value,
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ Configuration Boss enregistrée : **{self.arena.platform_label(settings['platform_key'])}** · "
            f"**{self.arena.format_label(settings['format_key'])}** · **BO3**.",
            ephemeral=True,
        )

    @boss.command(name="match_salon", description="Choisir le salon qui héberge les fils de match Boss")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def match_salon(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel | None = None,
    ) -> None:
        guild_id = self._guild_id(interaction)
        if interaction.guild is None:
            await interaction.response.send_message("❌ Serveur introuvable.", ephemeral=True)
            return
        if salon is None:
            salon = discord.utils.get(interaction.guild.text_channels, name="⚔️・match-boss")
            if salon is None:
                try:
                    salon = await interaction.guild.create_text_channel(
                        "⚔️・match-boss",
                        reason="Salon automatique du format Boss Hamtaro",
                    )
                except (discord.Forbidden, discord.HTTPException):
                    await interaction.response.send_message(
                        "❌ Hamtaro ne peut pas créer le salon. Crée-le manuellement puis utilise "
                        "`/staff formats match_salon salon:#ton-salon`.",
                        ephemeral=True,
                    )
                    return
        await self.arena.set_match_channel(interaction.guild, salon)
        me = interaction.guild.me
        warning = ""
        if me is not None:
            perms = salon.permissions_for(me)
            missing = []
            if not perms.send_messages:
                missing.append("Envoyer des messages")
            if not perms.create_public_threads:
                missing.append("Créer des fils publics")
            if not perms.manage_threads:
                missing.append("Gérer les fils")
            if missing:
                warning = "\n⚠️ Permissions à ajouter à Hamtaro : " + ", ".join(missing) + "."
        await interaction.response.send_message(
            f"✅ Les matchs Boss seront créés dans {salon.mention}.{warning}",
            ephemeral=True,
        )

    @boss.command(name="next_week", description="Commande héritée : aucun délai hebdomadaire")
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def next_week(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "ℹ️ Le format Boss n'utilise plus de changement hebdomadaire. "
            "Le challenger qui gagne prend désormais le trône immédiatement.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BossCog(bot))
