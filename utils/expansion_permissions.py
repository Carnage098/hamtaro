from __future__ import annotations

import discord
from discord import app_commands

from services.expansion_database import expansion_connection


DEFAULT_STAFF_ROLES = {
    "admin",
    "administrateur",
    "staff",
    "modo",
    "modérateur",
    "🛑modo",
    "arbitre",
    "judge",
}


def has_default_staff_role(member: discord.Member) -> bool:
    return any(role.name.casefold() in DEFAULT_STAFF_ROLES for role in member.roles)


async def is_staff_member(member: discord.Member | discord.User) -> bool:
    if not isinstance(member, discord.Member):
        return False

    permissions = member.guild_permissions
    if permissions.administrator or permissions.manage_guild:
        return True

    configured_role_ids: set[int] = set()
    try:
        async with expansion_connection() as db:
            row = await (
                await db.execute(
                    """
                    SELECT staff_role_id, judge_role_id
                    FROM expansion_settings
                    WHERE guild_id=?
                    """,
                    (str(member.guild.id),),
                )
            ).fetchone()
        if row:
            for value in (row["staff_role_id"], row["judge_role_id"]):
                if value and str(value).isdigit():
                    configured_role_ids.add(int(value))
    except Exception:
        # Le contrôle par noms reste utilisable pendant une migration ou
        # avant la première configuration de l'extension.
        configured_role_ids.clear()

    if configured_role_ids and any(role.id in configured_role_ids for role in member.roles):
        return True

    return has_default_staff_role(member)


def staff_only() -> app_commands.Check:
    async def predicate(interaction: discord.Interaction) -> bool:
        if await is_staff_member(interaction.user):
            return True
        raise app_commands.CheckFailure("Cette commande est réservée au staff.")

    return app_commands.check(predicate)
