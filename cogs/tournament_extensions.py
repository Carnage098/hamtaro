from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.expansion_database import init_expansion_schema
from services.swiss_pairing_service import SwissPairingService
from services.tournament_extensions_service import TournamentExtensionsService
from utils.expansion_permissions import staff_only


ISSUE_TYPES = {
    "absence": "no_response",
    "délai": "delay",
    "abandon": "forfeit",
    "connexion": "connection",
    "autre": "other",
}




class FeaturedMatchView(discord.ui.View):
    """Boutons persistants réservés aux deux joueurs d'un match vedette."""

    def __init__(
        self,
        *,
        bot: commands.Bot,
        service: TournamentExtensionsService,
        featured: dict[str, object],
    ) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.service = service
        self.featured = featured
        self.featured_id = int(featured["id"])
        self.player_ids = {
            str(featured.get("player1_id") or ""),
            str(featured.get("player2_id") or ""),
        } - {""}

        ready = discord.ui.Button(
            label="Je suis prêt",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"hamtaro:featured:{self.featured_id}:ready",
        )
        ready.callback = self.ready_callback
        self.add_item(ready)

        voice = discord.ui.Button(
            label="Je suis dans le vocal",
            emoji="🔊",
            style=discord.ButtonStyle.primary,
            custom_id=f"hamtaro:featured:{self.featured_id}:voice",
        )
        voice.callback = self.voice_callback
        self.add_item(voice)

        issue = discord.ui.Button(
            label="Signaler un problème",
            emoji="⚠️",
            style=discord.ButtonStyle.danger,
            custom_id=f"hamtaro:featured:{self.featured_id}:issue",
        )
        issue.callback = self.issue_callback
        self.add_item(issue)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) not in self.player_ids:
            await interaction.response.send_message(
                "❌ Seuls les deux joueurs du match peuvent utiliser ces boutons.",
                ephemeral=True,
            )
            return False
        return True

    async def ready_callback(self, interaction: discord.Interaction) -> None:
        await self.service.update_featured_checkin(
            featured_id=self.featured_id,
            discord_id=str(interaction.user.id),
            ready=True,
        )
        await interaction.response.send_message(
            "✅ Tu es indiqué comme prêt. Rejoins maintenant le salon vocal et partage ton écran.",
            ephemeral=True,
        )

    async def voice_callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Serveur introuvable.", ephemeral=True)
            return
        voice_channel_id = str(self.featured.get("voice_channel_id") or "")
        if not voice_channel_id:
            await interaction.response.send_message(
                "⚠️ Aucun salon vocal de streaming n'est configuré pour ce match.",
                ephemeral=True,
            )
            return
        voice_state = interaction.user.voice
        in_target = bool(
            voice_state
            and voice_state.channel
            and str(voice_state.channel.id) == voice_channel_id
        )
        streaming = bool(voice_state and voice_state.self_stream)
        await self.service.update_featured_checkin(
            featured_id=self.featured_id,
            discord_id=str(interaction.user.id),
            in_voice=in_target,
            streaming=streaming if in_target else False,
        )
        if not in_target:
            await interaction.response.send_message(
                f"❌ Tu n'es pas encore dans <#{voice_channel_id}>.",
                ephemeral=True,
            )
            return
        if not streaming:
            await interaction.response.send_message(
                "🔊 Ta présence dans le vocal est confirmée, mais ton partage d'écran n'est pas encore détecté. Active **Partager ton écran**, puis appuie de nouveau sur ce bouton.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "✅ Présence et partage d'écran confirmés.",
            ephemeral=True,
        )

    async def issue_callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Serveur introuvable.", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        opponent_id = next((value for value in self.player_ids if value != user_id), None)
        issue_id = await self.service.create_match_issue(
            guild_id=str(interaction.guild.id),
            tournament_id=(
                int(self.featured["tournament_id"])
                if self.featured.get("tournament_id") is not None
                else None
            ),
            source_kind=str(self.featured["source_kind"]),
            match_id=int(self.featured["match_id"]),
            reporter_id=user_id,
            opponent_id=opponent_id,
            issue_type="other",
            details=f"Problème signalé depuis le match vedette #{self.featured_id}.",
            requested_until=None,
        )
        settings = await self.service.settings(str(interaction.guild.id))
        judge_channel_id = settings.get("judge_channel_id")
        if judge_channel_id:
            channel = interaction.guild.get_channel(int(judge_channel_id))
            if isinstance(channel, discord.TextChannel):
                await channel.send(
                    f"⚠️ **Problème sur un match vedette** — signalement `#{issue_id}`\n"
                    f"Joueur : <@{user_id}> • Match : `{self.featured['source_kind']}:{self.featured['match_id']}`"
                )
        await interaction.response.send_message(
            f"✅ Le problème a été transmis au staff (`#{issue_id}`).",
            ephemeral=True,
        )


