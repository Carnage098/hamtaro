from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from services.araignee_format_service import AraigneeFormatService
from services.halloween_format_service import HalloweenFormatService


MAX_REQUEST_BYTES = 32_000

# HAMTARO FORMAT TROPHY INTEGRATION V1
# Métadonnées d'affichage uniquement : le trophée reste géré par le système /trophies.
FORMAT_TROPHIES: dict[str, dict[str, str]] = {
    "araignee": {
        "id": "ht-003",
        "code": "HT-003",
        "name": "Champion Spiderman",
        "label": "Trophée du tournoi Spiderman",
        "status": "À venir",
        "description": "Attribué au vainqueur du tournoi Spiderman.",
        "url": "/trophies/ht-003",
        "emoji": "🏆",
    },
}


def _format_page_data(service: AraigneeFormatService) -> dict[str, Any]:
    """Ajoute les métadonnées de présentation liées au format sans modifier l'API métier."""
    data = service.public_data()
    format_id = str(data.get("id") or "").strip().lower()
    trophy = FORMAT_TROPHIES.get(format_id)
    if trophy:
        data["trophy"] = dict(trophy)
    return data


def register_format_routes(
    application: web.Application,
    website_cog: Any,
) -> None:
    service = AraigneeFormatService()
    halloween_service = HalloweenFormatService()

    async def formats_page(request: web.Request) -> web.Response:
        return website_cog.render(
            "formats.html",
            request=request,
            formats=[_format_page_data(service), halloween_service.public_data()],
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
            format_data=_format_page_data(service),
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
    application.router.add_get("/api/formats/halloween/whitelist.txt", halloween_whitelist_txt)
    application.router.add_get("/api/formats/halloween/banlist.txt", halloween_banlist_txt)
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
