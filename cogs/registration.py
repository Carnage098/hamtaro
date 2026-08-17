from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import error_embed, info_embed, success_embed
from utils.tournament_resolver import (
    active_tournament_code_autocomplete,
    resolve_tournament,
)


class RegistrationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db

    # ==========================================================
    # OUTILS INTERNES
    # ==========================================================

    def _guild_id(self, interaction: discord.Interaction) -> str:
        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )
        return str(interaction.guild.id)

    async def _get_active_tournament(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ):
        return await resolve_tournament(
            interaction,
            self.db,
            code=code,
        )

    @staticmethod
    def _display_name(user: discord.abc.User) -> str:
        return (
            user.display_name
            if hasattr(user, "display_name")
            else user.name
        )

    @staticmethod
    def _avatar_url(user: discord.abc.User) -> str | None:
        avatar = getattr(user, "display_avatar", None)
        return avatar.url if avatar is not None else None

    @staticmethod
    async def _send_error(
        interaction: discord.Interaction,
        title: str,
        description: str,
        ephemeral: bool = True,
    ) -> None:
        embed = error_embed(
            title=title,
            description=description,
        )
        await interaction.followup.send(
            embed=embed,
            ephemeral=ephemeral,
        )

    # ==========================================================
    # INSCRIPTION
    # ==========================================================

    @app_commands.command(
        name="register",
        description="S'inscrire au tournoi sélectionné",
    )
    @app_commands.describe(
        deck="Deck que tu joues pour ce tournoi",
        code="Code facultatif du tournoi",
        team_id="ID de ton équipe 2v2 si tu en as plusieurs",
    )
    @app_commands.autocomplete(
        code=active_tournament_code_autocomplete,
    )
    async def register(
        self,
        interaction: discord.Interaction,
        deck: str | None = None,
        code: str | None = None,
        team_id: int | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            guild_id = self._guild_id(interaction)
            tournament = await self._get_active_tournament(
                interaction,
                code,
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi actif",
                    description=(
                        "Aucun tournoi actif avec inscriptions ouvertes."
                    ),
                )
                return

            # HAMTARO_2V2_V2:REGISTER
            duo_cog = self.bot.get_cog("Team2v2Cog")
            if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
                await duo_cog.register_from_native(interaction, tournament, team_id=team_id, deck=deck)
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
            await self._send_error(
                interaction=interaction,
                title="Inscription impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Inscription validée",
            description=(
                f"{interaction.user.mention}, tu es bien inscrit au tournoi.\n\n"
                "Ton inscription confirme directement ta disponibilité."
            ),
        )
        embed.add_field(
            name="🏆 Tournoi",
            value=f"**{tournament.name}** (`{tournament.code}`)",
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
        embed.set_footer(
            text="Hamtaro Tournament Manager"
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
        description="Se désinscrire du tournoi sélectionné",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi",
    )
    @app_commands.autocomplete(
        code=active_tournament_code_autocomplete,
    )
    async def unregister(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            tournament = await self._get_active_tournament(
                interaction,
                code,
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi actif",
                    description=(
                        "Il n'y a actuellement aucun tournoi actif."
                    ),
                )
                return

            # HAMTARO_2V2_V2:UNREGISTER
            duo_cog = self.bot.get_cog("Team2v2Cog")
            if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
                await duo_cog.unregister_from_native(interaction, tournament)
                return
            await self.db.unregister_player(
                tournament_id=tournament.id,
                discord_id=str(interaction.user.id),
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Désinscription impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Désinscription validée",
            description=(
                f"{interaction.user.mention}, tu es désinscrit du tournoi "
                f"**{tournament.name}**."
            ),
        )
        embed.set_footer(
            text="Hamtaro Tournament Manager"
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # MODIFIER LE DECK
    # ==========================================================

    @app_commands.command(
        name="deck",
        description="Modifier le deck déclaré pour le tournoi sélectionné",
    )
    @app_commands.describe(
        deck="Nom du deck",
        code="Code facultatif du tournoi",
    )
    @app_commands.autocomplete(
        code=active_tournament_code_autocomplete,
    )
    async def deck(
        self,
        interaction: discord.Interaction,
        deck: str,
        code: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            tournament = await self._get_active_tournament(
                interaction,
                code,
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi actif",
                    description=(
                        "Il n'y a actuellement aucun tournoi actif."
                    ),
                )
                return

            # HAMTARO_2V2_V2:DECK
            duo_cog = self.bot.get_cog("Team2v2Cog")
            if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
                await duo_cog.update_deck_from_native(interaction, tournament, deck)
                return
            registration = await self.db.get_registration_by_user(
                tournament_id=tournament.id,
                discord_id=str(interaction.user.id),
            )

            if registration is None:
                await self._send_error(
                    interaction=interaction,
                    title="Joueur non inscrit",
                    description="Tu n'es pas inscrit à ce tournoi.",
                )
                return

            await self.db.update_registration_deck(
                tournament_id=tournament.id,
                discord_id=str(interaction.user.id),
                deck=deck,
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Modification impossible",
                description=str(error),
            )
            return

        embed = success_embed(
            title="Deck mis à jour",
            description=(
                f"{interaction.user.mention}, ton deck a bien été modifié."
            ),
        )
        embed.add_field(
            name="🎴 Nouveau deck",
            value=f"`{deck}`",
            inline=False,
        )
        embed.set_footer(
            text="Hamtaro Tournament Manager"
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
        description="Voir les joueurs du tournoi sélectionné",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi",
    )
    @app_commands.autocomplete(
        code=active_tournament_code_autocomplete,
    )
    async def players(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=False)

        try:
            tournament = await self._get_active_tournament(
                interaction,
                code,
            )

            if tournament is None:
                await self._send_error(
                    interaction=interaction,
                    title="Aucun tournoi actif",
                    description=(
                        "Il n'y a actuellement aucun tournoi actif."
                    ),
                    ephemeral=True,
                )
                return

            # HAMTARO_2V2_V2:PLAYERS
            duo_cog = self.bot.get_cog("Team2v2Cog")
            if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
                await duo_cog.players_from_native(interaction, tournament)
                return
            registrations = await self.db.list_registrations(
                tournament.id
            )

        except ValueError as error:
            await self._send_error(
                interaction=interaction,
                title="Erreur",
                description=str(error),
                ephemeral=True,
            )
            return

        if not registrations:
            embed = info_embed(
                title="Aucun joueur inscrit",
                description=(
                    "Aucun joueur n'est inscrit pour le moment."
                ),
            )
            embed.set_footer(
                text="Hamtaro Tournament Manager"
            )

            await interaction.followup.send(
                embed=embed,
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

        embed = info_embed(
            title=f"Joueurs inscrits — {tournament.name}",
            description="\n".join(lines),
        )
        embed.add_field(
            name="📌 Disponibilité",
            value=(
                "Tous les joueurs inscrits sont automatiquement "
                "considérés comme disponibles."
            ),
            inline=False,
        )
        embed.set_footer(
            text=(
                f"{len(registrations)}/{tournament.max_players} "
                "joueurs inscrits"
            ),
        )

        await interaction.followup.send(
            embed=embed,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        RegistrationCog(bot)
    )
