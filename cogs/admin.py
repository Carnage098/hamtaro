from __future__ import annotations
from utils.permissions import staff_only
import discord

from discord.ext import commands
from discord import app_commands

from services.bracket_service import BracketService
from models.enums import TournamentStatus


class AdminCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot
        self.db = bot.db
        self.brackets = BracketService(self.db)

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

        guild_id = self._guild_id(interaction)

        return await self.db.get_active_tournament(
            guild_id
        )

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
    async def admin_health(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        ok = await self.db.health_check()

        if ok:

            await interaction.followup.send(
                "✅ Base de données connectée.",
                ephemeral=True,
            )

        else:

            await interaction.followup.send(
                "❌ Problème avec la base de données.",
                ephemeral=True,
            )

    # ==========================================================
    # RESET BRACKET
    # ==========================================================

    @app_commands.command(
        name="admin_reset_bracket",
        description="Supprimer le bracket du tournoi actif"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
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

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )

                return

            await self.brackets.reset_bracket(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            "✅ Bracket supprimé. Le tournoi est revenu en phase d'inscription.",
            ephemeral=True,
        )

    # ==========================================================
    # REGENERATE BRACKET
    # ==========================================================

    @app_commands.command(
        name="admin_regenerate_bracket",
        description="Régénérer complètement le bracket du tournoi actif"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
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

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )

                return

            await self.brackets.regenerate_bracket(
                tournament.id,
                shuffle=True,
            )

            text = await self.brackets.format_current_round(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ **Bracket régénéré !**\n\n{text}",
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

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )

                return

            current_round = await self.brackets.sync_current_round(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ Round synchronisé : `{current_round}`",
            ephemeral=True,
        )
        
    # ==========================================================
    # AJOUTER JOUEUR
    # ==========================================================

    @app_commands.command(
        name="admin_add_player",
        description="Ajouter manuellement un joueur au tournoi actif"
    )
    @app_commands.describe(
        joueur="Joueur à ajouter au tournoi",
        deck="Deck du joueur, optionnel"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
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

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
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

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ {joueur.mention} a été ajouté au tournoi actif.",
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

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )

                return

            await self.db.drop_player(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ {joueur.mention} a été marqué comme drop.",
            ephemeral=True,
        )

    # ==========================================================
    # DISQUALIFICATION
    # ==========================================================

    @app_commands.command(
        name="admin_dq",
        description="Disqualifier un joueur du tournoi actif"
    )
    @app_commands.describe(
        joueur="Joueur à disqualifier"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
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

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )

                return

            await self.db.disqualify_player(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ {joueur.mention} a été disqualifié.",
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

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )

                return

            await self.db.restore_player_registration(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ {joueur.mention} a été restauré dans le tournoi.",
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

            await interaction.followup.send(
                "❌ Le seed doit être supérieur ou égal à 1.",
                ephemeral=True,
            )

            return

        try:

            tournament = await self._get_active_tournament(
                interaction
            )

            if tournament is None:

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )

                return

            await self.db.set_registration_seed(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
                seed=seed,
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ Seed de {joueur.mention} défini à `{seed}`.",
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

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )

                return

            await self.db.set_registration_seed(
                tournament_id=tournament.id,
                discord_id=str(joueur.id),
                seed=None,
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ Seed de {joueur.mention} supprimé.",
            ephemeral=True,
        )

    # ==========================================================
    # FORCE STATUS
    # ==========================================================

    @app_commands.command(
        name="admin_status",
        description="Changer le statut du tournoi actif"
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
                name="check_in",
                value="check_in",
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

                await interaction.followup.send(
                    "❌ Aucun tournoi actif.",
                    ephemeral=True,
                )

                return

            await self.db.update_tournament_status(
                tournament_id=tournament.id,
                status=TournamentStatus(status.value),
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            f"✅ Statut du tournoi modifié : `{status.value}`",
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        AdminCog(bot)
    )
