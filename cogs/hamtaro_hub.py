from __future__ import annotations

import inspect
import logging
import os
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils.tournament_resolver import resolve_tournament


LOGGER = logging.getLogger(__name__)
HUB_TIMEOUT_SECONDS = 300
DEFAULT_WEBSITE_URL = "https://worker-production-5a11.up.railway.app"

STATUS_LABELS = {
    "registration": "🟢 Inscriptions ouvertes",
    "checkin": "🟡 Check-in",
    "check-in": "🟡 Check-in",
    "running": "🔴 En cours",
    "active": "🔴 En cours",
    "finished": "🏁 Terminé",
    "cancelled": "⚫ Annulé",
}


async def safe_ephemeral_send(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
) -> None:
    """Répond à une interaction, même si elle a déjà été différée."""

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                content=content,
                embed=embed,
                view=view,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                content=content,
                embed=embed,
                view=view,
                ephemeral=True,
            )
    except discord.NotFound as error:
        if error.code != 10062:
            raise


class HubRegistrationModal(discord.ui.Modal):
    """Fenêtre d'inscription ouverte depuis le centre Hamtaro."""

    def __init__(self, cog: "HamtaroHubCog") -> None:
        super().__init__(title="Inscription au tournoi Hamtaro")
        self.cog = cog

        self.deck = discord.ui.TextInput(
            label="Deck joué",
            placeholder="Ex. : Blue Eyes",
            required=False,
            max_length=100,
        )
        self.add_item(self.deck)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        deck_value = str(self.deck.value).strip() or None
        await self.cog.invoke_public_command(
            interaction,
            "register",
            deck=deck_value,
            code=None,
        )


class HubQuickResultModal(discord.ui.Modal):
    """Déclaration rapide d'un résultat depuis /hamtaro."""

    def __init__(
        self,
        *,
        match_center: commands.Cog,
        match_kind: str,
        match_id: int,
        player1_name: str,
        player2_name: str,
    ) -> None:
        super().__init__(title=f"Résultat du match #{match_id}")
        self.match_center = match_center
        self.match_kind = match_kind
        self.match_id = match_id

        self.player1_score = discord.ui.TextInput(
            label=f"Score de {player1_name}"[:45],
            placeholder="Ex. : 2",
            required=True,
            max_length=2,
        )
        self.player2_score = discord.ui.TextInput(
            label=f"Score de {player2_name}"[:45],
            placeholder="Ex. : 1",
            required=True,
            max_length=2,
        )
        self.add_item(self.player1_score)
        self.add_item(self.player2_score)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            score1 = int(str(self.player1_score.value).strip())
            score2 = int(str(self.player2_score.value).strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Les scores doivent être des nombres entiers.",
                ephemeral=True,
            )
            return

        if score1 < 0 or score2 < 0:
            await interaction.response.send_message(
                "❌ Un score ne peut pas être négatif.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            sent_staff, sent_opponent = (
                await self.match_center.submit_quick_result(  # type: ignore[attr-defined]
                    interaction=interaction,
                    match_kind=self.match_kind,
                    match_id=self.match_id,
                    player1_score=score1,
                    player2_score=score2,
                )
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Résultat impossible",
                    description=str(error),
                    colour=discord.Colour.red(),
                ),
                ephemeral=True,
            )
            return
        except Exception as error:
            LOGGER.exception(
                "Erreur de résultat rapide %s:%s",
                self.match_kind,
                self.match_id,
            )
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Erreur inattendue",
                    description="Le résultat n'a pas pu être transmis.",
                    colour=discord.Colour.red(),
                ),
                ephemeral=True,
            )
            return

        details = [
            (
                "✅ Résultat envoyé au staff."
                if sent_staff
                else "⚠️ Salon de validation inaccessible."
            ),
            (
                "✅ Confirmation envoyée à l'adversaire."
                if sent_opponent
                else "⚠️ L'adversaire n'a pas pu être contacté automatiquement."
            ),
            "Pour joindre une preuve, utilise aussi `/result`.",
        ]

        await interaction.followup.send(
            embed=discord.Embed(
                title="📊 Résultat déclaré",
                description="\n".join(details),
                colour=discord.Colour.green(),
            ),
            ephemeral=True,
        )


