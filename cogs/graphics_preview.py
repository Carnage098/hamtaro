from __future__ import annotations

import logging
import math

from dataclasses import dataclass
from datetime import datetime
from typing import Final

import discord

from discord import app_commands
from discord.ext import commands

from services.bracket_image_service import BracketImageService


LOGGER = logging.getLogger(__name__)


# ==========================================================
# DONNÉES FICTIVES
# ==========================================================


@dataclass(slots=True)
class PreviewTournament:
    """
    Tournoi fictif utilisé uniquement par /preview_bracket.
    """

    id: int
    name: str
    format: str
    status: str
    date: str
    organizer_name: str
    duration: str


@dataclass(slots=True)
class PreviewParticipant:
    """
    Participant utilisé pour construire le bracket de test.

    Le participant peut représenter :

    - un vrai membre du serveur Discord ;
    - un joueur fictif lorsque le serveur ne contient pas
      assez de membres.
    """

    discord_id: str
    name: str
    seed: int
    deck: str
    avatar_url: str | None = None


@dataclass(slots=True)
class PreviewMatch:
    """
    Match fictif compatible avec BracketImageService.
    """

    id: int
    tournament_id: int
    round: int
    match_number: int
    bracket_position: int

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

    player1_seed: int | None = None
    player2_seed: int | None = None

    player1_deck: str | None = None
    player2_deck: str | None = None

    next_match_id: int | None = None
    next_slot: int | None = None


# ==========================================================
# COG
# ==========================================================


