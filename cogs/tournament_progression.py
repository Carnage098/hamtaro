from __future__ import annotations

import asyncio
import re
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.swiss_service import SwissService
from utils.embeds import error_embed, info_embed, success_embed
from utils.permissions import is_staff_member
from utils.tournament_resolver import resolve_tournament


SWISS_NEXT_FOOTER = "HAMTARO_SWISS_NEXT:"
MATCH_KIND_BRACKET = "bracket"
MATCH_KIND_SWISS = "swiss"

FINAL_MATCH_STATUSES = {
    "approved",
    "cancelled",
    "completed",
    "finished",
    "refused",
    "rejected",
}


# ==========================================================
# OUTILS GÉNÉRAUX
# ==========================================================


def _row_to_dict(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    try:
        return obj[name]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, name, default)


def _clean_thread_name(text: str) -> str:
    text = re.sub(r"[^\w\- ]+", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip().lower())
    return text[:90] or "match-hamtaro"


def _bracket_round_name(round_number: int) -> str:
    names = {
        1: "Finale",
        2: "Demi-finales",
        3: "Quarts de finale",
        4: "Huitièmes de finale",
        5: "Seizièmes de finale",
        6: "Trente-deuxièmes de finale",
        7: "Soixante-quatrièmes de finale",
    }
    return names.get(round_number, f"Round {round_number}")


def _mention(discord_id: Any, fallback: str) -> str:
    if discord_id is None:
        return fallback
    return f"<@{discord_id}>"


# ==========================================================
# VUE PERSISTANTE : GÉNÉRER LA RONDE SUISSE SUIVANTE
# ==========================================================


