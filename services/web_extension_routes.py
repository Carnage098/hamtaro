from __future__ import annotations

import os
from typing import Any

from aiohttp import web

from services.competitive_service import CompetitiveService
from services.expansion_database import expansion_connection, normalize_format
from services.player_experience_service import PlayerExperienceService


class ExpansionWebRoutes:
    def __init__(self, website_cog: Any) -> None:
        self.website_cog = website_cog
        self.competitive = CompetitiveService()
        self.players = PlayerExperienceService()

    def guild_id(self, request: web.Request) -> str:
        requested = request.query.get("guild", "").strip()
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
        raise ValueError("Aucun serveur public n'est configuré pour cette page.")

    async def competitive_page(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        selected_format = normalize_format(request.query.get("format", "Général"))
        rankings = await self.competitive.ranking(guild_id, selected_format, limit=100)
        async with expansion_connection() as db:
            format_rows = await (
                await db.execute(
                    """
                    SELECT DISTINCT format FROM competitive_ratings
                    WHERE guild_id=? ORDER BY format
                    """,
                    (guild_id,),
                )
            ).fetchall()
            season = await (
                await db.execute(
                    """
                    SELECT * FROM competitive_seasons
                    WHERE guild_id=?
                    ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id DESC
                    LIMIT 1
                    """,
                    (guild_id,),
                )
            ).fetchone()
        formats = [str(row["format"]) for row in format_rows]
        if "Général" not in formats:
            formats.insert(0, "Général")
        if selected_format not in formats:
            formats.append(selected_format)
        return self.website_cog.render(
            "competitive.html",
            request=request,
            guild_id=guild_id,
            selected_format=selected_format,
            formats=formats,
            rankings=rankings,
            season=dict(season) if season else None,
        )

    async def duelist_page(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        discord_id = request.match_info["discord_id"]
        data = await self.players.profile(guild_id, discord_id)
        display_name = (
            data["player"].get("display_name")
            or data["player"].get("username")
            or discord_id
        )
        return self.website_cog.render(
            "duelist_plus.html",
            request=request,
            guild_id=guild_id,
            discord_id=discord_id,
            display_name=display_name,
            data=data,
        )

    async def competitive_api(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        format_name = normalize_format(request.query.get("format", "Général"))
        rankings = await self.competitive.ranking(guild_id, format_name, limit=100)
        return web.json_response(
            {
                "guild_id": guild_id,
                "format": format_name,
                "rankings": rankings,
            },
            headers={"Cache-Control": "no-store"},
        )


def register_expansion_routes(
    application: web.Application,
    website_cog: Any,
) -> None:
    routes = ExpansionWebRoutes(website_cog)
    application.router.add_get("/competitive", routes.competitive_page)
    application.router.add_get(
        r"/duelists/{discord_id:\d+}",
        routes.duelist_page,
    )
    application.router.add_get("/api/competitive", routes.competitive_api)
