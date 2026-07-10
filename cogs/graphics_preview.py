from __future__ import annotations

import math

from dataclasses import dataclass

import discord

from discord import app_commands
from discord.ext import commands

from services.bracket_image_service import BracketImageService
from utils.permissions import staff_only


# ==========================================================
# DONNÉES TEMPORAIRES DE PRÉVISUALISATION
# ==========================================================

@dataclass(slots=True)
class PreviewTournament:
    """
    Faux tournoi utilisé uniquement pour tester le rendu graphique.
    """

    id: int
    name: str
    format: str
    status: str


@dataclass(slots=True)
class PreviewMatch:
    """
    Faux match compatible avec BracketImageService.
    """

    id: int
    tournament_id: int

    round: int
    match_number: int
    bracket_position: int

    next_match_id: int | None
    next_slot: int | None

    player1_id: str | None
    player2_id: str | None

    player1_name: str | None
    player2_name: str | None

    player1_score: int
    player2_score: int

    winner_id: str | None
    winner_name: str | None

    status: str
    is_bye: bool = False


# ==========================================================
# COG
# ==========================================================

class GraphicsPreviewCog(commands.Cog):
    """
    Commandes temporaires permettant de tester les images Hamtaro.

    Cette extension pourra être supprimée lorsque les rendus
    graphiques seront définitivement validés.
    """

    PLAYER_NAMES = [
        "Hamtaro",
        "Bijou",
        "Boss",
        "Pashmina",
        "Oxnard",
        "Sandy",
        "Cappy",
        "Howdy",
        "Dexter",
        "Maxwell",
        "Penelope",
        "Stan",
        "Jingle",
        "Panda",
        "Snoozer",
        "Sparkle",
        "Joueur Toon",
        "Joueur K9",
        "Joueur Artmage",
        "Joueur Fiendsmith",
        "Joueur Maliss",
        "Joueur Yummy",
        "Joueur Mitsurugi",
        "Joueur Dracotail",
        "Joueur Blue-Eyes",
        "Joueur Branded",
        "Joueur Ryzeal",
        "Joueur Orcust",
        "Joueur Labrynth",
        "Joueur Memento",
        "Joueur Tenpai",
        "Joueur Chimera",
    ]

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.db = bot.db

        self.renderer = BracketImageService(
            self.db
        )

    # ==========================================================
    # CONSTRUCTION DES FAUX JOUEURS
    # ==========================================================

    def _build_players(
        self,
        player_count: int,
    ) -> list[tuple[str, str]]:
        """
        Construit les joueurs fictifs de l'aperçu.

        Chaque joueur possède :
        - un faux identifiant Discord ;
        - un nom d'affichage.
        """

        players: list[
            tuple[str, str]
        ] = []

        for index in range(
            player_count
        ):
            discord_id = str(
                100_000 + index
            )

            if index < len(
                self.PLAYER_NAMES
            ):
                player_name = (
                    self.PLAYER_NAMES[
                        index
                    ]
                )

            else:
                player_name = (
                    f"Joueur {index + 1}"
                )

            players.append(
                (
                    discord_id,
                    player_name,
                )
            )

        return players

    # ==========================================================
    # CONSTRUCTION DU FAUX BRACKET
    # ==========================================================

    def _build_bracket(
        self,
        player_count: int,
        final_mode: bool,
    ) -> dict[
        int,
        list[PreviewMatch],
    ]:
        """
        Génère un faux bracket cohérent.

        Exemple avec huit joueurs :

        - round 3 : quarts de finale ;
        - round 2 : demi-finales ;
        - round 1 : finale.

        En mode actif :
        - les anciens matchs sont terminés ;
        - la finale est en cours.

        En mode final :
        - tous les matchs sont terminés ;
        - le champion est affiché.
        """

        if player_count < 4:
            raise ValueError(
                "Le preview nécessite au moins quatre joueurs."
            )

        if player_count & (
            player_count - 1
        ):
            raise ValueError(
                "Le nombre de joueurs doit être une puissance de deux."
            )

        total_rounds = int(
            math.log2(
                player_count
            )
        )

        participants = self._build_players(
            player_count
        )

        bracket: dict[
            int,
            list[PreviewMatch],
        ] = {}

        match_id = 1

        for round_number in range(
            total_rounds,
            0,
            -1,
        ):
            round_matches: list[
                PreviewMatch
            ] = []

            next_participants: list[
                tuple[str, str]
            ] = []

            match_count = (
                len(participants)
                // 2
            )

            for match_index in range(
                match_count
            ):
                player1_id, player1_name = (
                    participants[
                        match_index * 2
                    ]
                )

                player2_id, player2_name = (
                    participants[
                        match_index * 2 + 1
                    ]
                )

                is_final = (
                    round_number == 1
                )

                match_completed = (
                    final_mode
                    or not is_final
                )

                if match_completed:
                    status = "completed"

                    player1_score = 2
                    player2_score = 1

                    winner_id = player1_id
                    winner_name = player1_name

                else:
                    status = "playing"

                    player1_score = 0
                    player2_score = 0

                    winner_id = None
                    winner_name = None

                if round_number > 1:
                    next_match_id = (
                        match_id
                        + match_count
                        + match_index
                        // 2
                    )

                    next_slot = (
                        1
                        if match_index % 2 == 0
                        else 2
                    )

                else:
                    next_match_id = None
                    next_slot = None

                match = PreviewMatch(
                    id=match_id,
                    tournament_id=9999,
                    round=round_number,
                    match_number=(
                        match_index + 1
                    ),
                    bracket_position=match_index,
                    next_match_id=next_match_id,
                    next_slot=next_slot,
                    player1_id=player1_id,
                    player2_id=player2_id,
                    player1_name=player1_name,
                    player2_name=player2_name,
                    player1_score=player1_score,
                    player2_score=player2_score,
                    winner_id=winner_id,
                    winner_name=winner_name,
                    status=status,
                    is_bye=False,
                )

                round_matches.append(
                    match
                )

                # Le premier joueur est utilisé comme vainqueur
                # fictif afin de construire le tour suivant.
                next_participants.append(
                    (
                        player1_id,
                        player1_name,
                    )
                )

                match_id += 1

            bracket[
                round_number
            ] = round_matches

            participants = (
                next_participants
            )

        return bracket

    # ==========================================================
    # COMMANDE TEMPORAIRE
    # ==========================================================

    @app_commands.command(
        name="preview_bracket",
        description="Tester temporairement le rendu graphique du bracket."
    )
    @app_commands.describe(
        joueurs="Nombre de joueurs fictifs à afficher.",
        final="Afficher le bracket actif ou le bracket final.",
    )
    @app_commands.choices(
        joueurs=[
            app_commands.Choice(
                name="4 joueurs",
                value=4,
            ),
            app_commands.Choice(
                name="8 joueurs",
                value=8,
            ),
            app_commands.Choice(
                name="16 joueurs",
                value=16,
            ),
            app_commands.Choice(
                name="32 joueurs",
                value=32,
            ),
        ]
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def preview_bracket(
        self,
        interaction: discord.Interaction,
        joueurs: app_commands.Choice[int],
        final: bool = False,
    ):
        """
        Génère une image sans utiliser les données réelles du serveur.
        """

        await interaction.response.defer(
            ephemeral=True
        )

        player_count = joueurs.value

        tournament = PreviewTournament(
            id=9999,
            name="Tournoi de démonstration Hamtaro",
            format="Format Actuel",
            status=(
                "finished"
                if final
                else "active"
            ),
        )

        try:
            bracket = self._build_bracket(
                player_count=player_count,
                final_mode=final,
            )

            image = await self.renderer.render(
                tournament=tournament,
                bracket=bracket,
                avatar_urls=None,
                final_mode=final,
            )

            image.seek(0)

        except Exception as error:
            await interaction.followup.send(
                (
                    "❌ Impossible de générer l'aperçu.\n\n"
                    f"Erreur : `{type(error).__name__}: {error}`"
                ),
                ephemeral=True,
            )

            return

        mode_name = (
            "final"
            if final
            else "actif"
        )

        filename = (
            f"hamtaro_preview_"
            f"{player_count}_joueurs_"
            f"{mode_name}.png"
        )

        discord_file = discord.File(
            fp=image,
            filename=filename,
        )

        embed = discord.Embed(
            title="🎨 Aperçu graphique Hamtaro",
            description=(
                f"Mode : **{mode_name}**\n"
                f"Joueurs fictifs : **{player_count}**\n\n"
                "Cette image n'utilise aucune donnée réelle "
                "et ne modifie aucun tournoi."
            ),
            color=(
                discord.Color.gold()
                if final
                else discord.Color.blurple()
            ),
        )

        embed.set_image(
            url=f"attachment://{filename}"
        )

        embed.set_footer(
            text=(
                "Commande temporaire de test — "
                "/preview_bracket"
            )
        )

        await interaction.followup.send(
            embed=embed,
            file=discord_file,
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        GraphicsPreviewCog(bot)
    )
