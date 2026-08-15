from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import discord
from discord import app_commands

LOGGER = logging.getLogger("hamtaro.command_compactor")
MAX_ROOT_COMMANDS = 100
MAX_GROUP_CHILDREN = 25

DIRECT_COMMANDS = {
    "register", "result", "hamtaro", "help", "rules",
    "meta", "coinflip", "dice", "hamtaro_site",
}

GROUP_DESCRIPTIONS = {
    "tournament": "Créer, lancer, gérer et terminer les tournois.",
    "match": "Matchs, salons de duel, historique et prochain adversaire.",
    "results": "Validation, correction et administration des résultats.",
    "bracket": "Arbres, affichage et publication des brackets.",
    "swiss": "Rondes suisses, appariements et classements.",
    "deck": "Decks, statistiques et outils liés aux decks.",
    "archetype": "Catalogue, fiches et artworks des archétypes.",
    "player": "Profils, statistiques, historique et progression des joueurs.",
    "casual": "Matchs casuals, files et résultats casuals.",
    "competition": "Classements, saisons et outils compétitifs.",
    "staff": "Administration, réparation, logs et outils staff.",
    "setup": "Configuration de Hamtaro et assistants de mise en place.",
    "graphics": "Prévisualisations et rendus graphiques.",
    "community": "Outils communautaires et animations.",
    "system": "Santé, diagnostic, export et outils système.",
}

MODULE_GROUPS = (
    ("cogs.tournament_start_preview", "tournament"),
    ("cogs.tournament_progression", "tournament"),
    ("cogs.tournament_extensions", "tournament"),
    ("cogs.tournament_context", "tournament"),
    ("cogs.tournament_manage", "tournament"),
    ("cogs.tournament_status", "tournament"),
    ("cogs.tournament_undo", "tournament"),
    ("cogs.tournament_export", "tournament"),
    ("cogs.end_tournament", "tournament"),
    ("cogs.tournament", "tournament"),
    ("cogs.match_history", "match"),
    ("cogs.match_center", "match"),
    ("cogs.nextmatch", "match"),
    ("cogs.results", "results"),
    ("cogs.casual_results_plus", "casual"),
    ("cogs.casual_matches", "casual"),
    ("cogs.bracket_full", "bracket"),
    ("cogs.bracket", "bracket"),
    ("cogs.swiss_graphics", "swiss"),
    ("cogs.swiss", "swiss"),
    ("cogs.deck_stats", "deck"),
    ("cogs.archetype_artworks", "archetype"),
    ("cogs.archetype_catalog", "archetype"),
    ("cogs.player_experience", "player"),
    ("cogs.profile", "player"),
    ("cogs.competitive", "competition"),
    ("cogs.setup_assistant", "setup"),
    ("cogs.staff_logs", "staff"),
    ("cogs.professional_tools", "staff"),
    ("cogs.repair", "staff"),
    ("cogs.admin", "staff"),
    ("cogs.graphics_preview", "graphics"),
    ("cogs.community_tools", "community"),
    ("cogs.system_health", "system"),
    ("cogs.public_website", "system"),
    ("cogs.expansion_tasks", "system"),
    ("cogs.expansion_hub", "system"),
)

PREFIX_GROUPS = (
    ("tournament_", "tournament"),
    ("match_", "match"),
    ("result_", "results"),
    ("results_", "results"),
    ("bracket_", "bracket"),
    ("swiss_", "swiss"),
    ("deck_", "deck"),
    ("archetype_", "archetype"),
    ("artwork_", "archetype"),
    ("player_", "player"),
    ("profile_", "player"),
    ("casual_", "casual"),
    ("competition_", "competition"),
    ("competitive_", "competition"),
    ("season_", "competition"),
    ("ranking_", "competition"),
    ("leaderboard_", "competition"),
    ("staff_", "staff"),
    ("admin_", "staff"),
    ("setup_", "setup"),
    ("graphics_", "graphics"),
    ("preview_", "graphics"),
    ("community_", "community"),
    ("system_", "system"),
    ("health_", "system"),
)

EXPLICIT_GROUPS = {
    "bracket": "bracket",
    "profile": "player",
    "nextmatch": "match",
    "matches": "match",
    "participants": "tournament",
    "seed": "tournament",
    "reshuffle": "tournament",
    "approve_result": "results",
    "reject_result": "results",
    "pending_results": "results",
    "deck_stats": "deck",
    "setup": "setup",
    "setup_plus": "setup",
    "repair": "staff",
    "staff_logs": "staff",
    "health": "system",
    "doctor": "system",
}

