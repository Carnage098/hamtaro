from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

import discord
from discord import app_commands

LOGGER = logging.getLogger("hamtaro.command_compactor")
MAX_ROOT_COMMANDS = 100
MAX_GROUP_CHILDREN = 25

# L'interface publique reste volontairement courte. Toutes les autres actions
# sont rangées sous l'espace de la personne qui les utilise.
DIRECT_COMMANDS = {"hamtaro", "help", "rules", "register", "result"}
ROLE_ROOTS = {"joueur", "staff", "admin"}
ROLE_DESCRIPTIONS = {
    "joueur": "Jouer un tournoi, gérer ses matchs et consulter son profil.",
    "staff": "Organiser les tournois, arbitrer et valider les résultats.",
    "admin": "Configurer, diagnostiquer et maintenir Hamtaro.",
}

TECHNICAL_CATEGORIES = {
    "tournament": "tournois", "match": "matchs", "results": "resultats",
    "bracket": "brackets", "swiss": "suisse", "deck": "decks",
    "archetype": "cartes", "player": "profil", "casual": "casual",
    "competition": "classements", "staff": "moderation",
    "setup": "configuration", "graphics": "affichage",
    "community": "communaute", "formats": "formats", "planning": "planning",
    "system": "maintenance",
}
CATEGORY_DESCRIPTIONS = {
    "tournois": "Inscriptions, participants et gestion des tournois.",
    "matchs": "Adversaires, salons de duel et historique des matchs.",
    "resultats": "Déclaration, validation et correction des résultats.",
    "brackets": "Affichage et publication des arbres de tournoi.",
    "suisse": "Rondes, appariements et classements suisses.",
    "decks": "Decks, statistiques et outils associés.",
    "cartes": "Catalogue et illustrations des archétypes.",
    "profil": "Profil, statistiques et progression du joueur.",
    "casual": "Matchs et résultats hors tournoi.",
    "classements": "Classements, saisons et compétition permanente.",
    "moderation": "Arbitrage, journaux et outils du staff.",
    "configuration": "Installation et configuration du serveur.",
    "affichage": "Aperçus, images et diffusion des tournois.",
    "communaute": "Sondages, événements et animations.",
    "formats": "Formats spéciaux : Boss, Halloween et équipes 2v2.",
    "planning": "Programmation, annonces et rappels des tournois.",
    "maintenance": "Santé, sauvegardes, exports et réparations.",
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
    ("cogs.match_history", "match"), ("cogs.match_center", "match"),
    ("cogs.nextmatch", "match"), ("cogs.results", "results"),
    ("cogs.boss", "formats"), ("cogs.halloween_tournament", "formats"),
    ("cogs.team_2v2", "formats"), ("cogs.role_panel", "player"),
    ("cogs.casual_results_plus", "casual"), ("cogs.casual_matches", "casual"),
    ("cogs.bracket_full", "bracket"), ("cogs.bracket", "bracket"),
    ("cogs.swiss_graphics", "swiss"), ("cogs.swiss", "swiss"),
    ("cogs.deck_stats", "deck"), ("cogs.archetype_artworks", "archetype"),
    ("cogs.archetype_catalog", "archetype"),
    ("cogs.player_experience", "player"), ("cogs.profile", "player"),
    ("cogs.competitive", "competition"), ("cogs.setup_assistant", "setup"),
    ("cogs.staff_logs", "staff"), ("cogs.professional_tools", "staff"),
    ("cogs.repair", "staff"), ("cogs.admin", "staff"),
    ("cogs.graphics_preview", "graphics"),
    ("cogs.community_tools", "community"),
    ("cogs.system_health", "system"), ("cogs.public_website", "system"),
    ("cogs.expansion_tasks", "system"), ("cogs.expansion_hub", "system"),
)
PREFIX_GROUPS = (
    ("tournament_", "tournament"), ("match_", "match"),
    ("result_", "results"), ("results_", "results"),
    ("bracket_", "bracket"), ("swiss_", "swiss"),
    ("deck_", "deck"), ("archetype_", "archetype"),
    ("artwork_", "archetype"), ("player_", "player"),
    ("profile_", "player"), ("casual_", "casual"),
    ("competition_", "competition"), ("competitive_", "competition"),
    ("season_", "competition"), ("ranking_", "competition"),
    ("leaderboard_", "competition"), ("staff_", "staff"),
    ("admin_", "staff"), ("setup_", "setup"),
    ("graphics_", "graphics"), ("preview_", "graphics"),
    ("community_", "community"), ("system_", "system"),
    ("health_", "system"),
)
EXPLICIT_GROUPS = {
    "register": "tournament", "join": "tournament", "players": "tournament",
    "unregister": "tournament", "leave": "tournament",
    "result": "results", "hamtaro_site": "community",
    "meta": "competition", "coinflip": "community", "dice": "community",
    "bracket": "bracket", "profile": "player", "nextmatch": "match",
    "matches": "match", "participants": "tournament", "seed": "tournament",
    "reshuffle": "tournament", "approve_result": "results",
    "reject_result": "results", "pending_results": "results",
    "deck_stats": "deck", "setup": "setup", "setup_plus": "setup",
    "repair": "staff", "staff_logs": "staff", "health": "system",
    "doctor": "system",
    "judge_call": "match", "judge_list": "staff", "judge_resolve": "staff",
    "feature_match": "graphics", "feature_status": "graphics",
    "schedule_create": "planning", "schedule_list": "planning",
    "schedule_cancel": "planning", "secure_history": "system",
    "secure_revert": "system", "swiss_pair": "swiss",
}
ROOT_TO_SUB = {
    "bracket": "voir", "profile": "voir", "matches": "voir",
    "participants": "liste", "setup": "ouvrir", "health": "etat",
}

