from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable

import discord
from discord import app_commands
from discord.ext import commands

from utils.permissions import is_staff_member


HELP_PAGE_SIZE = 7
HELP_TIMEOUT_SECONDS = 300


@dataclass(slots=True)
class HelpCommandInfo:
    """Informations affichables pour une commande slash."""

    command: app_commands.Command
    qualified_name: str
    description: str
    syntax: str
    category: str
    staff_only: bool


CATEGORY_META: "OrderedDict[str, tuple[str, str]]" = OrderedDict(
    {
        "Démarrage": (
            "🏠",
            "S'inscrire, consulter le tournoi et comprendre Hamtaro.",
        ),
        "Matchs et résultats": (
            "⚔️",
            "Voir son prochain match, déclarer un score et consulter l'historique.",
        ),
        "Bracket": (
            "🌳",
            "Consulter les tableaux à élimination directe et leurs images.",
        ),
        "Rondes suisses": (
            "🇨🇭",
            "Pairings, classements et commandes liées aux rondes suisses.",
        ),
        "Profils et statistiques": (
            "📊",
            "Profils des joueurs, statistiques et données sur les decks.",
        ),
        "Images et affichages": (
            "🖼️",
            "Générer les aperçus, brackets et classements illustrés.",
        ),
        "Staff — tournois": (
            "🏟️",
            "Créer, lancer, mettre en pause et faire progresser les tournois.",
        ),
        "Staff — résultats": (
            "✅",
            "Valider, corriger, refuser ou annuler des résultats.",
        ),
        "Staff — configuration": (
            "⚙️",
            "Configurer les salons, réparer le bot et exporter les données.",
        ),
        "Autres commandes": (
            "🐹",
            "Commandes qui ne correspondent pas encore à une catégorie dédiée.",
        ),
    }
)


# Ces noms complètent la détection faite avec default_permissions.
# Ils permettent de masquer correctement les commandes staff même lorsqu'une
# commande utilise seulement un check personnalisé comme @staff_only().
STAFF_COMMAND_NAMES = {
    "add_player",
    "admin_win",
    "approve_result",
    "cancel_tournament",
    "create_tournament",
    "end_tournament",
    "export_tournament",
    "generate_next_round",
    "match_center_repair",
    "match_center_setup",
    "pause_tournament",
    "pending_results",
    "progression_setup",
    "progression_status",
    "publish_matches",
    "reject_result",
    "remove_player",
    "repair_tournament",
    "result_setup",
    "resume_tournament",
    "special_result",
    "staff_logs_disable",
    "staff_logs_setup",
    "start_tournament",
    "tournament_check",
    "tournament_context",
    "tournament_context_clear",
    "tournament_context_set",
    "undo_history",
    "undo_tournament_action",
}

STAFF_PREFIXES = (
    "admin_",
    "approve_",
    "cancel_",
    "create_",
    "delete_",
    "end_",
    "export_",
    "force_",
    "generate_",
    "pause_",
    "progression_",
    "publish_",
    "reject_",
    "repair_",
    "resume_",
    "setup_",
    "special_",
    "staff_",
    "undo_",
)