class GraphicsPreviewCog(commands.Cog):
    """
    Commande temporaire de prévisualisation du renderer Hamtaro.

    Cette commande :

    - ne lit aucun tournoi réel ;
    - ne crée aucun tournoi ;
    - ne modifie pas la base de données ;
    - génère uniquement une image de démonstration.
    """

    PLAYER_NAMES: Final[tuple[str, ...]] = (
        "Roro",
        "Yusei",
        "Jaden",
        "Jack Atlas",
        "Yugi",
        "Kaiba",
        "Akiza",
        "Crow Hogan",
        "Marik",
        "Atem",
        "Joey",
        "Tristan",
        "Judai Yuki",
        "Johan",
        "Aster",
        "Chazz",
        "Kaito",
        "Yuma",
        "Shark",
        "Rio",
        "Pegasus",
        "Bakura",
        "Mai",
        "Mokuba",
        "Leo",
        "Luna",
        "Syrus",
        "Zane",
        "Alexis",
        "Bastion",
        "Shadi",
        "Ishizu",
        "Rex",
        "Weevil",
        "Misty",
        "Kiryū",
        "Bruno",
        "Kite",
        "Vector",
        "Astral",
        "Quattro",
        "Trey",
        "Quinton",
        "Anna",
        "Aoi",
        "Playmaker",
        "Soulburner",
        "Revolver",
        "Blue Angel",
        "Go Onizuka",
        "Yuya",
        "Yuto",
        "Yugo",
        "Yuri",
        "Reiji",
        "Shun",
        "Rin",
        "Ruri",
        "Serena",
        "Sawatori",
        "Gongenzaka",
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
        "Prince Bo",
        "Pepper",
        "Omar",
        "Sabu",
        "Roberto",
        "Laura",
        "Kana",
        "Maria",
        "Elder Ham",
        "Joueur Alpha",
        "Joueur Beta",
        "Joueur Gamma",
        "Joueur Delta",
        "Joueur Epsilon",
        "Joueur Omega",
    )

    DECKS: Final[tuple[str, ...]] = (
        "Artmage",
        "Toon",
        "K9",
        "Fiendsmith",
        "Notes Elfiques",
        "Blue-Eyes",
        "Branded",
        "Maliss",
        "Yummy",
        "Mitsurugi",
        "Dracotail",
        "Ryzeal",
        "Orcust",
        "Labrynth",
        "Memento",
        "Tenpai",
        "Chimera",
        "Sky Striker",
        "HERO",
        "Dark Magician",
        "Dragon Ruler",
        "Blackwing",
        "Synchron",
        "Cyber Dragon",
        "Traptrix",
        "Fire King",
        "Snake-Eye",
        "Vanquish Soul",
        "Centur-Ion",
        "Purrely",
        "Runick",
        "Eldlich",
    )

    SUPPORTED_PLAYER_COUNTS: Final[set[int]] = {
        2,
        4,
        8,
        16,
        32,
        64,
        128,
    }

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:
        self.bot = bot

        self.renderer = BracketImageService(
            getattr(
                bot,
                "db",
                None,
            )
        )

    # ==========================================================
    # DATE DE LA MAQUETTE
    # ==========================================================

    @staticmethod
    def _today_label() -> str:
        """
        Retourne la date actuelle en français.
        """

        months = {
            1: "JANVIER",
            2: "FÉVRIER",
            3: "MARS",
            4: "AVRIL",
            5: "MAI",
            6: "JUIN",
            7: "JUILLET",
            8: "AOÛT",
            9: "SEPTEMBRE",
            10: "OCTOBRE",
            11: "NOVEMBRE",
            12: "DÉCEMBRE",
        }

        today = datetime.now()

        return (
            f"{today.day} "
            f"{months[today.month]} "
            f"{today.year}"
        )

    # ==========================================================
    # MEMBRES DU SERVEUR
    # ==========================================================

    @staticmethod
    def _member_avatar_url(
        member: discord.Member,
    ) -> str | None:
        """
        Retourne l'URL de l'avatar ou de l'avatar Discord par défaut.
        """

        try:
            return str(
                member.display_avatar.url
            )

        except (
            AttributeError,
            TypeError,
        ):
            return None

    @staticmethod
    def _member_name(
        member: discord.Member,
    ) -> str:
        """
        Retourne le nom affiché du membre.
        """

        name = (
            member.display_name
            or member.name
            or f"Joueur {member.id}"
        )

        return name.strip() or f"Joueur {member.id}"

    def _guild_member_pool(
        self,
        interaction: discord.Interaction,
        enabled: bool,
    ) -> list[discord.Member]:
        """
        Récupère les membres pouvant être utilisés dans la maquette.

        L'utilisateur ayant lancé la commande est placé en premier,
        afin qu'il apparaisse généralement comme seed numéro 1.
        """

        if not enabled:
            return []

        guild = interaction.guild

        if guild is None:
            return []

        members: list[discord.Member] = []
        seen_ids: set[int] = set()

        command_user = interaction.user

        if (
            isinstance(
                command_user,
                discord.Member,
            )
            and not command_user.bot
        ):
            members.append(
                command_user
            )

            seen_ids.add(
                command_user.id
            )

        remaining_members = sorted(
            (
                member
                for member in guild.members
                if (
                    not member.bot
                    and member.id not in seen_ids
                )
            ),
            key=lambda member: (
                self._member_name(
                    member
                ).casefold(),
                member.id,
            ),
        )

        members.extend(
            remaining_members
        )

        return members

    # ==========================================================
    # PARTICIPANTS ET SEEDS
    # ==========================================================

    @staticmethod
    def _seed_order(
        player_count: int,
    ) -> list[int]:
        """
        Produit un ordre de seeds adapté à l'élimination directe.

        Les meilleurs seeds sont placés dans des zones opposées
        du bracket et ne peuvent se rencontrer qu'aux derniers tours.
        """

        if (
            player_count < 2
            or player_count
            & (
                player_count - 1
            )
        ):
            raise ValueError(
                "Le nombre de joueurs doit être "
                "une puissance de deux."
            )

        order = [
            1,
            2,
        ]

        current_size = 2

        while current_size < player_count:
            current_size *= 2

            expanded: list[int] = []

            for seed in order:
                expanded.extend(
                    (
                        seed,
                        current_size
                        + 1
                        - seed,
                    )
                )

            order = expanded

        return order

    def _participant_for_seed(
        self,
        seed: int,
        members: list[discord.Member],
    ) -> PreviewParticipant:
        """
        Crée un participant pour un seed précis.

        Un vrai membre Discord est utilisé lorsqu'il existe.
        Sinon, un joueur fictif est généré.
        """

        index = seed - 1

        deck = self.DECKS[
            index
            % len(
                self.DECKS
            )
        ]

        if index < len(
            members
        ):
            member = members[
                index
            ]

            return PreviewParticipant(
                discord_id=str(
                    member.id
                ),
                name=self._member_name(
                    member
                ),
                seed=seed,
                deck=deck,
                avatar_url=self._member_avatar_url(
                    member
                ),
            )

        fictional_index = (
            index
            - len(
                members
            )
        )

        if fictional_index < len(
            self.PLAYER_NAMES
        ):
            name = self.PLAYER_NAMES[
                fictional_index
            ]

        else:
            name = f"Joueur {seed}"

        return PreviewParticipant(
            discord_id=str(
                900_000
                + seed
            ),
            name=name,
            seed=seed,
            deck=deck,
            avatar_url=None,
        )

    def _build_participants(
        self,
        player_count: int,
        members: list[discord.Member],
    ) -> list[PreviewParticipant]:
        """
        Construit les participants dans l'ordre du bracket.
        """

        participants_by_seed = {
            seed: self._participant_for_seed(
                seed,
                members,
            )
            for seed in range(
                1,
                player_count + 1,
            )
        }

        return [
            participants_by_seed[
                seed
            ]
            for seed in self._seed_order(
                player_count
            )
        ]

    @staticmethod
    def _avatar_url_map(
        participants: list[PreviewParticipant],
    ) -> dict[str, str]:
        """
        Construit la table utilisée par BracketImageService
        pour télécharger les avatars Discord.
        """

        return {
            participant.discord_id: participant.avatar_url
            for participant in participants
            if participant.avatar_url
        }

    # ==========================================================
    # CONSTRUCTION DU BRACKET
    # ==========================================================

    @staticmethod
    def _winner_between(
        player1: PreviewParticipant,
        player2: PreviewParticipant,
    ) -> PreviewParticipant:
        """
        Le meilleur seed remporte le match fictif.
        """

        if player1.seed < player2.seed:
            return player1

        return player2

    @staticmethod
    def _completed_score(
        winner_slot: int,
        round_number: int,
        match_index: int,
        *,
        is_final: bool,
    ) -> tuple[int, int]:
        """
        Génère des scores variés mais cohérents.
        """

        if is_final:
            if winner_slot == 1:
                return (
                    3,
                    2,
                )

            return (
                2,
                3,
            )

        loser_score = (
            0
            if (
                round_number
                + match_index
            )
            % 3
            == 0
            else 1
        )

        if winner_slot == 1:
            return (
                2,
                loser_score,
            )

        return (
            loser_score,
            2,
        )

    def _build_bracket(
        self,
        player_count: int,
        final_mode: bool,
        participants: list[PreviewParticipant],
    ) -> dict[int, list[PreviewMatch]]:
        """
        Construit toutes les rondes du bracket de démonstration.

        En mode actif :

        - les tours précédents sont terminés ;
        - la finale est encore en cours.

        En mode final :

        - tous les matchs sont terminés ;
        - le champion est connu.
        """

        if player_count not in self.SUPPORTED_PLAYER_COUNTS:
            raise ValueError(
                "Le preview prend en charge 2, 4, 8, 16, "
                "32, 64 ou 128 joueurs."
            )

        if len(
            participants
        ) != player_count:
            raise ValueError(
                "Le nombre de participants fictifs "
                "ne correspond pas au bracket."
            )

        total_rounds = int(
            math.log2(
                player_count
            )
        )

        current_participants = list(
            participants
        )

        bracket: dict[
            int,
            list[PreviewMatch],
        ] = {}

        next_match_id = 1

        for round_number in range(
            total_rounds,
            0,
            -1,
        ):
            round_matches: list[
                PreviewMatch
            ] = []

            winners: list[
                PreviewParticipant
            ] = []

            match_count = (
                len(
                    current_participants
                )
                // 2
            )

            for match_index in range(
                match_count
            ):
                player1 = current_participants[
                    match_index * 2
                ]

                player2 = current_participants[
                    match_index * 2 + 1
                ]

                winner = self._winner_between(
                    player1,
                    player2,
                )

                winner_slot = (
                    1
                    if winner.discord_id
                    == player1.discord_id
                    else 2
                )

                is_final = (
                    round_number == 1
                )

                is_completed = (
                    final_mode
                    or not is_final
                )

                if is_completed:
                    (
                        player1_score,
                        player2_score,
                    ) = self._completed_score(
                        winner_slot,
                        round_number,
                        match_index,
                        is_final=is_final,
                    )

                    status = "completed"
                    winner_id: str | None = (
                        winner.discord_id
                    )
                    winner_name: str | None = (
                        winner.name
                    )

                else:
                    player1_score = 0
                    player2_score = 0
                    status = "playing"
                    winner_id = None
                    winner_name = None

                match = PreviewMatch(
                    id=next_match_id,
                    tournament_id=28,
                    round=round_number,
                    match_number=(
                        match_index + 1
                    ),
                    bracket_position=match_index,
                    player1_id=player1.discord_id,
                    player2_id=player2.discord_id,
                    player1_name=player1.name,
                    player2_name=player2.name,
                    player1_score=player1_score,
                    player2_score=player2_score,
                    winner_id=winner_id,
                    winner_name=winner_name,
                    status=status,
                    is_bye=False,
                    player1_seed=player1.seed,
                    player2_seed=player2.seed,
                    player1_deck=player1.deck,
                    player2_deck=player2.deck,
                )

                round_matches.append(
                    match
                )

                # Le vainqueur est propagé pour construire
                # le tour suivant de la maquette.
                winners.append(
                    winner
                )

                next_match_id += 1

            bracket[
                round_number
            ] = round_matches

            current_participants = (
                winners
            )

        return bracket

    # ==========================================================
    # COMMANDE TEMPORAIRE
    # ==========================================================

    @app_commands.command(
        name="preview_bracket",
        description=(
            "Prévisualiser le nouveau bracket graphique Hamtaro."
        ),
    )
    @app_commands.describe(
        joueurs=(
            "Nombre de joueurs fictifs dans le bracket."
        ),
        final=(
            "Afficher le tournoi terminé avec son champion."
        ),
        avatars_reels=(
            "Utiliser les avatars des membres du serveur."
        ),
    )
    @app_commands.choices(
        joueurs=[
            app_commands.Choice(
                name="2 joueurs",
                value=2,
            ),
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
            app_commands.Choice(
                name="64 joueurs — maquette finale",
                value=64,
            ),
            app_commands.Choice(
                name="128 joueurs",
                value=128,
            ),
        ]
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def preview_bracket(
        self,
        interaction: discord.Interaction,
        joueurs: app_commands.Choice[int],
        final: bool = False,
        avatars_reels: bool = True,
    ) -> None:
        """
        Génère une image sans toucher aux tournois réels.
        """

        permissions = getattr(
            interaction.user,
            "guild_permissions",
            None,
        )

        if (
            permissions is None
            or not permissions.manage_guild
        ):
            await interaction.response.send_message(
                (
                    "❌ Tu dois avoir la permission "
                    "**Gérer le serveur** pour utiliser "
                    "cette commande temporaire."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            thinking=True,
            ephemeral=True,
        )

        player_count = joueurs.value

        member_pool = self._guild_member_pool(
            interaction,
            avatars_reels,
        )

        participants = self._build_participants(
            player_count,
            member_pool,
        )

        avatar_urls = self._avatar_url_map(
            participants
        )

        organizer_name = getattr(
            interaction.user,
            "display_name",
            interaction.user.name,
        )

        tournament = PreviewTournament(
            id=28,
            name="HAMTARO CUP",
            format="EDISON",
            status=(
                "finished"
                if final
                else "active"
            ),
            date=self._today_label(),
            organizer_name=organizer_name,
            duration=(
                "15H42"
                if final
                else "EN COURS"
            ),
        )

        try:
            bracket = self._build_bracket(
                player_count=player_count,
                final_mode=final,
                participants=participants,
            )

            image = await self.renderer.render(
                tournament=tournament,
                bracket=bracket,
                avatar_urls=avatar_urls,
                final_mode=final,
            )

            image.seek(
                0
            )

        except Exception as error:
            LOGGER.exception(
                "Impossible de générer le preview "
                "graphique Hamtaro."
            )

            await interaction.followup.send(
                (
                    "❌ Impossible de générer "
                    "l'aperçu graphique.\n\n"
                    f"Erreur : "
                    f"`{type(error).__name__}: {error}`"
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

        real_avatar_count = len(
            avatar_urls
        )

        embed = discord.Embed(
            title=(
                "🎨 Prévisualisation du "
                "bracket Hamtaro"
            ),
            description=(
                f"Mode : **{mode_name}**\n"
                f"Joueurs : **{player_count}**\n"
                f"Avatars Discord chargés : "
                f"**{real_avatar_count}**\n"
                f"Tournoi de démonstration : "
                f"**Hamtaro Cup #28**\n\n"
                "Aucune donnée réelle de tournoi "
                "n'a été lue ou modifiée."
            ),
            color=(
                discord.Color.gold()
                if final
                else discord.Color.blue()
            ),
        )

        embed.set_image(
            url=f"attachment://{filename}"
        )

        embed.set_footer(
            text=(
                "Commande temporaire — "
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
) -> None:
    await bot.add_cog(
        GraphicsPreviewCog(
            bot
        )
    )
