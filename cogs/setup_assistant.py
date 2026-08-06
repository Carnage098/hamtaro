from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.expansion_database import init_expansion_schema
from services.tournament_extensions_service import TournamentExtensionsService
from utils.expansion_permissions import staff_only


class SetupAssistantCog(commands.Cog):
    setup_plus = app_commands.Group(
        name="setup_plus",
        description="Assistant de configuration des extensions Hamtaro",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = TournamentExtensionsService()

    async def cog_load(self) -> None:
        await init_expansion_schema()

    @setup_plus.command(name="configure", description="Configurer les salons et rôles des nouvelles fonctions")
    @staff_only()
    async def configure(
        self,
        interaction: discord.Interaction,
        annonces: discord.TextChannel,
        appels_arbitre: discord.TextChannel,
        matchs_vedettes: discord.TextChannel,
        salon_streaming: discord.VoiceChannel,
        role_staff: discord.Role,
        role_arbitre: discord.Role,
        format_par_defaut: str = "Général",
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        await self.service.save_settings(
            guild_id=str(interaction.guild.id),
            announcements_channel_id=str(annonces.id),
            judge_channel_id=str(appels_arbitre.id),
            featured_channel_id=str(matchs_vedettes.id),
            featured_voice_channel_id=str(salon_streaming.id),
            staff_role_id=str(role_staff.id),
            judge_role_id=str(role_arbitre.id),
            default_format=format_par_defaut,
            actor_id=str(interaction.user.id),
        )
        embed = discord.Embed(
            title="✅ Configuration Hamtaro enregistrée",
            color=discord.Color.green(),
        )
        embed.add_field(name="Annonces", value=annonces.mention, inline=True)
        embed.add_field(name="Appels d'arbitre", value=appels_arbitre.mention, inline=True)
        embed.add_field(name="Matchs vedettes", value=matchs_vedettes.mention, inline=True)
        embed.add_field(name="Vocal streaming", value=salon_streaming.mention, inline=True)
        embed.add_field(name="Rôle staff", value=role_staff.mention, inline=True)
        embed.add_field(name="Rôle arbitre", value=role_arbitre.mention, inline=True)
        embed.add_field(name="Format par défaut", value=format_par_defaut, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setup_plus.command(name="check", description="Vérifier les permissions utiles dans les salons configurés")
    @staff_only()
    async def check(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.me is None:
            await interaction.response.send_message("❌ Serveur ou membre bot introuvable.", ephemeral=True)
            return
        settings = await self.service.settings(str(interaction.guild.id))
        labels = {
            "announcements_channel_id": "Annonces",
            "judge_channel_id": "Appels d'arbitre",
            "featured_channel_id": "Matchs vedettes",
        }
        lines: list[str] = []
        for key, label in labels.items():
            raw_id = settings.get(key)
            if not raw_id:
                lines.append(f"❌ **{label}** : non configuré")
                continue
            channel = interaction.guild.get_channel(int(raw_id))
            if not isinstance(channel, discord.TextChannel):
                lines.append(f"❌ **{label}** : salon supprimé ou invalide")
                continue
            permissions = channel.permissions_for(interaction.guild.me)
            required = {
                "voir": permissions.view_channel,
                "envoyer": permissions.send_messages,
                "embeds": permissions.embed_links,
                "historique": permissions.read_message_history,
                "fils": permissions.create_public_threads,
                "gérer les fils": permissions.manage_threads,
            }
            missing = [name for name, allowed in required.items() if not allowed]
            if missing:
                lines.append(
                    f"⚠️ **{label}** {channel.mention} : manque " + ", ".join(missing)
                )
            else:
                lines.append(f"✅ **{label}** {channel.mention} : permissions correctes")
        voice_id = settings.get("featured_voice_channel_id")
        if not voice_id:
            lines.append("❌ **Vocal streaming** : non configuré")
        else:
            voice_channel = interaction.guild.get_channel(int(voice_id))
            if not isinstance(voice_channel, discord.VoiceChannel):
                lines.append("❌ **Vocal streaming** : salon supprimé ou invalide")
            else:
                permissions = voice_channel.permissions_for(interaction.guild.me)
                missing = []
                if not permissions.view_channel:
                    missing.append("voir")
                if not permissions.connect:
                    missing.append("se connecter")
                if not permissions.move_members:
                    missing.append("déplacer des membres (facultatif)")
                if missing:
                    lines.append(
                        f"⚠️ **Vocal streaming** {voice_channel.mention} : manque " + ", ".join(missing)
                    )
                else:
                    lines.append(f"✅ **Vocal streaming** {voice_channel.mention} : permissions correctes")

        if not self.bot.intents.voice_states:
            lines.append(
                "⚠️ **Intent Voice States** : désactivé ; Hamtaro ne pourra pas détecter la présence ni le partage d'écran."
            )
        else:
            lines.append("✅ **Intent Voice States** : activé")

        embed = discord.Embed(
            title="🔧 Vérification de configuration",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Le bot ne modifie pas automatiquement les permissions Discord.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setup_plus.command(name="show", description="Afficher la configuration actuelle")
    @staff_only()
    async def show(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        settings = await self.service.settings(str(interaction.guild.id))
        def mention_channel(value: str | None) -> str:
            return f"<#{value}>" if value else "Non configuré"
        def mention_role(value: str | None) -> str:
            return f"<@&{value}>" if value else "Non configuré"
        embed = discord.Embed(title="🔧 Configuration Hamtaro Plus", color=discord.Color.blurple())
        embed.add_field(name="Annonces", value=mention_channel(settings.get("announcements_channel_id")), inline=True)
        embed.add_field(name="Appels arbitre", value=mention_channel(settings.get("judge_channel_id")), inline=True)
        embed.add_field(name="Matchs vedettes", value=mention_channel(settings.get("featured_channel_id")), inline=True)
        embed.add_field(name="Vocal streaming", value=mention_channel(settings.get("featured_voice_channel_id")), inline=True)
        embed.add_field(name="Rôle staff", value=mention_role(settings.get("staff_role_id")), inline=True)
        embed.add_field(name="Rôle arbitre", value=mention_role(settings.get("judge_role_id")), inline=True)
        embed.add_field(name="Format par défaut", value=settings.get("default_format", "Général"), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupAssistantCog(bot))