class HelpCategorySelect(discord.ui.Select):
    """Menu déroulant permettant de choisir une catégorie."""

    def __init__(self, parent_view: "InteractiveHelpView") -> None:
        self.parent_view = parent_view

        options: list[discord.SelectOption] = [
            discord.SelectOption(
                label="Accueil",
                value="__home__",
                emoji="🏠",
                description="Revenir au menu principal.",
                default=parent_view.current_category is None,
            )
        ]

        for category, commands_list in parent_view.categories.items():
            emoji, description = CATEGORY_META[category]
            options.append(
                discord.SelectOption(
                    label=category,
                    value=category,
                    emoji=emoji,
                    description=f"{len(commands_list)} commande(s) — {description}"[:100],
                    default=parent_view.current_category == category,
                )
            )

        super().__init__(
            placeholder="Choisis une catégorie…",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        self.parent_view.current_category = (
            None if selected == "__home__" else selected
        )
        self.parent_view.page = 0
        self.parent_view.refresh_components()

        await interaction.response.edit_message(
            embed=self.parent_view.build_embed(),
            view=self.parent_view,
        )


class InteractiveHelpView(discord.ui.View):
    """Navigation interactive du menu d'aide."""

    def __init__(
        self,
        *,
        cog: "HelpCog",
        requester_id: int,
        is_staff: bool,
        categories: "OrderedDict[str, list[HelpCommandInfo]]",
    ) -> None:
        super().__init__(timeout=HELP_TIMEOUT_SECONDS)
        self.cog = cog
        self.requester_id = requester_id
        self.is_staff = is_staff
        self.categories = categories
        self.current_category: str | None = None
        self.page = 0
        self.message: discord.InteractionMessage | None = None

        self.refresh_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True

        await interaction.response.send_message(
            "❌ Ce menu d'aide appartient à une autre personne. Utilise `/help`.",
            ephemeral=True,
        )
        return False

    def refresh_components(self) -> None:
        self.clear_items()
        self.add_item(HelpCategorySelect(self))

        if self.current_category is not None:
            command_count = len(self.categories.get(self.current_category, []))
            page_count = max(1, (command_count + HELP_PAGE_SIZE - 1) // HELP_PAGE_SIZE)

            previous_button = discord.ui.Button(
                label="Précédent",
                emoji="◀️",
                style=discord.ButtonStyle.secondary,
                disabled=self.page <= 0,
                row=1,
            )
            previous_button.callback = self._previous_page
            self.add_item(previous_button)

            home_button = discord.ui.Button(
                label="Accueil",
                emoji="🏠",
                style=discord.ButtonStyle.primary,
                row=1,
            )
            home_button.callback = self._go_home
            self.add_item(home_button)

            next_button = discord.ui.Button(
                label="Suivant",
                emoji="▶️",
                style=discord.ButtonStyle.secondary,
                disabled=self.page >= page_count - 1,
                row=1,
            )
            next_button.callback = self._next_page
            self.add_item(next_button)

    async def _previous_page(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        self.refresh_components()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    async def _next_page(self, interaction: discord.Interaction) -> None:
        if self.current_category is not None:
            command_count = len(self.categories.get(self.current_category, []))
            page_count = max(1, (command_count + HELP_PAGE_SIZE - 1) // HELP_PAGE_SIZE)
            self.page = min(page_count - 1, self.page + 1)

        self.refresh_components()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    async def _go_home(self, interaction: discord.Interaction) -> None:
        self.current_category = None
        self.page = 0
        self.refresh_components()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    def build_embed(self) -> discord.Embed:
        if self.current_category is None:
            return self.cog.build_home_embed(
                categories=self.categories,
                is_staff=self.is_staff,
            )

        return self.cog.build_category_embed(
            category=self.current_category,
            commands_list=self.categories[self.current_category],
            page=self.page,
            is_staff=self.is_staff,
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


class HelpCog(commands.Cog):
    """Aide interactive et automatiquement synchronisée avec les slash commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ==========================================================
    # DÉTECTION ET CLASSEMENT
    # ==========================================================

    @staticmethod
    def _member_is_staff(user: discord.abc.User) -> bool:
        if not isinstance(user, discord.Member):
            return False

        permissions = user.guild_permissions
        if permissions.administrator or permissions.manage_guild:
            return True

        try:
            return bool(is_staff_member(user))
        except (AttributeError, TypeError):
            return False

    @staticmethod
    def _permission_marks_staff(command: app_commands.Command) -> bool:
        permissions = getattr(command, "default_permissions", None)
        if permissions is None:
            return False

        protected_permissions = (
            "administrator",
            "manage_guild",
            "manage_channels",
            "manage_messages",
            "moderate_members",
            "kick_members",
            "ban_members",
        )

        return any(
            bool(getattr(permissions, permission_name, False))
            for permission_name in protected_permissions
        )

    def _command_is_staff_only(self, command: app_commands.Command) -> bool:
        normalized_name = command.qualified_name.lower().replace(" ", "_")
        root_name = normalized_name.split("_")[0]
        callback = getattr(command, "callback", None)
        module_name = getattr(callback, "__module__", "").lower()

        if self._permission_marks_staff(command):
            return True

        if normalized_name in STAFF_COMMAND_NAMES:
            return True

        if normalized_name.startswith(STAFF_PREFIXES):
            return True

        if root_name in {
            "admin",
            "approve",
            "cancel",
            "create",
            "delete",
            "end",
            "export",
            "force",
            "generate",
            "pause",
            "progression",
            "publish",
            "reject",
            "repair",
            "resume",
            "setup",
            "special",
            "staff",
            "undo",
        }:
            return True

        staff_modules = (
            "cogs.admin",
            "cogs.repair",
            "cogs.staff_logs",
            "cogs.end_tournament",
            "cogs.tournament_undo",
            "cogs.tournament_export",
        )
        return module_name.startswith(staff_modules)

    @staticmethod
    def _build_syntax(command: app_commands.Command) -> str:
        parts = [f"/{command.qualified_name}"]

        for parameter in command.parameters:
            parameter_name = getattr(parameter, "display_name", parameter.name)
            if parameter.required:
                parts.append(f"<{parameter_name}>")
            else:
                parts.append(f"[{parameter_name}]")

        return " ".join(parts)

    @staticmethod
    def _category_for(command: app_commands.Command, staff_only: bool) -> str:
        name = command.qualified_name.lower().replace(" ", "_")
        callback = getattr(command, "callback", None)
        module_name = getattr(callback, "__module__", "").lower()

        if staff_only:
            if any(
                token in name
                for token in (
                    "approve",
                    "reject",
                    "pending_result",
                    "special_result",
                    "admin_win",
                    "undo",
                    "result_setup",
                )
            ):
                return "Staff — résultats"

            if any(
                token in name
                for token in (
                    "setup",
                    "repair",
                    "export",
                    "logs",
                    "context",
                    "status",
                    "publish_matches",
                )
            ):
                return "Staff — configuration"

            return "Staff — tournois"

        if name in {
            "help",
            "rules",
            "register",
            "join",
            "leave",
            "unregister",
            "tournament",
            "tournament_info",
            "tournament_status",
        } or module_name.endswith(("registration", "tournament_status")):
            return "Démarrage"

        if any(
            token in name
            for token in (
                "nextmatch",
                "result",
                "match_history",
                "history",
            )
        ) and "pending" not in name:
            return "Matchs et résultats"

        if "swiss" in name:
            return "Rondes suisses"

        if any(
            token in name
            for token in (
                "bracket",
                "final_bracket",
            )
        ):
            if "image" in name or "preview" in name:
                return "Images et affichages"
            return "Bracket"

        if any(
            token in name
            for token in (
                "profile",
                "deck_stats",
                "leaderboard",
                "ranking",
                "standings",
                "stats",
            )
        ):
            return "Profils et statistiques"

        if any(
            token in name
            for token in (
                "image",
                "preview",
                "graphics",
            )
        ):
            return "Images et affichages"

        return "Autres commandes"

    def _iter_chat_commands(self) -> Iterable[app_commands.Command]:
        def walk(item: app_commands.Command | app_commands.Group):
            if isinstance(item, app_commands.Group):
                for child in item.commands:
                    yield from walk(child)
            elif isinstance(item, app_commands.Command):
                yield item

        for root_command in self.bot.tree.get_commands():
            if isinstance(root_command, (app_commands.Command, app_commands.Group)):
                yield from walk(root_command)

    def collect_commands(
        self,
        *,
        is_staff: bool,
    ) -> "OrderedDict[str, list[HelpCommandInfo]]":
        category_map: dict[str, list[HelpCommandInfo]] = {
            category: [] for category in CATEGORY_META
        }

        seen_names: set[str] = set()

        for command in self._iter_chat_commands():
            qualified_name = command.qualified_name
            if qualified_name in seen_names:
                continue
            seen_names.add(qualified_name)

            staff_only = self._command_is_staff_only(command)
            if staff_only and not is_staff:
                continue

            category = self._category_for(command, staff_only)
            description = command.description or "Aucune description disponible."

            category_map[category].append(
                HelpCommandInfo(
                    command=command,
                    qualified_name=qualified_name,
                    description=description,
                    syntax=self._build_syntax(command),
                    category=category,
                    staff_only=staff_only,
                )
            )

        ordered_categories: "OrderedDict[str, list[HelpCommandInfo]]" = OrderedDict()
        for category in CATEGORY_META:
            commands_list = sorted(
                category_map[category],
                key=lambda info: info.qualified_name,
            )
            if commands_list:
                ordered_categories[category] = commands_list

        return ordered_categories

    # ==========================================================
    # EMBEDS
    # ==========================================================

    @staticmethod
    def build_home_embed(
        *,
        categories: "OrderedDict[str, list[HelpCommandInfo]]",
        is_staff: bool,
    ) -> discord.Embed:
        command_count = sum(len(commands_list) for commands_list in categories.values())
        detected_role = "Staff" if is_staff else "Joueur"

        embed = discord.Embed(
            title="🐹 Centre d'aide Hamtaro",
            description=(
                f"Rôle détecté : **{detected_role}**\n"
                f"Commandes accessibles : **{command_count}**\n\n"
                "Choisis une catégorie dans le menu ci-dessous. "
                "Les commandes staff sont automatiquement masquées aux joueurs."
            ),
            color=discord.Color.gold(),
        )

        for category, commands_list in categories.items():
            emoji, description = CATEGORY_META[category]
            embed.add_field(
                name=f"{emoji} {category} — {len(commands_list)}",
                value=description,
                inline=False,
            )

        embed.set_footer(
            text="Le menu lit automatiquement les commandes chargées par le bot."
        )
        return embed

    @staticmethod
    def build_category_embed(
        *,
        category: str,
        commands_list: list[HelpCommandInfo],
        page: int,
        is_staff: bool,
    ) -> discord.Embed:
        emoji, description = CATEGORY_META[category]
        page_count = max(1, (len(commands_list) + HELP_PAGE_SIZE - 1) // HELP_PAGE_SIZE)
        safe_page = min(max(page, 0), page_count - 1)
        start = safe_page * HELP_PAGE_SIZE
        displayed_commands = commands_list[start : start + HELP_PAGE_SIZE]

        embed = discord.Embed(
            title=f"{emoji} {category}",
            description=description,
            color=(
                discord.Color.orange()
                if category.startswith("Staff")
                else discord.Color.blurple()
            ),
        )

        for info in displayed_commands:
            staff_badge = " 🔒" if info.staff_only and is_staff else ""
            embed.add_field(
                name=f"`{info.syntax}`{staff_badge}",
                value=info.description,
                inline=False,
            )

        embed.set_footer(
            text=(
                f"Page {safe_page + 1}/{page_count} • "
                f"{len(commands_list)} commande(s) dans cette catégorie"
            )
        )
        return embed

    @staticmethod
    def build_command_embed(info: HelpCommandInfo) -> discord.Embed:
        emoji, _ = CATEGORY_META[info.category]
        embed = discord.Embed(
            title=f"{emoji} /{info.qualified_name}",
            description=info.description,
            color=(
                discord.Color.orange()
                if info.staff_only
                else discord.Color.blurple()
            ),
        )
        embed.add_field(
            name="Utilisation",
            value=f"`{info.syntax}`",
            inline=False,
        )
        embed.add_field(
            name="Catégorie",
            value=info.category,
            inline=True,
        )
        embed.add_field(
            name="Accès",
            value="🔒 Staff uniquement" if info.staff_only else "👤 Joueurs et staff",
            inline=True,
        )

        if info.command.parameters:
            parameter_lines: list[str] = []
            for parameter in info.command.parameters:
                display_name = getattr(parameter, "display_name", parameter.name)
                requirement = "obligatoire" if parameter.required else "facultatif"
                parameter_description = parameter.description or "Aucune précision."
                parameter_lines.append(
                    f"• `{display_name}` — {requirement} : {parameter_description}"
                )

            embed.add_field(
                name="Paramètres",
                value="\n".join(parameter_lines)[:1024],
                inline=False,
            )

        return embed

    # ==========================================================
    # COMMANDE /HELP
    # ==========================================================

    @app_commands.command(
        name="help",
        description="Ouvrir l'aide interactive de Hamtaro.",
    )
    @app_commands.describe(
        commande="Afficher directement l'aide d'une commande précise.",
        visible="Rendre l'aide visible à tout le salon.",
    )
    async def help_command(
        self,
        interaction: discord.Interaction,
        commande: str | None = None,
        visible: bool = False,
    ) -> None:
        is_staff = self._member_is_staff(interaction.user)
        categories = self.collect_commands(is_staff=is_staff)

        all_commands = [
            info
            for commands_list in categories.values()
            for info in commands_list
        ]

        if commande:
            normalized_query = commande.strip().lower().lstrip("/")
            exact_match = next(
                (
                    info
                    for info in all_commands
                    if info.qualified_name.lower() == normalized_query
                ),
                None,
            )

            if exact_match is not None:
                await interaction.response.send_message(
                    embed=self.build_command_embed(exact_match),
                    ephemeral=not visible,
                )
                return

            partial_matches = [
                info
                for info in all_commands
                if normalized_query in info.qualified_name.lower()
            ][:15]

            if not partial_matches:
                await interaction.response.send_message(
                    "❌ Aucune commande accessible ne correspond à cette recherche.",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title="🔎 Commandes trouvées",
                description="\n".join(
                    f"• `{info.syntax}` — {info.description}"
                    for info in partial_matches
                )[:4000],
                color=discord.Color.blurple(),
            )
            embed.set_footer(text="Relance /help avec le nom exact pour voir les détails.")
            await interaction.response.send_message(
                embed=embed,
                ephemeral=not visible,
            )
            return

        view = InteractiveHelpView(
            cog=self,
            requester_id=interaction.user.id,
            is_staff=is_staff,
            categories=categories,
        )

        await interaction.response.send_message(
            embed=view.build_embed(),
            view=view,
            ephemeral=not visible,
        )

        try:
            view.message = await interaction.original_response()
        except (discord.NotFound, discord.HTTPException):
            view.message = None

    @help_command.autocomplete("commande")
    async def help_command_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        is_staff = self._member_is_staff(interaction.user)
        categories = self.collect_commands(is_staff=is_staff)
        normalized_current = current.lower().lstrip("/")

        matches: list[app_commands.Choice[str]] = []
        for commands_list in categories.values():
            for info in commands_list:
                if normalized_current not in info.qualified_name.lower():
                    continue

                matches.append(
                    app_commands.Choice(
                        name=f"/{info.qualified_name} — {info.description}"[:100],
                        value=info.qualified_name[:100],
                    )
                )

                if len(matches) >= 25:
                    return matches

        return matches


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