ADMIN_MODULES = (
    "cogs.setup_assistant", "cogs.repair", "cogs.system_health",
    "cogs.tournament_export", "cogs.archetype_repair",
)
ADMIN_NAMES = {"hamtaro_backup", "hamtaro_health", "repair", "doctor"}
ADMIN_PREFIXES = ("setup_", "repair_", "health_", "backup_", "export_")
STAFF_MODULES = (
    "cogs.admin", "cogs.end_tournament", "cogs.tournament_context",
    "cogs.tournament_manage", "cogs.tournament_progression",
    "cogs.tournament_start_preview", "cogs.tournament_undo",
    "cogs.staff_logs", "cogs.professional_tools",
)
STAFF_NAMES = {
    "pending_results", "result_setup", "special_result", "admin_win",
    "start_tournament", "swiss_start", "staff_panel", "tournament_manage",
}
STAFF_PREFIXES = (
    "admin_", "approve_", "cancel_", "create_", "delete_", "end_",
    "force_", "generate_", "pause_", "progression_", "publish_",
    "reject_", "resume_", "special_", "staff_", "start_", "undo_",
)


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


def _leaf_commands(item) -> Iterable[app_commands.Command]:
    if isinstance(item, app_commands.Command):
        yield item
    elif isinstance(item, app_commands.Group):
        for child in item.commands:
            yield from _leaf_commands(child)


def _module(command) -> str:
    value = getattr(command, "module", None)
    if value:
        return str(value)
    callback = getattr(command, "callback", None)
    return str(getattr(callback, "__module__", "") or "")


def _classify(command) -> str:
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
        ("swiss", {"swiss", "suisse"}), ("deck", {"deck", "banlist", "format"}),
        ("archetype", {"archetype", "artwork"}),
        ("player", {"player", "profile", "joueur", "trophy", "trophies"}),
        ("casual", {"casual"}),
        ("competition", {"season", "ranking", "leaderboard", "competition"}),
        ("staff", {"staff", "admin", "repair", "moderation", "log"}),
        ("setup", {"setup", "configure", "config"}),
        ("graphics", {"graphics", "graphic", "image", "preview"}),
        ("community", {"community", "event", "fun"}),
        ("formats", {"boss", "halloween", "duo", "team"}),
    )
    for group, words in keyword_groups:
        if tokens & words:
            return group
    return "system"


