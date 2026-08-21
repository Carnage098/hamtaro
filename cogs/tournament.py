from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.bracket_service import BracketService
from services.tournament_start_service import TournamentStartService
from utils.tournament_resolver import (
    active_tournament_code_autocomplete,
    tournament_code_autocomplete,
    resolve_tournament,
)


FORMATS = [
    "Format Actuel",
    "Master Duel",
    "Genesys",
    "GOAT",
    "Edison",
    "HAT",
    "Tengu Plant",
    "Dragon Ruler",
    "TeleDAD",
    "Rush Duel",
    "Speed Duel",

    "Araignée",
    "Halloween",
]


TOURNAMENT_CAPACITIES = [
    4,
    8,
    16,
    32,
    64,
    128,
]


class TournamentCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:
        self.bot = bot
        self.db = bot.db
        self.brackets = BracketService(
            self.db
        )
        self.start_previews = TournamentStartService(
            bot
        )

    def _guild_id(
        self,
        interaction: discord.Interaction,
    ) -> str:
        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(
            interaction.guild.id
        )

    async def _safe_defer(
        self,
        interaction: discord.Interaction,
        *,
        ephemeral: bool,
    ) -> bool:
        """
        Accuse immédiatement réception de la commande.

        Retourne False si Discord considère déjà l'interaction
        comme expirée ou reconnue. Dans ce cas, la commande doit
        s'arrêter avant de modifier la base de données.
        """

        if interaction.response.is_done():
            return True

        try:
            await interaction.response.defer(
                ephemeral=ephemeral,
                thinking=True,
            )
            return True

        except discord.InteractionResponded:
            return True

        except discord.NotFound as error:
            if error.code == 10062:
                print(
                    "⚠️ Interaction expirée avant le defer :",
                    interaction.id,
                )
                return False

            raise

        except discord.HTTPException as error:
            if error.code in {
                10062,
                40060,
            }:
                print(
                    "⚠️ Interaction expirée ou déjà reconnue :",
                    interaction.id,
                    f"code={error.code}",
                )
                return False

            raise

    async def _resolve_tournament(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
        *,
        require_active: bool = True,
    ):
        return await resolve_tournament(
            interaction,
            self.db,
            code=code,
            require_active=require_active,
        )

    # ==========================================================
    # CRÉATION TOURNOI
    # ==========================================================

    @app_commands.command(
        name="create_tournament",
        description="Créer un tournoi Hamtaro",
    )
    @app_commands.describe(
        name="Nom du tournoi",
        format="Format du tournoi",
        max_players="Nombre maximum de joueurs / équipes",
        participants="Type de participants",
    )
    @app_commands.choices(
        format=[
            app_commands.Choice(
                name=format_name,
                value=format_name,
            )
            for format_name in FORMATS
        ]
    )
    @app_commands.choices(
        participants=[
            app_commands.Choice(name="👤 Solo 1v1", value="solo"),
            app_commands.Choice(name="👥 Équipes 2v2", value="duo"),
        ]
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def create_tournament(
        self,
        interaction: discord.Interaction,
        name: str,
        format: app_commands.Choice[str],
        max_players: int,
        participants: app_commands.Choice[str],
    ) -> None:
        acknowledged = await self._safe_defer(
            interaction,
            ephemeral=False,
        )

        if not acknowledged:
            return

        try:
            guild_id = self._guild_id(
                interaction
            )

            tournament = await self.db.create_tournament(
                guild_id=guild_id,
                name=name,
                format=format.value,
                max_players=max_players,
                created_by=str(
                    interaction.user.id
                ),
            )

            # HAMTARO_2V2_V2:TOURNAMENT
            duo_cog = self.bot.get_cog("Team2v2Cog")
            if duo_cog is None:
                raise RuntimeError("Le module 2v2 Hamtaro n'est pas chargé.")
            participant_mode = await duo_cog.set_participant_mode(
                int(tournament.id),
                participants.value,
            )
            if interaction.channel_id is not None:
                await self.db.select_tournament_for_channel(
                    guild_id=guild_id,
                    channel_id=str(
                        interaction.channel_id
                    ),
                    tournament_id=int(
                        tournament.id
                    ),
                    selected_by=str(
                        interaction.user.id
                    ),
                )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        except Exception as error:
            print(
                "❌ Erreur création tournoi :",
                repr(error),
            )

            await interaction.followup.send(
                (
                    "❌ Une erreur inattendue est survenue "
                    "pendant la création du tournoi."
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🏆 Tournoi créé",
            description=(
                "Les inscriptions sont maintenant ouvertes.\n"
                "Ce tournoi a été sélectionné automatiquement "
                "dans ce salon."
            ),
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Nom",
            value=tournament.name,
            inline=False,
        )

        embed.add_field(
            name="Format",
            value=tournament.format,
            inline=True,
        )

        embed.add_field(
            name="Participants",
            value=("👥 Équipes 2v2" if participant_mode == "duo" else "👤 Solo 1v1"),
            inline=True,
        )

        embed.add_field(
            name="Code",
            value=f"`{tournament.code}`",
            inline=True,
        )

        embed.add_field(
            name="ID",
            value=f"`{tournament.id}`",
            inline=True,
        )

        embed.add_field(
            name=("Équipes" if participant_mode == "duo" else "Joueurs"),
            value=f"0/{tournament.max_players}",
            inline=True,
        )

        embed.add_field(
            name="Statut",
            value="📋 Inscriptions ouvertes",
            inline=False,
        )
        if str(tournament.format).strip().casefold() == "halloween":
            embed.add_field(
                name="🎃 Bonbon / Sort",
                value=(
                    "Side Deck : 14 cartes normales + 1 Halloween Slot. "
                    "À l'inscription, chaque joueur déclare 1 Bonbon et 1 Sort."
                ),
                inline=False,
            )

        embed.set_footer(
            text=(
                "Inscris-toi avec /register. "
                "Le staff lancera le tournoi lorsque "
                "les inscriptions seront terminées."
            )
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=False,
        )

    # ==========================================================
    # VOIR TOURNOI ACTIF
    # ==========================================================

    @app_commands.command(
        name="tournament",
        description="Voir le tournoi sélectionné dans ce salon",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi à afficher",
    )
    @app_commands.autocomplete(
        code=tournament_code_autocomplete
    )
    async def tournament(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ) -> None:
        acknowledged = await self._safe_defer(
            interaction,
            ephemeral=False,
        )

        if not acknowledged:
            return

        try:
            tournament = await self._resolve_tournament(
                interaction,
                code,
                require_active=False,
            )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        if tournament is None:
            await interaction.followup.send(
                "❌ Aucun tournoi trouvé sur ce serveur.",
                ephemeral=True,
            )
            return

        registered = await self.db.count_registrations(
            tournament.id
        )

        status = getattr(
            tournament.status,
            "value",
            str(tournament.status),
        )

        embed = discord.Embed(
            title="🏆 Tournoi sélectionné",
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Nom",
            value=tournament.name,
            inline=False,
        )

        embed.add_field(
            name="Format",
            value=tournament.format,
            inline=True,
        )

        embed.add_field(
            name="Code",
            value=f"`{tournament.code}`",
            inline=True,
        )

        embed.add_field(
            name="ID",
            value=f"`{tournament.id}`",
            inline=True,
        )

        embed.add_field(
            name="Statut",
            value=status,
            inline=True,
        )

        embed.add_field(
            name="Inscriptions",
            value=f"{registered}/{tournament.max_players}",
            inline=True,
        )

        embed.add_field(
            name="Round actuel",
            value=str(
                tournament.current_round
            ),
            inline=True,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=False,
        )

    # ==========================================================
    # MODIFIER LE FORMAT D'UN TOURNOI
    # ==========================================================

    @app_commands.command(
        name="change_tournament_format",
        description="Modifier le format d'un tournoi avant son lancement",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi à modifier",
        nouveau_format="Nouveau format du tournoi",
    )
    @app_commands.autocomplete(
        code=active_tournament_code_autocomplete
    )
    @app_commands.choices(
        nouveau_format=[
            app_commands.Choice(
                name=format_name,
                value=format_name,
            )
            for format_name in FORMATS
        ]
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def change_tournament_format(
        self,
        interaction: discord.Interaction,
        nouveau_format: app_commands.Choice[str],
        code: str | None = None,
    ) -> None:
        """
        Modifie uniquement le format d'un tournoi encore en inscriptions.

        Le code du tournoi, les inscriptions et le type de compétition
        restent inchangés. Un éventuel brouillon de démarrage est annulé
        afin qu'il soit recréé avec le nouveau format.
        """
        acknowledged = await self._safe_defer(
            interaction,
            ephemeral=True,
        )
        if not acknowledged:
            return

        try:
            tournament = await self._resolve_tournament(
                interaction,
                code,
                require_active=True,
            )

            if tournament is None:
                await interaction.followup.send(
                    "❌ Aucun tournoi actif trouvé.",
                    ephemeral=True,
                )
                return

            status = getattr(
                tournament.status,
                "value",
                str(tournament.status),
            ).lower().strip()

            if status != "registration":
                await interaction.followup.send(
                    (
                        "❌ Le format ne peut être modifié que pendant "
                        "la phase d'inscription. Ce tournoi est déjà "
                        f"dans l'état `{status}`."
                    ),
                    ephemeral=True,
                )
                return

            ancien_format = str(tournament.format)
            format_cible = str(nouveau_format.value)

            if ancien_format == format_cible:
                await interaction.followup.send(
                    (
                        f"ℹ️ Le tournoi `{tournament.code}` utilise déjà "
                        f"le format **{format_cible}**."
                    ),
                    ephemeral=True,
                )
                return

            preview_cancelled = False
            pending_preview = await self.start_previews.pending_for_tournament(
                int(tournament.id)
            )
            if pending_preview is not None:
                await self.start_previews.cancel_preview(
                    int(pending_preview["id"]),
                    str(interaction.user.id),
                )
                preview_cancelled = True

            changed_rows = await self.db.update(
                """
                UPDATE tournaments
                SET format = ?
                WHERE id = ?
                  AND status = 'registration'
                """,
                (
                    format_cible,
                    int(tournament.id),
                ),
            )

            if changed_rows != 1:
                raise RuntimeError(
                    "Le tournoi a changé d'état pendant la modification."
                )

            updated_tournament = await self.db.get_tournament(
                int(tournament.id)
            )
            if updated_tournament is None:
                raise RuntimeError(
                    "Le tournoi a été modifié mais ne peut plus être relu."
                )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        except Exception as error:
            print(
                "❌ Erreur /change_tournament_format :",
                repr(error),
            )
            await interaction.followup.send(
                (
                    "❌ Le format du tournoi n'a pas pu être modifié. "
                    f"Détail : `{error}`"
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="✅ Format du tournoi modifié",
            description=(
                "Le tournoi reste en phase d'inscription. "
                "Les joueurs déjà inscrits sont conservés."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Tournoi",
            value=updated_tournament.name,
            inline=False,
        )
        embed.add_field(
            name="Code",
            value=f"`{updated_tournament.code}`",
            inline=True,
        )
        embed.add_field(
            name="Ancien format",
            value=ancien_format,
            inline=True,
        )
        embed.add_field(
            name="Nouveau format",
            value=format_cible,
            inline=True,
        )
        embed.add_field(
            name="Brouillon de démarrage",
            value=(
                "♻️ Ancien brouillon annulé"
                if preview_cancelled
                else "Aucun brouillon à annuler"
            ),
            inline=False,
        )
        embed.set_footer(
            text=(
                "Le code du tournoi ne change pas. "
                "Relance /start_tournament pour préparer un nouveau tirage."
            )
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # MODIFIER LA CAPACITÉ D'UN TOURNOI
    # ==========================================================

    @app_commands.command(
        name="change_tournament_capacity",
        description="Modifier la capacité d'un tournoi avant son lancement",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi à modifier",
        nouvelle_capacite="Nouveau nombre maximum de joueurs",
    )
    @app_commands.autocomplete(
        code=active_tournament_code_autocomplete
    )
    @app_commands.choices(
        nouvelle_capacite=[
            app_commands.Choice(
                name=f"{capacity} joueurs",
                value=capacity,
            )
            for capacity in TOURNAMENT_CAPACITIES
        ]
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def change_tournament_capacity(
        self,
        interaction: discord.Interaction,
        nouvelle_capacite: app_commands.Choice[int],
        code: str | None = None,
    ) -> None:
        """
        Modifie la capacité d'un tournoi encore en phase d'inscription.

        La capacité ne peut pas devenir inférieure au nombre de joueurs
        déjà inscrits. Un éventuel brouillon de démarrage est annulé.
        """
        acknowledged = await self._safe_defer(
            interaction,
            ephemeral=True,
        )
        if not acknowledged:
            return

        try:
            tournament = await self._resolve_tournament(
                interaction,
                code,
                require_active=True,
            )

            if tournament is None:
                await interaction.followup.send(
                    "❌ Aucun tournoi actif trouvé.",
                    ephemeral=True,
                )
                return

            status = getattr(
                tournament.status,
                "value",
                str(tournament.status),
            ).lower().strip()

            if status != "registration":
                await interaction.followup.send(
                    (
                        "❌ La capacité ne peut être modifiée que pendant "
                        "la phase d'inscription. Ce tournoi est déjà "
                        f"dans l'état `{status}`."
                    ),
                    ephemeral=True,
                )
                return

            ancienne_capacite = int(tournament.max_players)
            capacite_cible = int(nouvelle_capacite.value)

            if capacite_cible not in TOURNAMENT_CAPACITIES:
                await interaction.followup.send(
                    (
                        "❌ Capacité invalide. Valeurs autorisées : "
                        + ", ".join(
                            str(value)
                            for value in TOURNAMENT_CAPACITIES
                        )
                        + "."
                    ),
                    ephemeral=True,
                )
                return

            registered = await self.db.count_registrations(
                int(tournament.id)
            )

            if capacite_cible < registered:
                await interaction.followup.send(
                    (
                        f"❌ Impossible de réduire ce tournoi à "
                        f"**{capacite_cible} joueurs** : "
                        f"**{registered} joueur(s)** sont déjà inscrits."
                    ),
                    ephemeral=True,
                )
                return

            if ancienne_capacite == capacite_cible:
                await interaction.followup.send(
                    (
                        f"ℹ️ Le tournoi `{tournament.code}` possède déjà "
                        f"une capacité de **{capacite_cible} joueurs**."
                    ),
                    ephemeral=True,
                )
                return

            changed_rows = await self.db.update(
                """
                UPDATE tournaments
                SET max_players = ?
                WHERE id = ?
                  AND status = 'registration'
                  AND ? >= (
                      SELECT COUNT(*)
                      FROM registrations
                      WHERE tournament_id = ?
                        AND dropped = 0
                        AND disqualified = 0
                  )
                """,
                (
                    capacite_cible,
                    int(tournament.id),
                    capacite_cible,
                    int(tournament.id),
                ),
            )

            if changed_rows != 1:
                current_registered = await self.db.count_registrations(
                    int(tournament.id)
                )
                raise RuntimeError(
                    (
                        "La capacité n'a pas été modifiée. "
                        "Le tournoi a peut-être changé d'état ou "
                        f"compte désormais {current_registered} inscrit(s)."
                    )
                )

            preview_cancelled = False
            preview_warning = False

            try:
                pending_preview = (
                    await self.start_previews.pending_for_tournament(
                        int(tournament.id)
                    )
                )

                if pending_preview is not None:
                    await self.start_previews.cancel_preview(
                        int(pending_preview["id"]),
                        str(interaction.user.id),
                    )
                    preview_cancelled = True

            except Exception as preview_error:
                preview_warning = True
                print(
                    "⚠️ Capacité modifiée mais brouillon non annulé :",
                    repr(preview_error),
                )

            updated_tournament = await self.db.get_tournament(
                int(tournament.id)
            )

            if updated_tournament is None:
                raise RuntimeError(
                    "Le tournoi a été modifié mais ne peut plus être relu."
                )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        except Exception as error:
            print(
                "❌ Erreur /change_tournament_capacity :",
                repr(error),
            )
            await interaction.followup.send(
                (
                    "❌ La capacité du tournoi n'a pas pu être modifiée. "
                    f"Détail : `{error}`"
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="✅ Capacité du tournoi modifiée",
            description=(
                "Le tournoi reste en phase d'inscription. "
                "Les joueurs déjà inscrits sont conservés."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Tournoi",
            value=updated_tournament.name,
            inline=False,
        )
        embed.add_field(
            name="Code",
            value=f"`{updated_tournament.code}`",
            inline=True,
        )
        embed.add_field(
            name="Ancienne capacité",
            value=f"{ancienne_capacite} joueurs",
            inline=True,
        )
        embed.add_field(
            name="Nouvelle capacité",
            value=f"{capacite_cible} joueurs",
            inline=True,
        )
        embed.add_field(
            name="Inscriptions actuelles",
            value=f"{registered}/{capacite_cible}",
            inline=True,
        )

        if preview_warning:
            preview_status = (
                "⚠️ La capacité est modifiée, mais le brouillon "
                "n'a pas pu être annulé automatiquement."
            )
        elif preview_cancelled:
            preview_status = "♻️ Ancien brouillon annulé"
        else:
            preview_status = "Aucun brouillon à annuler"

        embed.add_field(
            name="Brouillon de démarrage",
            value=preview_status,
            inline=False,
        )
        embed.set_footer(
            text=(
                "Le code, le format et les inscriptions du tournoi "
                "restent inchangés."
            )
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ==========================================================
    # LANCER TOURNOI
    # ==========================================================

    @app_commands.command(
        name="start_tournament",
        description="Lancer le tournoi sélectionné",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi à lancer",
    )
    @app_commands.autocomplete(
        code=active_tournament_code_autocomplete
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def start_tournament(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ) -> None:
        acknowledged = await self._safe_defer(
            interaction,
            ephemeral=True,
        )

        if not acknowledged:
            return

        try:
            tournament = await self._resolve_tournament(
                interaction,
                code,
            )

            if tournament is None:
                await interaction.followup.send(
                    "❌ Aucun tournoi actif trouvé.",
                    ephemeral=True,
                )
                return

            status = getattr(
                tournament.status,
                "value",
                str(tournament.status),
            ).lower()

            if status == "running":
                await interaction.followup.send(
                    "❌ Le tournoi est déjà lancé.",
                    ephemeral=True,
                )
                return

            if status != "registration":
                await interaction.followup.send(
                    (
                        "❌ Le tournoi doit être en phase "
                        "d'inscription pour être lancé."
                    ),
                    ephemeral=True,
                )
                return

            # HAMTARO_2V2_V2:START_ELIMINATION
            duo_cog = self.bot.get_cog("Team2v2Cog")
            if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
                text = await duo_cog.start_from_native(int(tournament.id), "elimination")
                await interaction.followup.send(
                    "✅ **Tournoi 2v2 lancé en élimination directe !**\n\n" + text,
                    ephemeral=True,
                )
                return
            await self.brackets.generate(
                tournament.id
            )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        except Exception as error:
            print(
                "❌ Erreur /start_tournament :",
                repr(error),
            )

            await interaction.followup.send(
                (
                    "❌ Erreur pendant le lancement "
                    f"du tournoi : `{error}`"
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            (
                f"✅ Tournoi `{tournament.code}` "
                f"(ID `#{tournament.id}`) lancé avec succès."
            ),
            ephemeral=True,
        )

    # ==========================================================
    # ANNULER TOURNOI
    # ==========================================================

    @app_commands.command(
        name="cancel_tournament",
        description="Annuler le tournoi sélectionné",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi à annuler",
    )
    @app_commands.autocomplete(
        code=active_tournament_code_autocomplete
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def cancel_tournament(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ) -> None:
        acknowledged = await self._safe_defer(
            interaction,
            ephemeral=True,
        )

        if not acknowledged:
            return

        try:
            tournament = await self._resolve_tournament(
                interaction,
                code,
            )

            if tournament is None:
                await interaction.followup.send(
                    "❌ Aucun tournoi actif à annuler.",
                    ephemeral=True,
                )
                return

            await self.brackets.cancel_tournament(
                tournament.id
            )

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        except Exception as error:
            print(
                "❌ Erreur /cancel_tournament :",
                repr(error),
            )

            await interaction.followup.send(
                (
                    "❌ Une erreur inattendue est survenue "
                    "pendant l'annulation du tournoi."
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            (
                f"✅ Tournoi `{tournament.code}` "
                f"(ID `#{tournament.id}`) annulé."
            ),
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        TournamentCog(bot)
    )
