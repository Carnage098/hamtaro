from __future__ import annotations
from utils.embeds import success_embed, error_embed, info_embed
import discord

from discord.ext import commands
from discord import app_commands


class RegistrationCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.db = bot.db

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
        guild_id = self._guild_id(interaction)

        tournament = await self.db.get_active_tournament(
            guild_id
        )

        return tournament

    def _display_name(
        self,
        user: discord.abc.User,
    ) -> str:
        return (
            user.display_name
            if hasattr(user, "display_name")
            else user.name
        )

    def _avatar_url(
        self,
        user: discord.abc.User,
    ) -> str | None:
        avatar = getattr(user, "display_avatar", None)

        if avatar is None:
            return None

        return avatar.url

    # ==========================================================
    # INSCRIPTION
    # ==========================================================

    @app_commands.command(
        name="register",
        description="S'inscrire au tournoi actif"
    )
    @app_commands.describe(
        deck="Deck que tu joues pour ce tournoi"
    )
    async def register(
        self,
        interaction: discord.Interaction,
        deck: str | None = None,
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        try:
            guild_id = self._guild_id(interaction)

            tournament = await self.db.get_active_tournament(
                guild_id
            )

            if tournament is None:
                await interaction.followup.send(
                    "❌ Aucun tournoi actif avec inscriptions ouvertes.",
                    ephemeral=True,
                )
                return

            user = interaction.user
            username = self._display_name(user)
            avatar_url = self._avatar_url(user)

            registration = await self.db.register_player(
                tournament_id=tournament.id,
                guild_id=guild_id,
                discord_id=str(user.id),
                username=username,
                deck=deck,
                display_name=username,
                avatar_url=avatar_url,
            )

            current = await self.db.count_registrations(
                tournament.id
            )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🐹 Inscription validée",
            description=(
                f"{interaction.user.mention}, tu es bien inscrit au tournoi.\n\n"
                "Aucun check-in n'est nécessaire : ton inscription confirme ta disponibilité."
            ),
            color=discord.Color.green(),
        )

        embed.add_field(
            name="🏆 Tournoi",
            value=f"**{tournament.name}**",
            inline=False,
        )

        embed.add_field(
            name="🎴 Deck",
            value=f"`{registration.deck or 'Non renseigné'}`",
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
    # DÉSINSCRIPTION
    # ==========================================================

    @app_commands.command(
        name="unregister",
        description="Se désinscrire du tournoi actif"
    )
    async def unregister(
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

            await self.db.unregister_player(
                tournament_id=tournament.id,
                discord_id=str(interaction.user.id),
            )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🐹 Désinscription validée",
            description=(
                f"{interaction.user.mention}, tu es désinscrit du tournoi "
                f"**{tournament.name}**."
            ),
            color=discord.Color.orange(),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # CHECK-IN DÉSACTIVÉ
    # ==========================================================

    @app_commands.command(
        name="checkin",
        description="Ancienne commande de check-in"
    )
    async def checkin(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.send_message(
            (
                "🐹 Le check-in n'est plus nécessaire.\n\n"
                "Si tu es inscrit au tournoi, tu es automatiquement considéré comme disponible."
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="uncheckin",
        description="Ancienne commande pour annuler le check-in"
    )
    async def uncheckin(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.send_message(
            (
                "🐹 Le système de check-in est désactivé.\n\n"
                "Tu n'as rien à annuler : seule l'inscription compte maintenant."
            ),
            ephemeral=True,
        )

    # ==========================================================
    # MODIFIER DECK
    # ==========================================================

    @app_commands.command(
        name="deck",
        description="Modifier le deck déclaré pour le tournoi actif"
    )
    @app_commands.describe(
        deck="Nom du deck"
    )
    async def deck(
        self,
        interaction: discord.Interaction,
        deck: str,
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

            registration = await self.db.get_registration_by_user(
                tournament_id=tournament.id,
                discord_id=str(interaction.user.id),
            )

            if registration is None:
                await interaction.followup.send(
                    "❌ Tu n'es pas inscrit à ce tournoi.",
                    ephemeral=True,
                )
                return

            await self.db.update_registration_deck(
                tournament_id=tournament.id,
                discord_id=str(interaction.user.id),
                deck=deck,
            )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🐹 Deck mis à jour",
            description=(
                f"{interaction.user.mention}, ton deck a bien été modifié."
            ),
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="🎴 Nouveau deck",
            value=f"`{deck}`",
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # LISTE DES INSCRITS
    # ==========================================================

    @app_commands.command(
        name="players",
        description="Voir les joueurs inscrits au tournoi actif"
    )
    async def players(
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

            registrations = await self.db.list_registrations(
                tournament.id
            )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        if not registrations:
            await interaction.followup.send(
                "❌ Aucun joueur inscrit pour le moment.",
                ephemeral=True,
            )
            return

        lines = []

        for index, registration in enumerate(
            registrations,
            start=1,
        ):
            deck = registration.deck or "Non renseigné"

            lines.append(
                f"{index}. ✅ **{registration.username}** — `{deck}`"
            )

        embed = discord.Embed(
            title=f"👥 Joueurs inscrits — {tournament.name}",
            description="\n".join(lines),
            color=discord.Color.green(),
        )

        embed.add_field(
            name="📌 Disponibilité",
            value="Tous les joueurs inscrits sont automatiquement considérés comme disponibles.",
            inline=False,
        )

        embed.set_footer(
            text=f"{len(registrations)}/{tournament.max_players} joueurs inscrits"
        )

        await interaction.followup.send(
            embed=embed,
        )


async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        RegistrationCog(bot)
    )
