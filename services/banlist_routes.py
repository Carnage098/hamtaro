from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any, AsyncIterator

from aiohttp import web

from services.banlist_service import BanlistDataError, BanlistService


LOGGER = logging.getLogger(__name__)
_SERVICE_KEY: web.AppKey[BanlistService] = web.AppKey(
    "hamtaro_banlist_service",
    BanlistService,
)


def register_banlist_routes(
    application: web.Application,
    website_cog: Any,
) -> None:
    """Enregistre la page, l'API et la synchronisation des banlists."""

    project_root = Path(website_cog.web_directory).parent
    service = BanlistService(project_root)
    application[_SERVICE_KEY] = service

    async def synchronization_context(
        app: web.Application,
    ) -> AsyncIterator[None]:
        del app
        task = asyncio.create_task(
            service.periodic_sync(),
            name="hamtaro-banlists-periodic-sync",
        )
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    application.cleanup_ctx.append(synchronization_context)

    async def banlists_page(request: web.Request) -> web.Response:
        try:
            payload = service.load()
        except BanlistDataError as error:
            LOGGER.exception("Impossible de charger les banlists Hamtaro.")
            return website_cog.render(
                "error.html",
                request=request,
                status=500,
                title="Banlists indisponibles",
                message=str(error),
                status_code=500,
            )

        return website_cog.render(
            "banlists.html",
            request=request,
            formats=payload["formats"],
            categories=payload["categories"],
            format_count=payload["format_count"],
            category_count=payload["category_count"],
            data_updated_at=payload["updated_at"],
            disclaimer=payload["disclaimer"],
            revision=payload["revision"],
            sync=payload["sync"],
        )

    async def banlists_api(request: web.Request) -> web.Response:
        try:
            payload = service.load()
        except BanlistDataError as error:
            return web.json_response(
                {"ok": False, "error": str(error)},
                status=500,
                headers={"Cache-Control": "no-store"},
            )

        return web.json_response(
            {"ok": True, **payload},
            headers={"Cache-Control": "no-store"},
        )

    async def banlists_version_api(
        request: web.Request,
    ) -> web.Response:
        del request
        return web.json_response(
            service.version_payload(),
            headers={"Cache-Control": "no-store"},
        )

    application.router.add_get("/banlists", banlists_page)
    application.router.add_get("/api/banlists.json", banlists_api)
    application.router.add_get(
        "/api/banlists/version.json",
        banlists_version_api,
    )
