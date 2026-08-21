from __future__ import annotations

import logging
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger(__name__)

ROLE_NAME = os.getenv("DUELLISTE_ROLE_NAME", "Duelliste").strip() or "Duelliste"
CATEGORY_NAME = os.getenv("HAMTARO_CUP_CATEGORY_NAME", "Hamtaro Cup").strip() or "Hamtaro Cup"

ROLE_ID_RAW = os.getenv("DUELLISTE_ROLE_ID", "").strip()
CATEGORY_ID_RAW = os.getenv("HAMTARO_CUP_CATEGORY_ID", "").strip()

ROLE_ID = int(ROLE_ID_RAW) if ROLE_ID_RAW.isdigit() else None
CATEGORY_ID = int(CATEGORY_ID_RAW) if CATEGORY_ID_RAW.isdigit() else None

SELECT_CUSTOM_ID = "hamtaro:self_roles:v1"


def _find_role(guild: discord.Guild) -> Optional[discord.Role]:
    if ROLE_ID:
        role = guild.get_role(ROLE_ID)
        if role is not None:
            return role
    return discord.utils.get(guild.roles, name=ROLE_NAME)


def _find_category(guild: discord.Guild) -> Optional[discord.CategoryChannel]:
    if CATEGORY_ID:
        channel = guild.get_channel(CATEGORY_ID)
        if isinstance(channel, discord.CategoryChannel):
            return channel
    return discord.utils.get(guild.categories, name=CATEGORY_NAME)


async def _ensure_role(guild: discord.Guild) -> discord.Role:
    role = _find_role(guild)
    if role is not None:
        return role

    role = await guild.create_role(
        name=ROLE_NAME,
        permissions=discord.Permissions.none(),
        mentionable=False,
        hoist=False,
        reason="Hamtaro : création du rôle auto-attribuable Duelliste",
    )
    LOGGER.info("Rôle auto-attribuable créé : %s (%s)", role.name, role.id)
    return role


async def _configure_category_access(
    guild: discord.Guild,
    role: discord.Role,
) -> tuple[bool, str]:
    category = _find_category(guild)
    if category is None:
        return (
            False,
            f"Catégorie « {CATEGORY_NAME} » introuvable. "
            "Le panneau fonctionne, mais l'accès de catégorie doit être configuré.",
        )

    me = guild.me
    if me is None:
        return False, "Impossible de retrouver le membre correspondant au bot."

    perms = category.permissions_for(me)
    if not perms.manage_channels and not me.guild_permissions.administrator:
        return (
            False,
            "Hamtaro n'a pas la permission « Gérer les salons ». "
            "Le rôle fonctionne, mais je ne peux pas régler automatiquement la catégorie.",
        )

    everyone_overwrite = category.overwrites_for(guild.default_role)
    everyone_overwrite.view_channel = False
    await category.set_permissions(
        guild.default_role,
        overwrite=everyone_overwrite,
        reason="Hamtaro : masquer Hamtaro Cup aux membres sans rôle",
    )

    role_overwrite = category.overwrites_for(role)
    role_overwrite.view_channel = True
    await category.set_permissions(
        role,
        overwrite=role_overwrite,
        reason="Hamtaro : donner accès à Hamtaro Cup aux Duellistes",
    )

    return True, f"Accès à « {category.name} » configuré pour @{role.name}."


class RoleSelect(discord.ui.Select):
    def __init__(self, cog: "RolePanelCog") -> None:
        self.cog = cog
        super().__init__(
            custom_id=SELECT_CUSTOM_ID,
            placeholder="Choisissez un rôle",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Duelliste",
                    value="duelliste",
                    description="Accéder à la catégorie Hamtaro Cup",
                    emoji="⚔️",
                )
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "❌ Ce menu doit être utilisé dans le serveur.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=False)

        guild = interaction.guild
        member = interaction.user

        try:
            role = _find_role(guild)
            if role is None:
                if not guild.me or not guild.me.guild_permissions.manage_roles:
                    await interaction.followup.send(
                        "❌ Le rôle Duelliste n'existe pas et Hamtaro n'a pas "
                        "la permission « Gérer les rôles ».",
                        ephemeral=True,
                    )
                    return
                role = await _ensure_role(guild)

            me = guild.me
            if me is None:
                await interaction.followup.send(
                    "❌ Impossible de vérifier les permissions de Hamtaro.",
                    ephemeral=True,
                )
                return

            if not me.guild_permissions.manage_roles and not me.guild_permissions.administrator:
                await interaction.followup.send(
                    "❌ Hamtaro doit avoir la permission « Gérer les rôles ».",
                    ephemeral=True,
                )
                return

            if role >= me.top_role and not me.guild_permissions.administrator:
                await interaction.followup.send(
                    "❌ Le rôle Duelliste est placé trop haut. "
                    "Place-le sous le rôle de Hamtaro dans la hiérarchie.",
                    ephemeral=True,
                )
                return

            # Le menu agit comme un interrupteur :
            # - pas le rôle -> ajoute
            # - déjà le rôle -> retire
            if role in member.roles:
                await member.remove_roles(
                    role,
                    reason="Hamtaro : retrait volontaire via le panneau de rôles",
                )
                await interaction.followup.send(
                    "✅ Le rôle **Duelliste** a été retiré. "
                    "La catégorie **Hamtaro Cup** est de nouveau masquée.",
                    ephemeral=True,
                )
            else:
                await member.add_roles(
                    role,
                    reason="Hamtaro : sélection volontaire via le panneau de rôles",
                )
                await interaction.followup.send(
                    "✅ Tu as maintenant le rôle **Duelliste**. "
                    "La catégorie **Hamtaro Cup** est accessible.",
                    ephemeral=True,
                )

        except discord.Forbidden:
            LOGGER.exception("Permission Discord refusée pendant l'attribution du rôle")
            await interaction.followup.send(
                "❌ Hamtaro n'a pas les permissions nécessaires pour gérer ce rôle.",
                ephemeral=True,
            )
        except discord.HTTPException:
            LOGGER.exception("Erreur HTTP Discord pendant l'attribution du rôle")
            await interaction.followup.send(
                "❌ Discord a refusé la modification du rôle. Réessaie dans un instant.",
                ephemeral=True,
            )
        except Exception:
            LOGGER.exception("Erreur inattendue dans le panneau de rôles")
            await interaction.followup.send(
                "❌ Une erreur est survenue pendant la modification du rôle.",
                ephemeral=True,
            )


