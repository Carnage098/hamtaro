from __future__ import annotations

import os
from typing import Any

from aiohttp import web

from services.site_experience_service import SiteExperienceService


class SiteExperienceRoutes:
    def __init__(self, website_cog: Any) -> None:
        self.website_cog = website_cog
        self.service = SiteExperienceService(website_cog.bot)

    def guild_id(self, request: web.Request) -> str:
        requested = str(request.query.get("guild") or "").strip()
        if requested.isdigit():
            return requested

        configured = (
            os.getenv("PUBLIC_GUILD_ID")
            or os.getenv("GUILD_ID")
            or ""
        ).strip()
        if configured.isdigit():
            return configured

        guilds = list(getattr(self.website_cog.bot, "guilds", []))
        if guilds:
            return str(guilds[0].id)

        raise ValueError(
            "Aucun serveur public n'est configuré. "
            "Ajoute PUBLIC_GUILD_ID dans les variables Railway."
        )

    async def matches_page(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        data = await self.service.live_matches(guild_id)
        return self.website_cog.render(
            "matches.html",
            request=request,
            guild_id=guild_id,
            data=data,
        )

    async def matches_api(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        data = await self.service.live_matches(guild_id)
        return web.json_response(
            data,
            headers={"Cache-Control": "no-store"},
        )

    async def competitive_page(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        selected_format = str(request.query.get("format") or "Général")
        data = await self.service.competitive_dashboard(
            guild_id,
            selected_format,
        )
        return self.website_cog.render(
            "competitive.html",
            request=request,
            guild_id=guild_id,
            data=data,
        )

    async def competitive_api(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        selected_format = str(request.query.get("format") or "Général")
        data = await self.service.competitive_dashboard(
            guild_id,
            selected_format,
        )
        return web.json_response(
            data,
            headers={"Cache-Control": "no-store"},
        )

    async def seasons_page(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        data = await self.service.seasons_dashboard(guild_id)
        return self.website_cog.render(
            "seasons.html",
            request=request,
            guild_id=guild_id,
            data=data,
        )

    async def player_page(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        discord_id = str(request.match_info["discord_id"])
        data = await self.service.enriched_profile(
            guild_id,
            discord_id,
        )
        player = data.get("player") or {}
        display_name = (
            player.get("display_name")
            or player.get("username")
            or f"Joueur {discord_id}"
        )
        return self.website_cog.render(
            "player.html",
            request=request,
            guild_id=guild_id,
            discord_id=discord_id,
            display_name=display_name,
            data=data,
        )

    @staticmethod
    def _deck_filters(request: web.Request) -> tuple[str | None, int | None, int]:
        format_name = str(
            request.query.get("format") or ""
        ).strip() or None

        tournament_id: int | None = None
        raw_tournament_id = str(
            request.query.get("tournament_id") or ""
        ).strip()
        if raw_tournament_id.isdigit():
            tournament_id = int(raw_tournament_id)

        raw_minimum = str(
            request.query.get("minimum_matches") or "0"
        ).strip()
        minimum_matches = (
            int(raw_minimum)
            if raw_minimum.isdigit()
            else 0
        )
        return format_name, tournament_id, minimum_matches

    async def decks_page(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        format_name, tournament_id, minimum_matches = self._deck_filters(
            request
        )
        data = await self.service.deck_metagame(
            guild_id,
            format_name=format_name,
            tournament_id=tournament_id,
            minimum_matches=minimum_matches,
        )
        return self.website_cog.render(
            "decks.html",
            request=request,
            guild_id=guild_id,
            data=data,
        )

    async def decks_api(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        format_name, tournament_id, minimum_matches = self._deck_filters(
            request
        )
        data = await self.service.deck_metagame(
            guild_id,
            format_name=format_name,
            tournament_id=tournament_id,
            minimum_matches=minimum_matches,
        )
        return web.json_response(
            data,
            headers={"Cache-Control": "no-store"},
        )

    async def search_page(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        query = str(request.query.get("q") or "").strip()
        catalog = self.website_cog._build_command_catalog()
        results = await self.service.global_search(
            guild_id,
            query,
            command_catalog=catalog,
        )
        return self.website_cog.render(
            "search.html",
            request=request,
            guild_id=guild_id,
            query=query,
            results=results,
            total=sum(len(items) for items in results.values()),
        )

    async def search_api(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        query = str(request.query.get("q") or "").strip()
        catalog = self.website_cog._build_command_catalog()
        results = await self.service.global_search(
            guild_id,
            query,
            command_catalog=catalog,
        )
        return web.json_response(
            {
                "query": query,
                "results": results,
                "total": sum(len(items) for items in results.values()),
            },
            headers={"Cache-Control": "no-store"},
        )


def register_site_experience_routes(
    application: web.Application,
    website_cog: Any,
) -> SiteExperienceRoutes:
    routes = SiteExperienceRoutes(website_cog)

    application.router.add_get("/matches", routes.matches_page)
    application.router.add_get("/api/matches/live", routes.matches_api)

    application.router.add_get("/competitive", routes.competitive_page)
    application.router.add_get(
        "/competitive/seasons",
        routes.seasons_page,
    )
    application.router.add_get(
        "/api/competitive",
        routes.competitive_api,
    )

    application.router.add_get(
        r"/players/{discord_id:\d+}",
        routes.player_page,
    )
    application.router.add_get(
        r"/duelists/{discord_id:\d+}",
        routes.player_page,
    )

    application.router.add_get("/decks", routes.decks_page)
    application.router.add_get("/api/decks", routes.decks_api)
    application.router.add_get("/search", routes.search_page)
    application.router.add_get("/api/site/search", routes.search_api)

    return routes