class HamtaroHubView(discord.ui.View):
    """Menu joueur principal affiché par /hamtaro."""

    def __init__(
        self,
        *,
        cog: "HamtaroHubCog",
        requester_id: int,
    ) -> None:
        super().__init__(timeout=HUB_TIMEOUT_SECONDS)
        self.cog = cog
        self.requester_id = requester_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True

        await interaction.response.send_message(
            "❌ Ce centre Hamtaro appartient à une autre personne. Utilise `/hamtaro`.",
            ephemeral=True,
        )
        return False

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[Any],
    ) -> None:
        LOGGER.exception(
            "Erreur dans le centre /hamtaro (%s)",
            type(item).__name__,
            exc_info=error,
        )
        await safe_ephemeral_send(
            interaction,
            content="❌ Une erreur est survenue dans le centre Hamtaro.",
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True  # type: ignore[assignment]

        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    @discord.ui.button(
        label="S'inscrire",
        emoji="📝",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def register_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.send_modal(HubRegistrationModal(self.cog))

    @discord.ui.button(
        label="Prochain match",
        emoji="🎯",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def next_match_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.cog.invoke_public_command(
            interaction,
            "nextmatch",
            joueur=None,
            tournoi=None,
        )

    @discord.ui.button(
        label="Signaler résultat",
        emoji="📊",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def result_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.cog.open_result_modal(interaction)

    @discord.ui.button(
        label="Bracket",
        emoji="🌳",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def bracket_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.cog.invoke_public_command(
            interaction,
            "bracket",
            tournoi=None,
        )

    @discord.ui.button(
        label="Classement",
        emoji="🏆",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def ranking_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.cog.open_ranking(interaction)

    @discord.ui.button(
        label="Mon profil",
        emoji="👤",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def profile_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.cog.invoke_public_command(
            interaction,
            "profile",
            member=None,
            code=None,
            visible=False,
        )

    @discord.ui.button(
        label="Règlement",
        emoji="📜",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def rules_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.cog.open_rules(interaction)

    @discord.ui.button(
        label="Site Hamtaro",
        emoji="🌐",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def website_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.cog.open_website(interaction)

    @discord.ui.button(
        label="Aide",
        emoji="🆘",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def help_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.cog.invoke_public_command(
            interaction,
            "help",
            commande=None,
            visible=False,
        )

    @discord.ui.button(
        label="Actualiser",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.defer()
        embed = await self.cog.build_home_embed(interaction)
        await interaction.edit_original_response(embed=embed, view=self)


class HamtaroHubCog(commands.Cog):
    """Commande centrale /hamtaro destinée aux joueurs."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db

    # ==========================================================
    # OUTILS
    # ==========================================================

    async def current_tournament(self, interaction: discord.Interaction):
        if interaction.guild is None:
            raise ValueError("Cette commande doit être utilisée dans un serveur.")

        tournament = await resolve_tournament(
            interaction,
            self.db,
        )

        if tournament is None:
            raise ValueError(
                "Aucun tournoi n'est sélectionné dans ce salon et aucun tournoi actif n'a été trouvé."
            )

        return tournament

    @staticmethod
    def status_value(tournament: Any) -> str:
        raw_status = getattr(tournament, "status", "inconnu")
        return str(getattr(raw_status, "value", raw_status)).lower()

    async def invoke_public_command(
        self,
        interaction: discord.Interaction,
        command_name: str,
        **kwargs: Any,
    ) -> bool:
        """
        Réutilise la logique d'une commande publique déjà chargée.

        Les paramètres inconnus sont ignorés afin de rester compatible
        avec plusieurs versions du projet Hamtaro.
        """

        command = self.bot.tree.get_command(command_name)

        if not isinstance(command, app_commands.Command):
            await safe_ephemeral_send(
                interaction,
                content=(
                    f"❌ La commande `/{command_name}` n'est pas chargée. "
                    "Vérifie la liste `COGS` dans `bot.py`."
                ),
            )
            return False

        callback = getattr(command, "callback", None)
        if callback is None:
            callback = getattr(command, "_callback", None)

        if callback is None:
            await safe_ephemeral_send(
                interaction,
                content=f"❌ La commande `/{command_name}` ne peut pas être ouverte.",
            )
            return False

        signature = inspect.signature(callback)
        accepted_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key in signature.parameters
        }

        binding = getattr(command, "binding", None)

        try:
            if binding is not None:
                await callback(
                    binding,
                    interaction,
                    **accepted_kwargs,
                )
            else:
                await callback(
                    interaction,
                    **accepted_kwargs,
                )
        except discord.NotFound as error:
            if error.code == 10062:
                LOGGER.warning(
                    "Interaction expirée pendant l'ouverture de /%s",
                    command_name,
                )
                return False
            raise
        except Exception as error:
            LOGGER.exception(
                "Impossible d'ouvrir /%s depuis /hamtaro",
                command_name,
            )
            await safe_ephemeral_send(
                interaction,
                content=(
                    f"❌ Impossible d'ouvrir `/{command_name}` depuis le centre Hamtaro.\n"
                    f"Erreur : `{type(error).__name__}`"
                ),
            )
            return False

        return True

    # ==========================================================
    # EMBED PRINCIPAL
    # ==========================================================

    async def build_home_embed(
        self,
        interaction: discord.Interaction,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="🐹 Centre Hamtaro",
            description=(
                "Toutes les actions importantes du tournoi sont réunies ici.\n"
                "Choisis simplement un bouton."
            ),
            colour=discord.Colour.gold(),
        )

        try:
            tournament = await self.current_tournament(interaction)
        except ValueError as error:
            embed.add_field(
                name="🏟️ Tournoi",
                value=f"⚠️ {error}",
                inline=False,
            )
            embed.add_field(
                name="Que faire ?",
                value=(
                    "Le staff doit ouvrir ou sélectionner un tournoi. "
                    "Le bouton **Site Hamtaro** reste accessible."
                ),
                inline=False,
            )
        else:
            tournament_id = int(getattr(tournament, "id", 0) or 0)
            code = str(getattr(tournament, "code", tournament_id or "—"))
            name = str(getattr(tournament, "name", "Tournoi Hamtaro"))
            tournament_format = str(getattr(tournament, "format", "Format inconnu"))
            status = self.status_value(tournament)
            status_label = STATUS_LABELS.get(status, status.title())

            current = None
            maximum = getattr(tournament, "max_players", None)
            try:
                current = await self.db.count_registrations(tournament_id)
            except Exception:
                current = None

            participant_text = (
                f"{current}/{maximum}"
                if current is not None and maximum is not None
                else "Non disponible"
            )

            embed.add_field(
                name="🏟️ Tournoi sélectionné",
                value=(
                    f"**{name}**\n"
                    f"Code : `{code}` • ID : `#{tournament_id}`\n"
                    f"Format : **{tournament_format}**\n"
                    f"Statut : **{status_label}**\n"
                    f"Participants : **{participant_text}**"
                ),
                inline=False,
            )

            registration = None
            try:
                registration = await self.db.get_registration_by_user(
                    tournament_id=tournament_id,
                    discord_id=str(interaction.user.id),
                )
            except Exception:
                registration = None

            if registration is None:
                registration_text = "❌ Tu n'es pas encore inscrit à ce tournoi."
            else:
                deck = getattr(registration, "deck", None) or "Non renseigné"
                registration_text = f"✅ Inscrit • Deck : **{deck}**"

            embed.add_field(
                name="🎴 Ton inscription",
                value=registration_text,
                inline=False,
            )

        embed.add_field(
            name="⚡ Accès rapides",
            value=(
                "`S'inscrire` • `Prochain match` • `Signaler résultat`\n"
                "`Bracket` • `Classement` • `Profil` • `Règlement`"
            ),
            inline=False,
        )

        if self.bot.user is not None:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        embed.set_footer(
            text="Menu privé • Les boutons restent actifs pendant 5 minutes."
        )
        return embed

    # ==========================================================
    # RÉSULTAT RAPIDE
    # ==========================================================

    async def _find_player_match(
        self,
        *,
        tournament_id: int,
        player_id: str,
    ) -> tuple[str, dict[str, Any]] | None:
        bracket_match = None
        swiss_match = None

        try:
            row = await self.db.fetchone(
                """
                SELECT
                    id,
                    player1_id,
                    player2_id,
                    player1_name,
                    player2_name,
                    status,
                    round AS round_number,
                    match_number AS position_number
                FROM matches
                WHERE tournament_id = ?
                  AND (player1_id = ? OR player2_id = ?)
                  AND player1_id IS NOT NULL
                  AND player2_id IS NOT NULL
                  AND COALESCE(is_bye, 0) = 0
                  AND winner_id IS NULL
                  AND status IN ('waiting', 'pending', 'playing', 'reported')
                ORDER BY
                    CASE status
                        WHEN 'playing' THEN 0
                        WHEN 'waiting' THEN 1
                        WHEN 'pending' THEN 1
                        WHEN 'reported' THEN 2
                        ELSE 3
                    END,
                    round ASC,
                    match_number ASC,
                    id ASC
                LIMIT 1
                """,
                (tournament_id, player_id, player_id),
            )
            if row is not None:
                bracket_match = dict(row)
        except Exception as error:
            LOGGER.debug("Recherche match bracket impossible : %s", error)

        try:
            row = await self.db.fetchone(
                """
                SELECT
                    id,
                    player1_id,
                    player2_id,
                    player1_name,
                    player2_name,
                    status,
                    round_number,
                    table_number AS position_number
                FROM swiss_matches
                WHERE tournament_id = ?
                  AND (player1_id = ? OR player2_id = ?)
                  AND player1_id IS NOT NULL
                  AND player2_id IS NOT NULL
                  AND COALESCE(is_bye, 0) = 0
                  AND status IN ('pending', 'waiting', 'playing', 'reported')
                ORDER BY
                    CASE status
                        WHEN 'playing' THEN 0
                        WHEN 'pending' THEN 1
                        WHEN 'waiting' THEN 1
                        WHEN 'reported' THEN 2
                        ELSE 3
                    END,
                    round_number ASC,
                    table_number ASC,
                    id ASC
                LIMIT 1
                """,
                (tournament_id, player_id, player_id),
            )
            if row is not None:
                swiss_match = dict(row)
        except Exception as error:
            LOGGER.debug("Recherche match suisse impossible : %s", error)

        candidates: list[tuple[str, dict[str, Any]]] = []
        if bracket_match is not None:
            candidates.append(("bracket", bracket_match))
        if swiss_match is not None:
            candidates.append(("swiss", swiss_match))

        if not candidates:
            return None

        status_priority = {
            "playing": 0,
            "waiting": 1,
            "pending": 1,
            "reported": 2,
        }

        candidates.sort(
            key=lambda item: (
                status_priority.get(str(item[1].get("status")), 9),
                int(item[1].get("round_number") or 0),
                int(item[1].get("position_number") or 0),
            )
        )
        return candidates[0]

    async def open_result_modal(
        self,
        interaction: discord.Interaction,
    ) -> None:
        try:
            tournament = await self.current_tournament(interaction)
        except ValueError as error:
            await safe_ephemeral_send(interaction, content=f"❌ {error}")
            return

        match_data = await self._find_player_match(
            tournament_id=int(tournament.id),
            player_id=str(interaction.user.id),
        )

        if match_data is None:
            await safe_ephemeral_send(
                interaction,
                content=(
                    "✅ Aucun match jouable en attente n'a été trouvé pour toi "
                    "dans le tournoi sélectionné."
                ),
            )
            return

        match_kind, match = match_data
        match_center = self.bot.get_cog("MatchCenterCog")

        if match_center is None:
            await safe_ephemeral_send(
                interaction,
                content=(
                    "❌ Le centre de match n'est pas chargé. "
                    "Utilise temporairement `/result`."
                ),
            )
            return

        ensure_access = getattr(
            match_center,
            "ensure_participant_or_staff",
            None,
        )
        if ensure_access is not None:
            allowed = await ensure_access(
                interaction,
                match_kind,
                int(match["id"]),
            )
            if not allowed:
                return

        await interaction.response.send_modal(
            HubQuickResultModal(
                match_center=match_center,
                match_kind=match_kind,
                match_id=int(match["id"]),
                player1_name=str(match.get("player1_name") or "Joueur 1"),
                player2_name=str(match.get("player2_name") or "Joueur 2"),
            )
        )

    # ==========================================================
    # CLASSEMENT, RÈGLEMENT ET SITE
    # ==========================================================

    async def open_ranking(self, interaction: discord.Interaction) -> None:
        try:
            tournament = await self.current_tournament(interaction)
        except ValueError as error:
            await safe_ephemeral_send(interaction, content=f"❌ {error}")
            return

        swiss_settings = None
        get_swiss_settings = getattr(self.db, "get_swiss_settings", None)
        if get_swiss_settings is not None:
            try:
                swiss_settings = await get_swiss_settings(int(tournament.id))
            except Exception:
                swiss_settings = None

        if swiss_settings is not None:
            await self.invoke_public_command(
                interaction,
                "swiss_standings",
            )
            return

        if isinstance(
            self.bot.tree.get_command("leaderboard"),
            app_commands.Command,
        ):
            await self.invoke_public_command(
                interaction,
                "leaderboard",
            )
            return

        await safe_ephemeral_send(
            interaction,
            embed=discord.Embed(
                title="🏆 Classement du tournoi",
                description=(
                    "Ce tournoi n'utilise pas actuellement de classement suisse.\n\n"
                    "En élimination directe, la progression se consulte avec "
                    "**Bracket** et les performances individuelles avec **Mon profil**."
                ),
                colour=discord.Colour.gold(),
            ),
        )

    async def open_rules(self, interaction: discord.Interaction) -> None:
        if isinstance(
            self.bot.tree.get_command("rules"),
            app_commands.Command,
        ):
            await self.invoke_public_command(interaction, "rules")
            return

        embed = discord.Embed(
            title="📜 Règlement essentiel Hamtaro",
            description="Rappels principaux pour participer correctement.",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(
            name="1. Inscription",
            value=(
                "Ton inscription confirme ta disponibilité. "
                "Aucun check-in supplémentaire n'est nécessaire."
            ),
            inline=False,
        )
        embed.add_field(
            name="2. Nom du deck",
            value=(
                "La première lettre de chaque mot doit être en majuscule : "
                "`Blue Eyes` est correct, `blUe eYes` ne l'est pas."
            ),
            inline=False,
        )
        embed.add_field(
            name="3. Match et résultat",
            value=(
                "Utilise le fil de ton match pour contacter ton adversaire, "
                "puis déclare le score exact. Le staff valide le résultat final."
            ),
            inline=False,
        )
        embed.add_field(
            name="4. Formats",
            value=(
                "Le Double Loss et la limite de temps suisse ne s'appliquent "
                "pas aux tournois à élimination directe."
            ),
            inline=False,
        )
        embed.set_footer(text="Consulte le règlement complet du serveur pour tous les détails.")
        await safe_ephemeral_send(interaction, embed=embed)

    async def open_website(self, interaction: discord.Interaction) -> None:
        """Affiche immédiatement le lien du site sans relancer une commande slash."""

        website_url = os.getenv(
            "WEBSITE_BASE_URL",
            DEFAULT_WEBSITE_URL,
        ).strip().rstrip("/")

        if not website_url.startswith(("http://", "https://")):
            LOGGER.error(
                "WEBSITE_BASE_URL invalide : %r",
                website_url,
            )
            await safe_ephemeral_send(
                interaction,
                content=(
                    "❌ L'adresse du site Hamtaro est invalide. "
                    "Vérifie `WEBSITE_BASE_URL` dans Railway."
                ),
            )
            return

        embed = discord.Embed(
            title="🌐 Site public Hamtaro",
            description=(
                "Consulte les tournois, les résultats, les profils, "
                "les archives et les brackets."
            ),
            url=website_url,
            colour=discord.Colour.gold(),
        )

        if self.bot.user is not None:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        embed.set_footer(
            text="Hamtaro • Le bot officiel de Jjetgames du serveur Fun Row"
        )

        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="Ouvrir le site Hamtaro",
                emoji="🌐",
                style=discord.ButtonStyle.link,
                url=website_url,
            )
        )

        # Aucune base de données ni requête HTTP avant cette réponse.
        await safe_ephemeral_send(
            interaction,
            embed=embed,
            view=view,
        )

    # ==========================================================
    # COMMANDE
    # ==========================================================

    @app_commands.command(
        name="hamtaro",
        description="Ouvrir le centre de contrôle joueur Hamtaro",
    )
    async def hamtaro(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        embed = await self.build_home_embed(interaction)
        view = HamtaroHubView(
            cog=self,
            requester_id=interaction.user.id,
        )

        message = await interaction.followup.send(
            embed=embed,
            view=view,
            ephemeral=True,
            wait=True,
        )
        view.message = message


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HamtaroHubCog(bot))
