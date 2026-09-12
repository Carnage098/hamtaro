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
        "hamtaro", "help", "register", "joueur", "staff", "admin",
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
    assert hub.find_command("register").qualified_name == "register"
    assert hub.find_command("hamtaro_health").qualified_name == "admin maintenance health"
    assert hub.find_command("commande_absente") is None
