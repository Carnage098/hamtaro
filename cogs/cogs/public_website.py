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

        html = template.render(
            request=request,
            website_url=website_url,
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

    async def player_page(
        self,
        request: web.Request,
    ) -> web.Response:
        discord_id = request.match_info["discord_id"]
        player = await self.service.get_player_profile(discord_id)

        if player is None:
            raise web.HTTPNotFound()

        return self.render(
            "player.html",
            request=request,
            player=player,
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