ROOT_TO_SUB = {
    "bracket": "show",
    "profile": "show",
    "matches": "show",
    "participants": "list",
    "setup": "open",
    "health": "status",
}

@dataclass(slots=True)
class CompactionReport:
    roots_before: int
    roots_after: int
    actions_before: int
    actions_after: int
    moved: int
    group_sizes: dict[str, int]
    protected_roots: tuple[str, ...]

def _root_commands(tree):
    return list(tree.get_commands(type=discord.AppCommandType.chat_input))

def _count_actions(tree) -> int:
    return sum(
        isinstance(command, app_commands.Command)
        for command in tree.walk_commands(type=discord.AppCommandType.chat_input)
    )

def _module(command: app_commands.Command) -> str:
    value = getattr(command, "module", None)
    if value:
        return str(value)
    callback = getattr(command, "callback", None)
    return str(getattr(callback, "__module__", "") or "")

def _classify(command: app_commands.Command) -> str:
    name = command.name.lower()
    if name in EXPLICIT_GROUPS:
        return EXPLICIT_GROUPS[name]

    module = _module(command)
    for prefix, group in MODULE_GROUPS:
        if module.startswith(prefix):
            return group

    for prefix, group in PREFIX_GROUPS:
        if name.startswith(prefix):
            return group

    tokens = set(re.split(r"[_\-\s]+", name))
    keyword_groups = (
        ("tournament", {"tournament", "tournoi", "seed", "round", "participant"}),
        ("match", {"match", "duel", "opponent", "adversaire"}),
        ("results", {"result", "approve", "reject", "pending", "validation"}),
        ("bracket", {"bracket", "tree", "arbre"}),
        ("swiss", {"swiss", "suisse"}),
        ("deck", {"deck", "banlist", "format"}),
        ("archetype", {"archetype", "artwork"}),
        ("player", {"player", "profile", "joueur", "trophy", "trophies"}),
        ("casual", {"casual"}),
        ("competition", {"season", "ranking", "leaderboard", "competition"}),
        ("staff", {"staff", "admin", "repair", "moderation", "log"}),
        ("setup", {"setup", "configure", "config"}),
        ("graphics", {"graphics", "graphic", "image", "preview"}),
        ("community", {"community", "event", "fun"}),
    )
    for group, words in keyword_groups:
        if tokens & words:
            return group

    return "system"

def _sub_name(original: str, group: str) -> str:
    name = original.lower()
    for prefix in (group + "_",):
        if name.startswith(prefix) and len(name) > len(prefix):
            name = name[len(prefix):]
            break

    aliases = {
        "results": ("result_", "results_"),
        "player": ("player_", "profile_"),
        "competition": ("competition_", "competitive_", "season_", "ranking_"),
        "graphics": ("graphics_", "graphic_", "preview_"),
        "system": ("system_", "health_"),
    }
    for prefix in aliases.get(group, ()):
        if name.startswith(prefix) and len(name) > len(prefix):
            name = name[len(prefix):]
            break

    name = ROOT_TO_SUB.get(original.lower(), name)
    name = re.sub(r"[^a-z0-9_\-]", "_", name)
    name = re.sub(r"[_\-]{2,}", "_", name).strip("_-")
    return (name or "action")[:32]

def _unique_name(group: app_commands.Group, desired: str, original: str) -> str:
    used = {child.name for child in group.commands}
    if desired not in used:
        return desired
    fallback = re.sub(r"[^a-z0-9_\-]", "_", original.lower())[:32]
    if fallback and fallback not in used:
        return fallback

    i = 2
    while True:
        suffix = f"_{i}"
        candidate = f"{desired[:32-len(suffix)]}{suffix}"
        if candidate not in used:
            return candidate
        i += 1

def _get_group(tree, groups, requested, created):
    base = requested
    i = 1
    while True:
        name = base if i == 1 else f"{base}{i}"
        group = groups.get(name)
        if group is None:
            description = GROUP_DESCRIPTIONS.get(base, "Commandes Hamtaro regroupées.")
            if i > 1:
                description = f"{description} Suite {i}."
            group = app_commands.Group(
                name=name[:32],
                description=description[:100],
                guild_only=True,
            )
            tree.add_command(group)
            groups[name] = group
            created.add(name)
        if len(group.commands) < MAX_GROUP_CHILDREN:
            return group
        i += 1