def _has_staff_check(command: app_commands.Command) -> bool:
    for check in getattr(command, "checks", ()):
        identity = (
            f"{getattr(check, '__module__', '')}."
            f"{getattr(check, '__qualname__', '')}"
        ).lower()
        if "staff_only" in identity or "staffonly" in identity:
            return True
    return False


def _permission_is_protected(command: app_commands.Command) -> bool:
    permissions = getattr(command, "default_permissions", None)
    if permissions is None:
        return False
    return int(permissions.value) == 0 or any(
        bool(getattr(permissions, name, False))
        for name in (
            "administrator", "manage_guild", "manage_channels",
            "manage_messages", "moderate_members", "kick_members", "ban_members",
        )
    )


def _role_for_command(command: app_commands.Command) -> str:
    name = str(command.extras.get("_hamtaro_original_name", command.name)).lower()
    module = _module(command).lower()
    if name in ADMIN_NAMES or name.startswith(ADMIN_PREFIXES) or module.startswith(ADMIN_MODULES):
        return "admin"
    if (
        name in STAFF_NAMES
        or name.startswith(STAFF_PREFIXES)
        or module.startswith(STAFF_MODULES)
        or _permission_is_protected(command)
        or _has_staff_check(command)
    ):
        return "staff"
    return "joueur"


def _detach_leaf_commands(group: app_commands.Group) -> list[app_commands.Command]:
    """Détache les actions d'un ancien groupe pour les reclasser par usage."""
    leaves: list[app_commands.Command] = []
    for child in list(group.commands):
        if isinstance(child, app_commands.Command):
            group.remove_command(child.name)
            leaves.append(child)
        elif isinstance(child, app_commands.Group):
            leaves.extend(_detach_leaf_commands(child))
            group.remove_command(child.name)
    return leaves


def _sub_name(original: str, technical_group: str) -> str:
    name = original.lower()
    prefixes = {
        "results": ("result_", "results_"),
        "player": ("player_", "profile_"),
        "competition": ("competition_", "competitive_", "season_", "ranking_"),
        "graphics": ("graphics_", "graphic_", "preview_"),
        "system": ("system_", "health_", "hamtaro_"),
    }.get(technical_group, (technical_group + "_",))
    for prefix in prefixes:
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
    index = 2
    while True:
        suffix = f"_{index}"
        candidate = f"{desired[:32-len(suffix)]}{suffix}"
        if candidate not in used:
            return candidate
        index += 1


def _role_group(tree, role: str) -> app_commands.Group:
    existing = tree.get_command(role, type=discord.AppCommandType.chat_input)
    if isinstance(existing, app_commands.Group):
        return existing
    group = app_commands.Group(
        name=role,
        description=ROLE_DESCRIPTIONS[role],
        guild_only=True,
        default_permissions=(
            discord.Permissions(administrator=True)
            if role == "admin"
            else None
        ),
        extras={"hamtaro_role_space": role},
    )
    tree.add_command(group)
    return group


def _category_group(role_group: app_commands.Group, category: str) -> app_commands.Group:
    index = 1
    while True:
        name = category if index == 1 else f"{category}{index}"
        existing = next((child for child in role_group.commands if child.name == name), None)
        if existing is None:
            if len(role_group.commands) >= MAX_GROUP_CHILDREN:
                raise RuntimeError(f"Espace /{role_group.name} plein ({MAX_GROUP_CHILDREN} groupes).")
            group = app_commands.Group(
                name=name[:32],
                description=CATEGORY_DESCRIPTIONS.get(category, "Actions Hamtaro regroupées.")[:100],
            )
            role_group.add_command(group)
            return group
        if isinstance(existing, app_commands.Group) and len(existing.commands) < MAX_GROUP_CHILDREN:
            return existing
        index += 1