class TournamentExtensionsCog(commands.Cog):
    tourney = app_commands.Group(
        name="tourney_plus",
        description="Outils avancés de tournoi Hamtaro",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = TournamentExtensionsService()
        self.swiss = SwissPairingService()

    async def cog_load(self) -> None:
        await init_expansion_schema()
        for featured in await self.service.open_featured_matches():
            try:
                self.bot.add_view(
                    FeaturedMatchView(bot=self.bot, service=self.service, featured=featured),
                    message_id=int(featured["message_id"]),
                )
            except (TypeError, ValueError):
                continue

    @tourney.command(name="info", description="Afficher la fiche officielle d'un tournoi")
    async def info(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
        visible: bool = False,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=not visible)
        try:
            data = await self.service.tournament_info(str(interaction.guild.id), code)
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return
        tournament = data["tournament"]
        total_matches = data["bracket_total"] + data["swiss_total"]
        completed = data["bracket_completed"] + data["swiss_completed"]
        embed = discord.Embed(
            title=f"🏟️ {tournament['name']}",
            description=f"Code : `{tournament['code']}` • ID : `#{tournament['id']}`",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Format", value=tournament["format"], inline=True)
        embed.add_field(name="Statut", value=str(tournament["status"]).replace("_", " ").title(), inline=True)
        embed.add_field(name="Ronde", value=f"{tournament['current_round']}/{tournament['total_rounds']}", inline=True)
        embed.add_field(
            name="Participants",
            value=f"**{data['registrations']}/{tournament['max_players']}**\nListe d'attente : **{data['waitlist']}**",
            inline=True,
        )
        embed.add_field(
            name="Progression",
            value=f"**{completed}/{total_matches}** match(s) terminé(s)" if total_matches else "Pas encore de match.",
            inline=True,
        )
        embed.add_field(
            name="Champion",
            value=tournament.get("winner_name") or "Non déterminé",
            inline=True,
        )
        if data["featured"]:
            feature = data["featured"]
            embed.add_field(
                name="📺 Match vedette",
                value=f"{feature.get('title') or 'Match à suivre'} • `{feature['source_kind']}:{feature['match_id']}`",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=not visible)

    @tourney.command(name="recap", description="Générer un récapitulatif statistique de tournoi")
    async def recap(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
        visible: bool = True,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=not visible)
        try:
            data = await self.service.tournament_recap(str(interaction.guild.id), code)
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return
        tournament = data["tournament"]
        embed = discord.Embed(
            title=f"📊 Récapitulatif — {tournament['name']}",
            description=f"Champion : **{data['champion']}** • {data['registrations']} participant(s)",
            color=discord.Color.gold(),
        )
        if data["decks"]:
            embed.add_field(
                name="🎴 Decks représentés",
                value="\n".join(f"**{row['deck']}** : {row['players']}" for row in data["decks"][:8]),
                inline=True,
            )
        if data["common_scores"]:
            embed.add_field(
                name="⚔️ Scores fréquents",
                value="\n".join(f"**{score}** : {count}" for score, count in data["common_scores"]),
                inline=True,
            )
        if data["final_ranking"]:
            embed.add_field(
                name="🏆 Classement final",
                value="\n".join(f"`#{row['final_rank']}` **{row['username']}**" for row in data["final_ranking"]),
                inline=False,
            )
        if data["most_active"]:
            embed.add_field(
                name="🔥 Joueurs les plus actifs",
                value=" • ".join(f"{row['username']} ({row['matches']})" for row in data["most_active"]),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=not visible)

    @tourney.command(name="template_create", description="Créer un modèle de tournoi réutilisable")
    @staff_only()
    async def template_create(
        self,
        interaction: discord.Interaction,
        nom_modele: str,
        nom_tournoi: str,
        format: str,
        type_tournoi: str,
        joueurs_max: app_commands.Range[int, 4, 128],
        rondes: app_commands.Range[int, 1, 20] | None = None,
        best_of: str = "BO3",
        regles: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            template_id = await self.service.create_template(
                guild_id=str(interaction.guild.id),
                name=nom_modele,
                tournament_name=nom_tournoi,
                format_name=format,
                tournament_type=type_tournoi,
                max_players=int(joueurs_max),
                total_rounds=int(rondes) if rondes else None,
                best_of=best_of,
                rules=regles,
                actor_id=str(interaction.user.id),
            )
        except Exception as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ Modèle créé (`#{template_id}`).", ephemeral=True)

    @tourney.command(name="template_list", description="Afficher les modèles de tournoi")
    @staff_only()
    async def template_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        rows = await self.service.templates(str(interaction.guild.id))
        embed = discord.Embed(title="🧩 Modèles de tournoi", color=discord.Color.blurple())
        embed.description = "\n".join(
            f"`#{row['id']}` **{row['name']}** — {row['format']} • {row['tournament_type']} • {row['max_players']} joueurs"
            for row in rows
        ) or "Aucun modèle enregistré."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tourney.command(name="template_use", description="Créer un tournoi à partir d'un modèle")
    @staff_only()
    async def template_use(
        self,
        interaction: discord.Interaction,
        modele_id: int,
        code: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            result = await self.service.create_tournament_from_template(
                guild_id=str(interaction.guild.id),
                template_id=modele_id,
                code=code,
                actor_id=str(interaction.user.id),
            )
        except Exception as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ Tournoi **{result['tournament_name']}** créé avec le code `{result['code']}` (`#{result['tournament_id']}`).",
            ephemeral=True,
        )

    @tourney.command(name="waitlist_join", description="Rejoindre la liste d'attente d'un tournoi")
    async def waitlist_join(
        self,
        interaction: discord.Interaction,
        code: str,
        deck: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        tournament = await self.service.tournament_by_code(str(interaction.guild.id), code)
        if tournament is None:
            await interaction.response.send_message("❌ Tournoi introuvable.", ephemeral=True)
            return
        try:
            position = await self.service.join_waitlist(
                guild_id=str(interaction.guild.id),
                tournament_id=int(tournament["id"]),
                discord_id=str(interaction.user.id),
                username=interaction.user.display_name,
                deck_name=deck,
            )
        except Exception as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ Tu es en position **#{position}** sur la liste d'attente de **{tournament['name']}**.",
            ephemeral=True,
        )

    @tourney.command(name="waitlist_leave", description="Quitter une liste d'attente")
    async def waitlist_leave(self, interaction: discord.Interaction, code: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        tournament = await self.service.tournament_by_code(str(interaction.guild.id), code)
        if tournament is None:
            await interaction.response.send_message("❌ Tournoi introuvable.", ephemeral=True)
            return
        try:
            await self.service.leave_waitlist(int(tournament["id"]), str(interaction.user.id))
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message("✅ Tu as quitté la liste d'attente.", ephemeral=True)

    @tourney.command(name="waitlist_promote", description="Promouvoir le premier joueur en attente")
    @staff_only()
    async def waitlist_promote(self, interaction: discord.Interaction, code: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        tournament = await self.service.tournament_by_code(str(interaction.guild.id), code)
        if tournament is None:
            await interaction.response.send_message("❌ Tournoi introuvable.", ephemeral=True)
            return
        try:
            candidate = await self.service.promote_waitlist(
                guild_id=str(interaction.guild.id),
                tournament_id=int(tournament["id"]),
                actor_id=str(interaction.user.id),
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ **{candidate['username']}** a été inscrit depuis la liste d'attente.",
            ephemeral=True,
        )

    @tourney.command(name="judge_call", description="Demander l'intervention d'un arbitre")
    async def judge_call(
        self,
        interaction: discord.Interaction,
        motif: str,
        details: str | None = None,
        adversaire: discord.Member | None = None,
        code: str | None = None,
    ) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        tournament = await self.service.tournament_by_code(str(interaction.guild.id), code)
        call_id = await self.service.create_judge_call(
            guild_id=str(interaction.guild.id),
            tournament_id=int(tournament["id"]) if tournament else None,
            channel_id=str(interaction.channel.id),
            thread_id=str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None,
            reporter_id=str(interaction.user.id),
            opponent_id=str(adversaire.id) if adversaire else None,
            reason=motif,
            details=details,
        )
        settings = await self.service.settings(str(interaction.guild.id))
        judge_channel = interaction.guild.get_channel(int(settings["judge_channel_id"])) if settings.get("judge_channel_id") else None
        if isinstance(judge_channel, discord.TextChannel):
            embed = discord.Embed(
                title=f"⚖️ Appel d'arbitre #{call_id}",
                description=f"Motif : **{motif}**\n{details or 'Aucun détail.'}",
                color=discord.Color.orange(),
            )
            embed.add_field(name="Joueur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Salon", value=interaction.channel.mention, inline=True)
            if adversaire:
                embed.add_field(name="Adversaire", value=adversaire.mention, inline=True)
            await judge_channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Appel d'arbitre créé (`#{call_id}`). Le staff a été prévenu.", ephemeral=True
        )

    @tourney.command(name="judge_list", description="Afficher les appels d'arbitre ouverts")
    @staff_only()
    async def judge_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        rows = await self.service.open_judge_calls(str(interaction.guild.id))
        embed = discord.Embed(title="⚖️ Appels d'arbitre ouverts", color=discord.Color.orange())
        embed.description = "\n".join(
            f"`#{row['id']}` **{row['reason']}** • <@{row['reporter_id']}> • {row['status']}"
            for row in rows
        ) or "Aucun appel ouvert."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tourney.command(name="judge_resolve", description="Résoudre un appel d'arbitre")
    @staff_only()
    async def judge_resolve(
        self,
        interaction: discord.Interaction,
        appel_id: int,
        resolution: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            await self.service.resolve_judge_call(
                str(interaction.guild.id), appel_id, str(interaction.user.id), resolution
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message("✅ Appel résolu.", ephemeral=True)

    @tourney.command(name="match_issue", description="Signaler une absence, un délai ou un problème de match")
    async def match_issue(
        self,
        interaction: discord.Interaction,
        type_probleme: str,
        adversaire: discord.Member | None = None,
        details: str | None = None,
        code: str | None = None,
        match_id: int | None = None,
        type_match: str | None = None,
        delai_jusqua: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        normalized = ISSUE_TYPES.get(type_probleme.casefold(), type_probleme.casefold())
        tournament = await self.service.tournament_by_code(str(interaction.guild.id), code)
        try:
            issue_id = await self.service.create_match_issue(
                guild_id=str(interaction.guild.id),
                tournament_id=int(tournament["id"]) if tournament else None,
                source_kind=type_match,
                match_id=match_id,
                reporter_id=str(interaction.user.id),
                opponent_id=str(adversaire.id) if adversaire else None,
                issue_type=normalized,
                details=details,
                requested_until=delai_jusqua,
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ Signalement enregistré (`#{issue_id}`). Le staff pourra vérifier l'historique de contact.",
            ephemeral=True,
        )

    @tourney.command(name="feature_match", description="Annoncer un match vedette, avec ou sans diffusion externe")
    @staff_only()
    async def feature_match(
        self,
        interaction: discord.Interaction,
        type_match: str,
        match_id: int,
        salon: discord.TextChannel,
        code: str | None = None,
        salon_vocal: discord.VoiceChannel | None = None,
        lien_stream: str | None = None,
        commentateurs: str | None = None,
        titre: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            match = await self.service.resolve_featured_match(
                guild_id=str(interaction.guild.id),
                source_kind=type_match,
                match_id=match_id,
            )
            settings = await self.service.settings(str(interaction.guild.id))
            configured_voice_id = settings.get("featured_voice_channel_id")
            selected_voice = salon_vocal
            if selected_voice is None and configured_voice_id:
                candidate = interaction.guild.get_channel(int(configured_voice_id))
                if isinstance(candidate, discord.VoiceChannel):
                    selected_voice = candidate
            tournament = await self.service.tournament_by_code(str(interaction.guild.id), code)
            tournament_id = (
                int(tournament["id"])
                if tournament
                else int(match["tournament_id"]) if match.get("tournament_id") is not None else None
            )
            featured_id = await self.service.feature_match(
                guild_id=str(interaction.guild.id),
                tournament_id=tournament_id,
                source_kind=str(match["source_kind"]),
                match_id=match_id,
                channel_id=str(salon.id),
                voice_channel_id=str(selected_voice.id) if selected_voice else None,
                player1_id=str(match["player1_id"]),
                player2_id=str(match["player2_id"]),
                stream_url=lien_stream,
                commentators=commentateurs,
                title=titre,
                actor_id=str(interaction.user.id),
            )
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📺 {titre or 'Match vedette'}",
            description=(
                f"<@{match['player1_id']}> contre <@{match['player2_id']}>\n"
                f"Match : `{match['source_kind']}:{match_id}`"
            ),
            color=discord.Color.red(),
        )
        embed.add_field(name="Format", value=str(match.get("format") or "Non précisé"), inline=True)
        if match.get("round") is not None:
            embed.add_field(name="Ronde", value=str(match["round"]), inline=True)
        tournament_name = (tournament or {}).get("name") or match.get("tournament_name")
        tournament_code = (tournament or {}).get("code") or match.get("tournament_code")
        if tournament_name:
            value = str(tournament_name)
            if tournament_code:
                value += f" (`{tournament_code}`)"
            embed.add_field(name="Tournoi", value=value, inline=False)
        if selected_voice:
            embed.add_field(
                name="🔴 Salon streaming Discord",
                value=(
                    f"Les deux joueurs doivent rejoindre {selected_voice.mention} et **partager leur écran**. "
                    "Le match peut être observé sur Discord sans être diffusé sur Twitch ou YouTube."
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="Salon vocal",
                value="Aucun salon vocal configuré. Le staff peut relancer la commande avec `salon_vocal`.",
                inline=False,
            )
        if lien_stream:
            embed.add_field(name="Diffusion externe", value=f"[Regarder la diffusion]({lien_stream})", inline=False)
        else:
            embed.add_field(name="Diffusion externe", value="Aucune : match visible uniquement sur Discord.", inline=False)
        if commentateurs:
            embed.add_field(name="Commentateurs", value=commentateurs, inline=False)
        embed.set_footer(text=f"Match vedette #{featured_id} • Utilisez les boutons pour confirmer votre statut.")

        featured = {
            "id": featured_id,
            "guild_id": str(interaction.guild.id),
            "tournament_id": tournament_id,
            "source_kind": str(match["source_kind"]),
            "match_id": match_id,
            "channel_id": str(salon.id),
            "voice_channel_id": str(selected_voice.id) if selected_voice else None,
            "player1_id": str(match["player1_id"]),
            "player2_id": str(match["player2_id"]),
        }
        view = FeaturedMatchView(bot=self.bot, service=self.service, featured=featured)
        message = await salon.send(
            content=f"<@{match['player1_id']}> <@{match['player2_id']}>",
            embed=embed,
            view=view,
        )
        await self.service.set_featured_message(featured_id, str(message.id))

        dm_text = (
            f"📺 Ton match `{match['source_kind']}:{match_id}` a été choisi comme **match vedette**.\n"
            + (
                f"Rejoins {selected_voice.mention} sur **{interaction.guild.name}**, puis partage ton écran.\n"
                if selected_voice
                else "Aucun salon vocal n'a encore été sélectionné.\n"
            )
            + f"Annonce : {message.jump_url}"
        )
        for player_id in (str(match["player1_id"]), str(match["player2_id"])):
            try:
                user = self.bot.get_user(int(player_id)) or await self.bot.fetch_user(int(player_id))
                await user.send(dm_text)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

        await interaction.followup.send(
            f"✅ Match vedette annoncé (`#{featured_id}`) : {message.jump_url}",
            ephemeral=True,
        )

    @tourney.command(name="feature_status", description="Vérifier la présence et le partage d'écran d'un match vedette")
    @staff_only()
    async def feature_status(
        self,
        interaction: discord.Interaction,
        vedette_id: int,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            featured = await self.service.featured_match_by_id(str(interaction.guild.id), vedette_id)
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        voice_id = str(featured.get("voice_channel_id") or "")
        lines: list[str] = []
        for player_id in (str(featured.get("player1_id") or ""), str(featured.get("player2_id") or "")):
            if not player_id:
                continue
            member = interaction.guild.get_member(int(player_id))
            voice_state = member.voice if member else None
            in_voice = bool(voice_state and voice_state.channel and str(voice_state.channel.id) == voice_id)
            streaming = bool(in_voice and voice_state and voice_state.self_stream)
            await self.service.update_featured_checkin(
                featured_id=vedette_id,
                discord_id=player_id,
                in_voice=in_voice,
                streaming=streaming,
            )
            checkins = await self.service.featured_checkins(vedette_id)
            saved = next((row for row in checkins if str(row["discord_id"]) == player_id), {})
            lines.append(
                f"<@{player_id}> — prêt : {'✅' if saved.get('ready') else '❌'} • "
                f"vocal : {'✅' if in_voice else '❌'} • écran : {'✅' if streaming else '❌'}"
            )
        embed = discord.Embed(
            title=f"📺 État du match vedette #{vedette_id}",
            description="\n".join(lines) or "Aucun joueur enregistré.",
            color=discord.Color.blurple(),
        )
        if voice_id:
            embed.add_field(name="Salon attendu", value=f"<#{voice_id}>", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tourney.command(name="schedule_create", description="Programmer annonces et rappels d'un tournoi")
    @staff_only()
    async def schedule_create(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        code: str | None = None,
        modele_id: int | None = None,
        annonce_iso: str | None = None,
        rappel_iso: str | None = None,
        lancement_iso: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        tournament = await self.service.tournament_by_code(str(interaction.guild.id), code) if code else None
        try:
            schedule_id = await self.service.schedule_tournament(
                guild_id=str(interaction.guild.id),
                tournament_id=int(tournament["id"]) if tournament else None,
                template_id=modele_id,
                channel_id=str(salon.id),
                announce_at=annonce_iso,
                reminder_at=rappel_iso,
                start_prompt_at=lancement_iso,
                actor_id=str(interaction.user.id),
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ Programmation créée (`#{schedule_id}`).", ephemeral=True)

    @tourney.command(name="schedule_list", description="Afficher les programmations actives")
    @staff_only()
    async def schedule_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        rows = await self.service.schedules(str(interaction.guild.id))
        embed = discord.Embed(title="⏰ Programmations Hamtaro", color=discord.Color.blurple())
        embed.description = "\n\n".join(
            f"`#{row['id']}` **{row.get('tournament_name') or row.get('template_name') or 'Événement'}**\n"
            f"Annonce : {row['announce_at'] or '—'} • Rappel : {row['reminder_at'] or '—'} • Lancement : {row['start_prompt_at'] or '—'}"
            for row in rows
        ) or "Aucune programmation active."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tourney.command(name="schedule_cancel", description="Annuler une programmation")
    @staff_only()
    async def schedule_cancel(self, interaction: discord.Interaction, programmation_id: int) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            await self.service.cancel_schedule(
                str(interaction.guild.id), programmation_id, str(interaction.user.id)
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message("✅ Programmation annulée.", ephemeral=True)

    @tourney.command(name="swiss_pair", description="Générer une ronde suisse avancée sans rematches si possible")
    @staff_only()
    async def swiss_pair(self, interaction: discord.Interaction, code: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        tournament = await self.service.tournament_by_code(str(interaction.guild.id), code)
        if tournament is None:
            await interaction.response.send_message("❌ Tournoi introuvable.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.swiss.generate_next_round(int(tournament["id"]))
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"🔄 Ronde suisse {result['round_number']}",
            description=f"Rematches forcés : **{result['forced_rematches']}**",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Tables",
            value="\n".join(
                f"**Table {row['table_number']}** — {row['player1_name']} vs {row['player2_name']}"
                + (" ⚠️ rematch" if row.get("rematch") else "")
                for row in result["matches"]
            ),
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tourney.command(name="swiss_tiebreakers", description="Afficher Buchholz et taux de victoire des adversaires")
    async def swiss_tiebreakers(
        self,
        interaction: discord.Interaction,
        code: str,
        visible: bool = False,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        tournament = await self.service.tournament_by_code(str(interaction.guild.id), code)
        if tournament is None:
            await interaction.response.send_message("❌ Tournoi introuvable.", ephemeral=True)
            return
        rows = await self.swiss.standings(int(tournament["id"]))
        embed = discord.Embed(
            title=f"📊 Départages suisses — {tournament['name']}",
            color=discord.Color.blurple(),
        )
        embed.description = "\n".join(
            f"`#{row['rank']}` **{row['username']}** — {row['points']} pts • "
            f"Buchholz **{row['buchholz']}** • OMW **{row['opponent_win_rate']:.1f}%**"
            for row in rows[:25]
        ) or "Aucun classement disponible."
        embed.set_footer(text="Ordre : points, Buchholz, taux de victoire des adversaires, victoires.")
        await interaction.response.send_message(embed=embed, ephemeral=not visible)

    @tourney.command(name="staff_panel", description="Afficher le centre de contrôle staff")
    @staff_only()
    async def staff_panel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        calls = await self.service.open_judge_calls(str(interaction.guild.id))
        schedules = await self.service.schedules(str(interaction.guild.id))
        history = await self.service.action_history(str(interaction.guild.id), limit=5)
        embed = discord.Embed(
            title="🛡️ Centre de contrôle staff Hamtaro",
            description="Les fonctions sensibles restent séparées et journalisées.",
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="⚖️ Appels d'arbitre", value=str(len(calls)), inline=True)
        embed.add_field(name="⏰ Programmations", value=str(len(schedules)), inline=True)
        embed.add_field(name="↩️ Actions récentes", value=str(len(history)), inline=True)
        embed.add_field(
            name="Commandes essentielles",
            value=(
                "`/tourney_plus judge_list` • `/tourney_plus waitlist_promote`\n"
                "`/tourney_plus swiss_pair` • `/tourney_plus schedule_list`\n"
                "`/tourney_plus secure_history` • `/tourney_plus secure_revert`"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tourney.command(name="secure_history", description="Afficher l'historique des actions annulables")
    @staff_only()
    async def secure_history(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        rows = await self.service.action_history(str(interaction.guild.id), limit=20)
        embed = discord.Embed(title="↩️ Historique sécurisé", color=discord.Color.dark_gold())
        embed.description = "\n".join(
            f"`#{row['id']}` **{row['action_type']} {row['entity_type']}** • "
            f"{'annulable' if row['reversible'] and not row['reverted_at'] else 'verrouillée'}"
            for row in rows
        ) or "Aucune action enregistrée."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tourney.command(name="secure_revert", description="Annuler une action récente de l'extension")
    @staff_only()
    async def secure_revert(
        self,
        interaction: discord.Interaction,
        action_id: int,
        confirmation: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        if confirmation.strip().upper() != "CONFIRMER":
            await interaction.response.send_message(
                "❌ Écris exactement `CONFIRMER` pour effectuer l'annulation.", ephemeral=True
            )
            return
        try:
            message = await self.service.revert_action(
                str(interaction.guild.id), action_id, str(interaction.user.id)
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ {message}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentExtensionsCog(bot))
