from __future__ import annotations

import io
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from services.bracket_image_service import BracketImageService
from services.bracket_service import BracketService
from utils.tournament_resolver import resolve_tournament as resolve_selected_tournament


class BracketCog(commands.Cog):
    """
    Commandes liées aux tournois à élimination directe.

    Commandes graphiques :
    - /bracket
    - /final_bracket

    Commandes textuelles conservées :
    - /round
    - /round_show
    - /nextmatch
    - /finale
    - /matches
    - /winner
    """

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.db = bot.db

        self.brackets = BracketService(
            self.db
        )

        self.renderer = BracketImageService(
            self.db
        )

    # ==========================================================
    # OUTILS GÉNÉRAUX
    # ==========================================================

    @staticmethod
    def _status_value(
        status: Any,
    ) -> str:
        """
        Retourne la valeur texte d'un statut.

        Compatible avec :
        - Enum ;
        - chaîne de caractères ;
        - valeur inconnue.
        """

        return getattr(
            status,
            "value",
            str(status),
        ).lower()

    def _guild_id(
        self,
        interaction: discord.Interaction,
    ) -> str:
        """
        Retourne l'identifiant du serveur Discord.
        """

        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(
            interaction.guild.id
        )

    async def _get_active_tournament(
        self,
        interaction: discord.Interaction,
    ):
        """Retourne le tournoi sélectionné dans le salon."""

        return await resolve_selected_tournament(
            interaction,
            self.db,
        )

    async def _get_tournament_for_guild(
        self,
        interaction: discord.Interaction,
        tournament_id: int,
    ):
        """
        Récupère un tournoi précis et vérifie qu'il appartient
        bien au serveur dans lequel la commande est exécutée.
        """

        guild_id = self._guild_id(
            interaction
        )

        tournament = await self.db.get_tournament(
            tournament_id
        )

        if tournament is None:
            raise ValueError(
                f"Aucun tournoi trouvé avec l'identifiant #{tournament_id}."
            )

        tournament_guild_id = str(
            getattr(
                tournament,
                "guild_id",
                "",
            )
        )

        if tournament_guild_id != guild_id:
            raise ValueError(
                "Ce tournoi n'appartient pas à ce serveur."
            )

        return tournament

    async def _resolve_tournament(
        self,
        interaction: discord.Interaction,
        tournament_id: int | None,
    ):
        """
        Si un ID est fourni, récupère ce tournoi.

        Sinon, retourne le tournoi sélectionné dans le salon.
        """

        if tournament_id is not None:

            return await self._get_tournament_for_guild(
                interaction,
                tournament_id,
            )

        tournament = await self._get_active_tournament(
            interaction
        )

        if tournament is None:
            raise ValueError(
                "Aucun tournoi actif sur ce serveur."
            )

        return tournament

    async def _send_text(
        self,
        interaction: discord.Interaction,
        text: str,
        *,
        ephemeral: bool = False,
    ) -> None:
        """
        Envoie un texte Discord en évitant la limite
        des 2 000 caractères.
        """

        if len(text) <= 1900:

            await interaction.followup.send(
                text,
                ephemeral=ephemeral,
            )

            return

        chunks: list[str] = []
        current = ""

        for line in text.splitlines():

            candidate = (
                f"{current}\n{line}"
                if current
                else line
            )

            if len(candidate) > 1900:

                if current:
                    chunks.append(
                        current
                    )

                current = line

            else:

                current = candidate

        if current:

            chunks.append(
                current
            )

        for chunk in chunks:

            await interaction.followup.send(
                chunk,
                ephemeral=ephemeral,
            )

    # ==========================================================
    # AVATARS DISCORD
    # ==========================================================

    @staticmethod
    def _collect_player_ids(
        bracket: dict[
            int,
            list[Any],
        ],
    ) -> set[str]:
        """
        Récupère tous les identifiants Discord présents
        dans le bracket.
        """

        player_ids: set[str] = set()

        for matches in bracket.values():

            for match in matches:

                player1_id = getattr(
                    match,
                    "player1_id",
                    None,
                )

                player2_id = getattr(
                    match,
                    "player2_id",
                    None,
                )

                winner_id = getattr(
                    match,
                    "winner_id",
                    None,
                )

                if player1_id:
                    player_ids.add(
                        str(player1_id)
                    )

                if player2_id:
                    player_ids.add(
                        str(player2_id)
                    )

                if winner_id:
                    player_ids.add(
                        str(winner_id)
                    )

        return player_ids

    async def _build_avatar_urls(
        self,
        interaction: discord.Interaction,
        bracket: dict[
            int,
            list[Any],
        ],
    ) -> dict[str, str]:
        """
        Construit une table :

        {
            "discord_id": "url_avatar"
        }

        Le membre est d'abord recherché dans le cache Discord,
        puis récupéré avec l'API si nécessaire.
        """

        guild = interaction.guild

        if guild is None:
            return {}

        avatar_urls: dict[
            str,
            str,
        ] = {}

        player_ids = self._collect_player_ids(
            bracket
        )

        for discord_id in player_ids:

            try:

                numeric_id = int(
                    discord_id
                )

            except ValueError:

                continue

            member = guild.get_member(
                numeric_id
            )

            if member is None:

                try:

                    member = await guild.fetch_member(
                        numeric_id
                    )

                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ):

                    member = None

            if member is None:
                continue

            avatar_urls[discord_id] = (
                member.display_avatar.replace(
                    size=256,
                    static_format="png",
                ).url
            )

        return avatar_urls

    # ==========================================================
    # ENVOI DES IMAGES
    # ==========================================================

    async def _send_bracket_image(
        self,
        interaction: discord.Interaction,
        tournament: Any,
        *,
        final_mode: bool,
    ) -> None:
        """
        Charge les données du bracket, génère le PNG,
        puis l'envoie dans Discord.
        """

        tournament_id = getattr(
            tournament,
            "id",
            None,
        )

        if tournament_id is None:
            raise ValueError(
                "L'identifiant du tournoi est introuvable."
            )

        bracket = await self.brackets.get_bracket(
            tournament_id
        )

        if not bracket:
            raise ValueError(
                "Aucun bracket n'a été généré pour ce tournoi."
            )

        avatar_urls = await self._build_avatar_urls(
            interaction,
            bracket,
        )

        image_buffer = await self.renderer.render(
            tournament,
            bracket,
            avatar_urls=avatar_urls,
            final_mode=final_mode,
        )

        if not isinstance(
            image_buffer,
            io.BytesIO,
        ):
            raise RuntimeError(
                "Le moteur graphique n'a pas retourné une image valide."
            )

        filename = (
            f"hamtaro_final_bracket_{tournament_id}.png"
            if final_mode
            else f"hamtaro_bracket_{tournament_id}.png"
        )

        discord_file = discord.File(
            fp=image_buffer,
            filename=filename,
        )

        tournament_name = getattr(
            tournament,
            "name",
            "Tournoi Hamtaro",
        )

        tournament_format = getattr(
            tournament,
            "format",
            "Format inconnu",
        )

        if final_mode:

            message = (
                f"🏆 **Bracket final — {tournament_name}**\n"
                f"Tournoi `#{tournament_id}` • "
                f"Format : **{tournament_format}**"
            )

        else:

            message = (
                f"🐹 **Bracket en direct — {tournament_name}**\n"
                f"Tournoi `#{tournament_id}` • "
                f"Format : **{tournament_format}**\n"
                "Les résultats affichés correspondent aux "
                "résultats actuellement enregistrés."
            )

        try:

            await interaction.followup.send(
                content=message,
                file=discord_file,
                ephemeral=False,
            )

        except discord.HTTPException as error:

            image_size_mb = (
                image_buffer.getbuffer().nbytes
                / 1024
                / 1024
            )

            raise ValueError(
                "Discord n'a pas pu envoyer l'image du bracket. "
                f"Taille générée : {image_size_mb:.2f} Mo. "
                "Le fichier est peut-être trop volumineux pour "
                "la limite de pièces jointes du serveur."
            ) from error

    # ==========================================================
    # BRACKET GRAPHIQUE EN DIRECT
    # ==========================================================

    @app_commands.command(
        name="bracket",
        description="Afficher l'arbre graphique d'un tournoi en cours"
    )
    @app_commands.describe(
        tournament_id=(
            "ID du tournoi à afficher. "
            "Laisse vide pour utiliser le tournoi sélectionné."
        )
    )
    async def bracket(
        self,
        interaction: discord.Interaction,
        tournament_id: int | None = None,
    ):
        """
        Affiche le bracket graphique en direct.

        Sans ID :
            tournoi sélectionné dans le salon.

        Avec ID :
            tournoi précis du serveur.
        """

        await interaction.response.defer(
            ephemeral=False,
            thinking=True,
        )

        try:

            tournament = await self._resolve_tournament(
                interaction,
                tournament_id,
            )

            finished = await self.brackets.is_finished(
                tournament.id
            )

            if finished:

                await interaction.followup.send(
                    (
                        "ℹ️ Ce tournoi est terminé. "
                        "Utilise plutôt "
                        f"`/final_bracket tournament_id:{tournament.id}` "
                        "pour obtenir son affiche finale."
                    ),
                    ephemeral=True,
                )

                return

            await self._send_bracket_image(
                interaction,
                tournament,
                final_mode=False,
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

        except Exception as error:

            print(
                "❌ Erreur /bracket :",
                repr(error),
            )

            await interaction.followup.send(
                (
                    "❌ Une erreur inattendue est survenue pendant "
                    "la génération de l'image du bracket."
                ),
                ephemeral=True,
            )

    # ==========================================================
    # BRACKET FINAL D'UN TOURNOI TERMINÉ
    # ==========================================================

    @app_commands.command(
        name="final_bracket",
        description="Générer l'affiche finale d'un ancien tournoi"
    )
    @app_commands.describe(
        tournament_id=(
            "Identifiant du tournoi terminé à afficher"
        )
    )
    async def final_bracket(
        self,
        interaction: discord.Interaction,
        tournament_id: int,
    ):
        """
        Génère l'affiche complète d'un tournoi terminé.

        L'identifiant est obligatoire pour permettre de retrouver
        précisément un ancien tournoi.
        """

        await interaction.response.defer(
            ephemeral=False,
            thinking=True,
        )

        try:

            tournament = await self._get_tournament_for_guild(
                interaction,
                tournament_id,
            )

            finished = await self.brackets.is_finished(
                tournament.id
            )

            if not finished:

                await interaction.followup.send(
                    (
                        "❌ Ce tournoi n'est pas encore terminé.\n"
                        "Utilise `/bracket` pour consulter son "
                        "avancement actuel."
                    ),
                    ephemeral=True,
                )

                return

            winner = await self.brackets.get_winner(
                tournament.id
            )

            if winner is None:

                await interaction.followup.send(
                    (
                        "❌ Aucun champion n'est enregistré pour "
                        "ce tournoi. Vérifie que la finale a bien "
                        "été validée."
                    ),
                    ephemeral=True,
                )

                return

            await self._send_bracket_image(
                interaction,
                tournament,
                final_mode=True,
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

        except Exception as error:

            print(
                "❌ Erreur /final_bracket :",
                repr(error),
            )

            await interaction.followup.send(
                (
                    "❌ Une erreur inattendue est survenue pendant "
                    "la génération du bracket final."
                ),
                ephemeral=True,
            )

    # ==========================================================
    # ROUND ACTUEL
    # ==========================================================

    @app_commands.command(
        name="round",
        description="Afficher le round actuel"
    )
    async def current_round(
        self,
        interaction: discord.Interaction,
    ):
        """
        Affiche le round actuellement en cours sous forme textuelle.
        """

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

            text = await self.brackets.format_current_round(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await self._send_text(
            interaction,
            text,
            ephemeral=False,
        )

    # ==========================================================
    # ROUND PRÉCIS
    # ==========================================================

    @app_commands.command(
        name="round_show",
        description="Afficher un round précis du tournoi"
    )
    @app_commands.describe(
        round_number="Numéro du round à afficher"
    )
    async def round_show(
        self,
        interaction: discord.Interaction,
        round_number: app_commands.Range[int, 1, 7],
    ):
        """
        Affiche un round particulier sous forme textuelle.
        """

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

            matches = await self.brackets.get_round_matches(
                tournament.id,
                round_number,
            )

            if not matches:

                await interaction.followup.send(
                    "❌ Aucun match trouvé pour ce round.",
                    ephemeral=True,
                )

                return

            text = self.brackets.format_round(
                round_number,
                matches,
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await self._send_text(
            interaction,
            text,
            ephemeral=False,
        )

    # ==========================================================
    # PROCHAIN MATCH
    # ==========================================================

    @app_commands.command(
        name="nextmatch",
        description="Voir le prochain match d'un joueur"
    )
    @app_commands.describe(
        joueur=(
            "Joueur concerné. "
            "Laisse vide pour afficher ton propre match."
        )
    )
    async def nextmatch(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member | None = None,
    ):
        """
        Affiche le prochain match jouable du membre sélectionné.
        """

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

            target = (
                joueur
                or interaction.user
            )

            text = await self.brackets.format_next_match(
                tournament.id,
                str(target.id),
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            text,
            ephemeral=True,
        )

    # ==========================================================
    # FINALE TEXTUELLE
    # ==========================================================

    @app_commands.command(
        name="finale",
        description="Afficher la finale du tournoi actif"
    )
    async def finale(
        self,
        interaction: discord.Interaction,
    ):
        """
        Affiche uniquement la finale sous forme textuelle.
        """

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

            text = await self.brackets.format_final(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            text,
            ephemeral=False,
        )

    # ==========================================================
    # MATCHS JOUABLES
    # ==========================================================

    @app_commands.command(
        name="matches",
        description="Afficher les matchs actuellement jouables"
    )
    async def matches(
        self,
        interaction: discord.Interaction,
    ):
        """
        Affiche les matchs dont les deux joueurs sont connus.
        """

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

            text = await self.brackets.format_ready_matches(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        await self._send_text(
            interaction,
            text,
            ephemeral=False,
        )

    # ==========================================================
    # VAINQUEUR
    # ==========================================================

    @app_commands.command(
        name="winner",
        description="Afficher le vainqueur du tournoi actif"
    )
    async def winner(
        self,
        interaction: discord.Interaction,
    ):
        """
        Affiche le champion du tournoi actif.
        """

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

            winner = await self.brackets.get_winner(
                tournament.id
            )

        except ValueError as error:

            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )

            return

        if winner is None:

            await interaction.followup.send(
                "❌ Le tournoi n'a pas encore de vainqueur.",
                ephemeral=True,
            )

            return

        _, winner_name = winner

        await interaction.followup.send(
            (
                "🏆 Le vainqueur du tournoi est "
                f"**{winner_name}** !"
            ),
            ephemeral=False,
        )


async def setup(
    bot: commands.Bot,
):
    """
    Charge le Cog dans Hamtaro.
    """

    await bot.add_cog(
        BracketCog(bot)
    )