class RolePanelView(discord.ui.View):
    def __init__(self, cog: "RolePanelCog") -> None:
        super().__init__(timeout=None)
        self.add_item(RoleSelect(cog))


class RolePanelCog(commands.Cog):
    """Panneau persistant d'auto-attribution des rôles Hamtaro."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="roles_panel",
        description="Publie le panneau persistant permettant de choisir le rôle Duelliste.",
    )
    @app_commands.guild_only()
    async def roles_panel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans le serveur.",
                ephemeral=True,
            )
            return

        member = interaction.user
        if not (
            member.guild_permissions.administrator
            or member.guild_permissions.manage_roles
        ):
            await interaction.response.send_message(
                "⛔ Cette commande est réservée au staff ayant « Gérer les rôles ».",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        me = guild.me
        if me is None:
            await interaction.followup.send(
                "❌ Impossible de retrouver Hamtaro dans le serveur.",
                ephemeral=True,
            )
            return

        if not (me.guild_permissions.manage_roles or me.guild_permissions.administrator):
            await interaction.followup.send(
                "❌ Donne à Hamtaro la permission « Gérer les rôles » avant de lancer la commande.",
                ephemeral=True,
            )
            return

        try:
            role = await _ensure_role(guild)

            if role >= me.top_role and not me.guild_permissions.administrator:
                await interaction.followup.send(
                    "❌ Le rôle **Duelliste** est au-dessus du rôle de Hamtaro. "
                    "Déplace Duelliste sous Hamtaro puis relance `/roles_panel`.",
                    ephemeral=True,
                )
                return

            category_ok, category_message = await _configure_category_access(guild, role)

            embed = discord.Embed(
                title="Choisissez un rôle",
                description=(
                    "Sélectionnez le rôle qui vous correspond dans le menu ci-dessous.\n\n"
                    "⚔️ **Duelliste** — donne accès à la catégorie **Hamtaro Cup**.\n\n"
                    "*Sélectionnez Duelliste une deuxième fois pour retirer le rôle.*"
                ),
            )
            embed.set_footer(text="Hamtaro • Gestion automatique des rôles")

            if interaction.channel is None:
                await interaction.followup.send(
                    "❌ Salon introuvable.",
                    ephemeral=True,
                )
                return

            await interaction.channel.send(
                embed=embed,
                view=RolePanelView(self),
            )

            status = "✅ Panneau publié."
            if category_ok:
                status += f"\n✅ {category_message}"
            else:
                status += f"\n⚠️ {category_message}"

            await interaction.followup.send(status, ephemeral=True)

        except discord.Forbidden:
            LOGGER.exception("Permission refusée lors de la configuration du panneau")
            await interaction.followup.send(
                "❌ Hamtaro n'a pas les permissions nécessaires. "
                "Vérifie « Gérer les rôles » et, pour l'auto-configuration de la catégorie, "
                "« Gérer les salons ».",
                ephemeral=True,
            )
        except discord.HTTPException:
            LOGGER.exception("Erreur HTTP Discord lors de la configuration du panneau")
            await interaction.followup.send(
                "❌ Discord a refusé une modification pendant la configuration.",
                ephemeral=True,
            )
        except Exception:
            LOGGER.exception("Erreur inattendue lors de la création du panneau")
            await interaction.followup.send(
                "❌ Une erreur est survenue pendant la création du panneau.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    cog = RolePanelCog(bot)
    await bot.add_cog(cog)

    # Vue persistante : le menu reste utilisable après redémarrage de Hamtaro.
    bot.add_view(RolePanelView(cog))
    LOGGER.info("Panneau persistant de rôles enregistré.")
