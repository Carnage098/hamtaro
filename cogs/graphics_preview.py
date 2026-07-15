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
    """Tournoi fictif utilisé uniquement par /preview_bracket."""

    id: int
    name: str
    format: str
    status: str
    date: str
    organizer_name: str
    duration: str


@dataclass(slots=True)
class PreviewParticipant:
    """Participant fictif utilisé pour construire le bracket."""

    discord_id: str
    name: str
    seed: int
    deck: str


@dataclass(slots=True)
class PreviewMatch:
    """Match fictif compatible avec BracketImageService."""

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
    Commande temporaire de prévisualisation des images Hamtaro.

    Cette commande ne lit ni ne modifie les tournois réels de la base
    de données. Elle fabrique uniquement un bracket fictif en mémoire.
    """

    SUPPORTED_PLAYER_COUNTS: Final[frozenset[int]] = frozenset(
        {2, 4, 8, 16, 32, 64, 128}
    )

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
    )

    DISCORD_DEFAULT_AVATAR_COUNT: Final[int] = 6

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.renderer = BracketImageService(bot.db)

    # ==========================================================
    # PARTICIPANTS ET SEEDS
    # ==========================================================

    @staticmethod
    def _seed_order(player_count: int) -> list[int]:
        """
        Produit un ordre de seeds adapté à l'élimination directe.

        Les seeds 1 et 2 sont placés dans les deux moitiés opposées afin
        qu'ils ne puissent se rencontrer qu'en finale.
        """

        if player_count < 2 or player_count & (player_count - 1):
            raise ValueError(
                "Le nombre de joueurs doit être une puissance de deux."
            )

        order = [1, 2]
        current_size = 2

        while current_size < player_count:
            current_size *= 2
            expanded: list[int] = []

            for seed in order:
                expanded.extend((seed, current_size + 1 - seed))

            order = expanded

        return order

    def _participant_for_seed(self, seed: int) -> PreviewParticipant:
        index = seed - 1

        name = (
            self.PLAYER_NAMES[index]
            if index < len(self.PLAYER_NAMES)
            else f"Joueur {seed}"
        )
        deck = self.DECKS[index % len(self.DECKS)]

        return PreviewParticipant(
            discord_id=str(900_000 + seed),
            name=name,
            seed=seed,
            deck=deck,
        )

    def _build_participants(
        self,
        player_count: int,
    ) -> list[PreviewParticipant]:
        return [
            self._participant_for_seed(seed)
            for seed in self._seed_order(player_count)
        ]

    def _build_default_avatar_urls(
        self,
        player_count: int,
    ) -> dict[str, str]:
        """
        Associe un avatar Discord par défaut à chaque joueur fictif.

        Les previews affichent ainsi de véritables portraits ronds au lieu
        d'un simple bloc vide, sans utiliser les membres réels du serveur.
        """

        avatar_urls: dict[str, str] = {}

        for seed in range(1, player_count + 1):
            discord_id = str(900_000 + seed)
            avatar_index = (seed - 1) % self.DISCORD_DEFAULT_AVATAR_COUNT
            avatar_urls[discord_id] = (
                "https://cdn.discordapp.com/embed/avatars/"
                f"{avatar_index}.png"
            )

        return avatar_urls

    # ==========================================================
    # CONSTRUCTION DU BRACKET
    # ==========================================================

    @staticmethod
    def _winner_between(
        player1: PreviewParticipant,
        player2: PreviewParticipant,
    ) -> PreviewParticipant:
        """Le meilleur seed gagne le match fictif."""

        return player1 if player1.seed < player2.seed else player2

    @staticmethod
    def _completed_score(
        winner_slot: int,
        round_number: int,
        match_index: int,
        *,
        is_final: bool,
    ) -> tuple[int, int]:
        """Crée des scores variés mais cohérents pour la maquette."""

        if is_final:
            return (3, 2) if winner_slot == 1 else (2, 3)

        loser_score = 0 if (round_number + match_index) % 3 == 0 else 1
        return (
            (2, loser_score)
            if winner_slot == 1
            else (loser_score, 2)
        )

    def _build_bracket(
        self,
        player_count: int,
        final_mode: bool,
    ) -> dict[int, list[PreviewMatch]]:
        """
        Construit un bracket complet avec seeds, decks et progression.

        En mode actif, les tours précédents sont terminés et la finale reste
        en cours. En mode final, la finale est également terminée et le
        champion peut être affiché par BracketImageService.
        """

        if player_count not in self.SUPPORTED_PLAYER_COUNTS:
            raise ValueError(
                "Le preview prend en charge 2, 4, 8, 16, 32, 64 "
                "ou 128 joueurs."
            )

        total_rounds = int(math.log2(player_count))
        participants = self._build_participants(player_count)
        bracket: dict[int, list[PreviewMatch]] = {}

        next_match_id = 1

        for round_number in range(total_rounds, 0, -1):
            round_matches: list[PreviewMatch] = []
            winners: list[PreviewParticipant] = []
            match_count = len(participants) // 2

            for match_index in range(match_count):
                player1 = participants[match_index * 2]
                player2 = participants[match_index * 2 + 1]
                winner = self._winner_between(player1, player2)
                winner_slot = (
                    1
                    if winner.discord_id == player1.discord_id
                    else 2
                )

                is_final = round_number == 1
                is_completed = final_mode or not is_final

                if is_completed:
                    player1_score, player2_score = self._completed_score(
                        winner_slot,
                        round_number,
                        match_index,
                        is_final=is_final,
                    )
                    status = "completed"
                    winner_id: str | None = winner.discord_id
                    winner_name: str | None = winner.name
                else:
                    player1_score = 0
                    player2_score = 0
                    status = "playing"
                    winner_id = None
                    winner_name = None

                round_matches.append(
                    PreviewMatch(
                        id=next_match_id,
                        tournament_id=28,
                        round=round_number,
                        match_number=match_index + 1,
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
                )

                # Les finalistes doivent être connus même lorsque la finale
                # est encore en cours, afin de construire la dernière carte.
                winners.append(winner)
                next_match_id += 1

            bracket[round_number] = round_matches
            participants = winners

        return bracket

    # ==========================================================
    # OUTILS DE PRÉSENTATION
    # ==========================================================

    @staticmethod
    def _preview_date() -> str:
        """Retourne une date compacte et indépendante de la locale système."""

        return datetime.now().strftime("%d/%m/%Y")

    # ==========================================================
    # COMMANDE TEMPORAIRE
    # ==========================================================

    @app_commands.command(
        name="preview_bracket",
        description="Prévisualiser le nouveau bracket graphique Hamtaro.",
    )
    @app_commands.describe(
        joueurs="Nombre de joueurs fictifs du bracket.",
        final="Afficher le tournoi terminé avec la carte du champion.",
        avatars="Afficher les avatars Discord fictifs dans les cases.",
    )
    @app_commands.choices(
        joueurs=[
            app_commands.Choice(name="2 joueurs", value=2),
            app_commands.Choice(name="4 joueurs", value=4),
            app_commands.Choice(name="8 joueurs", value=8),
            app_commands.Choice(name="16 joueurs", value=16),
            app_commands.Choice(name="32 joueurs", value=32),
            app_commands.Choice(
                name="64 joueurs — format de la maquette",
                value=64,
            ),
            app_commands.Choice(name="128 joueurs", value=128),
        ]
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def preview_bracket(
        self,
        interaction: discord.Interaction,
        joueurs: app_commands.Choice[int],
        final: bool = False,
        avatars: bool = True,
    ) -> None:
        """Génère un aperçu sans toucher aux tournois réels."""

        permissions = getattr(
            interaction.user,
            "guild_permissions",
            None,
        )

        if permissions is None or not permissions.manage_guild:
            await interaction.response.send_message(
                "❌ Tu dois avoir la permission **Gérer le serveur** "
                "pour utiliser cette commande temporaire.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            thinking=True,
            ephemeral=True,
        )

        player_count = joueurs.value

        tournament = PreviewTournament(
            id=28,
            name="HAMTARO CUP",
            format="EDISON",
            status="finished" if final else "active",
            date=self._preview_date(),
            organizer_name="HAMTARO BOT",
            duration="15H42",
        )

        try:
            bracket = self._build_bracket(
                player_count=player_count,
                final_mode=final,
            )

            avatar_urls = (
                self._build_default_avatar_urls(player_count)
                if avatars
                else None
            )

            image = await self.renderer.render(
                tournament=tournament,
                bracket=bracket,
                avatar_urls=avatar_urls,
                final_mode=final,
            )
            image.seek(0)

        except Exception as error:
            LOGGER.exception(
                "Impossible de générer le preview graphique Hamtaro."
            )

            await interaction.followup.send(
                (
                    "❌ Impossible de générer l'aperçu graphique.\n\n"
                    f"Erreur : `{type(error).__name__}: {error}`"
                ),
                ephemeral=True,
            )
            return

        mode_name = "final" if final else "actif"
        filename = (
            f"hamtaro_preview_{player_count}_joueurs_{mode_name}.png"
        )

        discord_file = discord.File(
            fp=image,
            filename=filename,
        )

        embed = discord.Embed(
            title="🎨 Prévisualisation du bracket Hamtaro",
            description=(
                f"Mode : **{mode_name}**\n"
                f"Joueurs fictifs : **{player_count}**\n"
                f"Avatars : **{'activés' if avatars else 'désactivés'}**\n"
                "Tournoi de démonstration : **Hamtaro Cup #28**\n\n"
                "Aucune donnée réelle n'a été lue ou modifiée."
            ),
            color=(
                discord.Color.gold()
                if final
                else discord.Color.blue()
            ),
        )
        embed.set_image(url=f"attachment://{filename}")
        embed.set_footer(
            text="Commande temporaire — /preview_bracket"
        )

        await interaction.followup.send(
            embed=embed,
            file=discord_file,
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GraphicsPreviewCog(bot))
