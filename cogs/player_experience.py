from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.expansion_database import init_expansion_schema
from services.player_experience_service import PlayerExperienceService
from utils.expansion_permissions import staff_only


class PlayerExperienceCog(commands.Cog):
    duelist = app_commands.Group(
        name="duelist",
        description="Profil enrichi, tableau de bord, decks et succès",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = PlayerExperienceService()

    async def cog_load(self) -> None:
        await init_expansion_schema()

    @duelist.command(name="profile", description="Afficher la carte complète d'un duelliste")
    async def profile(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member | None = None,
        visible: bool = False,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        target = joueur or interaction.user
        await interaction.response.defer(ephemeral=not visible)
        data = await self.service.profile(str(interaction.guild.id), str(target.id))
        profile = data["profile"]
        stats = data["tournament_stats"]
        embed = discord.Embed(
            title=f"🐹 Profil de {target.display_name}",
            description=(profile.get("about") or "Aucune présentation enregistrée."),
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name="🎮 Préférences",
            value=(
                f"Formats : **{profile.get('favorite_formats') or 'Non renseignés'}**\n"
                f"Simulateurs : **{profile.get('simulators') or 'Non renseignés'}**\n"
                f"Disponibilités : **{profile.get('availability') or 'Non renseignées'}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏟️ Tournois",
            value=(
                f"Participations : **{int(stats.get('tournaments') or 0)}**\n"
                f"Titres : **{int(stats.get('titles') or 0)}** • Finales : **{int(stats.get('finals') or 0)}**\n"
                f"Top 4 : **{int(stats.get('top4') or 0)}**"
            ),
            inline=True,
        )
        if data["active_deck"]:
            deck = data["active_deck"]
            embed.add_field(
                name="🎴 Deck actif",
                value=f"**{deck['name']}**\n{deck['format']} • {deck['matches']} match(s)",
                inline=True,
            )
        if data["ratings"]:
            embed.add_field(
                name="📈 Meilleurs classements",
                value="\n".join(
                    f"**{row['format']}** : {row['rating']} ELO ({row['wins']}V/{row['losses']}D)"
                    for row in data["ratings"][:4]
                ),
                inline=False,
            )
        unlocked = data["achievements"][:6]
        embed.add_field(
            name="🏅 Succès",
            value=(
                " ".join(f"{row['emoji']} **{row['name']}**" for row in unlocked)
                if unlocked else "Aucun succès débloqué pour le moment."
            ),
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=not visible)

    @duelist.command(name="edit", description="Modifier tes préférences de duelliste")
    async def edit(
        self,
        interaction: discord.Interaction,
        formats_favoris: str = "",
        simulateurs: str = "",
        disponibilites: str = "",
        presentation: str = "",
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await self.service.update_profile(
            guild_id=str(interaction.guild.id),
            discord_id=str(interaction.user.id),
            favorite_formats=formats_favoris,
            simulators=simulateurs,
            availability=disponibilites,
            about=presentation,
        )
        await interaction.response.send_message("✅ Ton profil enrichi a été mis à jour.", ephemeral=True)

    @duelist.command(name="dashboard", description="Afficher ton tableau de bord personnel")
    async def dashboard(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        data = await self.service.dashboard(str(interaction.guild.id), str(interaction.user.id))
        embed = discord.Embed(
            title="⚡ Mon tableau de bord Hamtaro",
            color=discord.Color.blurple(),
        )
        if data.active_tournaments:
            embed.add_field(
                name="🏟️ Mes tournois actifs",
                value="\n".join(
                    f"**{row['name']}** (`{row['code']}`) • {row['format']} • {row['status']}"
                    for row in data.active_tournaments
                ),
                inline=False,
            )
        else:
            embed.add_field(name="🏟️ Mes tournois actifs", value="Aucun tournoi actif.", inline=False)
        if data.next_matches:
            lines = []
            for row in data.next_matches:
                opponent = row["player2_name"] if str(row["player1_id"]) == str(interaction.user.id) else row["player1_name"]
                lines.append(
                    f"**{row['tournament_name']}** • ronde {row['round_number']} • contre **{opponent}** • `{row['status']}`"
                )
            embed.add_field(name="🎯 Prochains matchs", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="🎯 Prochains matchs", value="Aucun match à jouer.", inline=False)
        embed.add_field(name="📨 Résultats en attente", value=str(data.pending_results), inline=True)
        embed.add_field(name="⚠️ Problèmes ouverts", value=str(data.open_issues), inline=True)
        if data.active_deck:
            embed.add_field(
                name="🎴 Deck actif",
                value=f"{data.active_deck['name']} • {data.active_deck['format']}",
                inline=True,
            )
        if data.ratings:
            embed.add_field(
                name="📈 ELO",
                value="\n".join(f"{row['format']} : **{row['rating']}**" for row in data.ratings),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @duelist.command(name="achievements", description="Afficher les succès d'un joueur")
    async def achievements(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        target = joueur or interaction.user
        rows = await self.service.achievements(str(interaction.guild.id), str(target.id))
        embed = discord.Embed(title=f"🏅 Succès de {target.display_name}", color=discord.Color.gold())
        embed.description = "\n".join(
            f"{row['emoji']} **{row['name']}** — {row['description']} "
            f"{'✅' if row['unlocked_at'] else '🔒'}"
            for row in rows
        ) or "Aucun succès disponible."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @duelist.command(name="deck_add", description="Ajouter un deck à ta bibliothèque")
    async def deck_add(
        self,
        interaction: discord.Interaction,
        nom: str,
        format: str,
        simulateur: str | None = None,
        notes: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            deck_id = await self.service.add_deck(
                guild_id=str(interaction.guild.id),
                discord_id=str(interaction.user.id),
                name=nom,
                format_name=format,
                simulator=simulateur,
                notes=notes,
            )
        except Exception as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ Deck ajouté à ta bibliothèque (`#{deck_id}`).", ephemeral=True)

    @duelist.command(name="deck_list", description="Afficher ta bibliothèque de decks")
    async def deck_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        rows = await self.service.list_decks(str(interaction.guild.id), str(interaction.user.id))
        embed = discord.Embed(title="🎴 Ma bibliothèque de decks", color=discord.Color.green())
        embed.description = "\n".join(
            f"`#{row['id']}` {'⭐' if row['is_active'] else '•'} **{row['name']}** — {row['format']} "
            f"({row['wins']}V/{row['losses']}D){' 🔒' if row['is_locked'] else ''}"
            for row in rows
        ) or "Ta bibliothèque est vide."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @duelist.command(name="deck_select", description="Choisir ton deck actif")
    async def deck_select(self, interaction: discord.Interaction, deck_id: int) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            deck = await self.service.select_deck(
                str(interaction.guild.id), str(interaction.user.id), deck_id
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ **{deck['name']}** est maintenant ton deck actif.", ephemeral=True)

    @duelist.command(name="deck_delete", description="Supprimer un deck non verrouillé")
    async def deck_delete(self, interaction: discord.Interaction, deck_id: int) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            await self.service.delete_deck(str(interaction.guild.id), str(interaction.user.id), deck_id)
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message("✅ Deck supprimé.", ephemeral=True)

    @duelist.command(name="deck_lock", description="Verrouiller ou déverrouiller le deck d'un joueur")
    @staff_only()
    async def deck_lock(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        deck_id: int,
        verrouille: bool,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            await self.service.set_deck_lock(
                str(interaction.guild.id), str(joueur.id), deck_id, verrouille
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ Deck {'verrouillé' if verrouille else 'déverrouillé'}.", ephemeral=True
        )

    @duelist.command(name="notifications", description="Configurer tes notifications Hamtaro")
    async def notifications(
        self,
        interaction: discord.Interaction,
        mode: str = "thread",
        prochain_match: bool = True,
        nouveau_tournoi: bool = True,
        rappel_resultat: bool = True,
        confirmation_resultat: bool = True,
        changement_ronde: bool = True,
        changement_classement: bool = False,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            await self.service.set_notifications(
                guild_id=str(interaction.guild.id),
                discord_id=str(interaction.user.id),
                delivery_mode=mode.lower(),
                next_match=prochain_match,
                new_tournament=nouveau_tournoi,
                result_reminder=rappel_resultat,
                result_confirmation=confirmation_resultat,
                round_change=changement_ronde,
                ranking_change=changement_classement,
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message("✅ Préférences de notification enregistrées.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlayerExperienceCog(bot))
