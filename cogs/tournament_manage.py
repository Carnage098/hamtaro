from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import error_embed, success_embed
from utils.permissions import is_staff_member
from utils.tournament_resolver import active_tournament_code_autocomplete, resolve_tournament


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    try:
        return obj[name]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, name, default)


def _status(obj: Any) -> str:
    raw = _value(obj, "status", "")
    return str(getattr(raw, "value", raw)).lower().strip()


class TournamentSettingsModal(discord.ui.Modal, title="Paramètres du tournoi"):
    format_value = discord.ui.TextInput(
        label="Format",
        placeholder="Laisser vide pour ne pas modifier",
        required=False,
        max_length=80,
    )
    capacity_value = discord.ui.TextInput(
        label="Capacité",
        placeholder="4, 8, 16, 32, 64, 128...",
        required=False,
        max_length=3,
    )

    def __init__(self, cog: "TournamentManageCog", tournament_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.tournament_id = tournament_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            changes = await self.cog.update_tournament_settings(
                tournament_id=self.tournament_id,
                new_format=str(self.format_value.value).strip() or None,
                capacity_text=str(self.capacity_value.value).strip() or None,
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=success_embed(
                title="Tournoi mis à jour",
                description="\n".join(f"• {item}" for item in changes),
            ),
            ephemeral=True,
        )


class DeckChangeModal(discord.ui.Modal, title="Changer le deck du joueur"):
    deck = discord.ui.TextInput(
        label="Nouveau deck",
        placeholder="Cyber Dragon",
        required=True,
        max_length=100,
    )

    def __init__(
        self,
        cog: "TournamentManageCog",
        tournament_id: int,
        player_id: str,
        player_name: str,
    ) -> None:
        super().__init__()
        self.cog = cog
        self.tournament_id = tournament_id
        self.player_id = player_id
        self.player_name = player_name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.change_player_deck(
                tournament_id=self.tournament_id,
                player_id=self.player_id,
                deck=str(self.deck.value),
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ Deck de **{self.player_name}** remplacé par **{str(self.deck.value).strip()}**.",
            ephemeral=True,
        )


class PlayerRemoveConfirm(discord.ui.View):
    def __init__(
        self,
        cog: "TournamentManageCog",
        requester_id: int,
        tournament_id: int,
        player_id: str,
        player_name: str,
    ) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.requester_id = requester_id
        self.tournament_id = tournament_id
        self.player_id = player_id
        self.player_name = player_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.requester_id

    @discord.ui.button(label="Confirmer la désinscription", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            await self.cog.remove_player(
                tournament_id=self.tournament_id,
                player_id=self.player_id,
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ **{self.player_name}** a été désinscrit du tournoi.",
            view=self,
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Annulé.", view=self)


class PlayerActionView(discord.ui.View):
    def __init__(
        self,
        cog: "TournamentManageCog",
        requester_id: int,
        tournament_id: int,
        player: dict[str, Any],
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.requester_id = requester_id
        self.tournament_id = tournament_id
        self.player = player

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("❌ Ce panneau staff ne t'appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Changer deck", emoji="🎴", style=discord.ButtonStyle.primary)
    async def change_deck(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            DeckChangeModal(
                self.cog,
                self.tournament_id,
                str(self.player["discord_id"]),
                str(self.player.get("display_name") or self.player.get("username") or "Joueur"),
            )
        )

    @discord.ui.button(label="Désinscrire", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        name = str(self.player.get("display_name") or self.player.get("username") or "Joueur")
        await interaction.response.send_message(
            f"⚠️ Désinscrire **{name}** ?",
            view=PlayerRemoveConfirm(
                self.cog,
                interaction.user.id,
                self.tournament_id,
                str(self.player["discord_id"]),
                name,
            ),
            ephemeral=True,
        )


class PlayerSelect(discord.ui.Select):
    def __init__(
        self,
        cog: "TournamentManageCog",
        requester_id: int,
        tournament_id: int,
        players: list[dict[str, Any]],
        page: int,
    ) -> None:
        self.cog = cog
        self.requester_id = requester_id
        self.tournament_id = tournament_id
        self.players = players
        self.page = page
        start = page * 25
        options = []
        for index, player in enumerate(players[start : start + 25], start=start):
            name = str(player.get("display_name") or player.get("username") or player.get("discord_id"))
            deck = str(player.get("deck") or "Deck non renseigné")
            options.append(
                discord.SelectOption(
                    label=name[:100],
                    description=deck[:100],
                    value=str(index),
                )
            )
        super().__init__(placeholder="Choisir un joueur", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("❌ Ce menu ne t'appartient pas.", ephemeral=True)
            return
        player = self.players[int(self.values[0])]
        name = str(player.get("display_name") or player.get("username") or "Joueur")
        embed = discord.Embed(title=f"👤 {name}", color=discord.Color.gold())
        embed.add_field(name="Discord ID", value=f"`{player.get('discord_id')}`", inline=False)
        embed.add_field(name="Deck", value=str(player.get("deck") or "Non renseigné"), inline=False)
        await interaction.response.send_message(
            embed=embed,
            view=PlayerActionView(
                self.cog,
                self.requester_id,
                self.tournament_id,
                player,
            ),
            ephemeral=True,
        )


class PlayerListView(discord.ui.View):
    def __init__(
        self,
        cog: "TournamentManageCog",
        requester_id: int,
        tournament_id: int,
        players: list[dict[str, Any]],
        page: int = 0,
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.requester_id = requester_id
        self.tournament_id = tournament_id
        self.players = players
        self.page = max(0, min(page, max(0, (len(players) - 1) // 25)))
        if players:
            self.add_item(PlayerSelect(cog, requester_id, tournament_id, players, self.page))
        self.previous.disabled = self.page <= 0
        self.next.disabled = (self.page + 1) * 25 >= len(players)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.requester_id

    @discord.ui.button(label="Précédents", style=discord.ButtonStyle.secondary, row=2)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            view=PlayerListView(
                self.cog, self.requester_id, self.tournament_id, self.players, self.page - 1
            )
        )

    @discord.ui.button(label="Suivants", style=discord.ButtonStyle.secondary, row=2)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            view=PlayerListView(
                self.cog, self.requester_id, self.tournament_id, self.players, self.page + 1
            )
        )


class FinishConfirmView(discord.ui.View):
    def __init__(self, cog: "TournamentManageCog", requester_id: int, tournament_id: int) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.requester_id = requester_id
        self.tournament_id = tournament_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.requester_id

    @discord.ui.button(label="Terminer définitivement", emoji="🏁", style=discord.ButtonStyle.danger)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        end_cog = self.cog.bot.get_cog("EndTournamentCog")
        if end_cog is None or not hasattr(end_cog, "finish_from_manage"):
            await interaction.response.send_message("❌ Le module de fin de tournoi n'est pas disponible.", ephemeral=True)
            return
        await end_cog.finish_from_manage(interaction, self.tournament_id)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Fin du tournoi annulée.", view=None)


class TournamentManageView(discord.ui.View):
    def __init__(self, cog: "TournamentManageCog", requester_id: int, tournament_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.requester_id = requester_id
        self.tournament_id = tournament_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("❌ Ce panneau staff ne t'appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Vue générale", emoji="📋", style=discord.ButtonStyle.primary)
    async def overview(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        tournament = await self.cog.db.get_tournament(self.tournament_id)
        await interaction.response.edit_message(
            embed=await self.cog.manage_embed(tournament),
            view=TournamentManageView(self.cog, self.requester_id, self.tournament_id),
        )

    @discord.ui.button(label="Joueurs", emoji="👥", style=discord.ButtonStyle.secondary)
    async def players(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        players = await self.cog.list_players(self.tournament_id)
        if not players:
            await interaction.response.send_message("📭 Aucun joueur inscrit.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"👥 **{len(players)} joueur(s)** — page 1/{max(1, (len(players)+24)//25)}",
            view=PlayerListView(self.cog, self.requester_id, self.tournament_id, players),
            ephemeral=True,
        )

    @discord.ui.button(label="Matchs", emoji="⚔️", style=discord.ButtonStyle.secondary)
    async def matches(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=await self.cog.matches_embed(self.tournament_id), ephemeral=True
        )

    @discord.ui.button(label="Publier", emoji="📣", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        progression = self.cog.bot.get_cog("TournamentProgressionCog")
        tournament = await self.cog.db.get_tournament(self.tournament_id)
        if progression is None or tournament is None:
            await interaction.followup.send("❌ Progression indisponible.", ephemeral=True)
            return
        count = await progression.publish_tournament(tournament)
        await interaction.followup.send(f"✅ **{count}** nouveau(x) match(s) publié(s).", ephemeral=True)

    @discord.ui.button(label="Paramètres", emoji="⚙️", style=discord.ButtonStyle.secondary)
    async def settings(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(TournamentSettingsModal(self.cog, self.tournament_id))

    @discord.ui.button(label="Résultats", emoji="✅", style=discord.ButtonStyle.secondary, row=1)
    async def results(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=await self.cog.results_embed(self.tournament_id), ephemeral=True
        )

    @discord.ui.button(label="Pause / Reprise", emoji="⏯️", style=discord.ButtonStyle.secondary, row=1)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        match_center = self.cog.bot.get_cog("MatchCenterCog")
        tournament = await self.cog.db.get_tournament(self.tournament_id)
        if match_center is None or tournament is None:
            await interaction.response.send_message("❌ Match Center indisponible.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if await match_center.is_tournament_paused(self.tournament_id):
            seconds = await match_center.resume_tournament_runtime(
                tournament=tournament, actor=interaction.user
            )
            progression = self.cog.bot.get_cog("TournamentProgressionCog")
            if progression is not None:
                await progression.publish_tournament(tournament)
            await interaction.followup.send(
                f"▶️ Tournoi repris après {seconds // 60} min {seconds % 60:02d} s de pause.",
                ephemeral=True,
            )
        else:
            await match_center.pause_tournament_runtime(
                tournament=tournament,
                actor=interaction.user,
                reason="Pause déclenchée depuis /tournament_manage",
            )
            await interaction.followup.send("⏸️ Tournoi mis en pause.", ephemeral=True)

    @discord.ui.button(label="Bracket", emoji="🌳", style=discord.ButtonStyle.secondary, row=1)
    async def bracket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=await self.cog.bracket_embed(self.tournament_id), ephemeral=True
        )

    @discord.ui.button(label="Terminer", emoji="🏁", style=discord.ButtonStyle.danger, row=1)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "⚠️ Hamtaro va figer les résultats, recalculer les profils, désactiver les panneaux et archiver les fils du tournoi.",
            view=FinishConfirmView(self.cog, self.requester_id, self.tournament_id),
            ephemeral=True,
        )


class TournamentManageCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db

    async def _ensure_staff(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        allowed = bool(
            isinstance(member, discord.Member)
            and (
                member.guild_permissions.administrator
                or member.guild_permissions.manage_guild
                or is_staff_member(member)
            )
        )
        if not allowed:
            await interaction.response.send_message("❌ Seul le staff peut utiliser ce panneau.", ephemeral=True)
        return allowed

    async def _columns(self, table: str) -> set[str]:
        rows = await self.db.fetchall(f"PRAGMA table_info({table})")
        return {str(row["name"] if "name" in row.keys() else row[1]) for row in rows}

    async def list_players(self, tournament_id: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT r.*, COALESCE(p.display_name, p.username, r.username, r.discord_id) AS display_name
            FROM registrations r
            JOIN tournaments t ON t.id = r.tournament_id
            LEFT JOIN players p ON p.guild_id = t.guild_id AND p.discord_id = r.discord_id
            WHERE r.tournament_id = ?
            ORDER BY LOWER(COALESCE(p.display_name, p.username, r.username, r.discord_id))
            """,
            (tournament_id,),
        )
        return [dict(row) for row in rows]

    async def manage_embed(self, tournament: Any) -> discord.Embed:
        tournament_id = int(_value(tournament, "id", 0))
        players = await self.list_players(tournament_id)
        bracket_count = int(
            await self.db.fetchval("SELECT COUNT(*) FROM matches WHERE tournament_id = ?", (tournament_id,)) or 0
        )
        swiss_count = 0
        try:
            swiss_count = int(
                await self.db.fetchval("SELECT COUNT(*) FROM swiss_matches WHERE tournament_id = ?", (tournament_id,)) or 0
            )
        except Exception:
            pass
        open_results = 0
        try:
            open_results = int(
                await self.db.fetchval(
                    "SELECT COUNT(*) FROM result_requests WHERE tournament_id = ? AND status IN ('pending','confirmed','contested','processing')",
                    (tournament_id,),
                ) or 0
            )
        except Exception:
            pass
        paused = False
        match_center = self.bot.get_cog("MatchCenterCog")
        if match_center is not None:
            paused = await match_center.is_tournament_paused(tournament_id)
        embed = discord.Embed(
            title=f"🛠️ Gestion — {_value(tournament, 'name', 'Tournoi Hamtaro')}",
            description="Toutes les actions principales du staff sont regroupées ici.",
            color=discord.Color.orange() if paused else discord.Color.gold(),
        )
        embed.add_field(name="Code", value=f"`{_value(tournament, 'code', '?')}`", inline=True)
        embed.add_field(name="Format", value=str(_value(tournament, "format", "?")), inline=True)
        embed.add_field(name="État", value="⏸️ Pause" if paused else str(_value(tournament, "status", "?")), inline=True)
        embed.add_field(
            name="Joueurs",
            value=f"**{len(players)}/{_value(tournament, 'max_players', '?')}**",
            inline=True,
        )
        embed.add_field(name="Matchs", value=f"**{bracket_count + swiss_count}**", inline=True)
        embed.add_field(name="Résultats en attente", value=f"**{open_results}**", inline=True)
        embed.set_footer(text="Les anciennes commandes de changement de format/capacité et pause/reprise sont remplacées par ce panneau.")
        return embed

    async def update_tournament_settings(
        self,
        *,
        tournament_id: int,
        new_format: str | None,
        capacity_text: str | None,
    ) -> list[str]:
        tournament = await self.db.get_tournament(tournament_id)
        if tournament is None:
            raise ValueError("Tournoi introuvable.")
        if _status(tournament) in {"finished", "cancelled"}:
            raise ValueError("Un tournoi terminé ou annulé est figé.")
        changes: list[str] = []
        if new_format:
            clean = " ".join(new_format.split())
            await self.db.execute("UPDATE tournaments SET format = ? WHERE id = ?", (clean, tournament_id))
            changes.append(f"Format → **{clean}**")
        if capacity_text:
            try:
                capacity = int(capacity_text)
            except ValueError as error:
                raise ValueError("La capacité doit être un nombre.") from error
            if not 4 <= capacity <= 256:
                raise ValueError("La capacité doit être comprise entre 4 et 256.")
            current = len(await self.list_players(tournament_id))
            if capacity < current:
                raise ValueError(f"Il y a déjà {current} joueurs inscrits.")
            columns = await self._columns("tournaments")
            is_swiss = False
            if "tournament_type" in columns:
                is_swiss = str(_value(tournament, "tournament_type", "")).lower() == "swiss"
            else:
                try:
                    is_swiss = bool(await self.db.fetchone("SELECT 1 FROM swiss_settings WHERE tournament_id = ?", (tournament_id,)))
                except Exception:
                    is_swiss = False
            if not is_swiss and capacity not in {4, 8, 16, 32, 64, 128}:
                raise ValueError("En élimination directe : 4, 8, 16, 32, 64 ou 128 joueurs.")
            target_column = "max_players" if "max_players" in columns else "size" if "size" in columns else None
            if target_column is None:
                raise ValueError("La colonne de capacité est introuvable dans la base.")
            await self.db.execute(f"UPDATE tournaments SET {target_column} = ? WHERE id = ?", (capacity, tournament_id))
            changes.append(f"Capacité → **{capacity}**")
        if not changes:
            raise ValueError("Aucune modification n'a été renseignée.")
        await self.db.commit()
        return changes

    async def change_player_deck(self, *, tournament_id: int, player_id: str, deck: str) -> None:
        clean = " ".join(deck.split()).strip()
        if not clean:
            raise ValueError("Le deck ne peut pas être vide.")
        changed = await self.db.update(
            "UPDATE registrations SET deck = ? WHERE tournament_id = ? AND discord_id = ?",
            (clean, tournament_id, player_id),
        )
        if changed != 1:
            raise ValueError("Inscription introuvable.")

    async def remove_player(self, *, tournament_id: int, player_id: str) -> None:
        tournament = await self.db.get_tournament(tournament_id)
        if tournament is None:
            raise ValueError("Tournoi introuvable.")
        if _status(tournament) not in {"registration", "ready", "draft", "open"}:
            raise ValueError("Après le lancement, utilise une décision staff plutôt qu'une désinscription.")
        changed = await self.db.update(
            "DELETE FROM registrations WHERE tournament_id = ? AND discord_id = ?",
            (tournament_id, player_id),
        )
        if changed != 1:
            raise ValueError("Inscription introuvable.")

    async def matches_embed(self, tournament_id: int) -> discord.Embed:
        rows: list[dict[str, Any]] = []
        for table, kind, round_col, position_col in (
            ("matches", "match", "round", "match_number"),
            ("swiss_matches", "match", "round_number", "table_number"),
        ):
            try:
                found = await self.db.fetchall(
                    f"SELECT id, {round_col} AS round_number, {position_col} AS position, player1_name, player2_name, status FROM {table} WHERE tournament_id = ? ORDER BY {round_col}, {position_col}",
                    (tournament_id,),
                )
                rows.extend(dict(row) for row in found)
            except Exception:
                continue
        embed = discord.Embed(title="⚔️ Matchs du tournoi", color=discord.Color.blurple())
        if not rows:
            embed.description = "Aucun match généré."
            return embed
        statuses: dict[str, int] = {}
        for row in rows:
            key = str(row.get("status") or "?")
            statuses[key] = statuses.get(key, 0) + 1
        embed.description = " · ".join(f"**{count}** {status}" for status, count in sorted(statuses.items()))
        lines = []
        for row in rows[:15]:
            lines.append(
                f"• R{row.get('round_number', '?')} · **{row.get('player1_name') or '?'}** vs **{row.get('player2_name') or '?'}** — `{row.get('status')}`"
            )
        embed.add_field(name="Aperçu", value="\n".join(lines), inline=False)
        if len(rows) > 15:
            embed.set_footer(text=f"{len(rows) - 15} autres matchs non affichés.")
        return embed

    async def results_embed(self, tournament_id: int) -> discord.Embed:
        embed = discord.Embed(title="✅ Résultats du tournoi", color=discord.Color.green())
        try:
            rows = await self.db.fetchall(
                """
                SELECT match_kind, match_id, player1_score, player2_score, result_type, status
                FROM result_requests
                WHERE tournament_id = ?
                ORDER BY updated_at DESC
                LIMIT 20
                """,
                (tournament_id,),
            )
        except Exception:
            rows = []
        if not rows:
            embed.description = "Aucune demande de résultat enregistrée."
            return embed
        pending = sum(str(row["status"]) in {"pending", "confirmed", "contested", "processing"} for row in rows)
        embed.description = f"**{pending}** résultat(s) encore en attente de décision."
        lines = []
        for row in rows[:15]:
            item = dict(row)
            label = "Double Loss" if item.get("result_type") == "double_loss" else f"{item.get('player1_score')}-{item.get('player2_score')}"
            lines.append(f"• Match #{item.get('match_id')} · **{label}** — `{item.get('status')}`")
        embed.add_field(name="Dernières demandes", value="\n".join(lines), inline=False)
        return embed

    async def bracket_embed(self, tournament_id: int) -> discord.Embed:
        embed = discord.Embed(title="🌳 État du bracket", color=discord.Color.gold())
        try:
            rows = await self.db.fetchall(
                """
                SELECT round, COUNT(*) AS total,
                       SUM(CASE WHEN winner_id IS NOT NULL THEN 1 ELSE 0 END) AS finished
                FROM matches WHERE tournament_id = ?
                GROUP BY round ORDER BY round DESC
                """,
                (tournament_id,),
            )
        except Exception:
            rows = []
        if not rows:
            embed.description = "Ce tournoi n'a pas de bracket à élimination directe."
            try:
                swiss = await self.db.fetchone(
                    "SELECT current_round, total_rounds, status FROM swiss_settings WHERE tournament_id = ?",
                    (tournament_id,),
                )
                if swiss is not None:
                    embed.description = (
                        f"Progression des rondes : **{swiss['current_round']}/{swiss['total_rounds']}** · `{swiss['status']}`"
                    )
            except Exception:
                pass
            return embed
        embed.description = "\n".join(
            f"• Round **{row['round']}** : {row['finished']}/{row['total']} terminé(s)"
            for row in rows
        )
        embed.set_footer(text="L'image officielle reste disponible avec /bracket ou /final_bracket.")
        return embed

    @app_commands.command(
        name="tournament_manage",
        description="Ouvrir le panneau de contrôle complet d'un tournoi",
    )
    @app_commands.describe(code="Code facultatif du tournoi")
    @app_commands.autocomplete(code=active_tournament_code_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def tournament_manage(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            tournament = await resolve_tournament(interaction, self.db, code=code, require_active=False)
        except ValueError as error:
            await interaction.followup.send(
                embed=error_embed(title="Tournoi introuvable", description=str(error)),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=await self.manage_embed(tournament),
            view=TournamentManageView(
                self,
                interaction.user.id,
                int(_value(tournament, "id")),
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentManageCog(bot))
