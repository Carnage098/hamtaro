from __future__ import annotations

import discord


HAMTARO_ICON = "🐹"


def success_embed(
    title: str,
    description: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{HAMTARO_ICON} {title}",
        description=description,
        color=discord.Color.green(),
    )

    return embed


def error_embed(
    title: str,
    description: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"❌ {title}",
        description=description,
        color=discord.Color.red(),
    )

    return embed


def warning_embed(
    title: str,
    description: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚠️ {title}",
        description=description,
        color=discord.Color.orange(),
    )

    return embed


def info_embed(
    title: str,
    description: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{HAMTARO_ICON} {title}",
        description=description,
        color=discord.Color.blue(),
    )

    return embed


def tournament_embed(
    title: str,
    description: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆 {title}",
        description=description,
        color=discord.Color.gold(),
    )

    return embed


def staff_embed(
    title: str,
    description: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🛠️ {title}",
        description=description,
        color=discord.Color.purple(),
    )

    return embed


def neutral_embed(
    title: str,
    description: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{HAMTARO_ICON} {title}",
        description=description,
        color=discord.Color.light_grey(),
    )

    return embed


def add_standard_footer(
    embed: discord.Embed,
) -> discord.Embed:
    embed.set_footer(
        text="Hamtaro Tournament Manager"
    )

    return embed
