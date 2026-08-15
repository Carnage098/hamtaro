from __future__ import annotations

from typing import Any

from aiohttp import web

from services.trophy_service import TrophyService


class TrophyRoutes:
    def __init__(self, website_cog: Any) -> None:
        self.website_cog = website_cog
        self.service = TrophyService(website_cog.bot)

    async def gallery_page(self, request: web.Request) -> web.Response:
        trophies = self.service.all_trophies()
        return self.website_cog.render(
            "trophies.html",
            request=request,
            trophies=trophies,
            total=len(trophies),
            awarded=sum(1 for trophy in trophies if trophy.get("is_awarded")),
        )

    async def detail_page(self, request: web.Request) -> web.Response:
        trophy = self.service.get_trophy(request.match_info["trophy_id"])
        if trophy is None:
            raise web.HTTPNotFound(text="Trophée introuvable")
        return self.website_cog.render(
            "trophy_detail.html",
            request=request,
            trophy=trophy,
        )

    async def list_api(self, request: web.Request) -> web.Response:
        trophies = self.service.all_trophies()
        return web.json_response(
            {"count": len(trophies), "trophies": trophies},
            headers={"Cache-Control": "no-store"},
        )

    async def detail_api(self, request: web.Request) -> web.Response:
        trophy = self.service.get_trophy(request.match_info["trophy_id"])
        if trophy is None:
            raise web.HTTPNotFound(text="Trophée introuvable")
        return web.json_response(trophy, headers={"Cache-Control": "no-store"})

    async def player_trophies_api(self, request: web.Request) -> web.Response:
        discord_id = str(request.match_info["discord_id"])
        trophies = self.service.trophies_for_player(discord_id)
        return web.json_response(
            {"discord_id": discord_id, "count": len(trophies), "trophies": trophies},
            headers={"Cache-Control": "no-store"},
        )


def register_trophy_routes(
    application: web.Application,
    website_cog: Any,
) -> TrophyRoutes:
    routes = TrophyRoutes(website_cog)
    application.router.add_get("/trophies", routes.gallery_page)
    application.router.add_get(r"/trophies/{trophy_id:[A-Za-z0-9_-]+}", routes.detail_page)
    application.router.add_get("/api/trophies", routes.list_api)
    application.router.add_get(r"/api/trophies/{trophy_id:[A-Za-z0-9_-]+}", routes.detail_api)
    application.router.add_get(
        r"/api/players/{discord_id:\d+}/trophies",
        routes.player_trophies_api,
    )
    return routes