def _preserve_root_only_restrictions(command: app_commands.Command) -> int:
    """Transforme les restrictions de racine en contrôles exécutés côté bot."""
    added = 0
    extras = command.extras
    required = getattr(command, "default_permissions", None)
    if required is not None and not extras.get("_hamtaro_default_permissions_guard"):
        required_value = int(required.value)

        async def default_permissions_guard(interaction: discord.Interaction) -> bool:
            permissions = getattr(interaction.user, "guild_permissions", None)
            if permissions is None:
                return False
            if getattr(permissions, "administrator", False):
                return True
            if required_value == 0:
                return False
            return (int(permissions.value) & required_value) == required_value

        command.add_check(default_permissions_guard)
        extras["_hamtaro_default_permissions_guard"] = True
        added += 1
    if getattr(command, "nsfw", False) and not extras.get("_hamtaro_nsfw_guard"):
        async def nsfw_guard(interaction: discord.Interaction) -> bool:
            checker = getattr(interaction.channel, "is_nsfw", None)
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
    """Réunit l'arbre Discord sous /joueur, /staff et /admin, sans perte."""
    logger = logger or LOGGER
    before = _root_commands(tree)
    actions_before = _count_actions(tree)
    movable = []
    protected = []
    restriction_guards = 0

    for item in before:
        if item.name in DIRECT_COMMANDS or item.name in ROLE_ROOTS:
            continue
        if getattr(item, "_guild_ids", None):
            protected.append(item.name)
            continue
        movable.append(item)

    for item in movable:
        tree.remove_command(item.name, type=discord.AppCommandType.chat_input)

    for item in movable:
        original = item.name
        if isinstance(item, app_commands.Group):
            for leaf in _detach_leaf_commands(item):
                leaf_original = leaf.name
                leaf.extras.setdefault("_hamtaro_original_name", leaf_original)
                technical = _classify(leaf)
                destination = _category_group(
                    _role_group(tree, _role_for_command(leaf)),
                    TECHNICAL_CATEGORIES[technical],
                )
                leaf.name = _unique_name(
                    destination,
                    _sub_name(leaf_original, technical),
                    leaf_original,
                )
                restriction_guards += _preserve_root_only_restrictions(leaf)
                destination.add_command(leaf)
            continue
        if not isinstance(item, app_commands.Command):
            continue
        item.extras.setdefault("_hamtaro_original_name", original)
        technical = _classify(item)
        destination = _category_group(
            _role_group(tree, _role_for_command(item)), TECHNICAL_CATEGORIES[technical],
        )
        item.name = _unique_name(destination, _sub_name(original, technical), original)
        restriction_guards += _preserve_root_only_restrictions(item)
        destination.add_command(item)

    after = _root_commands(tree)
    actions_after = _count_actions(tree)
    if len(after) > MAX_ROOT_COMMANDS:
        raise RuntimeError(f"Arbre slash encore trop gros : {len(after)}/{MAX_ROOT_COMMANDS} racines.")
    if actions_after != actions_before:
        raise RuntimeError(f"Perte d'actions pendant la compaction : {actions_before} -> {actions_after}.")

    role_sizes = {
        role: len(group.commands)
        for role in ROLE_ROOTS
        if isinstance((group := tree.get_command(role)), app_commands.Group)
    }
    logger.info(
        "Navigation par rôle : %s racines -> %s ; %s actions conservées ; "
        "%s déplacées ; %s garde(s) ajoutée(s).",
        len(before), len(after), actions_after, len(movable), restriction_guards,
    )
    if protected:
        logger.warning("Commandes liées à une guild non déplacées : %s", ", ".join(sorted(protected)))
    return CompactionReport(
        roots_before=len(before), roots_after=len(after), actions_before=actions_before,
        actions_after=actions_after, moved=len(movable), group_sizes=role_sizes,
        protected_roots=tuple(sorted(protected)),
    )


def log_command_tree_summary(tree, *, logger=None) -> None:
    logger = logger or LOGGER
    roots = _root_commands(tree)
    actions = _count_actions(tree)
    groups = [item for item in roots if isinstance(item, app_commands.Group)]
    direct = [item for item in roots if isinstance(item, app_commands.Command)]
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("🐹 NAVIGATION HAMTARO PAR RÔLE")
    logger.info("Commandes racines  : %s / %s", len(roots), MAX_ROOT_COMMANDS)
    logger.info("Actions conservées : %s", actions)
    for group in sorted(groups, key=lambda item: item.name):
        logger.info("  /%-14s %2s rubrique(s)", group.name, len(group.commands))
    if direct:
        logger.info("Accès directs : %s", ", ".join(f"/{item.name}" for item in direct))
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
