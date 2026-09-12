from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from cogs.hamtaro_hub import HamtaroHubCog
from services.command_compactor import compact_command_tree


def _command(name: str, module: str) -> app_commands.Command:
    async def callback(interaction: discord.Interaction) -> None:
        del interaction

    callback.__module__ = module
    return app_commands.Command(name=name, description="Test Hamtaro", callback=callback)


def _tree() -> tuple[commands.Bot, app_commands.CommandTree]:
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    bot.db = object()  # type: ignore[attr-defined]
    return bot, bot.tree


def test_navigation_has_three_role_spaces_and_keeps_every_action() -> None:
    bot, tree = _tree()
    tree.add_command(_command("hamtaro", "cogs.hamtaro_hub"))
    tree.add_command(_command("help", "cogs.help"))
    tree.add_command(_command("register", "cogs.registration"))
    tree.add_command(_command("create_tournament", "cogs.tournament"))
    tree.add_command(_command("hamtaro_health", "cogs.system_health"))

    legacy = app_commands.Group(name="boss", description="Ancien groupe")
    legacy.add_command(_command("inscription", "cogs.boss"))
    legacy.add_command(_command("set", "cogs.boss"))
    tree.add_command(legacy)

    before = sum(isinstance(item, app_commands.Command) for item in tree.walk_commands())
    report = compact_command_tree(tree)
    after = sum(isinstance(item, app_commands.Command) for item in tree.walk_commands())

    assert before == after == report.actions_after
    assert {item.name for item in tree.get_commands()} == {
        "hamtaro", "aide", "inscription", "joueur", "staff", "admin",
    }
    assert all(
        len(item.qualified_name.split()) <= 3
        for item in tree.walk_commands()
        if isinstance(item, app_commands.Command)
    )
    assert tree.get_command("admin").default_permissions.administrator  # type: ignore[union-attr]

    # La seconde passe (après les cogs optionnels) ne doit rien déplacer.
    second = compact_command_tree(tree)
    assert second.moved == 0
    assert second.actions_after == before

def test_hub_resolves_commands_after_compaction() -> None:
    bot, tree = _tree()
    tree.add_command(_command("register", "cogs.registration"))
    tree.add_command(_command("hamtaro_health", "cogs.system_health"))
    compact_command_tree(tree)

    hub = HamtaroHubCog(bot)
    assert hub.find_command("register").qualified_name == "inscription"
    assert hub.find_command("hamtaro_health").qualified_name == "admin maintenance sante"
    assert hub.find_command("commande_absente") is None


def test_visible_command_names_are_french_after_compaction() -> None:
    _bot, tree = _tree()
    tree.add_command(_command("result", "cogs.results"))
    tree.add_command(_command("create_tournament", "cogs.tournament"))
    tree.add_command(_command("pending_results", "cogs.results"))

    compact_command_tree(tree)

    qualified_names = {
        command.qualified_name
        for command in tree.walk_commands()
        if isinstance(command, app_commands.Command)
    }
    assert "resultat" in qualified_names
    assert "staff tournois creer_tournoi" in qualified_names
    assert "joueur resultats resultats_en_attente" not in qualified_names
    assert any(name.endswith("resultats_en_attente") for name in qualified_names)


def test_large_role_space_is_split_below_discord_character_limit() -> None:
    _bot, tree = _tree()
    for index in range(45):
        command = _command(f"player_tool_{index}", "cogs.player_experience")
        command.description = "O" * 100
        tree.add_command(command)

    compact_command_tree(tree)
    role_pages = [
        command
        for command in tree.get_commands()
        if command.name.startswith("joueur")
    ]
    assert len(role_pages) >= 2

    def text_characters(value: object) -> int:
        if isinstance(value, dict):
            return sum(
                len(str(child))
                if key in {"name", "description", "value"}
                and isinstance(child, (str, int, float))
                else text_characters(child)
                for key, child in value.items()
            )
        if isinstance(value, list):
            return sum(text_characters(child) for child in value)
        return 0

    assert all(text_characters(page.to_dict(tree)) <= 4000 for page in role_pages)


def test_staff_space_can_use_a_fourth_page_after_translation() -> None:
    _bot, tree = _tree()
    for category_index in range(4):
        for command_index in range(20):
            command = _command(
                f"staff_{category_index}_{command_index}",
                f"cogs.staff_section_{category_index}",
            )
            command.description = "Outil détaillé réservé à l'équipe d'organisation."
            tree.add_command(command)

    compact_command_tree(tree)

    pages = [
        command
        for command in tree.get_commands()
        if command.name.startswith("staff")
    ]
    assert len(pages) <= 4
