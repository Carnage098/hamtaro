from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands

from services.bracket_service import BracketService
from services.admin_log_service import AdminLogService

from models.enums import TournamentStatus

from utils.embeds import success_embed, error_embed, info_embed
from utils.permissions import staff_only
from utils.tournament_resolver import resolve_tournament


class AdminCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.db = bot.db
        self.brackets = BracketService(self.db)
        self.logs = AdminLogService()

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

    async def _get_active_tournament(
        self,
        interaction: discord.Interaction,
    ):
        return await resolve_tournament(
            interaction,
            self.db,
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

    async def _log_action(
        self,
        interaction: discord.Interaction,
        action: str,
        target: discord.Member | None = None,
        tournament=None,
        details: str | None = None,
    ):
        try:
            guild_id = self._guild_id(interaction)

            await self.logs.record(
                guild_id=guild_id,
                actor_id=str(interaction.user.id),
                actor_name=interaction.user.display_name,
                action=action,
                target_id=str(target.id) if target else None,
                target_name=target.display_name if target else None,
                tournament_id=getattr(tournament, "id", None),
                tournament_name=getattr(tournament, "name", None),
                details=details,
            )

        except Exception as error:
            print(
                f"⚠️ Impossible d'enregistrer le log staff : {error}"
            )

    def _status_value(
        self,
        tournament,
    ) -> str:
        status = getattr(
            tournament,
            "status",
            "",
        )

        return getattr(
            status,
            "value",
            str(status),
        )

    def _can_edit_players_before_start(
        self,
        tournament,
    ) -> bool:
        status = self._status_value(
            tournament
        )

        return status in {
            "registration",
            "check_in",
        }

    # ==========================================================
    # HEALTH CHECK
    # ==========================================================

    @app_commands.command(
        name="admin_health",
        description="Vérifier si la base de données répond"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_health(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        ok = await self.db.health_check()

        if ok:
            embed = success_embed(
                title="Base de données connectée",
                description="La base de données répond correctement.",
            )

        else:
            embed = error_embed(
                title="Problème base de données",
                description=(
                    "Hamtaro n'arrive pas à joindre correctement "
                    "la base de données."
                ),
            )

        await self._log_action(
            interaction=interaction,
            action="admin_health",
            details="OK" if ok else "Erreur base de données",
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # RESET BRACKET
    # ==========================================================

    @app_commands.command(
        name="admin_reset_bracket",
        description="Supprimer le bracket du tournoi sélectionné"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_reset_bracket(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            await self.brackets.reset_bracket(
                tournament.id
            )

            await self._log_action(
                interaction=interaction,
                action="admin_reset_bracket",
                tournament=tournament,
                details="Bracket supprimé",
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Reset impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Bracket supprimé",
            description=(
                "Le bracket a été supprimé.\n\n"
                "Le tournoi est revenu en phase d'inscription."
            ),
        )

        embed.add_field(
            name="🏆 Tournoi",
            value=f"**{tournament.name}**",
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # REGENERATE BRACKET
    # ==========================================================

    @app_commands.command(
        name="admin_regenerate_bracket",
        description="Régénérer complètement le bracket du tournoi sélectionné"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_regenerate_bracket(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer(
            ephemeral=False
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            await self.brackets.regenerate_bracket(
                tournament.id,
                shuffle=True,
            )

            text = await self.brackets.format_current_round(
                tournament.id
            )

            await self._log_action(
                interaction=interaction,
                action="admin_regenerate_bracket",
                tournament=tournament,
                details="Bracket régénéré avec shuffle=True",
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Régénération impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Bracket régénéré",
            description=(
                f"Le bracket du tournoi **{tournament.name}** a été régénéré."
            ),
        )

        embed.add_field(
            name="⚔️ Round actuel",
            value=text[:1024] if text else "Aucun match à afficher.",
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=False,
        )

    # ==========================================================
    # SYNC ROUND
    # ==========================================================

    @app_commands.command(
        name="admin_sync_round",
        description="Recalculer le round actuel du tournoi"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_sync_round(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            current_round = await self.brackets.sync_current_round(
                tournament.id
            )

            await self._log_action(
                interaction=interaction,
                action="admin_sync_round",
                tournament=tournament,
                details=f"Round actuel : {current_round}",
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Synchronisation impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Round synchronisé",
            description=(
                f"Le round actuel du tournoi **{tournament.name}** a été recalculé."
            ),
        )

        embed.add_field(
            name="🔄 Round actuel",
            value=f"`{current_round}`",
            inline=True,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # AJOUTER JOUEUR
    # ==========================================================

    @app_commands.command(
        name="admin_add_player",
        description="Ajouter manuellement un joueur au tournoi sélectionné"
    )
    @app_commands.describe(
        joueur="Joueur à ajouter au tournoi",
        deck="Deck du joueur, optionnel"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_add_player(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        deck: str | None = None,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            guild_id = self._guild_id(interaction)

            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            if not self._can_edit_players_before_start(tournament):
                await self._send_error(
                    interaction=interaction,
                    title="Ajout impossible",
                    description=(
                        "Tu ne peux ajouter un joueur manuellement que pendant "
                        "la phase d'inscription.\n\n"
                        "Si le tournoi a déjà commencé, il vaut mieux éviter "
                        "de modifier les inscrits pour ne pas casser le bracket."
                    ),
                )
                return

            await self.db.register_player(
                tournament_id=tournament.id,
                guild_id=guild_id,
                discord_id=str(joueur.id),
                username=joueur.name,
                deck=deck,
                display_name=joueur.display_name,
                avatar_url=joueur.display_avatar.url,
            )

            current = await self.db.count_registrations(
                tournament.id
            )

            await self._log_action(
                interaction=interaction,
                action="admin_add_player",
                target=joueur,
                tournament=tournament,
                details=f"Deck : {deck or 'Non renseigné'}",
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Ajout impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Joueur ajouté",
            description=(
                f"{joueur.mention} a été ajouté au tournoi sélectionné."
            ),
        )

        embed.add_field(
            name="🏆 Tournoi",
            value=f"**{tournament.name}**",
            inline=False,
        )

        embed.add_field(
            name="🎴 Deck",
            value=f"`{deck or 'Non renseigné'}`",
            inline=True,
        )

        embed.add_field(
            name="📊 Inscrits",
            value=f"**{current}/{tournament.max_players}**",
            inline=True,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # RETIRER JOUEUR AVANT LE DÉBUT
    # ==========================================================

    @app_commands.command(
        name="remove_player",
        description="Retirer un joueur du tournoi sélectionné avant son lancement"
    )
    @app_commands.describe(
        joueur="Joueur à retirer du tournoi",
        raison="Raison du retrait, optionnel"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def remove_player(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        raison: str | None = None,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            if not self._can_edit_players_before_start(tournament):
                await self._send_error(
                    interaction=interaction,
                    title="Retrait impossible",
                    description=(
                        "Tu ne peux retirer complètement un joueur que pendant "
                        "la phase d'inscription.\n\n"
                        "Si le tournoi a déjà commencé, utilise plutôt `/admin_drop`."
                    ),
                )
                return

            registration = await self.db.get_registration_by_user(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
            )

            if registration is None:
                await self._send_error(
                    interaction=interaction,
                    title="Joueur non inscrit",
                    description=(
                        f"{joueur.mention} n'est pas inscrit au tournoi "
                        f"**{tournament.name}**."
                    ),
                )
                return

            await self.db.unregister_player(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
            )

            current = await self.db.count_registrations(
                tournament.id
            )

            await self._log_action(
                interaction=interaction,
                action="remove_player",
                target=joueur,
                tournament=tournament,
                details=raison or "Aucune raison indiquée",
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Retrait impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Joueur retiré",
            description=(
                f"{joueur.mention} a été retiré du tournoi **{tournament.name}**."
            ),
        )

        embed.add_field(
            name="📊 Inscrits restants",
            value=f"**{current}/{tournament.max_players}**",
            inline=True,
        )

        if raison:
            embed.add_field(
                name="📝 Raison",
                value=raison,
                inline=False,
            )

        embed.set_footer(
            text="Action staff Hamtaro"
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # DROP JOUEUR
    # ==========================================================

    @app_commands.command(
        name="admin_drop",
        description="Marquer un joueur comme ayant abandonné le tournoi"
    )
    @app_commands.describe(
        joueur="Joueur à drop"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_drop(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            await self.db.drop_player(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
            )

            await self._log_action(
                interaction=interaction,
                action="admin_drop",
                target=joueur,
                tournament=tournament,
                details="Joueur marqué comme drop",
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Drop impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Joueur drop",
            description=(
                f"{joueur.mention} a été marqué comme drop pour le tournoi "
                f"**{tournament.name}**."
            ),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # DISQUALIFICATION
    # ==========================================================

    @app_commands.command(
        name="admin_dq",
        description="Disqualifier un joueur du tournoi sélectionné"
    )
    @app_commands.describe(
        joueur="Joueur à disqualifier"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_dq(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            await self.db.disqualify_player(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
            )

            await self._log_action(
                interaction=interaction,
                action="admin_dq",
                target=joueur,
                tournament=tournament,
                details="Joueur disqualifié",
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Disqualification impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Joueur disqualifié",
            description=(
                f"{joueur.mention} a été disqualifié du tournoi "
                f"**{tournament.name}**."
            ),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # RESTORE JOUEUR
    # ==========================================================

    @app_commands.command(
        name="admin_restore",
        description="Annuler le drop ou la disqualification d'un joueur"
    )
    @app_commands.describe(
        joueur="Joueur à restaurer"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_restore(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            await self.db.restore_player_registration(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
            )

            await self._log_action(
                interaction=interaction,
                action="admin_restore",
                target=joueur,
                tournament=tournament,
                details="Drop/DQ annulé",
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Restauration impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Joueur restauré",
            description=(
                f"{joueur.mention} a été restauré dans le tournoi "
                f"**{tournament.name}**."
            ),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # SEED JOUEUR
    # ==========================================================

    @app_commands.command(
        name="admin_seed",
        description="Définir le seed d'un joueur"
    )
    @app_commands.describe(
        joueur="Joueur concerné",
        seed="Seed du joueur"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_seed(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        seed: int,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        if seed < 1:
            await self._send_error(
                interaction=interaction,
                title="Seed invalide",
                description="Le seed doit être supérieur ou égal à 1.",
            )
            return

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            await self.db.set_registration_seed(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
                seed=seed,
            )

            await self._log_action(
                interaction=interaction,
                action="admin_seed",
                target=joueur,
                tournament=tournament,
                details=f"Seed défini : {seed}",
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Seed impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Seed défini",
            description=(
                f"Le seed de {joueur.mention} a été défini à `{seed}`."
            ),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # CLEAR SEED
    # ==========================================================

    @app_commands.command(
        name="admin_clear_seed",
        description="Supprimer le seed d'un joueur"
    )
    @app_commands.describe(
        joueur="Joueur concerné"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_clear_seed(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            await self.db.set_registration_seed(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
                seed=None,
            )

            await self._log_action(
                interaction=interaction,
                action="admin_clear_seed",
                target=joueur,
                tournament=tournament,
                details="Seed supprimé",
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Suppression impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Seed supprimé",
            description=(
                f"Le seed de {joueur.mention} a été supprimé."
            ),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # FORCE STATUS
    # ==========================================================

    @app_commands.command(
        name="admin_status",
        description="Changer le statut du tournoi sélectionné"
    )
    @app_commands.describe(
        status="Nouveau statut"
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(
                name="registration",
                value="registration",
            ),
            app_commands.Choice(
                name="running",
                value="running",
            ),
            app_commands.Choice(
                name="finished",
                value="finished",
            ),
            app_commands.Choice(
                name="cancelled",
                value="cancelled",
            ),
        ]
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def admin_status(
        self,
        interaction: discord.Interaction,
        status: app_commands.Choice[str],
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi sélectionné",
                    description="Il n'y a actuellement aucun tournoi sélectionné.",
                )
                return

            old_status = self._status_value(
                tournament
            )

            await self.db.update_tournament_status(
                tournament_id=tournament.id,
                status=TournamentStatus(status.value),
            )

            await self._log_action(
                interaction=interaction,
                action="admin_status",
                tournament=tournament,
                details=f"{old_status} -> {status.value}",
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Changement impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Statut modifié",
            description=(
                f"Le statut du tournoi **{tournament.name}** a été modifié."
            ),
        )

        embed.add_field(
            name="📌 Nouveau statut",
            value=f"`{status.value}`",
            inline=True,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
):
    service = AdminLogService()

    await service.init_table()

    await bot.add_cog(
        AdminCog(bot)
    )
