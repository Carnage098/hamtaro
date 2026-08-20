from __future__ import annotations

import json
import os
from typing import Any

from aiohttp import web

from services.araignee_format_service import AraigneeFormatService
from services.halloween_format_service import HalloweenFormatService
from services.boss_service import BossService


MAX_REQUEST_BYTES = 32_000


def register_format_routes(
    application: web.Application,
    website_cog: Any,
) -> None:
    service = AraigneeFormatService()
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
                service.public_data(),
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

    async def araignee_page(request: web.Request) -> web.Response:
        return website_cog.render(
            "format_araignee.html",
            request=request,
            format_data=service.public_data(),
        )

    async def araignee_api(request: web.Request) -> web.Response:
        return web.json_response(
            service.public_data(),
            headers={
                "Cache-Control": "no-store",
                "X-Araignee-Pool-Revision": service.pool_revision(),
            },
        )

    async def araignee_pool_txt(request: web.Request) -> web.Response:
        body = "\n".join(
            f"{index}. {card}"
            for index, card in enumerate(service.pool(), start=1)
        ) + "\n"
        return web.Response(
            text=body,
            content_type="text/plain",
            charset="utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": (
                    'attachment; filename="pool_format_araignee.txt"'
                ),
            },
        )

    async def araignee_validate(request: web.Request) -> web.Response:
        if request.content_length is not None and request.content_length > MAX_REQUEST_BYTES:
            return web.json_response(
                {"ok": False, "error": "Requête trop volumineuse."},
                status=413,
            )

        try:
            payload = await request.json()
        except (json.JSONDecodeError, TypeError):
            return web.json_response(
                {"ok": False, "error": "Corps JSON invalide."},
                status=400,
            )

        decklist = str((payload or {}).get("decklist") or "")
        if not decklist.strip():
            return web.json_response(
                {"ok": False, "error": "La decklist est vide."},
                status=400,
            )

        try:
            result = service.validate_text(decklist)
        except ValueError as error:
            return web.json_response(
                {"ok": False, "error": str(error)},
                status=400,
            )

        return web.json_response(
            {
                "ok": True,
                "format": "Araignée",
                "pool_revision": service.pool_revision(),
                "result": result.to_dict(),
            },
            headers={"Cache-Control": "no-store"},
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
    application.router.add_get("/formats/araignee", araignee_page)
    application.router.add_get("/api/formats/araignee", araignee_api)
    application.router.add_get(
        "/api/formats/araignee/pool.txt",
        araignee_pool_txt,
    )
    application.router.add_post(
        "/api/formats/araignee/validate",
        araignee_validate,
    )
