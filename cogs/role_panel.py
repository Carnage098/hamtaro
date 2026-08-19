from __future__ import annotations

import logging
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger(__name__)

ROLE_NAME = os.getenv("DUELLISTE_ROLE_NAME", "Duelliste").strip() or "Duelliste"

ROLE_ID_RAW = os.getenv("DUELLISTE_ROLE_ID", "").strip()
CATEGORY_ID_RAW = os.getenv("HAMTARO_CUP_CATEGORY_ID", "").strip()

ROLE_ID = int(ROLE_ID_RAW) if ROLE_ID_RAW.isdigit() else None
CATEGORY_ID = int(CATEGORY_ID_RAW) if CATEGORY_ID_RAW.isdigit() else None

SELECT_CUSTOM_ID = "hamtaro:self_roles:duelliste:id:v1"


def find_role(guild: discord.Guild) -> Optional[discord.Role]:
    if ROLE_ID:
        role = guild.get_role(ROLE_ID)
        if role is not None:
            return role
    return discord.utils.get(guild.roles, name=ROLE_NAME)


def find_category(guild: discord.Guild) -> Optional[discord.CategoryChannel]:
    if not CATEGORY_ID:
        return None

    channel = guild.get_channel(CATEGORY_ID)
    if isinstance(channel, discord.CategoryChannel):
        return channel

    return None


async def ensure_role(guild: discord.Guild) -> discord.Role:
    role = find_role(guild)
    if role is not None:
        return role

    role = await guild.create_role(
        name=ROLE_NAME,
        permissions=discord.Permissions.none(),
        mentionable=False,
        hoist=False,
        reason="Hamtaro : création du rôle auto-attribuable Duelliste",
    )
    LOGGER.info("Rôle Duelliste créé : %s", role.id)
    return role


async def configure_category_access(
    guild: discord.Guild,
    role: discord.Role,
) -> tuple[bool, str]:
    if not CATEGORY_ID:
        return (
            False,
            "La variable Railway HAMTARO_CUP_CATEGORY_ID n'est pas configurée.",
        )

    category = find_category(guild)
    if category is None:
        return (
            False,
            f"Aucune catégorie Discord trouvée avec l'ID {CATEGORY_ID}.",
        )

    me = guild.me
    if me is None:
        return False, "Impossible de retrouver Hamtaro dans le serveur."

    if not (
        me.guild_permissions.manage_channels
        or me.guild_permissions.administrator
    ):
        return (
            False,
            "Hamtaro n'a pas la permission « Gérer les salons ».",
        )

    # On ne modifie que Voir le salon pour préserver toutes les autres permissions.
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
        reason="Hamtaro : accès Hamtaro Cup pour Duelliste",
    )

    return True, f"Accès à « {category.name} » configuré pour @{role.name}."


class DuellisteSelect(discord.ui.Select):
    def __init__(self) -> None:
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

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        member = interaction.user
        me = guild.me

        if me is None:
            await interaction.followup.send(
                "❌ Impossible de retrouver Hamtaro dans le serveur.",
                ephemeral=True,
            )
            return

        if not (
            me.guild_permissions.manage_roles
            or me.guild_permissions.administrator
        ):
            await interaction.followup.send(
                "❌ Hamtaro doit avoir la permission **Gérer les rôles**.",
                ephemeral=True,
            )
            return

        try:
            role = await ensure_role(guild)

            if role >= me.top_role and not me.guild_permissions.administrator:
                await interaction.followup.send(
                    "❌ Le rôle **Duelliste** doit être placé sous le rôle de Hamtaro.",
                    ephemeral=True,
                )
                return

            if role in member.roles:
                await member.remove_roles(
                    role,
                    reason="Retrait volontaire via le panneau de rôles Hamtaro",
                )
                await interaction.followup.send(
                    "✅ Le rôle **Duelliste** a été retiré.",
                    ephemeral=True,
                )
            else:
                await member.add_roles(
                    role,
                    reason="Attribution volontaire via le panneau de rôles Hamtaro",
                )
                await interaction.followup.send(
                    "✅ Tu as maintenant le rôle **Duelliste** et l'accès à la catégorie.",
                    ephemeral=True,
                )

        except discord.Forbidden:
            LOGGER.exception("Permission refusée pour le rôle Duelliste")
            await interaction.followup.send(
                "❌ Hamtaro n'a pas les permissions nécessaires pour gérer ce rôle.",
                ephemeral=True,
            )
        except discord.HTTPException:
            LOGGER.exception("Erreur HTTP Discord pendant la gestion du rôle")
            await interaction.followup.send(
                "❌ Discord a refusé la modification. Réessaie.",
                ephemeral=True,
            )
        except Exception:
            LOGGER.exception("Erreur inattendue dans le panneau Duelliste")
            await interaction.followup.send(
                "❌ Une erreur inattendue est survenue.",
                ephemeral=True,
            )


class DuellisteRoleView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(DuellisteSelect())


class DuellisteRolePanel(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="roles_panel",
        description="Publie le panneau permanent de sélection du rôle Duelliste.",
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
                "⛔ Cette commande est réservée au staff.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        me = guild.me

        if me is None:
            await interaction.followup.send(
                "❌ Impossible de retrouver Hamtaro.",
                ephemeral=True,
            )
            return

        if not (
            me.guild_permissions.manage_roles
            or me.guild_permissions.administrator
        ):
            await interaction.followup.send(
                "❌ Donne à Hamtaro la permission **Gérer les rôles**.",
                ephemeral=True,
            )
            return

        if not CATEGORY_ID:
            await interaction.followup.send(
                "❌ Configure d'abord `HAMTARO_CUP_CATEGORY_ID` sur Railway, "
                "puis redémarre Hamtaro.",
                ephemeral=True,
            )
            return

        try:
            role = await ensure_role(guild)

            if role >= me.top_role and not me.guild_permissions.administrator:
                await interaction.followup.send(
                    "❌ Place le rôle **Duelliste** sous le rôle de Hamtaro.",
                    ephemeral=True,
                )
                return

            category_ok, category_msg = await configure_category_access(guild, role)

            if not category_ok:
                await interaction.followup.send(
                    f"❌ {category_msg}",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title="Choisissez un rôle",
                description=(
                    "Sélectionnez le rôle qui vous correspond dans le menu ci-dessous.\n\n"
                    "⚔️ **Duelliste** — donne accès à la catégorie **Hamtaro Cup**.\n\n"
                    "Sélectionnez **Duelliste** une deuxième fois pour retirer le rôle."
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
                view=DuellisteRoleView(),
            )

            await interaction.followup.send(
                f"✅ Panneau publié.\n✅ {category_msg}",
                ephemeral=True,
            )

        except discord.Forbidden:
            LOGGER.exception("Permission refusée pendant /roles_panel")
            await interaction.followup.send(
                "❌ Hamtaro doit avoir **Gérer les rôles** et **Gérer les salons**.",
                ephemeral=True,
            )
        except discord.HTTPException:
            LOGGER.exception("Erreur HTTP pendant /roles_panel")
            await interaction.followup.send(
                "❌ Discord a refusé une modification pendant la configuration.",
                ephemeral=True,
            )
        except Exception:
            LOGGER.exception("Erreur inattendue pendant /roles_panel")
            await interaction.followup.send(
                "❌ Une erreur est survenue pendant la création du panneau.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DuellisteRolePanel(bot))
    bot.add_view(DuellisteRoleView())
    LOGGER.info("Panneau persistant Duelliste (catégorie par ID) enregistré.")
