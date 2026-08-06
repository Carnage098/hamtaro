from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from services.expansion_database import init_expansion_schema
from services.tournament_start_service import (
    SINGLE_ELIMINATION,
    TournamentStartService,
)
from utils.expansion_permissions import is_staff_member, staff_only
try:
    from utils.tournament_resolver import (
        active_tournament_code_autocomplete,
        resolve_tournament,
    )
except ImportError:
    from utils.tournament_resolver import resolve_tournament

    async def active_tournament_code_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        del interaction, current
        return []


LOGGER = logging.getLogger(__name__)


ROUND_LABELS = {
    1: "Finale",
    2: "Demi-finales",
    3: "Quarts de finale",
    4: "Huitièmes de finale",
    5: "Seizièmes de finale",
    6: "32es de finale",
    7: "64es de finale",
}


def _chunk_lines(lines: list[str], limit: int = 950) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in lines:
        size = len(line) + 1
        if current and current_size + size > limit:
            chunks.append("\n".join(current))
            current = []
            current_size = 0
        current.append(line)
        current_size += size
    if current:
        chunks.append("\n".join(current))
    return chunks or ["Aucun appariement."]


class SeedOrderModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        cog: "TournamentStartPreviewCog",
        preview: dict[str, Any],
        source_message: discord.Message,
    ) -> None:
        super().__init__(title="Modifier les seeds du bracket", timeout=600)
        self.cog = cog
        self.preview = preview
        self.source_message = source_message

        initial = "\n".join(
            f"{player['seed']} = {player['discord_id']}"
            for player in preview["players"]
        )
        self.order = discord.ui.TextInput(
            label="Ordre des seeds",
            style=discord.TextStyle.paragraph,
            default=initial[:4000],
            placeholder="1 = identifiant Discord\n2 = identifiant Discord",
            required=True,
            max_length=4000,
        )
        self.add_item(self.order)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await is_staff_member(interaction.user):
            await interaction.response.send_message(
                "❌ Cette action est réservée au staff.",
                ephemeral=True,
            )
            return
        participant_ids = [
            str(player["discord_id"]) for player in self.preview["players"]
        ]
        try:
            ordered_ids = self.cog.service.parse_seed_order(
                str(self.order.value), participant_ids
            )
            updated = await self.cog.service.update_seed_order(
                int(self.preview["id"]), ordered_ids
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        except Exception as error:
            LOGGER.exception("Erreur pendant la modification des seeds", exc_info=error)
            await interaction.response.send_message(
                "❌ Les seeds n'ont pas pu être modifiés.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        view = PendingStartView(cog=self.cog, preview=updated)
        try:
            await self.source_message.edit(
                embed=self.cog.build_preview_embed(updated),
                view=view,
            )
        except discord.HTTPException:
            pass
        await interaction.followup.send(
            "✅ Les seeds et les affiches de la première ronde ont été recalculés.",
            ephemeral=True,
        )


class PendingStartView(discord.ui.View):
    def __init__(
        self,
        *,
        cog: "TournamentStartPreviewCog",
        preview: dict[str, Any],
    ) -> None:
        super().__init__(timeout=3600)
        self.cog = cog
        self.preview = preview
        self.preview_id = int(preview["id"])

        confirm = discord.ui.Button(
            label="Confirmer et lancer",
            emoji="✅",
            style=discord.ButtonStyle.success,
        )
        confirm.callback = self.confirm_callback
        self.add_item(confirm)

        if preview["tournament_type"] == SINGLE_ELIMINATION:
            reshuffle = discord.ui.Button(
                label="Remélanger",
                emoji="🔀",
                style=discord.ButtonStyle.primary,
            )
            reshuffle.callback = self.reshuffle_callback
            self.add_item(reshuffle)

            seeds = discord.ui.Button(
                label="Modifier les seeds",
                emoji="🔢",
                style=discord.ButtonStyle.secondary,
            )
            seeds.callback = self.seeds_callback
            self.add_item(seeds)

        cancel = discord.ui.Button(
            label="Annuler le brouillon",
            emoji="✖️",
            style=discord.ButtonStyle.danger,
        )
        cancel.callback = self.cancel_callback
        self.add_item(cancel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await is_staff_member(interaction.user):
            return True
        await interaction.response.send_message(
            "❌ Ces boutons sont réservés au staff.",
            ephemeral=True,
        )
        return False

    async def confirm_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            confirmed = await self.cog.service.confirm_preview(
                self.preview_id,
                str(interaction.user.id),
            )
        except (ValueError, RuntimeError) as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return
        except Exception as error:
            LOGGER.exception("Erreur pendant la confirmation du tournoi", exc_info=error)
            await interaction.followup.send(
                "❌ Le tournoi n'a pas pu être lancé. Les créations partielles ont été annulées.",
                ephemeral=True,
            )
            return

        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(
            embed=self.cog.build_confirmed_embed(confirmed),
            view=self,
        )
        await interaction.followup.send(
            "✅ Le tournoi est maintenant réellement lancé.",
            ephemeral=True,
        )

    async def reshuffle_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            updated = await self.cog.service.reshuffle(self.preview_id)
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return
        self.preview = updated
        await interaction.edit_original_response(
            embed=self.cog.build_preview_embed(updated),
            view=PendingStartView(cog=self.cog, preview=updated),
        )

    async def seeds_callback(self, interaction: discord.Interaction) -> None:
        preview = await self.cog.service.get_preview(self.preview_id)
        if preview is None:
            await interaction.response.send_message(
                "❌ Ce brouillon n'existe plus.", ephemeral=True
            )
            return
        if interaction.message is None:
            await interaction.response.send_message(
                "❌ Le message de prévisualisation est introuvable.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            SeedOrderModal(
                cog=self.cog,
                preview=preview,
                source_message=interaction.message,
            )
        )

    async def cancel_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            cancelled = await self.cog.service.cancel_preview(
                self.preview_id, str(interaction.user.id)
            )
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        embed = self.cog.build_preview_embed(cancelled)
        embed.title = f"✖️ Brouillon annulé — {cancelled['tournament_name']}"
        embed.colour = discord.Colour.red()
        await interaction.edit_original_response(embed=embed, view=self)


class TournamentStartPreviewCog(commands.Cog):
    """Remplace le démarrage immédiat par une validation staff en deux étapes."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = TournamentStartService(bot)

    async def cog_load(self) -> None:
        await init_expansion_schema()

    @staticmethod
    def structure_label(preview: dict[str, Any]) -> str:
        if preview["tournament_type"] == SINGLE_ELIMINATION:
            return "Élimination directe"
        return "Rondes suisses"

    @staticmethod
    def _round_plan(preview: dict[str, Any]) -> list[str]:
        total_rounds = int(preview["total_rounds"])
        if preview["tournament_type"] == SINGLE_ELIMINATION:
            return [
                (
                    f"• **{ROUND_LABELS.get(round_number, f'Ronde {round_number}')}** "
                    + (
                        "— affiches proposées ci-dessous"
                        if round_number == total_rounds
                        else "— en attente des vainqueurs"
                    )
                )
                for round_number in range(total_rounds, 0, -1)
            ]
        return [
            (
                f"• **Ronde {round_number}** — "
                + ("appariements proposés ci-dessous" if round_number == 1 else "à générer après validation de la ronde précédente")
            )
            for round_number in range(1, total_rounds + 1)
        ]

    def build_preview_embed(self, preview: dict[str, Any]) -> discord.Embed:
        embed = discord.Embed(
            title=f"⏳ Démarrage en attente — {preview['tournament_name']}",
            description=(
                "Aucun match réel n'a encore été créé. Vérifie les rondes et les "
                "appariements, puis confirme ou modifie le brouillon."
            ),
            colour=discord.Colour.orange(),
        )
        embed.add_field(
            name="Tournoi",
            value=(
                f"Code : `{preview['tournament_code']}`\n"
                f"Format : **{preview['tournament_format']}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Structure",
            value=(
                f"**{self.structure_label(preview)}**\n"
                f"{len(preview['players'])} joueurs • {preview['total_rounds']} rondes"
            ),
            inline=True,
        )
        embed.add_field(
            name="État",
            value=f"**En attente du staff**\nVersion du tirage : `{preview['version']}`",
            inline=True,
        )

        plan_chunks = _chunk_lines(self._round_plan(preview))
        for index, chunk in enumerate(plan_chunks, start=1):
            embed.add_field(
                name="🗓️ Plan des rondes" if index == 1 else "🗓️ Plan des rondes — suite",
                value=chunk,
                inline=False,
            )

        pairing_lines: list[str] = []
        for pairing in preview["pairings"]:
            table = int(pairing["table_number"])
            player1 = f"**#{self._seed_for(preview, pairing['player1_id'])}** {pairing['player1_name']}"
            if pairing.get("is_bye") or not pairing.get("player2_id"):
                pairing_lines.append(f"Table {table} — {player1} reçoit un **BYE**")
            else:
                player2 = f"**#{self._seed_for(preview, pairing['player2_id'])}** {pairing['player2_name']}"
                pairing_lines.append(f"Table {table} — {player1} **vs** {player2}")

        for index, chunk in enumerate(_chunk_lines(pairing_lines), start=1):
            embed.add_field(
                name=(
                    "🎯 Première ronde proposée"
                    if index == 1
                    else "🎯 Première ronde — suite"
                ),
                value=chunk,
                inline=False,
            )

        if preview["tournament_type"] == SINGLE_ELIMINATION:
            seed_lines = [
                f"`#{player['seed']}` — {player['username']} (`{player['discord_id']}`)"
                for player in preview["players"]
            ]
            for index, chunk in enumerate(_chunk_lines(seed_lines), start=1):
                embed.add_field(
                    name="🔢 Seeds" if index == 1 else "🔢 Seeds — suite",
                    value=chunk,
                    inline=False,
                )
            embed.set_footer(
                text="Remélanger change tous les seeds. Modifier les seeds permet un ordre manuel."
            )
        else:
            embed.set_footer(
                text="Les rondes suivantes seront générées à partir des résultats et du classement suisse."
            )
        return embed

    @staticmethod
    def _seed_for(preview: dict[str, Any], discord_id: Any) -> int | str:
        wanted = str(discord_id)
        for player in preview["players"]:
            if str(player["discord_id"]) == wanted:
                return int(player["seed"])
        return "?"

    def build_confirmed_embed(self, preview: dict[str, Any]) -> discord.Embed:
        embed = self.build_preview_embed(preview)
        embed.title = f"✅ Tournoi lancé — {preview['tournament_name']}"
        embed.description = (
            "Le staff a confirmé ce tirage. Les matchs de la première ronde sont "
            "maintenant enregistrés et accessibles aux joueurs."
        )
        embed.colour = discord.Colour.green()
        embed.set_footer(text="Le brouillon est archivé dans l'historique Hamtaro.")
        return embed

    async def _selected_tournament(
        self,
        interaction: discord.Interaction,
        code: str | None,
    ) -> Any:
        # Les versions récentes du resolver acceptent `code` et
        # `require_active`. Le fallback conserve la compatibilité avec les
        # anciennes versions de Hamtaro.
        try:
            tournament = await resolve_tournament(
                interaction,
                self.bot.db,
                code=code,
                require_active=True,
            )
        except TypeError:
            tournament = None
            if code and interaction.guild is not None:
                getter = getattr(self.bot.db, "get_tournament_by_code", None)
                if callable(getter):
                    tournament = await getter(
                        str(interaction.guild.id),
                        code,
                    )
            if tournament is None:
                tournament = await resolve_tournament(interaction, self.bot.db)

        if tournament is None and interaction.guild is not None:
            tournament = await self.bot.db.get_active_tournament(
                str(interaction.guild.id)
            )
        if tournament is None:
            raise ValueError("Aucun tournoi actif ou sélectionné n'a été trouvé.")
        return tournament

    async def _start_preview(
        self,
        interaction: discord.Interaction,
        *,
        code: str | None,
        rondes: int | None,
        visible: bool,
        recreer: bool,
        require_swiss: bool | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=not visible)
        if interaction.guild is None:
            await interaction.followup.send(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return
        try:
            tournament = await self._selected_tournament(interaction, code)
            tournament_type = self.service.tournament_type(tournament)
            if require_swiss is True and tournament_type != "swiss":
                raise ValueError(
                    "Le tournoi sélectionné est à élimination directe. Utilise `/start_tournament`."
                )
            preview = await self.service.create_preview(
                guild_id=str(interaction.guild.id),
                tournament=tournament,
                total_rounds=rondes,
                actor_id=str(interaction.user.id),
                channel_id=str(interaction.channel_id) if interaction.channel_id else None,
                force_new_draw=recreer,
            )
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return
        except Exception as error:
            LOGGER.exception("Erreur pendant la préparation du tournoi", exc_info=error)
            await interaction.followup.send(
                "❌ La prévisualisation du tournoi n'a pas pu être créée.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=self.build_preview_embed(preview),
            view=PendingStartView(cog=self, preview=preview),
            ephemeral=not visible,
        )

    @app_commands.command(
        name="start_tournament",
        description="Prévisualiser les rondes puis confirmer le lancement du tournoi",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi à préparer",
        rondes="Nombre de rondes suisses ; calcul automatique si omis",
        visible="Afficher le brouillon publiquement",
        recreer="Abandonner l'ancien brouillon et refaire le tirage",
    )
    @app_commands.autocomplete(code=active_tournament_code_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def start_tournament(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
        rondes: app_commands.Range[int, 1, 30] | None = None,
        visible: bool = False,
        recreer: bool = False,
    ) -> None:
        await self._start_preview(
            interaction,
            code=code,
            rondes=rondes,
            visible=visible,
            recreer=recreer,
        )

    @app_commands.command(
        name="swiss_start",
        description="Alias : prévisualiser puis confirmer le lancement suisse",
    )
    @app_commands.describe(
        code="Code facultatif du tournoi suisse à préparer",
        rondes="Nombre total de rondes suisses",
        visible="Afficher le brouillon publiquement",
        recreer="Abandonner l'ancien brouillon et refaire les appariements",
    )
    @app_commands.autocomplete(code=active_tournament_code_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    async def swiss_start(
        self,
        interaction: discord.Interaction,
        code: str | None = None,
        rondes: app_commands.Range[int, 1, 30] | None = None,
        visible: bool = False,
        recreer: bool = False,
    ) -> None:
        await self._start_preview(
            interaction,
            code=code,
            rondes=rondes,
            visible=visible,
            recreer=recreer,
            require_swiss=True,
        )


async def setup(bot: commands.Bot) -> None:
    # Les anciens cogs restent chargés pour leurs autres commandes, mais leurs
    # démarrages immédiats sont remplacés par le flux de prévisualisation.
    for command_name in ("start_tournament", "swiss_start"):
        try:
            bot.tree.remove_command(command_name)
        except Exception:
            LOGGER.debug("Commande %s absente avant remplacement.", command_name)
    await bot.add_cog(TournamentStartPreviewCog(bot))
