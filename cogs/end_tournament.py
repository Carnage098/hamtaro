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

            "branded": "Branded",
            "despia": "Branded Despia",
            "branded despia": "Branded Despia",
            "albaz": "Branded",
            "fallen of albaz": "Branded",

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
    # TOURNOI À TERMINER
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

    async def _get_tournament_for_end(
        self,
        guild_id: str,
        reference: str | None,
    ) -> aiosqlite.Row | None:
        """
        Résout le tournoi à terminer.

        - Avec `tournoi`, accepte l'ID ou le code public.
        - Sans `tournoi`, prend le tournoi actif.
        - S'il n'y a plus de tournoi actif (cas fréquent après validation de
          la finale, qui peut déjà passer le tournoi à finished), reprend
          le tournoi terminé le plus récent du serveur.
        """
        if reference is not None and str(reference).strip():
            value = str(reference).strip()

            async with aiosqlite.connect(DATABASE) as db:
                db.row_factory = aiosqlite.Row

                if value.isdigit():
                    cursor = await db.execute(
                        """
                        SELECT *
                        FROM tournaments
                        WHERE guild_id = ?
                          AND status != 'cancelled'
                          AND (
                              id = ?
                              OR LOWER(COALESCE(code, '')) = LOWER(?)
                          )
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (guild_id, int(value), value),
                    )
                else:
                    cursor = await db.execute(
                        """
                        SELECT *
                        FROM tournaments
                        WHERE guild_id = ?
                          AND status != 'cancelled'
                          AND LOWER(COALESCE(code, '')) = LOWER(?)
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (guild_id, value),
                    )

                return await cursor.fetchone()

        active = await self._get_active_tournament(guild_id)
        if active is not None:
            return active

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM tournaments
                WHERE guild_id = ?
                  AND status = 'finished'
                ORDER BY COALESCE(finished_at, created_at) DESC, id DESC
                LIMIT 1
                """,
                (guild_id,),
            )
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
        """
        Secours SQL : lit explicitement la finale (round = 1).

        L'ancienne version triait les rounds en DESC, ce qui pouvait
        sélectionner un match d'un tour précédent.
        """
        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT
                    winner_id,
                    winner_name
                FROM matches
                WHERE tournament_id = ?
                  AND round = 1
                  AND winner_id IS NOT NULL
                ORDER BY match_number ASC, id DESC
                LIMIT 1
            """, (tournament_id,))

            row = await cursor.fetchone()

        if row is None:
            return None, None

        return row["winner_id"], row["winner_name"]

    async def _get_verified_bracket_winner(
        self,
        tournament_id: int,
    ) -> tuple[bool, str | None, str | None]:
        """
        Retourne (has_bracket, winner_id, winner_name).

        Lorsqu'un bracket existe, la vraie finale fait foi : elle doit être
        terminée/validée et posséder un vainqueur.
        """
        bracket_cog = self.bot.get_cog("BracketCog")

        # Si le cog bracket est momentanément indisponible, on vérifie
        # directement si des matchs de bracket existent.
        if bracket_cog is None:
            async with aiosqlite.connect(DATABASE) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM matches
                    WHERE tournament_id = ?
                    """,
                    (tournament_id,),
                )
                row = await cursor.fetchone()

            has_bracket = bool(row and int(row["count"] or 0) > 0)
            if not has_bracket:
                return False, None, None

            winner_id, winner_name = await self._get_winner_from_final_match(
                tournament_id
            )
            if winner_id is None or winner_name is None:
                raise ValueError(
                    "La finale n'est pas encore terminée ou aucun vainqueur "
                    "n'est enregistré."
                )
            return True, str(winner_id), str(winner_name)

        bracket = await bracket_cog.brackets.get_bracket(tournament_id)
        if not bracket:
            return False, None, None

        final = await bracket_cog.brackets.get_final(tournament_id)
        if final is None:
            raise ValueError(
                "La finale du bracket est introuvable."
            )

        raw_status = getattr(final, "status", "")
        status = getattr(raw_status, "value", str(raw_status)).lower().strip()

        if status not in {
            "completed",
            "validated",
            "finished",
            "approved",
        }:
            raise ValueError(
                "La finale n'est pas encore terminée ou validée. "
                "Valide d'abord son résultat."
            )

        winner_id = getattr(final, "winner_id", None)
        winner_name = getattr(final, "winner_name", None)

        if winner_id is None or winner_name is None:
            raise ValueError(
                "La finale est terminée, mais aucun vainqueur n'est enregistré."
            )

        return True, str(winner_id), str(winner_name)

    async def _publish_final_bracket(
        self,
        interaction: discord.Interaction,
        tournament_id: int,
    ) -> None:
        """
        Réutilise exactement le moteur du cog /final_bracket.
        """
        bracket_cog = self.bot.get_cog("BracketCog")
        if bracket_cog is None:
            raise RuntimeError(
                "Le module BracketCog n'est pas chargé."
            )

        database = getattr(self.bot, "db", None)
        if database is None:
            raise RuntimeError(
                "La base de données Hamtaro n'est pas disponible."
            )

        tournament = await database.get_tournament(tournament_id)
        if tournament is None:
            raise RuntimeError(
                "Le tournoi terminé est introuvable."
            )

        await bracket_cog._send_bracket_image(
            interaction,
            tournament,
            final_mode=True,
        )

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
                    finished_at = COALESCE(
                        finished_at,
                        CURRENT_TIMESTAMP
                    )
                WHERE id = ?
            """, (
                winner_id,
                winner_name,
                tournament_id,
            ))

            await db.commit()

    # ==========================================================
    # NETTOYAGE ET FINALISATION MODERNE
    # ==========================================================

    async def _table_exists(self, table_name: str) -> bool:
        database = getattr(self.bot, "db", None)
        if database is None:
            return False
        row = await database.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table_name,),
        )
        return row is not None

    async def _assert_results_are_frozen_ready(self, tournament_id: int) -> None:
        database = getattr(self.bot, "db", None)
        if database is None:
            return
        if await self._table_exists("result_requests"):
            pending = int(
                await database.fetchval(
                    """
                    SELECT COUNT(*) FROM result_requests
                    WHERE tournament_id = ?
                      AND status IN ('pending','confirmed','contested','processing')
                    """,
                    (tournament_id,),
                )
                or 0
            )
            if pending:
                raise ValueError(
                    f"{pending} résultat(s) sont encore en validation. "
                    "Traite-les avant de terminer le tournoi."
                )

        # Une ronde suisse inachevée ne doit pas être figée par erreur.
        if await self._table_exists("swiss_matches"):
            pending_swiss = int(
                await database.fetchval(
                    """
                    SELECT COUNT(*) FROM swiss_matches
                    WHERE tournament_id = ?
                      AND COALESCE(is_bye, 0) = 0
                      AND LOWER(COALESCE(status, 'pending')) NOT IN (
                          'approved','validated','completed','finished','cancelled'
                      )
                    """,
                    (tournament_id,),
                )
                or 0
            )
            if pending_swiss:
                raise ValueError(
                    f"{pending_swiss} match(s) suisse(s) ne sont pas terminés."
                )

    async def _cleanup_tournament_runtime(self, tournament_id: int) -> dict[str, int]:
        database = getattr(self.bot, "db", None)
        if database is None:
            return {"threads": 0, "panels": 0, "assistance": 0}

        sessions: list[dict] = []
        if await self._table_exists("match_center_sessions"):
            sessions = [
                dict(row)
                for row in await database.fetchall(
                    "SELECT * FROM match_center_sessions WHERE tournament_id = ?",
                    (tournament_id,),
                )
            ]

        thread_ids: set[str] = {
            str(row.get("thread_id"))
            for row in sessions
            if row.get("thread_id")
        }
        if await self._table_exists("match_thread_context"):
            rows = await database.fetchall(
                "SELECT thread_id FROM match_thread_context WHERE tournament_id = ?",
                (tournament_id,),
            )
            thread_ids.update(str(row["thread_id"]) for row in rows if row["thread_id"])
        if await self._table_exists("progression_match_publications"):
            rows = await database.fetchall(
                "SELECT thread_id FROM progression_match_publications WHERE tournament_id = ?",
                (tournament_id,),
            )
            thread_ids.update(str(row["thread_id"]) for row in rows if row["thread_id"])

        panels = 0
        match_center = self.bot.get_cog("MatchCenterCog")
        if match_center is not None:
            for row in sessions:
                try:
                    await match_center._refresh_panel(
                        str(row["match_kind"]),
                        int(row["match_id"]),
                        disabled=True,
                    )
                    panels += 1
                except Exception:
                    pass

        archived = 0
        for thread_id in thread_ids:
            try:
                channel = self.bot.get_channel(int(thread_id))
                if channel is None:
                    channel = await self.bot.fetch_channel(int(thread_id))
                if isinstance(channel, discord.Thread):
                    try:
                        await channel.send(
                            "🏁 **Tournoi terminé.** Les résultats sont figés et ce fil est archivé."
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                    await channel.edit(
                        archived=True,
                        locked=True,
                        reason="Fin automatique du tournoi Hamtaro",
                    )
                    archived += 1
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
                continue

        if await self._table_exists("match_center_sessions"):
            await database.execute(
                """
                UPDATE match_center_sessions
                SET status='completed', updated_at=CURRENT_TIMESTAMP
                WHERE tournament_id = ?
                """,
                (tournament_id,),
            )
        assistance = 0
        if await self._table_exists("staff_assistance_requests"):
            cursor = await database.execute(
                """
                UPDATE staff_assistance_requests
                SET status='resolved', resolution='Tournoi terminé automatiquement',
                    resolved_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE tournament_id = ? AND status IN ('open','claimed')
                """,
                (tournament_id,),
            )
            assistance = max(int(cursor.rowcount or 0), 0)
        if await self._table_exists("tournament_runtime_state"):
            await database.execute(
                """
                UPDATE tournament_runtime_state
                SET status='finished', pause_started_at=NULL,
                    updated_at=CURRENT_TIMESTAMP
                WHERE tournament_id = ?
                """,
                (tournament_id,),
            )
        await database.commit()
        return {"threads": archived, "panels": panels, "assistance": assistance}

    async def _refresh_tournament_profiles(self, guild_id: str, tournament_id: int) -> int:
        database = getattr(self.bot, "db", None)
        if database is None:
            return 0
        player_ids = [
            str(row["discord_id"])
            for row in await database.fetchall(
                "SELECT discord_id FROM registrations WHERE tournament_id = ?",
                (tournament_id,),
            )
            if row["discord_id"]
        ]
        try:
            from services.analytics_service import AnalyticsService

            return await AnalyticsService().refresh_player_statistics(
                guild_id=guild_id,
                player_ids=player_ids,
            )
        except Exception as error:
            print(f"⚠️ Recalcul des profils à la fin du tournoi : {error}")
            return 0

    async def _swiss_final_top(self, tournament_id: int) -> list[dict]:
        database = getattr(self.bot, "db", None)
        if database is None or not hasattr(database, "get_swiss_standings"):
            return []
        try:
            standings = await database.get_swiss_standings(tournament_id)
        except Exception:
            return []
        output: list[dict] = []
        for row in standings[:10]:
            try:
                output.append(dict(row))
            except (TypeError, ValueError):
                output.append(
                    {
                        "username": getattr(row, "username", "Joueur"),
                        "points": getattr(row, "points", 0),
                    }
                )
        return output

    async def _complete_tournament(
        self,
        interaction: discord.Interaction,
        tournament,
        *,
        manual_winner: Optional[discord.Member] = None,
        other_threshold_percent: int = 5,
    ) -> None:
        tournament_id = int(tournament["id"])
        tournament_name = tournament["name"]
        guild_id = str(tournament["guild_id"])

        await self._assert_results_are_frozen_ready(tournament_id)

        (
            has_bracket,
            final_winner_id,
            final_winner_name,
        ) = await self._get_verified_bracket_winner(tournament_id)

        winner_id: str | None = None
        winner_name: str | None = None
        if has_bracket:
            winner_id = final_winner_id
            winner_name = final_winner_name
        elif manual_winner is not None:
            winner_id = str(manual_winner.id)
            winner_name = manual_winner.display_name
        else:
            winner_id, winner_name = await self._get_winner_from_tournament(tournament_id)
            if winner_id is None:
                winner_id, winner_name = await self._get_winner_from_final_match(tournament_id)
            if winner_id is None:
                swiss_preview = await self._swiss_final_top(tournament_id)
                if swiss_preview:
                    first = swiss_preview[0]
                    winner_id = str(
                        first.get("discord_id")
                        or first.get("player_id")
                        or first.get("id")
                        or ""
                    ) or None
                    winner_name = str(
                        first.get("username")
                        or first.get("display_name")
                        or first.get("player_name")
                        or "Champion suisse"
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
        cleanup = await self._cleanup_tournament_runtime(tournament_id)
        profiles = await self._refresh_tournament_profiles(guild_id, tournament_id)
        swiss_top = await self._swiss_final_top(tournament_id)

        embed = discord.Embed(
            title="🏁 Tournoi terminé",
            description=(
                f"Le tournoi **{tournament_name}** est terminé. Les résultats sont figés, "
                "les panneaux sont désactivés et les fils ont été archivés."
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="Format", value=tournament["format"], inline=True)
        embed.add_field(name="Code", value=f"`{tournament['code']}`", inline=True)
        if winner_id is not None and winner_name is not None:
            embed.add_field(name="Vainqueur", value=f"🏆 **{winner_name}**", inline=False)
        else:
            embed.add_field(name="Vainqueur", value="Non détecté automatiquement.", inline=False)

        if distribution:
            deck_lines = [
                f"• **{item['deck']}** : {item['count']} joueur(s) — {item['percent']:.1f}%"
                for item in distribution
            ]
            embed.add_field(
                name="📊 Répartition des decks",
                value="\n".join(deck_lines)[:1024],
                inline=False,
            )
        else:
            embed.add_field(
                name="📊 Répartition des decks",
                value="Aucun deck renseigné pour ce tournoi.",
                inline=False,
            )

        if swiss_top:
            lines = []
            for index, row in enumerate(swiss_top[:10], start=1):
                name = row.get("username") or row.get("player_name") or row.get("display_name") or f"Joueur {index}"
                points = row.get("points", row.get("score", 0))
                lines.append(f"**{index}.** {name} — **{points} pt(s)**")
            embed.add_field(name="🇨🇭 Classement final", value="\n".join(lines), inline=False)

        embed.add_field(
            name="🧹 Nettoyage automatique",
            value=(
                f"Fils archivés : **{cleanup['threads']}**\n"
                f"Panneaux désactivés : **{cleanup['panels']}**\n"
                f"Demandes staff clôturées : **{cleanup['assistance']}**\n"
                f"Profils recalculés : **{profiles}**"
            ),
            inline=False,
        )
        embed.set_footer(
            text=(
                f"Les decks sous {other_threshold_percent}% sont regroupés dans Autres. "
                "Hamtaro a figé l'état final du tournoi."
            )
        )

        if chart_file is not None:
            embed.set_image(url="attachment://deck_distribution.png")
            await interaction.followup.send(embed=embed, file=chart_file, ephemeral=False)
        else:
            await interaction.followup.send(embed=embed, ephemeral=False)

        if has_bracket:
            try:
                await self._publish_final_bracket(interaction, tournament_id)
            except Exception as error:
                await interaction.followup.send(
                    "⚠️ Le tournoi est bien terminé, mais l'image du bracket final "
                    f"n'a pas pu être publiée : `{type(error).__name__}: {error}`.",
                    ephemeral=True,
                )

    async def finish_from_manage(
        self,
        interaction: discord.Interaction,
        tournament_id: int,
    ) -> None:
        """Entrée utilisée par le bouton Terminer de /tournament_manage."""
        await interaction.response.defer(ephemeral=False, thinking=True)
        tournament = await self._get_tournament_for_end(
            str(interaction.guild_id),
            str(tournament_id),
        )
        if tournament is None:
            await interaction.followup.send("❌ Tournoi introuvable.", ephemeral=True)
            return
        try:
            await self._complete_tournament(interaction, tournament)
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)

    # ==========================================================
    # COMMANDE END TOURNAMENT
    # ==========================================================

    @app_commands.command(
        name="end_tournament",
        description="Terminer le tournoi, vérifier la finale et publier le bracket final"
    )
    @app_commands.describe(
        tournoi="ID ou code du tournoi. Laisse vide pour utiliser le tournoi courant.",
        winner="Vainqueur manuel uniquement si le tournoi ne possède pas de bracket",
        other_threshold_percent="Pourcentage minimum avant de regrouper dans Autres"
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @staff_only()
    async def end_tournament(
        self,
        interaction: discord.Interaction,
        tournoi: Optional[str] = None,
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

        tournament = await self._get_tournament_for_end(
            guild_id,
            tournoi,
        )

        if tournament is None:
            await interaction.followup.send(
                "❌ Aucun tournoi correspondant trouvé.",
                ephemeral=True,
            )
            return

        try:
            await self._complete_tournament(
                interaction,
                tournament,
                manual_winner=winner,
                other_threshold_percent=other_threshold_percent,
            )
        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return



async def setup(bot: commands.Bot):
    await bot.add_cog(
        EndTournamentCog(bot)
    )
