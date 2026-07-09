from __future__ import annotations

import discord

from discord import app_commands


STAFF_ROLE_NAMES = {
    "Admin",
    "Staff",
    "Tournament Staff",
    "Organisateur",
    "Organisateur Tournoi",
    "Modo",
    "Modérateur",
}


class StaffOnly(app_commands.CheckFailure):
    pass


def is_staff_member(user: discord.abc.User) -> bool:
    if not isinstance(user, discord.Member):
        return False

    if user.guild_permissions.administrator:
        return True

    if user.guild_permissions.manage_guild:
        return True

    user_roles = {
        role.name.lower()
        for role in user.roles
    }

    allowed_roles = {
        role.lower()
        for role in STAFF_ROLE_NAMES
    }

    return bool(
        user_roles.intersection(allowed_roles)
    )


async def staff_only_check(
    interaction: discord.Interaction,
) -> bool:
    if is_staff_member(interaction.user):
        return True

    raise StaffOnly(
        "Commande réservée au staff."
    )


def staff_only():
    return app_commands.check(
        staff_only_check
    )
