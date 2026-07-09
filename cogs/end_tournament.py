from __future__ import annotations

import io
import re
from collections import Counter
from typing import Optional

import aiosqlite
import discord
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from discord.ext import commands
from discord import app_commands

from utils.permissions import staff_only

try:
    from config import DATABASE
except ImportError:
    from database import DATABASE


class EndTournamentCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ==========================================================
    # OUTILS
    # ==========================================================

    def _guild_id(self, interaction: discord.Interaction) -> str:
        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(interaction.guild.id)

    def _clean_deck_text(self, deck: str) -> str:
        cleaned = deck.strip().lower()

        cleaned = cleaned.replace("’", "'")
        cleaned = cleaned.replace("é", "e")
        cleaned = cleaned.replace("è", "e")
        cleaned = cleaned.replace("ê", "e")
        cleaned = cleaned.replace("ë", "e")
        cleaned = cleaned.replace("à", "a")
        cleaned = cleaned.replace("â", "a")
        cleaned = cleaned.replace("ä", "a")
        cleaned = cleaned.replace("î", "i")
        cleaned = cleaned.replace("ï", "i")
        cleaned = cleaned.replace("ô", "o")
        cleaned = cleaned.replace("ö", "o")
        cleaned = cleaned.replace("ù", "u")
        cleaned = cleaned.replace("û", "u")
        cleaned = cleaned.replace("ü", "u")
        cleaned = cleaned.replace("ç", "c")

        cleaned = re.sub(r"[^a-z0-9+\-*/. ]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)

        return cleaned.strip()

    def _has_any(self, cleaned: str, words: list[str]) -> bool:
        return any(word in cleaned for word in words)

    def _normalize_deck_name(self, deck: Optional[str]) -> str:
        """
        Normalise les noms de decks pour le diagramme.
        Exemple :
        - k9 fiendsmith / K-9 Fiendsmith / Fiendsmith K9 -> K9 Fiendsmith
        - notes elfiques / elfnote / elf note -> Elfnote
        """

        if deck is None:
            return "Deck inconnu"

        cleaned = self._clean_deck_text(deck)

        if cleaned == "":
            return "Deck inconnu"

        # ======================================================
        # COMBOS / ENGINES MÉTA RÉCENTS
        # ======================================================

        has_k9 = self._has_any(cleaned, [
            "k9",
            "k-9",
            "k 9",
        ])

        has_fiendsmith = self._has_any(cleaned, [
            "fiendsmith",
            "fiend smith",
            "smith",
        ])

        has_artmage = self._has_any(cleaned, [
            "artmage",
            "art mage",
        ])

        has_yummy = self._has_any(cleaned, [
            "yummy",
        ])

        has_dracotail = self._has_any(cleaned, [
            "dracotail",
            "draco tail",
            "dragon tail",
            "dragontail",
        ])

        has_elfnote = self._has_any(cleaned, [
            "elfnote",
            "elf note",
            "notes elfiques",
            "note elfique",
            "elfique",
        ])

        has_branded = self._has_any(cleaned, [
            "branded",
            "albion",
            "albaz",
            "despia",
        ])

        has_vanquish_soul = self._has_any(cleaned, [
            "vanquish soul",
            "vsoul",
            "v soul",
            "vs ",
            " v s",
        ])

        has_punk = self._has_any(cleaned, [
            "p.u.n.k",
            "punk",
            "p u n k",
        ])

        has_live_twin = self._has_any(cleaned, [
            "live twin",
            "livetwin",
            "evil twin",
            "eviltwin",
        ])

        has_chimera = self._has_any(cleaned, [
            "chimera",
            "chimere",
        ])

        has_snake_eye = self._has_any(cleaned, [
            "snake eye",
            "snake-eye",
            "snake eyes",
            "snake-eyes",
        ])

        has_yubel = self._has_any(cleaned, [
            "yubel",
        ])

        has_orcust = self._has_any(cleaned, [
            "orcust",
            "orcuste",
        ])

        has_mitsurugi = self._has_any(cleaned, [
            "mitsurugi",
        ])

        has_ryzeal = self._has_any(cleaned, [
            "ryzeal",
            "ryzeol",
            "ryzeal",
            "ryzeal",
        ])

        if has_k9 and has_fiendsmith:
            return "K9 Fiendsmith"

        if has_k9 and has_artmage:
            return "Artmage K9"

        if has_k9 and has_vanquish_soul:
            return "K9 Vanquish Soul"

        if has_k9 and has_punk:
            return "K9 P.U.N.K."

        if has_fiendsmith and has_yummy:
            return "Fiendsmith Yummy"

        if has_fiendsmith and has_live_twin:
            return "Live Twin Fiendsmith"

        if has_fiendsmith and has_chimera:
            return "Chimera Fiendsmith"

        if has_fiendsmith and has_yubel:
            return "Yubel Fiendsmith"

        if has_fiendsmith and has_snake_eye:
            return "Snake-Eye Fiendsmith"

        if has_branded and has_dracotail:
            return "Branded Dracotail"

        if has_branded and has_elfnote:
            return "Branded Elfnote"

        if has_branded and has_fiendsmith:
            return "Branded Fiendsmith"

        if has_branded and has_orcust:
            return "Branded Orcust"

        if has_mitsurugi and has_fiendsmith:
            return "Mitsurugi Fiendsmith"

        if has_ryzeal and has_fiendsmith:
            return "Ryzeal Fiendsmith"

        if has_ryzeal and has_mitsurugi:
            return "Ryzeal Mitsurugi"

        # ======================================================
        # ARCHÉTYPES SEULS / ALIAS FRÉQUENTS
        # ======================================================

        aliases = {
            # Nouveaux / récents
            "k9": "K9",
            "k-9": "K9",
            "k 9": "K9",

            "artmage": "Artmage",
            "art mage": "Artmage",

            "fiendsmith": "Fiendsmith",
            "fiend smith": "Fiendsmith",

            "notes elfiques": "Elfnote",
            "note elfique": "Elfnote",
            "elfnote": "Elfnote",
            "elf note": "Elfnote",

            "yummy": "Yummy",

            "dracotail": "Dracotail",
            "draco tail": "Dracotail",
            "dragon tail": "Dracotail",
            "dragontail": "Dracotail",

            "maliss": "Maliss",
            "m∀lice": "Maliss",
            "malice": "Maliss",

            "mitsurugi": "Mitsurugi",

            "ryzeal": "Ryzeal",
            "ryzeol": "Ryzeal",

            "kewl tune": "Kewl Tune",
            "cool tune": "Kewl Tune",
            "killer tune": "Kewl Tune",

            "radiant typhoon": "Radiant Typhoon",
            "typhon radieux": "Radiant Typhoon",

            # Branded / Albaz
            "branded": "Branded",
            "despia": "Branded Despia",
            "branded despia": "Branded Despia",
            "albaz": "Branded",
            "fallen of albaz": "Branded",

            # Decks compétitifs connus
            "vanquish soul": "Vanquish Soul",
            "vs": "Vanquish Soul",

            "snake eye": "Snake-Eye",
            "snake-eye": "Snake-Eye",
            "snake eyes": "Snake-Eye",
            "snake-eyes": "Snake-Eye",

            "fire king": "Fire King",
            "fire kings": "Fire King",

            "azamina": "Azamina",
            "sinful spoils": "Sinful Spoils",

            "white forest": "White Forest",
            "foret blanche": "White Forest",

            "orcust": "Orcust",
            "orcuste": "Orcust",

            "memento": "Memento",
            "primite": "Primite",

            "voiceless voice": "Voiceless Voice",
            "sans voix": "Voiceless Voice",

            "lunalight": "Lunalight",
            "luna light": "Lunalight",

            "labrynth": "Labrynth",
            "labyrinth": "Labrynth",

            "purrely": "Purrely",
            "runick": "Runick",
            "spright": "Spright",

            "kashtira": "Kashtira",
            "tearlament": "Tearlaments",
            "tearlaments": "Tearlaments",

            "tenpai": "Tenpai Dragon",
            "tenpai dragon": "Tenpai Dragon",

            "sky striker": "Sky Striker",
            "sky striker ace": "Sky Striker",

            "rescue ace": "Rescue-ACE",
            "rescue-ace": "Rescue-ACE",
            "r ace": "Rescue-ACE",

            "centurion": "Centur-Ion",
            "centur-ion": "Centur-Ion",

            "goblin biker": "Goblin Biker",
            "gobelin biker": "Goblin Biker",

            "infernoid": "Infernoid",
            "s-force": "S-Force",
            "s force": "S-Force",

            # Decks populaires / rogue / casual utiles dans les stats
            "toon": "Toon",
            "toons": "Toon",

            "blue eyes": "Blue-Eyes",
            "blue-eyes": "Blue-Eyes",
            "blue eye": "Blue-Eyes",
            "yeux bleus": "Blue-Eyes",

            "dark magician": "Dark Magician",
            "magicien sombre": "Dark Magician",

            "red eyes": "Red-Eyes",
            "red-eyes": "Red-Eyes",
            "yeux rouges": "Red-Eyes",

            "hero": "HERO",
            "heroes": "HERO",
            "heros": "HERO",

            "salamangreat": "Salamangreat",
            "salamangrande": "Salamangreat",

            "mathmech": "Mathmech",
            "mathmech circular": "Mathmech",

            "marincess": "Marincess",
            "drytron": "Drytron",
            "exosister": "Exosister",

            "rikka": "Rikka",
            "plant": "Plant",
            "plants": "Plant",
            "plante": "Plant",
            "plantes": "Plant",

            "dragonmaid": "Dragonmaid",
            "dragon maid": "Dragonmaid",

            "shaddoll": "Shaddoll",
            "invoked": "Invoked",
            "dogmatika": "Dogmatika",

            "ddd": "D/D/D",
            "d/d/d": "D/D/D",

            "floo": "Floowandereeze",
            "floowandereeze": "Floowandereeze",
            "floow": "Floowandereeze",

            "adamancipator": "Adamancipator",
            "blackwing": "Blackwing",
            "aile noire": "Blackwing",

            "crystal beast": "Crystal Beast",
            "crystal beasts": "Crystal Beast",
            "bete cristalline": "Crystal Beast",

            "traptrix": "Traptrix",
            "eldlich": "Eldlich",
            "ninja": "Ninja",

            "burning abyss": "Burning Abyss",
            "ba": "Burning Abyss",

            "phantom knight": "Phantom Knights",
            "phantom knights": "Phantom Knights",
            "pk": "Phantom Knights",
        }

        if cleaned in aliases:
            return aliases[cleaned]

        # ======================================================
        # DÉTECTIONS PARTIELLES
        # ======================================================

        partial_checks = [
            ("K9", ["k9", "k-9", "k 9"]),
            ("Artmage", ["artmage", "art mage"]),
            ("Fiendsmith", ["fiendsmith", "fiend smith"]),
            ("Elfnote", ["elfnote", "elf note", "notes elfiques", "note elfique"]),
            ("Yummy", ["yummy"]),
            ("Dracotail", ["dracotail", "dragon tail", "draco tail"]),
            ("Maliss", ["maliss", "malice"]),
            ("Mitsurugi", ["mitsurugi"]),
            ("Ryzeal", ["ryzeal", "ryzeol"]),
            ("Kewl Tune", ["kewl tune", "cool tune", "killer tune"]),
            ("Radiant Typhoon", ["radiant typhoon"]),
            ("Branded", ["branded", "albaz"]),
            ("Snake-Eye", ["snake eye", "snake-eye", "snake eyes", "snake-eyes"]),
            ("Fire King", ["fire king", "fire kings"]),
            ("Vanquish Soul", ["vanquish soul"]),
            ("Azamina", ["azamina"]),
            ("White Forest", ["white forest", "foret blanche"]),
            ("Toon", ["toon"]),
            ("Blue-Eyes", ["blue eyes", "blue-eyes", "yeux bleus"]),
            ("Dark Magician", ["dark magician", "magicien sombre"]),
            ("HERO", ["hero", "heros"]),
            ("Sky Striker", ["sky striker"]),
            ("Labrynth", ["labrynth", "labyrinth"]),
            ("Kashtira", ["kashtira"]),
            ("Tearlaments", ["tearlament", "tearlaments"]),
            ("Tenpai Dragon", ["tenpai"]),
            ("Rescue-ACE", ["rescue ace", "rescue-ace"]),
            ("Runick", ["runick"]),
            ("Spright", ["spright"]),
            ("Purrely", ["purrely"]),
            ("Lunalight", ["lunalight", "luna light"]),
            ("Orcust", ["orcust", "orcuste"]),
            ("Memento", ["memento"]),
            ("Primite", ["primite"]),
        ]

        for official_name, patterns in partial_checks:
            if self._has_any(cleaned, patterns):
                return official_name

        return cleaned.title()

    # ==========================================================
    # TOURNOI ACTIF
    # ==========================================================

    async def _get_active_tournament(
        self,
        guild_id: str,
    ) -> aiosqlite.Row | None:

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT *
                FROM tournaments
                WHERE guild_id = ?
                AND status IN (
                    'registration',
                    'running'
                )
                ORDER BY created_at DESC
                LIMIT 1
            """, (guild_id,))

            return await cursor.fetchone()

    # ==========================================================
    # VAINQUEUR
    # ==========================================================

    async def _get_winner_from_tournament(
        self,
        tournament_id: int,
    ) -> tuple[str | None, str | None]:

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    winner_id,
                    winner_name
                FROM tournaments
                WHERE id = ?
            """, (tournament_id,))

            row = await cursor.fetchone()

        if row is None:
            return None, None

        return row["winner_id"], row["winner_name"]

    async def _get_winner_from_final_match(
        self,
        tournament_id: int,
    ) -> tuple[str | None, str | None]:

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    winner_id,
                    winner_name
                FROM matches
                WHERE tournament_id = ?
                AND winner_id IS NOT NULL
                ORDER BY round DESC, match_number DESC, id DESC
                LIMIT 1
            """, (tournament_id,))

            row = await cursor.fetchone()

        if row is None:
            return None, None

        return row["winner_id"], row["winner_name"]

    # ==========================================================
    # DECKS
    # ==========================================================

    async def _get_deck_distribution(
        self,
        tournament_id: int,
        other_threshold_percent: int,
    ) -> list[dict]:

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT deck
                FROM registrations
                WHERE tournament_id = ?
                AND dropped = 0
                AND disqualified = 0
            """, (tournament_id,))

            rows = await cursor.fetchall()

        counter = Counter()

        for row in rows:
            deck_name = self._normalize_deck_name(row["deck"])
            counter[deck_name] += 1

        total = sum(counter.values())

        if total == 0:
            return []

        distribution = []
        other_count = 0

        for deck_name, count in counter.most_common():
            percent = (count / total) * 100

            if percent < other_threshold_percent:
                other_count += count
            else:
                distribution.append({
                    "deck": deck_name,
                    "count": count,
                    "percent": percent,
                })

        if other_count > 0:
            distribution.append({
                "deck": "Autres",
                "count": other_count,
                "percent": (other_count / total) * 100,
            })

        return distribution

    # ==========================================================
    # DIAGRAMME
    # ==========================================================

    def _create_deck_pie_chart(
        self,
        distribution: list[dict],
        tournament_name: str,
    ) -> discord.File | None:

        if not distribution:
            return None

        labels = [
            f"{item['deck']} ({item['count']})"
            for item in distribution
        ]

        sizes = [
            item["count"]
            for item in distribution
        ]

        fig, ax = plt.subplots(
            figsize=(9, 8)
        )

        wedges, texts, autotexts = ax.pie(
            sizes,
            autopct="%1.1f%%",
            startangle=90,
        )

        ax.legend(
            wedges,
            labels,
            title="Decks",
            loc="center left",
            bbox_to_anchor=(1, 0, 0.5, 1),
        )

        ax.set_title(
            f"Répartition des decks — {tournament_name}"
        )

        ax.axis("equal")

        buffer = io.BytesIO()

        plt.savefig(
            buffer,
            format="png",
            bbox_inches="tight",
            dpi=150,
        )

        plt.close(fig)

        buffer.seek(0)

        return discord.File(
            fp=buffer,
            filename="deck_distribution.png",
        )

    # ==========================================================
    # FINIR LE TOURNOI
    # ==========================================================

    async def _finish_tournament(
        self,
        tournament_id: int,
        winner_id: str | None,
        winner_name: str | None,
    ) -> None:

        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("""
                UPDATE tournaments
                SET
                    status = 'finished',
                    winner_id = ?,
                    winner_name = ?,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                winner_id,
                winner_name,
                tournament_id,
            ))

            await db.commit()

    # ==========================================================
    # COMMANDE END TOURNAMENT
    # ==========================================================

    @app_commands.command(
        name="end_tournament",
        description="Terminer le tournoi actif et générer le diagramme des decks"
    )
    @app_commands.describe(
        winner="Vainqueur du tournoi si Hamtaro ne le détecte pas automatiquement",
        other_threshold_percent="Pourcentage minimum avant de regrouper dans Autres"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def end_tournament(
        self,
        interaction: discord.Interaction,
        winner: Optional[discord.Member] = None,
        other_threshold_percent: int = 5,
    ):

        await interaction.response.defer(
            ephemeral=False
        )

        if other_threshold_percent < 0:
            other_threshold_percent = 0

        if other_threshold_percent > 25:
            other_threshold_percent = 25

        try:
            guild_id = self._guild_id(interaction)

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        tournament = await self._get_active_tournament(
            guild_id
        )

        if tournament is None:
            await interaction.followup.send(
                "❌ Aucun tournoi actif trouvé.",
                ephemeral=True,
            )
            return

        tournament_id = tournament["id"]
        tournament_name = tournament["name"]

        winner_id = None
        winner_name = None

        if winner is not None:
            winner_id = str(winner.id)
            winner_name = winner.display_name

        else:
            winner_id, winner_name = await self._get_winner_from_tournament(
                tournament_id
            )

            if winner_id is None:
                winner_id, winner_name = await self._get_winner_from_final_match(
                    tournament_id
                )

        distribution = await self._get_deck_distribution(
            tournament_id=tournament_id,
            other_threshold_percent=other_threshold_percent,
        )

        chart_file = self._create_deck_pie_chart(
            distribution=distribution,
            tournament_name=tournament_name,
        )

        await self._finish_tournament(
            tournament_id=tournament_id,
            winner_id=winner_id,
            winner_name=winner_name,
        )

        embed = discord.Embed(
            title="🏁 Tournoi terminé",
            description=f"Le tournoi **{tournament_name}** est maintenant terminé.",
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Format",
            value=tournament["format"],
            inline=True,
        )

        embed.add_field(
            name="Code",
            value=f"`{tournament['code']}`",
            inline=True,
        )

        if winner_id is not None and winner_name is not None:
            embed.add_field(
                name="Vainqueur",
                value=f"🏆 **{winner_name}**",
                inline=False,
            )

        else:
            embed.add_field(
                name="Vainqueur",
                value="Non détecté automatiquement.",
                inline=False,
            )

        if distribution:
            deck_lines = []

            for item in distribution:
                deck_lines.append(
                    f"• **{item['deck']}** : {item['count']} joueur(s) — {item['percent']:.1f}%"
                )

            embed.add_field(
                name="📊 Répartition des decks",
                value="\n".join(deck_lines),
                inline=False,
            )

            embed.set_footer(
                text=f"Les decks sous {other_threshold_percent}% sont regroupés dans Autres."
            )

        else:
            embed.add_field(
                name="📊 Répartition des decks",
                value="Aucun deck renseigné pour ce tournoi.",
                inline=False,
            )

        if chart_file is not None:
            embed.set_image(
                url="attachment://deck_distribution.png"
            )

            await interaction.followup.send(
                embed=embed,
                file=chart_file,
                ephemeral=False,
            )

        else:
            await interaction.followup.send(
                embed=embed,
                ephemeral=False,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(
        EndTournamentCog(bot)
    )
