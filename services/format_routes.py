from __future__ import annotations

import os
from typing import Any

from aiohttp import web

from services.halloween_format_service import HalloweenFormatService
from services.boss_service import BossService


def register_format_routes(
    application: web.Application,
    website_cog: Any,
) -> None:
    boss_service = BossService()
    halloween_service = HalloweenFormatService()

    async def formats_page(request: web.Request) -> web.Response:
        configured_guild = str(
            request.query.get("guild")
            or os.environ.get("PUBLIC_GUILD_ID")
            or os.environ.get("GUILD_ID")
            or ""
        ).strip()
        if not configured_guild:
            guilds = list(getattr(website_cog.bot, "guilds", []))
            configured_guild = str(guilds[0].id) if guilds else ""
        boss_card = await boss_service.public_format_card(
            configured_guild if configured_guild.isdigit() else None
        )
        return website_cog.render(
            "formats.html",
            request=request,
            formats=[
                halloween_service.public_data(),
                boss_card,
            ],
        )

    async def halloween_page(request: web.Request) -> web.Response:
        return website_cog.render(
            "format_halloween.html",
            request=request,
            format_data=halloween_service.public_data(),
        )

    async def halloween_api(request: web.Request) -> web.Response:
        return web.json_response(
            halloween_service.public_data(),
            headers={"Cache-Control": "no-store"},
        )

    async def halloween_whitelist_txt(request: web.Request) -> web.Response:
        return web.Response(
            text=halloween_service.whitelist_text(),
            content_type="text/plain",
            charset="utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="whitelist_format_halloween.txt"',
            },
        )

    async def halloween_banlist_txt(request: web.Request) -> web.Response:
        return web.Response(
            text=halloween_service.banlist_text(),
            content_type="text/plain",
            charset="utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="banlist_format_halloween.txt"',
            },
        )

    application.router.add_get("/formats", formats_page)
    application.router.add_get("/formats/halloween", halloween_page)
    application.router.add_get("/api/formats/halloween", halloween_api)
    application.router.add_get(
        "/api/formats/halloween/whitelist.txt",
        halloween_whitelist_txt,
    )
    application.router.add_get(
        "/api/formats/halloween/banlist.txt",
        halloween_banlist_txt,
    )
