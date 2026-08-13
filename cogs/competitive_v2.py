from __future__ import annotations

import os
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from services.deck_intelligence_service import DeckIntelligenceService
from services.tournament_live_service import TournamentLiveService
from utils.permissions import staff_only


FORMATS = (
    "Format Actuel",
    "Master Duel",
    "Genesys",
    "GOAT",
    "Edison",
    "HAT",
    "Tengu Plant",
    "Dragon Ruler",
    "TeleDAD",
    "Rush Duel",
    "Speed Duel",
)


class TournamentNameModal(discord.ui.Modal, title="Créer le tournoi Hamtaro"):
    name = discord.ui.TextInput(
        label="Nom du tournoi",
        placeholder="Hamtaro CUP #12",
        max_length=80,
    )

    def __init__(self, owner_view: "TournamentAssistantView") -> None:
        super().__init__()
        self.owner_view = owner_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette action doit être faite dans un serveur.",
                ephemeral=True,
            )
            return
        try:
            tournament = await view.cog.bot.db.create_tournament(
                guild_id=str(interaction.guild.id),
                name=str(self.name.value).strip(),
                format=view.format_name,
                max_players=view.capacity,
                created_by=str(interaction.user.id),
            )
            await view.cog.live.save_settings(
                tournament.id,
                structure=view.structure,
                best_of=view.best_of,
                public_decks=True,
                live_enabled=True,
            )
            if interaction.channel_id is not None:
                try:
                    await view.cog.bot.db.select_tournament_for_channel(
                        str(interaction.guild.id),
                        str(interaction.channel_id),
                        tournament.id,
                        selected_by=str(interaction.user.id),
                    )
                except Exception:
                    pass
        except Exception as error:
            await interaction.response.send_message(
                f"❌ Création impossible : {error}",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="✅ Tournoi créé",
            description=(
                f"**{tournament.name}** (`{tournament.code}`)\n"
                "Le tournoi utilise les services Hamtaro existants ; "
                "l'assistant ne remplace aucune commande."
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="Format", value=view.format_name)
        embed.add_field(name="Structure", value=view.structure_label)
        embed.add_field(name="Matchs", value=f"BO{view.best_of}")
        embed.add_field(name="Capacité", value=str(view.capacity))
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TournamentAssistantView(discord.ui.View):
    def __init__(self, cog: "CompetitiveV2Cog", user_id: int) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.user_id = user_id
        self.format_name = "Format Actuel"
        self.structure = "elimination"
        self.structure_label = "Élimination directe"
        self.best_of = 3
        self.capacity = 16

        format_select = discord.ui.Select(
            placeholder="1. Format",
            options=[
                discord.SelectOption(label=name, value=name)
                for name in FORMATS
            ],
            row=0,
        )
        structure_select = discord.ui.Select(
            placeholder="2. Structure",
            options=[
                discord.SelectOption(
                    label="Élimination directe",
                    value="elimination",
                    emoji="🌳",
                ),
                discord.SelectOption(
                    label="Rondes suisses",
                    value="swiss",
                    emoji="🇨🇭",
                ),
            ],
            row=1,
        )
        bo_select = discord.ui.Select(
            placeholder="3. Durée des matchs",
            options=[
                discord.SelectOption(label="BO1", value="1"),
                discord.SelectOption(label="BO3", value="3", default=True),
                discord.SelectOption(label="BO5", value="5"),
            ],
            row=2,
        )
        capacity_select = discord.ui.Select(
            placeholder="4. Capacité",
            options=[
                discord.SelectOption(
                    label=f"{value} joueurs",
                    value=str(value),
                    default=value == 16,
                )
                for value in (4, 8, 16, 32, 64)
            ],
            row=3,
        )
        create_button = discord.ui.Button(
            label="Résumé et création",
            style=discord.ButtonStyle.success,
            emoji="🏆",
            row=4,
        )

        async def format_cb(interaction: discord.Interaction) -> None:
            self.format_name = format_select.values[0]
            await interaction.response.defer()

        async def structure_cb(interaction: discord.Interaction) -> None:
            self.structure = structure_select.values[0]
            self.structure_label = (
                "Rondes suisses"
                if self.structure == "swiss"
                else "Élimination directe"
            )
            await interaction.response.defer()

        async def bo_cb(interaction: discord.Interaction) -> None:
            self.best_of = int(bo_select.values[0])
            await interaction.response.defer()

        async def capacity_cb(interaction: discord.Interaction) -> None:
            self.capacity = int(capacity_select.values[0])
            await interaction.response.defer()

        async def create_cb(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(TournamentNameModal(self))

        format_select.callback = format_cb
        structure_select.callback = structure_cb
        bo_select.callback = bo_cb
        capacity_select.callback = capacity_cb
        create_button.callback = create_cb

        self.add_item(format_select)
        self.add_item(structure_select)
        self.add_item(bo_select)
        self.add_item(capacity_select)
        self.add_item(create_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Cet assistant appartient au membre du staff qui l'a ouvert.",
                ephemeral=True,
            )
            return False
        return True


class CompetitiveV2Cog(commands.Cog):
    broadcast = app_commands.Group(
        name="broadcast",
        description="Diffusion et matchs live Hamtaro",
    )
    deck_registry = app_commands.Group(
        name="deck_registry",
        description="Normalisation des noms de decks Hamtaro",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.live = TournamentLiveService()
        self.decks = DeckIntelligenceService()

    async def cog_load(self) -> None:
        await self.live.ensure_schema()
        await self.decks.ensure_schema(self.bot.db)

    @app_commands.command(
        name="tournament_assistant",
        description="Créer un tournoi avec l'assistant interactif Hamtaro",
    )
    @staff_only()
    async def tournament_assistant(
        self,
        interaction: discord.Interaction,
    ) -> None:
        view = TournamentAssistantView(self, interaction.user.id)
        embed = discord.Embed(
            title="🧠 Assistant de création de tournoi",
            description=(
                "Choisis le **format**, la **structure**, le **BO** et la "
                "**capacité**, puis clique sur **Résumé et création**.\n\n"
                "Les commandes historiques restent disponibles."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )

    @deck_registry.command(
        name="resolve",
        description="Voir le nom canonique qu'Hamtaro utilisera",
    )
    async def deck_resolve(
        self,
        interaction: discord.Interaction,
        nom: str,
    ) -> None:
        if interaction.guild is None:
            return
        canonical = await self.decks.canonicalize(
            self.bot.db,
            str(interaction.guild.id),
            nom,
        )
        await interaction.response.send_message(
            f"🎴 `{nom}` → **{canonical or 'Non renseigné'}**",
            ephemeral=True,
        )

    @deck_registry.command(
        name="alias",
        description="Associer un alias à un nom de deck canonique",
    )
    @staff_only()
    async def deck_alias(
        self,
        interaction: discord.Interaction,
        alias: str,
        canonique: str,
    ) -> None:
        if interaction.guild is None:
            return
        value = await self.decks.add_alias(
            self.bot.db,
            str(interaction.guild.id),
            alias,
            canonique,
            str(interaction.user.id),
        )
        await interaction.response.send_message(
            f"✅ `{alias}` sera désormais enregistré comme **{value}**.",
            ephemeral=True,
        )

    @broadcast.command(
        name="feature",
        description="Mettre un match en vedette sur Hamtaro Live",
    )
    @staff_only()
    async def feature(
        self,
        interaction: discord.Interaction,
        tournoi_id: int,
        match_id: int,
        type_match: str = "bracket",
    ) -> None:
        kind = "swiss" if type_match.lower().startswith("s") else "bracket"
        try:
            await self.live.set_featured(
                tournoi_id,
                kind,
                match_id,
                str(interaction.user.id),
            )
        except ValueError as error:
            await interaction.response.send_message(
                f"❌ {error}", ephemeral=True
            )
            return
        base = os.getenv("WEBSITE_BASE_URL", "").rstrip("/")
        await interaction.response.send_message(
            f"⭐ Match `{kind}:{match_id}` mis en vedette.\n"
            + (f"🌐 {base}/live" if base else ""),
            ephemeral=False,
        )

    @broadcast.command(
        name="links",
        description="Envoyer aux joueurs leurs liens privés de partage d'écran",
    )
    @staff_only()
    async def links(
        self,
        interaction: discord.Interaction,
        tournoi_id: int,
        match_id: int,
        type_match: str = "bracket",
    ) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        kind = "swiss" if type_match.lower().startswith("s") else "bracket"
        match = await self.live.match(kind, match_id)
        if not match or int(match["tournament_id"]) != tournoi_id:
            await interaction.followup.send("❌ Match introuvable.", ephemeral=True)
            return
        base = os.getenv("WEBSITE_BASE_URL", "").rstrip("/")
        if not base:
            await interaction.followup.send(
                "❌ WEBSITE_BASE_URL n'est pas configurée.", ephemeral=True
            )
            return

        sent = []
        failed = []
        for slot in (1, 2):
            player_id = str(match.get(f"player{slot}_id") or "")
            player_name = str(match.get(f"player{slot}_name") or player_id)
            if not player_id.isdigit():
                continue
            token = await self.live.create_publish_token(
                tournament_id=tournoi_id,
                kind=kind,
                match_id=match_id,
                player_id=player_id,
            )
            url = f"{base}/live/publish/{token}"
            member = interaction.guild.get_member(int(player_id))
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(int(player_id))
                except Exception:
                    member = None
            if member is None:
                failed.append(player_name)
                continue
            try:
                await member.send(
                    "🔴 **Hamtaro Live**\n"
                    "Tu peux diffuser volontairement ton écran pour ce match.\n"
                    "Le navigateur te demandera exactement quel écran ou onglet "
                    "tu souhaites partager. Aucun enregistrement automatique.\n\n"
                    f"{url}"
                )
                sent.append(player_name)
            except discord.HTTPException:
                failed.append(player_name)

        message = (
            f"✅ Liens envoyés : {', '.join(sent) if sent else 'aucun'}."
        )
        if failed:
            message += f"\n⚠️ DM impossible : {', '.join(failed)}."
        await interaction.followup.send(message, ephemeral=True)

    @broadcast.command(
        name="stop",
        description="Révoquer les liens de diffusion d'un match",
    )
    @staff_only()
    async def stop(
        self,
        interaction: discord.Interaction,
        match_id: int,
        type_match: str = "bracket",
    ) -> None:
        kind = "swiss" if type_match.lower().startswith("s") else "bracket"
        await self.live.revoke_match_tokens(kind, match_id)
        await interaction.response.send_message(
            f"⏹️ Liens de diffusion révoqués pour `{kind}:{match_id}`.",
            ephemeral=True,
        )

    @broadcast.command(
        name="status",
        description="Voir les matchs actuellement diffusés",
    )
    async def status(
        self,
        interaction: discord.Interaction,
        tournoi_id: int,
    ) -> None:
        try:
            center = await self.live.live_center(tournoi_id)
        except ValueError as error:
            await interaction.response.send_message(
                f"❌ {error}", ephemeral=True
            )
            return
        live_matches = center["live_matches"]
        lines = [
            f"🔴 `{m['kind']}:{m['id']}` — "
            f"{m.get('player1_name') or '?'} vs {m.get('player2_name') or '?'}"
            for m in live_matches
        ]
        await interaction.response.send_message(
            "\n".join(lines) if lines else "⚫ Aucun match diffusé actuellement.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CompetitiveV2Cog(bot))
