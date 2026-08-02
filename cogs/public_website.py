from __future__ import annotations

import asyncio
import logging
import os
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

        application.router.add_get("/", self.index_page)
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

        html = template.render(
            request=request,
            website_url=website_url,
            social_links=social_links,
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
    # PAGES
    # ==========================================================

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
        # Discord exige une première réponse très rapide.
        # Le defer empêche l'erreur 10062 si l'interaction prend du retard.
        await interaction.response.defer(
            thinking=True,
            ephemeral=True,
        )

        website_url = os.getenv(
            "WEBSITE_BASE_URL",
            "",
        ).strip().rstrip("/")

        if not website_url:
            await interaction.followup.send(
                (
                    "❌ Le site est activé, mais `WEBSITE_BASE_URL` "
                    "n'est pas encore configurée dans Railway."
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🌐 Site public Hamtaro",
            description=(
                "Consulte les tournois, les résultats, les archives "
                "et les brackets officiels."
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
            )
        )

        await interaction.followup.send(
            embed=embed,
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PublicWebsiteCog(bot))
