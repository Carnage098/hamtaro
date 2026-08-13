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


async def _table_exists(db: Any, table_name: str) -> bool:
    row = await db.fetchone(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        LIMIT 1
        """,
        (table_name,),
    )
    return row is not None


async def _tournament_from_match_thread(
    db: Any,
    *,
    guild_id: str,
    channel_id: str,
) -> Any | None:
    """Résout le tournoi lié au fil Hamtaro courant.

    match_thread_context est la source centrale. match_center_sessions puis
    progression_match_publications servent de fallback pour les anciens fils.
    """

    if await _table_exists(db, "match_thread_context"):
        row = await db.fetchone(
            """
            SELECT tournament_id
            FROM match_thread_context
            WHERE guild_id = ? AND thread_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (str(guild_id), str(channel_id)),
        )
        if row is not None:
            tournament = await db.get_tournament(int(row["tournament_id"]))
            if tournament is not None:
                return tournament

    if await _table_exists(db, "match_center_sessions"):
        row = await db.fetchone(
            """
            SELECT tournament_id
            FROM match_center_sessions
            WHERE guild_id = ? AND thread_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (str(guild_id), str(channel_id)),
        )
        if row is not None:
            tournament = await db.get_tournament(int(row["tournament_id"]))
            if tournament is not None:
                return tournament

    if await _table_exists(db, "progression_match_publications"):
        row = await db.fetchone(
            """
            SELECT tournament_id
            FROM progression_match_publications
            WHERE guild_id = ? AND thread_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (str(guild_id), str(channel_id)),
        )
        if row is not None:
            tournament = await db.get_tournament(int(row["tournament_id"]))
            if tournament is not None:
                return tournament

    return None


async def resolve_tournament(
    interaction: discord.Interaction,
    db: Any,
    *,
    code: str | None = None,
    require_active: bool = True,
) -> Any:
    """Résout automatiquement le tournoi ciblé par une commande.

    Priorité :
    1. code fourni explicitement ;
    2. tournoi lié au fil de match Hamtaro courant ;
    3. unique tournoi actif du serveur.

    /tournament_select n'est plus utilisé.
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
            raise ValueError(f"Le tournoi `{tournament.code}` est terminé ou annulé.")

        return tournament

    thread_tournament = await _tournament_from_match_thread(
        db,
        guild_id=guild_id,
        channel_id=channel_id,
    )
    if thread_tournament is not None:
        if require_active and _status_value(thread_tournament) in INACTIVE_STATUSES:
            raise ValueError(
                f"Le tournoi `{thread_tournament.code}` lié à ce fil est terminé ou annulé."
            )
        return thread_tournament

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
        "Utilise le code du tournoi dans la commande. Dans un fil de match Hamtaro, "
        "le tournoi est détecté automatiquement."
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


async def tournament_code_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplétion de tous les codes du serveur, y compris les tournois terminés.

    Cette fonction est conservée pour compatibilité avec les cogs historiques
    (tournament, match_history, swiss_graphics, profile, deck_stats, exports...).
    Elle n'implique pas le retour de /tournament_select : elle ne sert qu'à
    proposer des codes dans les options des commandes qui en ont encore besoin.
    """

    if interaction.guild is None:
        return []

    db = getattr(interaction.client, "db", None)
    if db is None:
        return []

    try:
        tournaments = await db.list_tournaments(
            str(interaction.guild.id),
            include_finished=True,
        )
    except (AttributeError, TypeError):
        # Compatibilité avec une DatabaseService plus ancienne : au minimum,
        # on propose les tournois actifs au lieu de faire échouer le chargement.
        try:
            tournaments = await db.list_active_tournaments(
                str(interaction.guild.id)
            )
        except (AttributeError, TypeError):
            return []

    needle = current.strip().lower()
    choices: list[discord.app_commands.Choice[str]] = []

    for tournament in tournaments:
        code = str(getattr(tournament, "code", "") or "").strip()
        name = str(getattr(tournament, "name", "Tournoi") or "Tournoi").strip()
        status = _status_value(tournament)

        if not code:
            continue

        label = f"{code} — {name}"
        if status:
            label += f" — {status}"

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