def _preserve_root_only_restrictions(command: app_commands.Command) -> int:
    """Convertit les restrictions Discord racine en checks runtime avant déplacement.

    Discord n'applique pas default_permissions/nsfw au niveau d'une sous-commande.
    Les checks existants sont conservés et ces gardes s'ajoutent uniquement quand
    l'ancienne commande racine portait réellement la restriction.
    """
    added = 0
    extras = command.extras

    required = getattr(command, "default_permissions", None)
    if required is not None and not extras.get("_hamtaro_default_permissions_guard"):
        required_value = int(required.value)

        async def default_permissions_guard(interaction: discord.Interaction) -> bool:
            member_permissions = getattr(interaction.user, "guild_permissions", None)
            if member_permissions is None:
                return False
            if getattr(member_permissions, "administrator", False):
                return True
            # Une permission par défaut vide signifie : administrateurs uniquement.
            if required_value == 0:
                return False
            return (int(member_permissions.value) & required_value) == required_value

        command.add_check(default_permissions_guard)
        extras["_hamtaro_default_permissions_guard"] = True
        added += 1

    if getattr(command, "nsfw", False) and not extras.get("_hamtaro_nsfw_guard"):
        async def nsfw_guard(interaction: discord.Interaction) -> bool:
            channel = interaction.channel
            checker = getattr(channel, "is_nsfw", None)
            if checker is None:
                return False
            try:
                return bool(checker())
            except Exception:
                return False

        command.add_check(nsfw_guard)
        extras["_hamtaro_nsfw_guard"] = True
        added += 1

    return added


def compact_command_tree(tree, *, logger=None) -> CompactionReport:
    logger = logger or LOGGER
    before = _root_commands(tree)
    actions_before = _count_actions(tree)

    groups = {
        cmd.name: cmd for cmd in before if isinstance(cmd, app_commands.Group)
    }
    created = set()
    movable = []
    protected = []
    restriction_guards = 0

    for cmd in before:
        if not isinstance(cmd, app_commands.Command):
            continue
        if cmd.name in DIRECT_COMMANDS:
            continue
        if getattr(cmd, "_guild_ids", None):
            protected.append(cmd.name)
            continue
        movable.append(cmd)

    for cmd in movable:
        tree.remove_command(cmd.name, type=discord.AppCommandType.chat_input)

    for cmd in movable:
        original = cmd.name
        target = _classify(cmd)
        group = _get_group(tree, groups, target, created)
        new_name = _unique_name(group, _sub_name(original, target), original)

        # Les métadonnées root-only seraient ignorées par Discord une fois la
        # commande transformée en sous-commande : on les garde comme checks.
        restriction_guards += _preserve_root_only_restrictions(cmd)

        # discord.py rattache lui-même la commande au groupe dans add_command().
        cmd.name = new_name
        group.add_command(cmd)

    after = _root_commands(tree)
    actions_after = _count_actions(tree)
    sizes = {name: len(group.commands) for name, group in sorted(groups.items())}

    if len(after) > MAX_ROOT_COMMANDS:
        raise RuntimeError(
            f"Arbre slash encore trop gros : {len(after)}/{MAX_ROOT_COMMANDS} racines."
        )
    if actions_after != actions_before:
        raise RuntimeError(
            f"Perte d'actions pendant la compaction : {actions_before} -> {actions_after}."
        )

    logger.info(
        "Compaction commandes : %s racines -> %s ; %s actions conservées ; "
        "%s déplacées ; %s garde(s) de sécurité ajoutée(s).",
        len(before), len(after), actions_after, len(movable), restriction_guards,
    )

    if protected:
        logger.warning(
            "Commandes non déplacées car liées à une guild précise : %s",
            ", ".join(sorted(protected)),
        )

    return CompactionReport(
        roots_before=len(before),
        roots_after=len(after),
        actions_before=actions_before,
        actions_after=actions_after,
        moved=len(movable),
        group_sizes=sizes,
        protected_roots=tuple(sorted(protected)),
    )

def log_command_tree_summary(tree, *, logger=None) -> None:
    logger = logger or LOGGER
    roots = _root_commands(tree)
    actions = _count_actions(tree)
    groups = [x for x in roots if isinstance(x, app_commands.Group)]
    direct = [x for x in roots if isinstance(x, app_commands.Command)]

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("🐹 HAMTARO COMMAND TREE")
    logger.info("Commandes racines  : %s / %s", len(roots), MAX_ROOT_COMMANDS)
    logger.info("Actions slash      : %s", actions)
    logger.info("Groupes            : %s", len(groups))
    logger.info("Commandes directes : %s", len(direct))
    logger.info("Marge racines      : %s", MAX_ROOT_COMMANDS - len(roots))
    for group in sorted(groups, key=lambda x: x.name):
        logger.info("  /%-14s %2s sous-commande(s)", group.name, len(group.commands))
    if direct:
        logger.info("Directes : %s", ", ".join(f"/{x.name}" for x in direct))
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
