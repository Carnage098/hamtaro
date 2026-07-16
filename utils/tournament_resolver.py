from __future__ import annotations

from typing import Any

import discord


INACTIVE_STATUSES = {"finished", "cancelled"}


def _status_value(tournament: Any) -> str:
    status = getattr(tournament, "status", "")
    return str(getattr(status, "value", status)).lower()


def _require_guild_and_channel(
    interaction: discord.Interaction,
) -> tuple[str, str]:
    if interaction.guild is None:
        raise ValueError("Cette commande doit être utilisée dans un serveur Discord.")

    if interaction.channel_id is None:
        raise ValueError("Impossible d'identifier le salon Discord actuel.")

    return str(interaction.guild.id), str(interaction.channel_id)


async def resolve_tournament(
    interaction: discord.Interaction,
    db: Any,
    *,
    code: str | None = None,
    require_active: bool = True,
) -> Any:
    """
    Résout le tournoi ciblé par une commande.

    Priorité :
    1. code fourni explicitement ;
    2. tournoi sélectionné dans le salon ;
    3. unique tournoi actif du serveur.
    """

    guild_id, channel_id = _require_guild_and_channel(interaction)

    if code is not None and code.strip():
        tournament = await db.get_guild_tournament_by_code(
            guild_id,
            code.strip(),
        )
        if tournament is None:
            raise ValueError(f"Aucun tournoi trouvé avec le code `{code.strip().upper()}`.")

        if require_active and _status_value(tournament) in INACTIVE_STATUSES:
            raise ValueError(
                f"Le tournoi `{tournament.code}` est terminé ou annulé."
            )

        return tournament

    selected = await db.get_selected_tournament(guild_id, channel_id)
    if selected is not None:
        if require_active and _status_value(selected) in INACTIVE_STATUSES:
            raise ValueError(
                f"Le tournoi sélectionné `{selected.code}` est terminé ou annulé. "
                "Sélectionne un autre tournoi avec `/tournament_select`."
            )
        return selected

    active = await db.list_active_tournaments(guild_id)
    if not active:
        raise ValueError("Aucun tournoi actif sur ce serveur.")

    if len(active) == 1:
        return active[0]

    preview = "\n".join(
        f"• `{tournament.code}` — {tournament.name}"
        for tournament in active[:10]
    )
    raise ValueError(
        "Plusieurs tournois sont actifs sur ce serveur.\n"
        f"{preview}\n"
        "Utilise `/tournament_select` dans ce salon ou indique le code du tournoi."
    )


async def active_tournament_code_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplétion des codes des tournois actifs du serveur."""

    if interaction.guild is None:
        return []

    db = getattr(interaction.client, "db", None)
    if db is None:
        return []

    tournaments = await db.list_active_tournaments(str(interaction.guild.id))
    needle = current.strip().lower()
    choices: list[discord.app_commands.Choice[str]] = []

    for tournament in tournaments:
        code = str(tournament.code)
        name = str(tournament.name)
        label = f"{code} — {name}"
        if needle and needle not in label.lower():
            continue
        choices.append(
            discord.app_commands.Choice(
                name=label[:100],
                value=code,
            )
        )
        if len(choices) >= 25:
            break

    return choices
