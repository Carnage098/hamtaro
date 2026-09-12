from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from contextlib import suppress
from typing import Any

import discord
from discord.ext import commands

from services.boss_arena_service import BossArenaService


LOGGER = logging.getLogger("hamtaro.boss.arena")


class BossMatchView(discord.ui.View):
    """Vue persistante commune à tous les fils Boss.

    Le match est retrouvé grâce à l'identifiant du fil Discord ; aucun identifiant
    de match n'est encodé dans le custom_id, ce qui permet de réutiliser la même
    vue après un redémarrage Railway.
    """

    def __init__(self, coordinator: "BossArenaCoordinator") -> None:
        super().__init__(timeout=None)
        self.coordinator = coordinator

    @discord.ui.button(
        label="Victoire Boss",
        emoji="👑",
        style=discord.ButtonStyle.primary,
        custom_id="hamtaro:boss_arena:report_boss",
    )
    async def report_boss(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.coordinator.handle_report(interaction, winner_side="boss")

    @discord.ui.button(
        label="Victoire Challenger",
        emoji="⚔️",
        style=discord.ButtonStyle.success,
        custom_id="hamtaro:boss_arena:report_challenger",
    )
    async def report_challenger(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.coordinator.handle_report(interaction, winner_side="challenger")

    @discord.ui.button(
        label="Confirmer",
        emoji="✅",
        style=discord.ButtonStyle.secondary,
        custom_id="hamtaro:boss_arena:confirm",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.coordinator.handle_confirmation(interaction)

    @discord.ui.button(
        label="Contester",
        emoji="⚠️",
        style=discord.ButtonStyle.danger,
        custom_id="hamtaro:boss_arena:contest",
    )
    async def contest(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.coordinator.handle_contest(interaction)


class BossArenaCoordinator:
    def __init__(self, bot: commands.Bot, boss_service: Any) -> None:
        self.bot = bot
        self.boss_service = boss_service
        self.store = BossArenaService()
        self._guild_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._watch_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        await self.store.ensure_schema()
        self.bot.add_view(BossMatchView(self))
        if self._watch_task is None or self._watch_task.done():
            creator = getattr(self.bot, "create_background_task", None)
            if callable(creator):
                self._watch_task = creator(
                    self._watch_loop(), name="hamtaro-boss-arena-watch"
                )
            else:
                self._watch_task = asyncio.create_task(
                    self._watch_loop(), name="hamtaro-boss-arena-watch"
                )

    def cog_unload(self) -> None:
        if self._watch_task is not None and not self._watch_task.done():
            self._watch_task.cancel()

    async def _watch_loop(self) -> None:
        await self.bot.wait_until_ready()
        try:
            while not self.bot.is_closed():
                for guild in list(self.bot.guilds):
                    try:
                        await self.maybe_start_next(guild)
                    except Exception:
                        LOGGER.exception(
                            "Surveillance de la file Boss impossible pour %s", guild.id
                        )
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise

    async def settings(self, guild_id: str) -> dict[str, Any]:
        return await self.store.settings(guild_id)

    async def challenger_has_active_match(
        self, guild_id: str, challenger_id: str
    ) -> bool:
        return (
            await self.store.match_for_challenger(guild_id, challenger_id)
        ) is not None

    async def reset_for_new_boss(self, guild_id: str) -> None:
        await self.store.clear_configuration(guild_id)

    async def on_manual_boss_change(
        self,
        guild: discord.Guild,
        *,
        old_boss_id: str | None,
        new_boss_id: str,
    ) -> None:
        guild_id = str(guild.id)
        await self.store.clear_configuration(guild_id)
        with suppress(ValueError):
            await self.boss_service.unregister_challenger(
                guild_id, new_boss_id, force=True
            )
        if not old_boss_id or str(old_boss_id) == str(new_boss_id):
            return
        rows = await self.store.active_matches_for_boss(guild_id, str(old_boss_id))
        for row in rows:
            await self.store.cancel_match(
                int(row["id"]),
                reason="Le staff a changé le Boss manuellement",
                restore_challenger=True,
            )
            await self._finish_thread(
                guild,
                row,
                text=(
                    "🔒 **Match fermé automatiquement.**\n"
                    "Le staff a changé le Boss. Le challenger retourne dans la file."
                ),
            )

    async def configure(
        self,
        guild: discord.Guild,
        *,
        boss_id: str,
        platform_key: str,
        format_key: str,
    ) -> dict[str, Any]:
        if await self.store.active_match(str(guild.id)):
            raise ValueError(
                "Impossible de changer de plateforme ou de format pendant un match Boss actif."
            )
        settings = await self.store.configure(
            str(guild.id),
            boss_id,
            platform_key,
            format_key,
        )
        await self.maybe_start_next(guild)
        return settings

    async def set_match_channel(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
    ) -> None:
        await self.store.set_match_channel(str(guild.id), str(channel.id))
        await self.maybe_start_next(guild)

    def platform_label(self, key: str | None) -> str:
        return self.store.PLATFORM_LABELS.get(str(key), str(key or "Non choisie"))

    def format_label(self, key: str | None) -> str:
        return self.store.FORMAT_LABELS.get(str(key), str(key or "Non choisi"))

    async def recover_and_start(self, guild: discord.Guild) -> None:
        """Répare seulement un match dont le fil a réellement disparu."""
        guild_id = str(guild.id)
        async with self._guild_locks[guild_id]:
            active = await self.store.active_match(guild_id)
            if active and active.get("thread_id"):
                thread = guild.get_thread(int(active["thread_id"]))
                if thread is None:
                    try:
                        fetched = await guild.fetch_channel(int(active["thread_id"]))
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        fetched = None
                    if not isinstance(fetched, discord.Thread):
                        await self.store.cancel_match(
                            int(active["id"]),
                            reason="Fil Discord introuvable après redémarrage",
                            restore_challenger=True,
                        )
                else:
                    return
            elif active and active.get("status") == "creating":
                await self.store.cancel_match(
                    int(active["id"]),
                    reason="Création interrompue avant le redémarrage",
                    restore_challenger=True,
                )
        await self.maybe_start_next(guild)

    async def maybe_start_next(self, guild: discord.Guild) -> dict[str, Any] | None:
        guild_id = str(guild.id)
        async with self._guild_locks[guild_id]:
            if await self.store.active_match(guild_id):
                return None

            state = await self.boss_service.state(guild_id)
            boss_id = str(state.get("boss_id") or "")
            if not boss_id or str(state.get("status") or "") != "active":
                return None

            settings = await self.store.settings(guild_id)
            if str(settings.get("configured_boss_id") or "") != boss_id:
                return None
            if not settings.get("platform_key") or not settings.get("format_key"):
                return None

            channel_id = str(settings.get("match_channel_id") or "")
            if not channel_id.isdigit():
                return None
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                try:
                    fetched = await guild.fetch_channel(int(channel_id))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    return None
                channel = fetched if isinstance(fetched, discord.TextChannel) else None
            if channel is None:
                return None

            challengers = await self.boss_service.challengers(guild_id)
            challenger = next(
                (
                    row
                    for row in challengers
                    if str(row.get("status")) in {"registered", "scheduled"}
                    and str(row.get("discord_id")) != boss_id
                ),
                None,
            )
            if challenger is None:
                return None

            platform_key = str(
                challenger.get("preferred_platform_key")
                or settings["platform_key"]
            )
            format_key = str(
                challenger.get("preferred_format_key")
                or settings["format_key"]
            )
            try:
                self.store.validate_configuration(platform_key, format_key)
            except ValueError:
                platform_key = str(settings["platform_key"])
                format_key = str(settings["format_key"])

            try:
                match = await self.store.create_match(
                    guild_id=guild_id,
                    reign_number=int(state.get("week_number") or 1),
                    boss_id=boss_id,
                    boss_name=str(state.get("boss_name") or boss_id),
                    challenger_id=str(challenger["discord_id"]),
                    challenger_name=str(challenger["username"]),
                    challenger_row_id=int(challenger["id"]),
                    platform_key=platform_key,
                    format_key=format_key,
                )
            except ValueError:
                return None

            embed = self._match_embed(match)
            message: discord.Message | None = None
            thread: discord.Thread | None = None
            try:
                message = await channel.send(embed=embed)
                thread_name = self._thread_name(match)
                thread = await message.create_thread(
                    name=thread_name,
                    auto_archive_duration=1440,
                )
                await self.store.attach_discord_resources(
                    int(match["id"]),
                    parent_channel_id=str(channel.id),
                    announcement_message_id=str(message.id),
                    thread_id=str(thread.id),
                )
                availability_line = (
                    f"🕒 Disponibilité annoncée : {challenger['availability']}\n"
                    if challenger.get("availability")
                    else ""
                )
                await thread.send(
                    content=(
                        f"👑 Boss : <@{match['boss_id']}>\n"
                        f"⚔️ Challenger : <@{match['challenger_id']}>\n"
                        f"🎮 {self.platform_label(match['platform_key'])}\n"
                        f"🎴 {self.format_label(match['format_key'])}\n"
                        + availability_line
                        +
                        "🏆 BO3\n\n"
                        "À la fin du duel, un joueur déclare le vainqueur puis "
                        "l'autre joueur confirme."
                    ),
                    view=BossMatchView(self),
                )
                return await self.store.match_by_thread(guild_id, str(thread.id))
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.exception("Impossible de créer le fil de match Boss dans %s", channel.id)
                await self.store.cancel_match(
                    int(match["id"]),
                    reason="Discord a refusé la création du fil",
                    restore_challenger=True,
                )
                if thread is not None:
                    with suppress(discord.HTTPException, discord.Forbidden):
                        await thread.edit(locked=True, archived=True)
                if message is not None:
                    with suppress(discord.HTTPException, discord.Forbidden):
                        await message.edit(content="❌ Création du match Boss annulée.")
                return None

    def _match_embed(self, match: dict[str, Any]) -> discord.Embed:
        embed = discord.Embed(
            title=f"👑 BOSS MATCH #{match['id']}",
            description=(
                f"<@{match['boss_id']}> **VS** <@{match['challenger_id']}>\n\n"
                f"🎮 **{self.platform_label(match['platform_key'])}**\n"
                f"🎴 **{self.format_label(match['format_key'])}**\n"
                "🏆 **BO3**\n"
                "🔴 Match en cours"
            ),
            colour=discord.Colour.orange(),
        )
        embed.set_footer(text="Format Boss · Hamtaro")
        return embed

    @staticmethod
    def _thread_name(match: dict[str, Any]) -> str:
        boss = str(match.get("boss_name") or "boss")
        challenger = str(match.get("challenger_name") or "challenger")
        raw = f"boss-{boss}-vs-{challenger}".lower()
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "-" for ch in raw)
        return safe[:95].strip(" -") or f"boss-match-{match['id']}"

    async def _match_from_interaction(
        self,
        interaction: discord.Interaction,
    ) -> dict[str, Any] | None:
        if interaction.guild is None or interaction.channel_id is None:
            await interaction.response.send_message(
                "❌ Ce bouton doit être utilisé dans un fil de match Boss.",
                ephemeral=True,
            )
            return None
        match = await self.store.match_by_thread(
            str(interaction.guild.id),
            str(interaction.channel_id),
        )
        if match is None:
            await interaction.response.send_message(
                "❌ Hamtaro ne retrouve pas ce match Boss.",
                ephemeral=True,
            )
            return None
        return match

    @staticmethod
    def _participants(match: dict[str, Any]) -> set[str]:
        return {str(match["boss_id"]), str(match["challenger_id"])}

    async def handle_report(
        self,
        interaction: discord.Interaction,
        *,
        winner_side: str,
    ) -> None:
        match = await self._match_from_interaction(interaction)
        if match is None:
            return
        user_id = str(interaction.user.id)
        if user_id not in self._participants(match):
            await interaction.response.send_message(
                "❌ Seuls le Boss et son challenger peuvent utiliser ces boutons.",
                ephemeral=True,
            )
            return
        winner_id = (
            str(match["boss_id"])
            if winner_side == "boss"
            else str(match["challenger_id"])
        )
        try:
            claim = await self.store.report_result(
                int(match["id"]),
                winner_id=winner_id,
                reporter_id=user_id,
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        other_id = next(pid for pid in self._participants(match) if pid != user_id)
        await interaction.response.send_message(
            f"✅ Résultat déclaré. <@{other_id}> doit maintenant confirmer ou contester.",
            ephemeral=True,
        )
        if isinstance(interaction.channel, discord.Thread):
            with suppress(discord.HTTPException, discord.Forbidden):
                await interaction.channel.send(
                    f"📊 Résultat déclaré : <@{claim['reported_winner_id']}> gagnant. "
                    f"<@{other_id}>, utilise **Confirmer** ou **Contester**."
                )

    async def handle_confirmation(self, interaction: discord.Interaction) -> None:
        match = await self._match_from_interaction(interaction)
        if match is None:
            return
        if str(match.get("status")) != "pending_confirmation" or not match.get("reported_winner_id"):
            await interaction.response.send_message(
                "❌ Aucun résultat n'attend de confirmation.",
                ephemeral=True,
            )
            return
        user_id = str(interaction.user.id)
        if user_id not in self._participants(match):
            await interaction.response.send_message(
                "❌ Seuls les joueurs du match peuvent confirmer.",
                ephemeral=True,
            )
            return
        if user_id == str(match.get("reported_by")):
            await interaction.response.send_message(
                "❌ Le joueur qui déclare le résultat ne peut pas le confirmer lui-même.",
                ephemeral=True,
            )
            return

        winner_id = str(match["reported_winner_id"])
        winner = interaction.guild.get_member(int(winner_id)) if interaction.guild else None
        winner_name = winner.display_name if winner is not None else winner_id

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.finalize_result(
                interaction.guild,
                challenger_id=str(match["challenger_id"]),
                winner_id=winner_id,
                winner_name=winner_name,
                arena_match=match,
            )
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        if result["boss_won"]:
            await interaction.followup.send("✅ Résultat confirmé : le Boss conserve son trône.", ephemeral=True)
        else:
            await interaction.followup.send(
                f"✅ Résultat confirmé : <@{result['new_boss_id']}> devient immédiatement le nouveau Boss.",
                ephemeral=True,
            )

    async def handle_contest(self, interaction: discord.Interaction) -> None:
        match = await self._match_from_interaction(interaction)
        if match is None:
            return
        if str(match.get("status")) != "pending_confirmation":
            await interaction.response.send_message(
                "❌ Aucun résultat n'attend de contestation.",
                ephemeral=True,
            )
            return
        user_id = str(interaction.user.id)
        if user_id not in self._participants(match):
            await interaction.response.send_message(
                "❌ Seuls les joueurs du match peuvent contester.",
                ephemeral=True,
            )
            return
        if user_id == str(match.get("reported_by")):
            await interaction.response.send_message(
                "❌ Le déclarant ne peut pas contester sa propre déclaration.",
                ephemeral=True,
            )
            return
        await self.store.mark_disputed(int(match["id"]))
        await interaction.response.send_message(
            "⚠️ Résultat contesté. Le fil reste ouvert et le staff peut trancher avec `/boss resultat`.",
            ephemeral=True,
        )
        if isinstance(interaction.channel, discord.Thread):
            with suppress(discord.HTTPException, discord.Forbidden):
                await interaction.channel.send(
                    "⚠️ **Résultat contesté.** Le match reste ouvert jusqu'à la décision du staff."
                )

    async def finalize_manual(
        self,
        guild: discord.Guild,
        *,
        challenger_id: str,
        winner_id: str,
        winner_name: str,
    ) -> dict[str, Any]:
        arena_match = await self.store.match_for_challenger(str(guild.id), challenger_id)
        return await self.finalize_result(
            guild,
            challenger_id=challenger_id,
            winner_id=winner_id,
            winner_name=winner_name,
            arena_match=arena_match,
        )

    async def finalize_result(
        self,
        guild: discord.Guild | None,
        *,
        challenger_id: str,
        winner_id: str,
        winner_name: str,
        arena_match: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if guild is None:
            raise ValueError("Serveur Discord introuvable.")
        guild_id = str(guild.id)
        async with self._guild_locks[guild_id]:
            before = await self.boss_service.state(guild_id)
            old_boss_id = str(before.get("boss_id") or "")
            old_boss_name = str(before.get("boss_name") or old_boss_id)
            old_reign = int(before.get("week_number") or 1)

            result = await self.boss_service.record_result(
                guild_id,
                challenger_id,
                winner_id,
                winner_name,
            )

            if result["boss_won"]:
                state = result["state"]
                if arena_match is not None:
                    await self.store.complete_match(int(arena_match["id"]), winner_id)
                    await self._finish_thread(
                        guild,
                        arena_match,
                        text=(
                            f"👑 **LE BOSS CONSERVE SON TRÔNE**\n"
                            f"<@{old_boss_id}> remporte le duel.\n"
                            f"🔥 Série actuelle : **{int(state.get('wins_current') or 0)} victoire(s)**."
                        ),
                    )
                await self._announce(
                    guild,
                    title="👑 LE BOSS CONSERVE SON TRÔNE",
                    description=(
                        f"<@{old_boss_id}> bat <@{challenger_id}>.\n"
                        f"🔥 Série : **{int(state.get('wins_current') or 0)} victoire(s)**."
                    ),
                )
                output = {
                    **result,
                    "new_boss_id": old_boss_id,
                    "migrated": 0,
                }
            else:
                # Le service historique pose d'abord successor_id. On applique
                # immédiatement son mécanisme next_week afin de conserver toutes
                # ses écritures d'historique sans attendre une vraie semaine.
                after = await self.boss_service.next_week(guild_id)
                new_boss_id = str(after.get("boss_id") or challenger_id)
                new_reign = int(after.get("week_number") or old_reign + 1)

                migrated = await self.store.migrate_waiting_challengers(
                    guild_id,
                    old_reign=old_reign,
                    new_reign=new_reign,
                    excluded_ids={new_boss_id},
                )
                await self.boss_service.set_registrations(guild_id, True)
                await self.store.clear_configuration(guild_id)

                active_rows = await self.store.active_matches_for_boss(guild_id, old_boss_id)
                for row in active_rows:
                    if arena_match is not None and int(row["id"]) == int(arena_match["id"]):
                        continue
                    await self.store.cancel_match(
                        int(row["id"]),
                        reason="Le Boss a été détrôné dans un autre match",
                        restore_challenger=False,
                    )
                    await self._finish_thread(
                        guild,
                        row,
                        text=(
                            "🔒 **Match fermé automatiquement.**\n"
                            "Le Boss a été détrôné dans un autre match. "
                            "Ta place est conservée dans la file du nouveau Boss."
                        ),
                    )

                if arena_match is not None:
                    await self.store.complete_match(int(arena_match["id"]), winner_id)
                    await self._finish_thread(
                        guild,
                        arena_match,
                        text=(
                            "⚔️ **LE BOSS EST TOMBÉ !**\n"
                            f"<@{challenger_id}> détrône <@{old_boss_id}> et devient "
                            "immédiatement le nouveau Boss."
                        ),
                    )

                await self._announce(
                    guild,
                    title="⚔️ LE BOSS EST TOMBÉ !",
                    description=(
                        f"<@{challenger_id}> détrône <@{old_boss_id}>.\n\n"
                        f"👑 **Nouveau Boss : <@{new_boss_id}>**\n"
                        f"♻️ **{migrated}** challenger(s) conservé(s) dans la file.\n"
                        "Le nouveau Boss doit choisir sa plateforme et son format avec `/boss config`."
                    ),
                )
                output = {
                    **result,
                    "state": after,
                    "new_boss_id": new_boss_id,
                    "old_boss_id": old_boss_id,
                    "old_boss_name": old_boss_name,
                    "migrated": migrated,
                }

        # Hors du verrou : éviter qu'une création de fil Discord longue ne bloque
        # une confirmation concurrente déjà terminée.
        if output["boss_won"]:
            await self.maybe_start_next(guild)
        return output

    async def _finish_thread(
        self,
        guild: discord.Guild,
        match: dict[str, Any],
        *,
        text: str,
    ) -> None:
        thread_id = str(match.get("thread_id") or "")
        if not thread_id.isdigit():
            return
        thread = guild.get_thread(int(thread_id))
        if thread is None:
            try:
                fetched = await guild.fetch_channel(int(thread_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                fetched = None
            thread = fetched if isinstance(fetched, discord.Thread) else None
        if thread is None:
            return
        with suppress(discord.HTTPException, discord.Forbidden):
            await thread.send(text)
        with suppress(discord.HTTPException, discord.Forbidden):
            await thread.edit(locked=True, archived=True)

    async def _announce(
        self,
        guild: discord.Guild,
        *,
        title: str,
        description: str,
    ) -> None:
        state = await self.boss_service.state(str(guild.id))
        channel_id = str(state.get("announcement_channel_id") or "")
        if not channel_id.isdigit():
            return
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return
        embed = discord.Embed(
            title=title,
            description=description,
            colour=discord.Colour.orange(),
        )
        embed.set_footer(text="Format Boss · Hamtaro")
        with suppress(discord.HTTPException, discord.Forbidden):
            await channel.send(embed=embed)