class NextSwissRoundView(discord.ui.View):
    def __init__(self, cog: "TournamentProgressionCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Générer la ronde suivante",
        emoji="🔄",
        style=discord.ButtonStyle.success,
        custom_id="hamtaro:progression:swiss:next",
    )
    async def generate_next_round(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self.cog._ensure_staff(interaction):
            return

        reference = self.cog._extract_swiss_next_reference(interaction.message)
        if reference is None:
            await interaction.response.send_message(
                "❌ Impossible d'identifier la ronde concernée.",
                ephemeral=True,
            )
            return

        tournament_id, completed_round = reference
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            next_round = await self.cog.generate_next_swiss_round(
                tournament_id=tournament_id,
                completed_round=completed_round,
                actor=interaction.user,
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(
                    title="Génération impossible",
                    description=str(error),
                ),
                ephemeral=True,
            )
            return
        except Exception as error:
            print(f"❌ Génération ronde suisse suivante : {error}")
            await interaction.followup.send(
                embed=error_embed(
                    title="Erreur inattendue",
                    description="La ronde suivante n'a pas pu être générée.",
                ),
                ephemeral=True,
            )
            return

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        try:
            await interaction.message.edit(view=self)
        except (discord.Forbidden, discord.HTTPException):
            pass

        await interaction.followup.send(
            embed=success_embed(
                title=f"Ronde {next_round} générée",
                description=(
                    "Les nouveaux matchs ont été publiés et les joueurs "
                    "ont été notifiés."
                ),
            ),
            ephemeral=True,
        )


# ==========================================================
# COG DE PROGRESSION
# ==========================================================


class TournamentProgressionCog(commands.Cog):
    """
    Couche Discord de progression automatique.

    Le moteur de bracket continue d'avancer les gagnants et SwissService
    continue de calculer les pairings. Ce cog s'occupe de :

    - détecter les matchs devenus jouables ;
    - publier les affrontements dans un salon ;
    - créer un fil Discord par match ;
    - notifier les deux joueurs ;
    - proposer ou générer la ronde suisse suivante ;
    - éviter les doubles publications grâce à des tables dédiées.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db
        self.swiss = SwissService(self.db)
        self._publish_locks: dict[tuple[str, int], asyncio.Lock] = {}

    # ==========================================================
    # CYCLE DE VIE
    # ==========================================================

    async def cog_load(self) -> None:
        await self._init_tables()
        self.bot.add_view(NextSwissRoundView(self))
        if not self.scan_new_matches.is_running():
            self.scan_new_matches.start()

    async def cog_unload(self) -> None:
        if self.scan_new_matches.is_running():
            self.scan_new_matches.cancel()

    # ==========================================================
    # TABLES
    # ==========================================================

    async def _init_tables(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS progression_settings (
                guild_id TEXT PRIMARY KEY,
                matches_channel_id TEXT,
                staff_channel_id TEXT,
                staff_role_id TEXT,
                create_threads INTEGER NOT NULL DEFAULT 1,
                auto_generate_swiss INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS progression_match_publications (
                match_kind TEXT NOT NULL,
                match_id INTEGER NOT NULL,
                guild_id TEXT NOT NULL,
                tournament_id INTEGER NOT NULL,
                channel_id TEXT,
                message_id TEXT,
                thread_id TEXT,
                status TEXT NOT NULL DEFAULT 'processing',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (match_kind, match_id)
            )
            """
        )

        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS progression_round_publications (
                tournament_id INTEGER NOT NULL,
                match_kind TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                channel_id TEXT,
                message_id TEXT,
                status TEXT NOT NULL DEFAULT 'processing',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tournament_id, match_kind, round_number)
            )
            """
        )

        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS progression_swiss_actions (
                tournament_id INTEGER NOT NULL,
                completed_round INTEGER NOT NULL,
                status TEXT NOT NULL,
                channel_id TEXT,
                message_id TEXT,
                acted_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tournament_id, completed_round)
            )
            """
        )

        await self.db.commit()

    # ==========================================================
    # CONFIGURATION ET PERMISSIONS
    # ==========================================================

    async def _settings(self, guild_id: str) -> dict[str, Any] | None:
        row = await self.db.fetchone(
            "SELECT * FROM progression_settings WHERE guild_id = ?",
            (guild_id,),
        )
        return _row_to_dict(row)

    async def _ensure_staff(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "❌ Cette action doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return False

        settings = await self._settings(str(interaction.guild_id))
        configured_role_id = str(settings.get("staff_role_id") or "") if settings else ""
        has_configured_role = any(
            str(role.id) == configured_role_id
            for role in member.roles
        ) if configured_role_id else False

        allowed = (
            member.guild_permissions.administrator
            or member.guild_permissions.manage_guild
            or is_staff_member(member)
            or has_configured_role
        )

        if not allowed:
            await interaction.response.send_message(
                "❌ Seul le staff peut utiliser cette action.",
                ephemeral=True,
            )
            return False
        return True

    async def _get_text_channel(
        self,
        guild_id: str,
        setting_name: str,
    ) -> discord.TextChannel | None:
        settings = await self._settings(guild_id)
        if settings is None:
            return None

        channel_id = settings.get(setting_name)
        if not channel_id:
            return None

        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None

        return channel if isinstance(channel, discord.TextChannel) else None

    # ==========================================================
    # RÉSERVATION IDEMPOTENTE
    # ==========================================================

    def _lock_for(self, match_kind: str, match_id: int) -> asyncio.Lock:
        key = (match_kind, match_id)
        if key not in self._publish_locks:
            self._publish_locks[key] = asyncio.Lock()
        return self._publish_locks[key]

    async def _claim_match_publication(
        self,
        *,
        match_kind: str,
        match_id: int,
        guild_id: str,
        tournament_id: int,
    ) -> bool:
        cursor = await self.db.execute(
            """
            INSERT OR IGNORE INTO progression_match_publications (
                match_kind,
                match_id,
                guild_id,
                tournament_id,
                status
            )
            VALUES (?, ?, ?, ?, 'processing')
            """,
            (match_kind, match_id, guild_id, tournament_id),
        )
        await self.db.commit()
        return cursor.rowcount == 1

    async def _release_match_claim(self, match_kind: str, match_id: int) -> None:
        await self.db.execute(
            """
            DELETE FROM progression_match_publications
            WHERE match_kind = ? AND match_id = ? AND status = 'processing'
            """,
            (match_kind, match_id),
        )
        await self.db.commit()

    async def _claim_round_publication(
        self,
        *,
        tournament_id: int,
        match_kind: str,
        round_number: int,
    ) -> bool:
        cursor = await self.db.execute(
            """
            INSERT OR IGNORE INTO progression_round_publications (
                tournament_id,
                match_kind,
                round_number,
                status
            )
            VALUES (?, ?, ?, 'processing')
            """,
            (tournament_id, match_kind, round_number),
        )
        await self.db.commit()
        return cursor.rowcount == 1

    async def _release_round_claim(
        self,
        tournament_id: int,
        match_kind: str,
        round_number: int,
    ) -> None:
        await self.db.execute(
            """
            DELETE FROM progression_round_publications
            WHERE tournament_id = ? AND match_kind = ?
              AND round_number = ? AND status = 'processing'
            """,
            (tournament_id, match_kind, round_number),
        )
        await self.db.commit()

    # ==========================================================
    # RÉCUPÉRATION DES MATCHS
    # ==========================================================

    async def _ready_bracket_matches(self, tournament_id: int) -> list[dict[str, Any]]:
        query = """
            SELECT *
            FROM matches
            WHERE tournament_id = ?
              AND player1_id IS NOT NULL
              AND player2_id IS NOT NULL
              AND LOWER(COALESCE(status, 'pending')) NOT IN (
                    'approved', 'cancelled', 'completed',
                    'finished', 'refused', 'rejected'
              )
            ORDER BY round DESC, match_number ASC, id ASC
        """
        rows = await self.db.fetchall(query, (tournament_id,))
        return [dict(row) for row in rows]

    async def _all_bracket_round_matches(
        self,
        tournament_id: int,
        round_number: int,
    ) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT *
            FROM matches
            WHERE tournament_id = ? AND round = ?
            ORDER BY match_number ASC, id ASC
            """,
            (tournament_id, round_number),
        )
        return [dict(row) for row in rows]

    @staticmethod
    def _bracket_round_is_fully_known(matches: list[dict[str, Any]]) -> bool:
        if not matches:
            return False
        for match in matches:
            is_bye = int(match.get("is_bye") or 0) == 1
            if is_bye:
                continue
            if not match.get("player1_id") or not match.get("player2_id"):
                return False
        return True

    async def _swiss_round_matches(
        self,
        tournament_id: int,
        round_number: int,
    ) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT *
            FROM swiss_matches
            WHERE tournament_id = ? AND round_number = ?
            ORDER BY table_number ASC, id ASC
            """,
            (tournament_id, round_number),
        )
        return [dict(row) for row in rows]

    # ==========================================================
    # EMBEDS ET PUBLICATION
    # ==========================================================

    def _match_embed(
        self,
        *,
        tournament: Any,
        match_kind: str,
        match: dict[str, Any],
    ) -> discord.Embed:
        tournament_name = str(_value(tournament, "name", "Tournoi Hamtaro"))
        tournament_code = str(_value(tournament, "code", "—"))
        tournament_format = str(_value(tournament, "format", "—"))

        if match_kind == MATCH_KIND_SWISS:
            round_number = int(match.get("round_number") or 0)
            position_name = f"Table {match.get('table_number', '?')}"
            phase_name = f"Ronde suisse {round_number}"
        else:
            round_number = int(match.get("round") or 0)
            position_name = f"Match {match.get('id')}"
            phase_name = _bracket_round_name(round_number)

        player1_id = match.get("player1_id")
        player2_id = match.get("player2_id")
        player1_name = str(match.get("player1_name") or "Joueur 1")
        player2_name = str(match.get("player2_name") or "Joueur 2")

        embed = discord.Embed(
            title=f"⚔️ {position_name} — {phase_name}",
            description=(
                f"{_mention(player1_id, player1_name)} **contre** "
                f"{_mention(player2_id, player2_name)}"
            ),
            colour=discord.Colour.gold(),
        )
        embed.add_field(
            name="🏟️ Tournoi",
            value=f"**{tournament_name}** (`{tournament_code}`)",
            inline=False,
        )
        embed.add_field(name="🎴 Format", value=tournament_format, inline=True)
        embed.add_field(
            name="🧭 Système",
            value="Rondes suisses" if match_kind == MATCH_KIND_SWISS else "Élimination directe",
            inline=True,
        )
        embed.add_field(
            name="🆔 Référence",
            value=f"`{match_kind}:{match.get('id')}`",
            inline=True,
        )
        embed.add_field(
            name="📊 Déclarer le résultat",
            value=(
                "Utilisez `/result` à la fin du duel. "
                "Le résultat sera ensuite envoyé au staff."
            ),
            inline=False,
        )
        embed.set_footer(text="Hamtaro crée un fil dédié sous ce message.")
        return embed

    async def _create_match_thread(
        self,
        *,
        starter_message: discord.Message,
        tournament: Any,
        match_kind: str,
        match: dict[str, Any],
    ) -> discord.Thread | None:
        player1_name = str(match.get("player1_name") or "joueur-1")
        player2_name = str(match.get("player2_name") or "joueur-2")
        name = _clean_thread_name(
            f"{match_kind}-{match.get('id')}-{player1_name}-vs-{player2_name}"
        )

        try:
            thread = await starter_message.create_thread(
                name=name,
                auto_archive_duration=1440,
                reason="Fil automatique de match Hamtaro",
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"⚠️ Création du fil pour {match_kind}:{match.get('id')} : {error}")
            return None

        for player_id in (match.get("player1_id"), match.get("player2_id")):
            if not player_id:
                continue
            member = thread.guild.get_member(int(player_id))
            if member is None:
                continue
            try:
                await thread.add_user(member)
            except (discord.Forbidden, discord.HTTPException):
                pass

        await thread.send(
            content=(
                f"{_mention(match.get('player1_id'), player1_name)} "
                f"{_mention(match.get('player2_id'), player2_name)}\n\n"
                "Ce fil est votre espace de match. Vous pouvez y organiser le duel, "
                "poser une question et conserver les informations utiles.\n\n"
                "À la fin, utilisez `/result`."
            ),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        return thread

    async def _notify_match_players(
        self,
        *,
        tournament: Any,
        match_kind: str,
        match: dict[str, Any],
        thread: discord.Thread | None,
    ) -> None:
        tournament_name = str(_value(tournament, "name", "Tournoi Hamtaro"))
        ids = (match.get("player1_id"), match.get("player2_id"))

        for player_id in ids:
            if not player_id:
                continue
            try:
                user = self.bot.get_user(int(player_id)) or await self.bot.fetch_user(int(player_id))
            except (discord.NotFound, discord.HTTPException):
                continue

            opponent_name = (
                str(match.get("player2_name") or "Adversaire")
                if str(player_id) == str(match.get("player1_id"))
                else str(match.get("player1_name") or "Adversaire")
            )
            if match_kind == MATCH_KIND_SWISS:
                position = f"table {match.get('table_number')} — ronde {match.get('round_number')}"
            else:
                position = f"match {match.get('id')} — {_bracket_round_name(int(match.get('round') or 0))}"

            description = (
                f"Ton nouveau match du tournoi **{tournament_name}** est disponible.\n\n"
                f"Adversaire : **{opponent_name}**\n"
                f"Position : **{position}**"
            )
            if thread is not None:
                description += f"\nFil du match : {thread.mention}"

            embed = discord.Embed(
                title="⚔️ Nouveau match Hamtaro",
                description=description,
                colour=discord.Colour.gold(),
            )
            try:
                await user.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def _publish_single_match(
        self,
        *,
        tournament: Any,
        match_kind: str,
        match: dict[str, Any],
    ) -> bool:
        match_id = int(match["id"])
        tournament_id = int(_value(tournament, "id"))
        guild_id = str(_value(tournament, "guild_id"))

        async with self._lock_for(match_kind, match_id):
            claimed = await self._claim_match_publication(
                match_kind=match_kind,
                match_id=match_id,
                guild_id=guild_id,
                tournament_id=tournament_id,
            )
            if not claimed:
                return False

            channel = await self._get_text_channel(guild_id, "matches_channel_id")
            if channel is None:
                await self._release_match_claim(match_kind, match_id)
                return False

            settings = await self._settings(guild_id) or {}
            embed = self._match_embed(
                tournament=tournament,
                match_kind=match_kind,
                match=match,
            )

            try:
                message = await channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except (discord.Forbidden, discord.HTTPException) as error:
                print(f"⚠️ Publication match {match_kind}:{match_id} : {error}")
                await self._release_match_claim(match_kind, match_id)
                return False

            thread: discord.Thread | None = None
            if int(settings.get("create_threads") or 0) == 1:
                thread = await self._create_match_thread(
                    starter_message=message,
                    tournament=tournament,
                    match_kind=match_kind,
                    match=match,
                )

            if thread is not None:
                link_view = discord.ui.View()
                link_view.add_item(
                    discord.ui.Button(
                        label="Ouvrir le fil du match",
                        emoji="🔗",
                        style=discord.ButtonStyle.link,
                        url=thread.jump_url,
                    )
                )
                try:
                    await message.edit(view=link_view)
                except (discord.Forbidden, discord.HTTPException):
                    pass

            await self.db.execute(
                """
                UPDATE progression_match_publications
                SET channel_id = ?, message_id = ?, thread_id = ?,
                    status = 'published', updated_at = CURRENT_TIMESTAMP
                WHERE match_kind = ? AND match_id = ?
                """,
                (
                    str(channel.id),
                    str(message.id),
                    str(thread.id) if thread else None,
                    match_kind,
                    match_id,
                ),
            )
            await self.db.commit()

        await self._notify_match_players(
            tournament=tournament,
            match_kind=match_kind,
            match=match,
            thread=thread,
        )
        return True

    async def _publish_round_summary(
        self,
        *,
        tournament: Any,
        match_kind: str,
        round_number: int,
        matches: list[dict[str, Any]],
    ) -> bool:
        tournament_id = int(_value(tournament, "id"))
        guild_id = str(_value(tournament, "guild_id"))

        claimed = await self._claim_round_publication(
            tournament_id=tournament_id,
            match_kind=match_kind,
            round_number=round_number,
        )
        if not claimed:
            return False

        channel = await self._get_text_channel(guild_id, "matches_channel_id")
        if channel is None:
            await self._release_round_claim(tournament_id, match_kind, round_number)
            return False

        lines: list[str] = []
        for match in matches:
            is_bye = int(match.get("is_bye") or 0) == 1 or not match.get("player2_id")
            if match_kind == MATCH_KIND_SWISS:
                prefix = f"**Table {match.get('table_number', '?')}**"
            else:
                prefix = f"**Match {match.get('id')}**"

            player1 = _mention(match.get("player1_id"), str(match.get("player1_name") or "Joueur 1"))
            if is_bye:
                lines.append(f"{prefix} — 🛋️ BYE pour {player1}")
            else:
                player2 = _mention(match.get("player2_id"), str(match.get("player2_name") or "Joueur 2"))
                lines.append(f"{prefix} — {player1} contre {player2}")

        phase_name = (
            f"Ronde suisse {round_number}"
            if match_kind == MATCH_KIND_SWISS
            else _bracket_round_name(round_number)
        )
        embed = discord.Embed(
            title=f"⚔️ {phase_name}",
            description="\n".join(lines) or "Aucun match à afficher.",
            colour=discord.Colour.gold(),
        )
        embed.add_field(
            name="🏟️ Tournoi",
            value=(
                f"**{_value(tournament, 'name', 'Tournoi Hamtaro')}** "
                f"(`{_value(tournament, 'code', '—')}`)"
            ),
            inline=False,
        )
        embed.set_footer(text="Un fil dédié est créé pour chaque affrontement jouable.")

        try:
            message = await channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"⚠️ Publication résumé {match_kind} ronde {round_number} : {error}")
            await self._release_round_claim(tournament_id, match_kind, round_number)
            return False

        await self.db.execute(
            """
            UPDATE progression_round_publications
            SET channel_id = ?, message_id = ?, status = 'published',
                updated_at = CURRENT_TIMESTAMP
            WHERE tournament_id = ? AND match_kind = ? AND round_number = ?
            """,
            (str(channel.id), str(message.id), tournament_id, match_kind, round_number),
        )
        await self.db.commit()
        return True

    # ==========================================================
    # PUBLICATION BRACKET ET SUISSE
    # ==========================================================

    async def publish_bracket_matches(self, tournament: Any) -> int:
        tournament_id = int(_value(tournament, "id"))
        matches = await self._ready_bracket_matches(tournament_id)
        if not matches:
            return 0

        round_numbers = sorted(
            {int(match.get("round") or 0) for match in matches},
            reverse=True,
        )

        # Le résumé d'une phase n'est publié que lorsque tous ses affrontements
        # sont connus. Les messages individuels restent, eux, immédiats.
        for round_number in round_numbers:
            all_round_matches = await self._all_bracket_round_matches(
                tournament_id,
                round_number,
            )
            if self._bracket_round_is_fully_known(all_round_matches):
                await self._publish_round_summary(
                    tournament=tournament,
                    match_kind=MATCH_KIND_BRACKET,
                    round_number=round_number,
                    matches=all_round_matches,
                )

        published = 0
        for match in matches:
            if await self._publish_single_match(
                tournament=tournament,
                match_kind=MATCH_KIND_BRACKET,
                match=match,
            ):
                published += 1
        return published

    async def publish_swiss_round(
        self,
        tournament: Any,
        round_number: int,
    ) -> int:
        matches = await self._swiss_round_matches(
            int(_value(tournament, "id")),
            round_number,
        )
        if not matches:
            return 0

        await self._publish_round_summary(
            tournament=tournament,
            match_kind=MATCH_KIND_SWISS,
            round_number=round_number,
            matches=matches,
        )

        published = 0
        for match in matches:
            is_bye = int(match.get("is_bye") or 0) == 1 or not match.get("player2_id")
            if is_bye:
                continue
            status = str(match.get("status") or "pending").lower()
            if status in FINAL_MATCH_STATUSES:
                continue
            if await self._publish_single_match(
                tournament=tournament,
                match_kind=MATCH_KIND_SWISS,
                match=match,
            ):
                published += 1
        return published

    async def publish_tournament(self, tournament: Any) -> int:
        total = await self.publish_bracket_matches(tournament)

        settings = await self.db.fetchone(
            "SELECT * FROM swiss_settings WHERE tournament_id = ?",
            (int(_value(tournament, "id")),),
        )
        swiss_settings = _row_to_dict(settings)
        if swiss_settings and str(swiss_settings.get("status") or "").lower() == "running":
            current_round = int(swiss_settings.get("current_round") or 0)
            if current_round > 0:
                total += await self.publish_swiss_round(tournament, current_round)
                await self._maybe_offer_or_generate_next_swiss_round(
                    tournament=tournament,
                    swiss_settings=swiss_settings,
                )
        return total

    # ==========================================================
    # PROGRESSION SUISSE
    # ==========================================================

    async def _pending_swiss_matches(
        self,
        tournament_id: int,
        round_number: int,
    ) -> int:
        value = await self.db.fetchval(
            """
            SELECT COUNT(*)
            FROM swiss_matches
            WHERE tournament_id = ? AND round_number = ?
              AND COALESCE(is_bye, 0) = 0
              AND LOWER(COALESCE(status, 'pending')) NOT IN (
                    'approved', 'cancelled', 'completed',
                    'finished', 'refused', 'rejected'
              )
            """,
            (tournament_id, round_number),
        )
        return int(value or 0)

    async def _claim_swiss_action(
        self,
        tournament_id: int,
        completed_round: int,
        status: str,
    ) -> bool:
        cursor = await self.db.execute(
            """
            INSERT OR IGNORE INTO progression_swiss_actions (
                tournament_id,
                completed_round,
                status
            )
            VALUES (?, ?, ?)
            """,
            (tournament_id, completed_round, status),
        )
        await self.db.commit()
        return cursor.rowcount == 1

    async def _delete_swiss_action(self, tournament_id: int, completed_round: int) -> None:
        await self.db.execute(
            "DELETE FROM progression_swiss_actions WHERE tournament_id = ? AND completed_round = ?",
            (tournament_id, completed_round),
        )
        await self.db.commit()

    async def _maybe_offer_or_generate_next_swiss_round(
        self,
        *,
        tournament: Any,
        swiss_settings: dict[str, Any],
    ) -> None:
        tournament_id = int(_value(tournament, "id"))
        guild_id = str(_value(tournament, "guild_id"))
        current_round = int(swiss_settings.get("current_round") or 0)
        total_rounds = int(swiss_settings.get("total_rounds") or 0)

        if current_round < 1:
            return
        if await self._pending_swiss_matches(tournament_id, current_round) > 0:
            return

        settings = await self._settings(guild_id)
        if settings is None:
            return

        if current_round >= total_rounds:
            claimed = await self._claim_swiss_action(
                tournament_id,
                current_round,
                "finishing",
            )
            if not claimed:
                return

            try:
                await self.db.finish_swiss_tournament(tournament_id)
                channel = (
                    await self._get_text_channel(guild_id, "matches_channel_id")
                    or await self._get_text_channel(guild_id, "staff_channel_id")
                )
                if channel is not None:
                    message = await channel.send(
                        embed=success_embed(
                            title="🏁 Rondes suisses terminées",
                            description=(
                                f"Toutes les rondes suisses de **{_value(tournament, 'name', 'ce tournoi')}** "
                                "sont terminées. Le classement final peut maintenant être affiché."
                            ),
                        )
                    )
                    await self.db.execute(
                        """
                        UPDATE progression_swiss_actions
                        SET status = 'finished', channel_id = ?, message_id = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE tournament_id = ? AND completed_round = ?
                        """,
                        (str(channel.id), str(message.id), tournament_id, current_round),
                    )
                    await self.db.commit()
            except Exception:
                await self._delete_swiss_action(tournament_id, current_round)
                raise
            return

        auto_generate = int(settings.get("auto_generate_swiss") or 0) == 1
        if auto_generate:
            claimed = await self._claim_swiss_action(
                tournament_id,
                current_round,
                "generating",
            )
            if not claimed:
                return
            try:
                await self.swiss.next_round(tournament_id)
                await self.db.execute(
                    """
                    UPDATE progression_swiss_actions
                    SET status = 'generated', updated_at = CURRENT_TIMESTAMP
                    WHERE tournament_id = ? AND completed_round = ?
                    """,
                    (tournament_id, current_round),
                )
                await self.db.commit()
                refreshed = await self.db.get_tournament(tournament_id)
                if refreshed is not None:
                    await self.publish_swiss_round(refreshed, current_round + 1)
            except Exception:
                await self._delete_swiss_action(tournament_id, current_round)
                raise
            return

        claimed = await self._claim_swiss_action(
            tournament_id,
            current_round,
            "prompting",
        )
        if not claimed:
            return

        channel = (
            await self._get_text_channel(guild_id, "staff_channel_id")
            or await self._get_text_channel(guild_id, "matches_channel_id")
        )
        if channel is None:
            await self._delete_swiss_action(tournament_id, current_round)
            return

        embed = discord.Embed(
            title=f"✅ Ronde suisse {current_round} terminée",
            description=(
                "Tous les résultats ont été validés. Le staff peut maintenant "
                f"générer la ronde **{current_round + 1}**."
            ),
            colour=discord.Colour.green(),
        )
        embed.add_field(
            name="🏟️ Tournoi",
            value=f"**{_value(tournament, 'name', 'Tournoi Hamtaro')}**",
            inline=False,
        )
        embed.set_footer(
            text=f"{SWISS_NEXT_FOOTER}{tournament_id}:{current_round}"
        )

        try:
            message = await channel.send(
                embed=embed,
                view=NextSwissRoundView(self),
            )
        except (discord.Forbidden, discord.HTTPException):
            await self._delete_swiss_action(tournament_id, current_round)
            return

        await self.db.execute(
            """
            UPDATE progression_swiss_actions
            SET status = 'prompted', channel_id = ?, message_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE tournament_id = ? AND completed_round = ?
            """,
            (str(channel.id), str(message.id), tournament_id, current_round),
        )
        await self.db.commit()

    def _extract_swiss_next_reference(
        self,
        message: discord.Message | None,
    ) -> tuple[int, int] | None:
        if message is None or not message.embeds:
            return None
        footer = message.embeds[0].footer.text or ""
        pattern = rf"{re.escape(SWISS_NEXT_FOOTER)}(\d+):(\d+)"
        match = re.search(pattern, footer)
        if match is None:
            return None
        return int(match.group(1)), int(match.group(2))

    async def generate_next_swiss_round(
        self,
        *,
        tournament_id: int,
        completed_round: int,
        actor: discord.abc.User,
    ) -> int:
        action = await self.db.fetchone(
            """
            SELECT * FROM progression_swiss_actions
            WHERE tournament_id = ? AND completed_round = ?
            """,
            (tournament_id, completed_round),
        )
        action_dict = _row_to_dict(action)
        if action_dict and str(action_dict.get("status")) == "generated":
            raise ValueError("La ronde suivante a déjà été générée.")

        settings = await self.db.get_swiss_settings(tournament_id)
        if settings is None:
            raise ValueError("Les rondes suisses ne sont pas lancées.")

        current_round = int(settings["current_round"])
        if current_round != completed_round:
            raise ValueError(
                "La progression de ce tournoi a déjà changé. "
                "Actualise le message ou vérifie la ronde actuelle."
            )
        if await self._pending_swiss_matches(tournament_id, completed_round) > 0:
            raise ValueError("Des matchs de la ronde sont encore en attente.")

        await self.swiss.next_round(tournament_id)
        next_round = completed_round + 1

        await self.db.execute(
            """
            INSERT INTO progression_swiss_actions (
                tournament_id, completed_round, status, acted_by
            )
            VALUES (?, ?, 'generated', ?)
            ON CONFLICT(tournament_id, completed_round)
            DO UPDATE SET
                status = 'generated',
                acted_by = excluded.acted_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (tournament_id, completed_round, str(actor.id)),
        )
        await self.db.commit()

        tournament = await self.db.get_tournament(tournament_id)
        if tournament is not None:
            await self.publish_swiss_round(tournament, next_round)
        return next_round

    # ==========================================================
    # INTÉGRATION AVEC RESULTS.PY
    # ==========================================================

    async def handle_result_approved(
        self,
        *,
        guild_id: str,
        tournament_id: int,
        match_kind: str,
        match_id: int,
    ) -> None:
        """Appelé par ResultsCog pour une progression immédiate."""
        del guild_id, match_id
        await asyncio.sleep(0.2)
        tournament = await self.db.get_tournament(tournament_id)
        if tournament is None:
            return
        await self.publish_tournament(tournament)

    # ==========================================================
    # SCAN AUTOMATIQUE
    # ==========================================================

    @tasks.loop(seconds=30)
    async def scan_new_matches(self) -> None:
        try:
            tournaments = await self.db.fetchall(
                """
                SELECT *
                FROM tournaments
                WHERE status NOT IN ('finished', 'cancelled')
                ORDER BY id ASC
                """
            )
            for row in tournaments:
                tournament = await self.db.get_tournament(int(row["id"]))
                if tournament is None:
                    continue
                settings = await self._settings(str(_value(tournament, "guild_id")))
                if settings is None or not settings.get("matches_channel_id"):
                    continue
                try:
                    await self.publish_tournament(tournament)
                except Exception as error:
                    print(
                        f"⚠️ Scan progression tournoi {_value(tournament, 'id')} : {error}"
                    )
        except Exception as error:
            print(f"⚠️ Scan global progression Hamtaro : {error}")

    @scan_new_matches.before_loop
    async def before_scan_new_matches(self) -> None:
        await self.bot.wait_until_ready()

    # ==========================================================
    # COMMANDES
    # ==========================================================

    @app_commands.command(
        name="progression_setup",
        description="Configurer la publication automatique des matchs Hamtaro",
    )
    @app_commands.describe(
        matches_channel="Salon public où afficher les nouveaux matchs",
        staff_channel="Salon où proposer la ronde suisse suivante",
        staff_role="Rôle staff autorisé à générer les rondes",
        create_threads="Créer automatiquement un fil par match",
        auto_generate_swiss="Générer la ronde suivante sans clic du staff",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def progression_setup(
        self,
        interaction: discord.Interaction,
        matches_channel: discord.TextChannel,
        staff_channel: discord.TextChannel | None = None,
        staff_role: discord.Role | None = None,
        create_threads: bool = True,
        auto_generate_swiss: bool = False,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild.id)
        staff_channel = staff_channel or matches_channel

        await self.db.execute(
            """
            INSERT INTO progression_settings (
                guild_id,
                matches_channel_id,
                staff_channel_id,
                staff_role_id,
                create_threads,
                auto_generate_swiss,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                matches_channel_id = excluded.matches_channel_id,
                staff_channel_id = excluded.staff_channel_id,
                staff_role_id = excluded.staff_role_id,
                create_threads = excluded.create_threads,
                auto_generate_swiss = excluded.auto_generate_swiss,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                guild_id,
                str(matches_channel.id),
                str(staff_channel.id),
                str(staff_role.id) if staff_role else None,
                int(create_threads),
                int(auto_generate_swiss),
            ),
        )
        await self.db.commit()

        embed = success_embed(
            title="Progression automatique configurée",
            description=(
                "Hamtaro détectera désormais les nouveaux affrontements et "
                "les publiera automatiquement."
            ),
        )
        embed.add_field(
            name="⚔️ Salon des matchs",
            value=matches_channel.mention,
            inline=False,
        )
        embed.add_field(
            name="🛠️ Salon staff",
            value=staff_channel.mention,
            inline=False,
        )
        embed.add_field(
            name="💬 Fils automatiques",
            value="Activés" if create_threads else "Désactivés",
            inline=True,
        )
        embed.add_field(
            name="🔄 Ronde suisse automatique",
            value="Activée" if auto_generate_swiss else "Validation staff",
            inline=True,
        )
        embed.add_field(
            name="🛡️ Rôle staff",
            value=staff_role.mention if staff_role else "Système staff actuel",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        tournaments = await self.db.fetchall(
            """
            SELECT id FROM tournaments
            WHERE guild_id = ? AND status NOT IN ('finished', 'cancelled')
            """,
            (guild_id,),
        )
        for row in tournaments:
            tournament = await self.db.get_tournament(int(row["id"]))
            if tournament is not None:
                await self.publish_tournament(tournament)

    @app_commands.command(
        name="publish_matches",
        description="Forcer la publication des matchs nouvellement disponibles",
    )
    @app_commands.describe(code="Code facultatif du tournoi")
    @app_commands.default_permissions(manage_guild=True)
    async def publish_matches(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            tournament = await resolve_tournament(
                interaction,
                self.db,
                code=code,
            )
            if tournament is None:
                raise ValueError("Aucun tournoi sélectionné.")
            published = await self.publish_tournament(tournament)
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(title="Publication impossible", description=str(error)),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=info_embed(
                title="Publication vérifiée",
                description=(
                    f"**{published}** nouveau(x) match(s) ont été publiés. "
                    "Les matchs déjà annoncés n'ont pas été renvoyés."
                ),
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="generate_next_round",
        description="Générer la prochaine ronde suisse terminée",
    )
    @app_commands.describe(code="Code facultatif du tournoi")
    @app_commands.default_permissions(manage_guild=True)
    async def generate_next_round_command(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            tournament = await resolve_tournament(
                interaction,
                self.db,
                code=code,
            )
            if tournament is None:
                raise ValueError("Aucun tournoi sélectionné.")
            settings = await self.db.get_swiss_settings(int(_value(tournament, "id")))
            if settings is None:
                raise ValueError("Les rondes suisses ne sont pas lancées.")
            completed_round = int(settings["current_round"])
            next_round = await self.generate_next_swiss_round(
                tournament_id=int(_value(tournament, "id")),
                completed_round=completed_round,
                actor=interaction.user,
            )
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(title="Génération impossible", description=str(error)),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success_embed(
                title=f"Ronde {next_round} générée",
                description="Les matchs et leurs fils Discord ont été publiés.",
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="progression_status",
        description="Voir la configuration de progression Hamtaro",
    )
    async def progression_status(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        settings = await self._settings(str(interaction.guild.id))
        if settings is None:
            await interaction.response.send_message(
                embed=info_embed(
                    title="Progression non configurée",
                    description="Le staff doit utiliser `/progression_setup`.",
                ),
                ephemeral=True,
            )
            return

        matches_channel = interaction.guild.get_channel(
            int(settings["matches_channel_id"])
        ) if settings.get("matches_channel_id") else None
        staff_channel = interaction.guild.get_channel(
            int(settings["staff_channel_id"])
        ) if settings.get("staff_channel_id") else None

        embed = discord.Embed(
            title="⚙️ Progression automatique Hamtaro",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(
            name="Salon des matchs",
            value=matches_channel.mention if matches_channel else "Introuvable",
            inline=False,
        )
        embed.add_field(
            name="Salon staff",
            value=staff_channel.mention if staff_channel else "Introuvable",
            inline=False,
        )
        embed.add_field(
            name="Fils automatiques",
            value="Oui" if int(settings.get("create_threads") or 0) else "Non",
            inline=True,
        )
        embed.add_field(
            name="Rondes suisses automatiques",
            value="Oui" if int(settings.get("auto_generate_swiss") or 0) else "Avec validation staff",
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentProgressionCog(bot))
