from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands
from jinja2 import (
    Environment,
    FileSystemLoader,
    select_autoescape,
)

from services.analytics_service import AnalyticsService
from services.bracket_export_service import (
    BracketExportService,
    FINISHED_STATUSES,
)


LOGGER = logging.getLogger(__name__)
HAMTARO_SITE_BUILD = "interaction-fix-2026-08-04-2133"


def _truthy(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default

    return value.strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }


class PublicWebsiteCog(commands.Cog):
    """
    Site vitrine Hamtaro lancé dans le même processus que le bot.

    Cette solution garde le même accès SQLite et le même moteur d'image.
    Elle n'ajoute aucune administration web.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = BracketExportService(bot)
        self.analytics = AnalyticsService()

        project_root = Path(__file__).resolve().parent.parent
        self.web_directory = project_root / "web"
        self.template_directory = self.web_directory / "templates"
        self.static_directory = self.web_directory / "static"

        self.jinja = Environment(
            loader=FileSystemLoader(str(self.template_directory)),
            autoescape=select_autoescape(("html", "xml")),
            enable_async=False,
        )

        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.application: web.Application | None = None

    async def cog_load(self) -> None:
        LOGGER.warning(
            "[HAMTARO_SITE] version=%s fichier=%s",
            HAMTARO_SITE_BUILD,
            __file__,
        )

        if not _truthy(os.getenv("WEBSITE_ENABLED"), default=True):
            LOGGER.info("Site public Hamtaro désactivé.")
            return

        await self._start_server()

    def cog_unload(self) -> None:
        if self.runner is not None:
            asyncio.create_task(self._stop_server())

    # ==========================================================
    # SERVEUR
    # ==========================================================

    async def _start_server(self) -> None:
        if self.runner is not None:
            return

        application = web.Application(
            middlewares=[
                self._security_headers_middleware,
                self._error_middleware,
            ]
        )

        application.router.add_get("/", self.home_page)
        application.router.add_get("/tournaments", self.index_page)
        application.router.add_get(
            r"/tournaments/{tournament_id:\d+}",
            self.tournament_page,
        )
        application.router.add_get(
            r"/api/tournaments/{tournament_id:\d+}/bracket.png",
            self.bracket_image,
        )
        application.router.add_get(
            r"/api/tournaments/{tournament_id:\d+}/version.json",
            self.bracket_version,
        )
        application.router.add_get(
            r"/players/{discord_id:\d+}",
            self.player_page,
        )
        application.router.add_get("/profiles", self.profiles_page)
        application.router.add_get(
            "/participants",
            self.participants_page,
        )
        application.router.add_get("/guide", self.guide_page)
        application.router.add_get("/results", self.results_page)
        application.router.add_get("/decks", self.decks_page)
        application.router.add_get("/archives", self.archives_page)
        application.router.add_get("/health", self.health_page)
        application.router.add_get("/favicon.ico", self.favicon)

        if self.static_directory.exists():
            application.router.add_static(
                "/static/",
                path=str(self.static_directory),
                name="static",
            )

        runner = web.AppRunner(
            application,
            access_log=LOGGER,
        )
        await runner.setup()

        host = os.getenv("WEBSITE_HOST", "0.0.0.0")
        try:
            port = int(os.getenv("PORT", "8080"))
        except ValueError:
            port = 8080

        site = web.TCPSite(
            runner,
            host=host,
            port=port,
        )

        try:
            await site.start()
        except Exception:
            await runner.cleanup()
            LOGGER.exception(
                "Impossible de lancer le site public Hamtaro "
                "sur %s:%s.",
                host,
                port,
            )
            raise

        self.application = application
        self.runner = runner
        self.site = site

        LOGGER.info(
            "Site public Hamtaro lancé sur %s:%s.",
            host,
            port,
        )

    async def _stop_server(self) -> None:
        runner = self.runner
        self.runner = None
        self.site = None
        self.application = None

        if runner is not None:
            await runner.cleanup()

    # ==========================================================
    # MIDDLEWARES
    # ==========================================================

    @web.middleware
    async def _security_headers_middleware(
        self,
        request: web.Request,
        handler,
    ) -> web.StreamResponse:
        response = await handler(request)

        response.headers.setdefault(
            "X-Content-Type-Options",
            "nosniff",
        )
        response.headers.setdefault(
            "X-Frame-Options",
            "SAMEORIGIN",
        )
        response.headers.setdefault(
            "Referrer-Policy",
            "strict-origin-when-cross-origin",
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )

        return response

    @web.middleware
    async def _error_middleware(
        self,
        request: web.Request,
        handler,
    ) -> web.StreamResponse:
        try:
            return await handler(request)

        except web.HTTPException as error:
            if error.status == 404:
                return self.render(
                    "error.html",
                    request=request,
                    status=404,
                    title="Page introuvable",
                    message="Cette page ou ce tournoi n'existe pas.",
                    status_code=404,
                )
            raise

        except ValueError as error:
            return self.render(
                "error.html",
                request=request,
                status=404,
                title="Élément introuvable",
                message=str(error),
                status_code=404,
            )

        except Exception:
            LOGGER.exception(
                "Erreur non gérée sur le site Hamtaro : %s",
                request.path,
            )
            return self.render(
                "error.html",
                request=request,
                status=500,
                title="Erreur du site",
                message=(
                    "Le site n'a pas pu afficher cette page. "
                    "Le bot Discord continue de fonctionner."
                ),
                status_code=500,
            )

    # ==========================================================
    # RENDU
    # ==========================================================

    def render(
        self,
        template_name: str,
        *,
        request: web.Request,
        status_code: int = 200,
        **context: Any,
    ) -> web.Response:
        template = self.jinja.get_template(template_name)

        website_url = os.getenv(
            "WEBSITE_BASE_URL",
            "",
        ).rstrip("/")

        social_links = {
            "youtube": os.getenv(
                "JJET_YOUTUBE_URL",
                "https://www.youtube.com/@jjetgames2869",
            ).strip(),
            "twitch": os.getenv(
                "JJET_TWITCH_URL",
                "https://www.twitch.tv/jjetgames",
            ).strip(),
            "tiktok": os.getenv(
                "JJET_TIKTOK_URL",
                "https://www.tiktok.com/@jjetgames",
            ).strip(),
            "discord": os.getenv(
                "JJET_DISCORD_URL",
                "https://discord.gg/ZGUhg8yTZC",
            ).strip(),
            "x": os.getenv(
                "JJET_X_URL",
                "https://x.com/jjetgames?s=21&t=lZrZN0RjrW7lPWv3CWFipQ",
            ).strip(),
            "instagram": os.getenv(
                "JJET_INSTAGRAM_URL",
                "https://www.instagram.com/jjettgames/",
            ).strip(),
        }

        bot_avatar_url = ""

        if self.bot.user is not None:
            try:
                bot_avatar_url = self.bot.user.display_avatar.replace(
                    size=256,
                    static_format="png",
                ).url
            except Exception:
                bot_avatar_url = self.bot.user.display_avatar.url

        html = template.render(
            request=request,
            website_url=website_url,
            social_links=social_links,
            bot_avatar_url=bot_avatar_url,
            **context,
        )

        return web.Response(
            text=html,
            content_type="text/html",
            charset="utf-8",
            status=status_code,
            headers={
                "Cache-Control": "no-store",
            },
        )

    @staticmethod
    def _status(value: Any) -> str:
        return str(value or "").lower().strip()

    # ==========================================================
    # GUIDE ET CATALOGUE DES COMMANDES
    # ==========================================================

    @staticmethod
    def _guide_role(command_name: str) -> str:
        """
        Classement indicatif pour la documentation du site.

        Les contrôles de permissions définis dans les cogs Discord
        restent toujours prioritaires.
        """

        normalized = command_name.lower().replace(" ", "_")

        admin_keywords = {
            "admin",
            "repair",
            "undo",
            "delete",
            "remove",
            "force",
            "end_tournament",
            "tournament_export",
            "staff_logs",
            "configuration",
            "settings",
            "setup",
            "reset",
            "purge",
        }

        staff_keywords = {
            "approve",
            "reject",
            "pending",
            "create_tournament",
            "start_tournament",
            "open_registration",
            "close_registration",
            "swiss_start",
            "swiss_pair",
            "swiss_report",
            "pair",
            "validate",
            "validation",
            "progression",
            "graphics_preview",
            "swiss_preview",
            "final_bracket",
            "bracket_full",
            "manage",
            "moderation",
        }

        if any(keyword in normalized for keyword in admin_keywords):
            return "admin"

        if any(keyword in normalized for keyword in staff_keywords):
            return "staff"

        return "community"

    @staticmethod
    def _parameter_syntax(parameter: Any) -> str:
        name = str(
            getattr(parameter, "display_name", None)
            or getattr(parameter, "name", "option")
        )

        required = bool(getattr(parameter, "required", False))

        if required:
            return f"<{name}>"

        return f"[{name}]"

    @classmethod
    def _command_entry(
        cls,
        command: Any,
        qualified_name: str,
    ) -> dict[str, Any]:
        parameters = list(
            getattr(command, "parameters", None)
            or []
        )

        syntax_parts = [
            cls._parameter_syntax(parameter)
            for parameter in parameters
        ]

        syntax = "/" + qualified_name
        if syntax_parts:
            syntax += " " + " ".join(syntax_parts)

        options: list[dict[str, Any]] = []
        for parameter in parameters:
            option_name = str(
                getattr(parameter, "display_name", None)
                or getattr(parameter, "name", "option")
            )

            option_description = str(
                getattr(parameter, "description", "")
                or "Option de la commande."
            )

            options.append(
                {
                    "name": option_name,
                    "description": option_description,
                    "required": bool(
                        getattr(parameter, "required", False)
                    ),
                }
            )

        description = str(
            getattr(command, "description", "")
            or "Commande Hamtaro."
        )

        role = cls._guide_role(qualified_name)

        return {
            "name": qualified_name,
            "slash_name": "/" + qualified_name,
            "syntax": syntax,
            "description": description,
            "role": role,
            "options": options,
            "search_text": " ".join(
                [
                    qualified_name,
                    syntax,
                    description,
                    role,
                    *[
                        (
                            f"{option['name']} "
                            f"{option['description']}"
                        )
                        for option in options
                    ],
                ]
            ).lower(),
        }

    @classmethod
    def _flatten_app_command(
        cls,
        command: Any,
        *,
        prefix: str = "",
    ) -> list[dict[str, Any]]:
        command_name = str(getattr(command, "name", "") or "")
        qualified_name = " ".join(
            part
            for part in (prefix, command_name)
            if part
        ).strip()

        children = list(
            getattr(command, "commands", None)
            or []
        )

        if children:
            entries: list[dict[str, Any]] = []

            for child in children:
                entries.extend(
                    cls._flatten_app_command(
                        child,
                        prefix=qualified_name,
                    )
                )

            return entries

        if not qualified_name:
            return []

        return [
            cls._command_entry(
                command,
                qualified_name,
            )
        ]

    def _build_command_catalog(
        self,
    ) -> dict[str, list[dict[str, Any]]]:
        catalog: dict[str, list[dict[str, Any]]] = {
            "community": [],
            "staff": [],
            "admin": [],
        }

        seen: set[str] = set()

        commands = list(self.bot.tree.get_commands())

        guild_id = self._public_guild_id()
        if guild_id is not None:
            try:
                guild_commands = self.bot.tree.get_commands(
                    guild=discord.Object(id=int(guild_id))
                )
                commands.extend(guild_commands)
            except (TypeError, ValueError):
                pass

        for command in commands:
            for entry in self._flatten_app_command(command):
                name = entry["name"]

                if name in seen:
                    continue

                seen.add(name)
                catalog[entry["role"]].append(entry)

        for role_entries in catalog.values():
            role_entries.sort(
                key=lambda entry: entry["name"].lower()
            )

        return catalog

    # ==========================================================
    # PAGES
    # ==========================================================

    async def home_page(
        self,
        request: web.Request,
    ) -> web.Response:
        tournaments = await self.service.list_tournaments(limit=80)

        open_statuses = {
            "registration",
            "registrations",
            "open",
            "waiting",
        }

        current_statuses = {
            "active",
            "started",
            "running",
            "in_progress",
            "playing",
            "swiss",
        }

        open_tournaments = [
            item
            for item in tournaments
            if self._status(item.get("status")) in open_statuses
        ]

        current_tournaments = [
            item
            for item in tournaments
            if self._status(item.get("status")) in current_statuses
        ]

        archived_tournaments = [
            item
            for item in tournaments
            if self._status(item.get("status")) in FINISHED_STATUSES
        ]

        featured_tournaments = (
            open_tournaments
            + current_tournaments
        )[:6]

        if not featured_tournaments:
            featured_tournaments = archived_tournaments[:3]

        recent_results = await self.service.list_recent_results(
            limit=6
        )

        command_catalog = self._build_command_catalog()
        command_count = sum(
            len(commands)
            for commands in command_catalog.values()
        )

        home_stats = {
            "open": len(open_tournaments),
            "active": len(current_tournaments),
            "archived": len(archived_tournaments),
            "commands": command_count,
        }

        return self.render(
            "home.html",
            request=request,
            featured_tournaments=featured_tournaments,
            recent_results=recent_results,
            home_stats=home_stats,
        )

    async def index_page(
        self,
        request: web.Request,
    ) -> web.Response:
        tournaments = await self.service.list_tournaments(limit=80)

        open_statuses = {
            "registration",
            "registrations",
            "open",
            "waiting",
        }

        current_statuses = {
            "active",
            "started",
            "running",
            "in_progress",
            "playing",
            "swiss",
        }

        open_tournaments = [
            item
            for item in tournaments
            if self._status(item.get("status")) in open_statuses
        ]

        current_tournaments = [
            item
            for item in tournaments
            if self._status(item.get("status")) in current_statuses
        ]

        recent_archives = [
            item
            for item in tournaments
            if self._status(item.get("status")) in FINISHED_STATUSES
        ][:8]

        return self.render(
            "index.html",
            request=request,
            open_tournaments=open_tournaments,
            current_tournaments=current_tournaments,
            recent_archives=recent_archives,
        )

    async def tournament_page(
        self,
        request: web.Request,
    ) -> web.Response:
        tournament_id = int(request.match_info["tournament_id"])
        tournament = await self.service.get_tournament_page_data(
            tournament_id
        )

        bracket_version: str | None = None
        bracket_error: str | None = None

        try:
            bracket_version = await self.service.get_version(
                tournament_id
            )
        except ValueError as error:
            bracket_error = str(error)

        return self.render(
            "tournament.html",
            request=request,
            tournament=tournament,
            bracket_version=bracket_version,
            bracket_error=bracket_error,
        )

    async def guide_page(
        self,
        request: web.Request,
    ) -> web.Response:
        command_catalog = self._build_command_catalog()

        command_count = sum(
            len(commands)
            for commands in command_catalog.values()
        )

        role_counts = {
            role: len(commands)
            for role, commands in command_catalog.items()
        }

        return self.render(
            "guide.html",
            request=request,
            command_catalog=command_catalog,
            command_count=command_count,
            role_counts=role_counts,
        )
    async def results_page(
        self,
        request: web.Request,
    ) -> web.Response:
        results = await self.service.list_recent_results(limit=150)

        return self.render(
            "results.html",
            request=request,
            results=results,
        )

    async def decks_page(
        self,
        request: web.Request,
    ) -> web.Response:
        decks = await self.service.list_deck_statistics(limit=150)

        return self.render(
            "decks.html",
            request=request,
            decks=decks,
        )

    async def archives_page(
        self,
        request: web.Request,
    ) -> web.Response:
        tournaments = await self.service.list_archives(limit=150)

        return self.render(
            "archives.html",
            request=request,
            tournaments=tournaments,
        )

    def _public_guild_id(self) -> str | None:
        configured = (
            os.getenv("PUBLIC_GUILD_ID")
            or os.getenv("GUILD_ID")
            or ""
        ).strip()

        if configured.isdigit():
            return configured

        if self.bot.guilds:
            return str(self.bot.guilds[0].id)

        return None

    async def _public_member(
        self,
        guild_id: str,
        discord_id: str,
    ) -> discord.Member | None:
        try:
            guild = self.bot.get_guild(int(guild_id))
            member_id = int(discord_id)
        except (TypeError, ValueError):
            return None

        if guild is None:
            return None

        member = guild.get_member(member_id)
        if member is not None:
            return member

        try:
            return await guild.fetch_member(member_id)
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            return None

    @staticmethod
    def _profile_matches(
        matches: list[dict[str, Any]],
        player_id: str,
    ) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []

        for raw_match in matches:
            match = dict(raw_match)
            player1_id = str(match.get("player1_id") or "")
            player2_id = str(match.get("player2_id") or "")

            if player1_id == player_id:
                opponent_name = match.get("player2_name") or "BYE"
            elif player2_id == player_id:
                opponent_name = match.get("player1_name") or "BYE"
            else:
                opponent_name = "Adversaire inconnu"

            is_bye = int(match.get("is_bye") or 0) == 1
            is_double_loss = int(match.get("is_double_loss") or 0) == 1
            winner_id = str(match.get("winner_id") or "")

            if is_bye:
                result_code = "BYE"
                result_label = "BYE"
            elif is_double_loss:
                result_code = "DL"
                result_label = "Double Loss"
            elif winner_id == player_id:
                result_code = "W"
                result_label = "Victoire"
            elif winner_id:
                result_code = "L"
                result_label = "Défaite"
            else:
                result_code = "N"
                result_label = "Non déterminé"

            score_text = str(match.get("score_text") or "").strip()
            if not score_text:
                score_text = (
                    f"{int(match.get('player1_score') or 0)}"
                    f"-{int(match.get('player2_score') or 0)}"
                )

            if match.get("match_kind") == "swiss":
                round_label = (
                    f"Ronde {match.get('round_number') or '?'}"
                    f" · Table {match.get('table_number') or '?'}"
                )
            else:
                round_label = (
                    f"Round {match.get('round_number') or '?'}"
                    f" · Match {match.get('table_number') or '?'}"
                )

            match.update(
                {
                    "opponent_name": opponent_name,
                    "result_code": result_code,
                    "result_label": result_label,
                    "score_display": score_text,
                    "round_label": round_label,
                }
            )
            prepared.append(match)

        return prepared

    @staticmethod
    def _participant_date(value: Any) -> str:
        if value in (None, ""):
            return "Aucune date"

        raw = str(value).strip()
        date_part = raw[:10]

        pieces = date_part.split("-")
        if len(pieces) == 3 and all(pieces):
            return f"{pieces[2]}/{pieces[1]}/{pieces[0]}"

        return date_part or "Aucune date"

    async def _list_public_participants(
        self,
    ) -> list[dict[str, Any]]:
        rows = await self.service._safe_fetchall(
            """
            SELECT
                r.discord_id,

                COALESCE(
                    (
                        SELECT NULLIF(TRIM(r2.username), '')
                        FROM registrations r2
                        WHERE r2.discord_id = r.discord_id
                          AND r2.username IS NOT NULL
                          AND TRIM(r2.username) != ''
                        ORDER BY
                            COALESCE(r2.registered_at, '') DESC,
                            r2.tournament_id DESC
                        LIMIT 1
                    ),
                    'Joueur Hamtaro'
                ) AS username,

                COUNT(DISTINCT r.tournament_id)
                    AS tournaments_played,

                COUNT(*) AS registrations_count,

                SUM(
                    CASE
                        WHEN r.final_rank = 1 THEN 1
                        ELSE 0
                    END
                ) AS tournament_wins,

                SUM(
                    CASE
                        WHEN r.final_rank IS NOT NULL
                         AND r.final_rank <= 4 THEN 1
                        ELSE 0
                    END
                ) AS top_four,

                MAX(r.registered_at) AS last_participation,

                (
                    SELECT NULLIF(TRIM(r2.deck), '')
                    FROM registrations r2
                    WHERE r2.discord_id = r.discord_id
                      AND r2.deck IS NOT NULL
                      AND TRIM(r2.deck) != ''
                    ORDER BY
                        COALESCE(r2.registered_at, '') DESC,
                        r2.tournament_id DESC
                    LIMIT 1
                ) AS latest_deck,

                (
                    SELECT t2.name
                    FROM registrations r2
                    JOIN tournaments t2
                      ON t2.id = r2.tournament_id
                    WHERE r2.discord_id = r.discord_id
                      AND LOWER(
                          COALESCE(t2.status, '')
                      ) != 'cancelled'
                    ORDER BY
                        COALESCE(r2.registered_at, '') DESC,
                        r2.tournament_id DESC
                    LIMIT 1
                ) AS latest_tournament

            FROM registrations r
            JOIN tournaments t
              ON t.id = r.tournament_id

            WHERE LOWER(
                COALESCE(t.status, '')
            ) != 'cancelled'

            GROUP BY r.discord_id

            ORDER BY
                tournaments_played DESC,
                last_participation DESC,
                username ASC

            LIMIT 500
            """
        )

        guild = None
        guild_id = self._public_guild_id()

        if guild_id is not None:
            try:
                guild = self.bot.get_guild(int(guild_id))
            except (TypeError, ValueError):
                guild = None

        participants: list[dict[str, Any]] = []

        for row in rows:
            participant = dict(row)

            discord_id = str(
                participant.get("discord_id")
                or ""
            )

            username = str(
                participant.get("username")
                or "Joueur Hamtaro"
            )

            participant["discord_id"] = discord_id
            participant["username"] = username
            participant["display_name"] = username
            participant["avatar_url"] = ""

            for numeric_field in (
                "tournaments_played",
                "registrations_count",
                "tournament_wins",
                "top_four",
            ):
                try:
                    participant[numeric_field] = int(
                        participant.get(numeric_field)
                        or 0
                    )
                except (TypeError, ValueError):
                    participant[numeric_field] = 0

            participant["latest_deck"] = (
                str(participant.get("latest_deck") or "")
                or "Non renseigné"
            )

            participant["latest_tournament"] = (
                str(
                    participant.get("latest_tournament")
                    or ""
                )
                or "Aucun tournoi"
            )

            participant["last_participation_display"] = (
                self._participant_date(
                    participant.get("last_participation")
                )
            )

            if guild is not None and discord_id.isdigit():
                member = guild.get_member(int(discord_id))

                if member is not None:
                    participant["display_name"] = (
                        member.display_name
                    )
                    participant["username"] = member.name

                    try:
                        participant["avatar_url"] = (
                            member.display_avatar.replace(
                                size=256,
                                static_format="png",
                            ).url
                        )
                    except Exception:
                        participant["avatar_url"] = (
                            member.display_avatar.url
                        )

            participant["search_text"] = " ".join(
                [
                    participant["display_name"],
                    participant["username"],
                    participant["latest_deck"],
                    participant["latest_tournament"],
                    discord_id,
                ]
            ).lower()

            participants.append(participant)

        return participants

    async def participants_page(
        self,
        request: web.Request,
    ) -> web.Response:
        participants = await self._list_public_participants()

        raw_threshold = os.getenv(
            "REGULAR_PARTICIPANT_MIN_TOURNAMENTS",
            "3",
        )

        try:
            regular_threshold = max(
                2,
                min(50, int(raw_threshold)),
            )
        except (TypeError, ValueError):
            regular_threshold = 3

        regular_participants = [
            participant
            for participant in participants
            if (
                participant["tournaments_played"]
                >= regular_threshold
            )
        ]

        total_registrations = sum(
            participant["registrations_count"]
            for participant in participants
        )

        total_titles = sum(
            participant["tournament_wins"]
            for participant in participants
        )

        participant_stats = {
            "participants": len(participants),
            "regulars": len(regular_participants),
            "registrations": total_registrations,
            "titles": total_titles,
        }

        return self.render(
            "participants.html",
            request=request,
            participants=participants,
            regular_participants=regular_participants,
            regular_threshold=regular_threshold,
            participant_stats=participant_stats,
        )

    async def profiles_page(
        self,
        request: web.Request,
    ) -> web.Response:
        discord_id = str(
            request.query.get("discord_id") or ""
        ).strip()

        if discord_id:
            if not discord_id.isdigit():
                return self.render(
                    "profiles.html",
                    request=request,
                    error=(
                        "L'identifiant Discord doit contenir "
                        "uniquement des chiffres."
                    ),
                )

            raise web.HTTPFound(f"/players/{discord_id}")

        return self.render(
            "profiles.html",
            request=request,
            error=None,
        )

    async def player_page(
        self,
        request: web.Request,
    ) -> web.Response:
        discord_id = request.match_info["discord_id"]
        guild_id = self._public_guild_id()

        if guild_id is None:
            raise ValueError(
                "Aucun serveur Discord public n'est configuré. "
                "Ajoute PUBLIC_GUILD_ID dans Railway."
            )

        member = await self._public_member(
            guild_id,
            discord_id,
        )

        fallback_name = (
            member.display_name
            if member is not None
            else f"Joueur {discord_id}"
        )

        summary, matches, decks = (
            await self.analytics.get_player_profile(
                guild_id=guild_id,
                player_id=discord_id,
                fallback_name=fallback_name,
            )
        )

        avatar_url = summary.avatar_url
        if member is not None:
            avatar_url = member.display_avatar.replace(
                size=256,
                static_format="png",
            ).url

        display_name = summary.display_name or fallback_name
        username = summary.username or fallback_name

        prepared_matches = self._profile_matches(
            matches,
            discord_id,
        )

        return self.render(
            "player.html",
            request=request,
            player_id=discord_id,
            display_name=display_name,
            username=username,
            avatar_url=avatar_url,
            summary=summary,
            matches=prepared_matches,
            decks=decks,
            profile_scope="Tous les tournois du serveur",
        )

    # ==========================================================
    # API
    # ==========================================================

    async def bracket_image(
        self,
        request: web.Request,
    ) -> web.StreamResponse:
        tournament_id = int(request.match_info["tournament_id"])

        image_path, signature = await self.service.get_or_generate(
            tournament_id
        )

        response = web.FileResponse(
            path=image_path,
            headers={
                "Cache-Control": "public, max-age=30, must-revalidate",
                "ETag": f'"{signature}"',
                "Content-Disposition": (
                    f'inline; filename="hamtaro_bracket_{tournament_id}.png"'
                ),
            },
        )
        response.content_type = "image/png"
        return response

    async def bracket_version(
        self,
        request: web.Request,
    ) -> web.Response:
        tournament_id = int(request.match_info["tournament_id"])
        signature = await self.service.get_version(tournament_id)

        return web.json_response(
            {
                "tournament_id": tournament_id,
                "version": signature,
            },
            headers={
                "Cache-Control": "no-store",
            },
        )

    async def health_page(
        self,
        request: web.Request,
    ) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "service": "hamtaro-public-website",
                "bot_ready": self.bot.is_ready(),
            },
            headers={
                "Cache-Control": "no-store",
            },
        )

    async def favicon(
        self,
        request: web.Request,
    ) -> web.Response:
        return web.Response(status=204)

    # ==========================================================
    # COMMANDE DISCORD
    # ==========================================================

    @app_commands.command(
        name="hamtaro_site",
        description="Afficher le lien du site public Hamtaro",
    )
    async def hamtaro_site(
        self,
        interaction: discord.Interaction,
    ) -> None:
        started = time.perf_counter()
        interaction_age = max(
            0.0,
            (
                discord.utils.utcnow()
                - interaction.created_at
            ).total_seconds(),
        )

        LOGGER.warning(
            (
                "[HAMTARO_SITE] START version=%s id=%s "
                "age=%.3fs gateway=%.3fs"
            ),
            HAMTARO_SITE_BUILD,
            interaction.id,
            interaction_age,
            float(getattr(self.bot, "latency", 0.0) or 0.0),
        )

        website_url = os.getenv(
            "WEBSITE_BASE_URL",
            "https://worker-production-5a11.up.railway.app",
        ).strip().rstrip("/")

        if not website_url.startswith(("http://", "https://")):
            LOGGER.error(
                "[HAMTARO_SITE] WEBSITE_BASE_URL invalide : %r",
                website_url,
            )
            await interaction.response.send_message(
                (
                    "❌ L'adresse du site Hamtaro est invalide. "
                    "Vérifie `WEBSITE_BASE_URL` dans Railway."
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🌐 Site public Hamtaro",
            description=(
                "Consulte les tournois, les résultats, "
                "les archives et les brackets officiels."
            ),
            url=website_url,
            colour=discord.Colour.gold(),
        )
        embed.add_field(
            name="Lien du site",
            value=f"[Ouvrir le site Hamtaro]({website_url})",
            inline=False,
        )

        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="Ouvrir le site",
                url=website_url,
                emoji="🌐",
                style=discord.ButtonStyle.link,
            )
        )

        try:
            # Un seul appel à Discord : aucune base de données,
            # aucune requête HTTP et aucun rendu du site avant la réponse.
            await interaction.response.send_message(
                embed=embed,
                view=view,
                ephemeral=False,
            )
        except discord.NotFound as error:
            LOGGER.warning(
                (
                    "[HAMTARO_SITE] NOT_FOUND id=%s code=%s "
                    "age=%.3fs total=%.3fs"
                ),
                interaction.id,
                error.code,
                interaction_age,
                time.perf_counter() - started,
            )
            if error.code != 10062:
                raise
            return
        except discord.InteractionResponded:
            await interaction.followup.send(
                content=f"🌐 Site public Hamtaro : {website_url}",
                ephemeral=False,
            )

        LOGGER.warning(
            "[HAMTARO_SITE] END_OK id=%s total=%.3fs",
            interaction.id,
            time.perf_counter() - started,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PublicWebsiteCog(bot))
