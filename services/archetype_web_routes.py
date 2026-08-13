from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from services.archetype_meta_service import ArchetypeMetaService

if TYPE_CHECKING:
    from cogs.public_website import PublicWebsiteCog

LOGGER = logging.getLogger(__name__)
_REGISTER_FLAG = "hamtaro_archetype_routes_registered"


def register_archetype_routes(application: web.Application, site: "PublicWebsiteCog") -> None:
    """Enregistre les pages Méta/Archétypes sur l'application aiohttp Hamtaro.

    V4 : le service est créé ici si le site ne l'a pas déjà. Cela évite d'avoir
    à modifier le __init__ de PublicWebsiteCog et rend l'intégration beaucoup
    plus résistante aux évolutions du fichier cogs/public_website.py.
    """
    if application.get(_REGISTER_FLAG):
        LOGGER.info("Routes Méta/Archétypes déjà enregistrées ; aucun doublon ajouté.")
        return

    service = getattr(site, "archetype_meta", None)
    if service is None:
        service = ArchetypeMetaService()
        setattr(site, "archetype_meta", service)

    async def archetypes_page(request: web.Request) -> web.Response:
        guild_id = site._public_guild_id()
        if guild_id is None:
            raise ValueError(
                "Aucun serveur Discord public n'est configuré. Ajoute PUBLIC_GUILD_ID dans Railway."
            )

        format_filter = str(request.query.get("format") or "").strip() or None
        search = str(request.query.get("q") or "").strip() or None
        sort_by = str(request.query.get("sort") or "players").strip()
        if sort_by not in {"players", "win_rate", "matches", "wins", "name"}:
            sort_by = "players"

        archetypes = await service.list_archetypes(
            guild_id,
            format_filter=format_filter,
            search=search,
            sort_by=sort_by,
        )
        formats = await service.list_formats(guild_id)

        player_ids: set[str] = set()
        for row in archetypes:
            for player in await service.players_for_deck(
                guild_id,
                row["deck"],
                format_filter=format_filter,
            ):
                player_ids.add(str(player["discord_id"]))

        # Chaque match apparaît dans les statistiques des deux decks impliqués.
        total_matches = sum(int(row.get("matches", 0)) for row in archetypes) // 2

        return site.render(
            "archetypes.html",
            request=request,
            archetypes=archetypes,
            formats=formats,
            selected_format=format_filter or "",
            search=search or "",
            sort_by=sort_by,
            total_players=len(player_ids),
            total_matches=total_matches,
        )

    async def archetype_detail(request: web.Request) -> web.Response:
        guild_id = site._public_guild_id()
        if guild_id is None:
            raise ValueError("Aucun serveur Discord public n'est configuré.")

        slug = str(request.match_info.get("slug") or "").strip()
        format_filter = str(request.query.get("format") or "").strip() or None
        row = await service.get_archetype_by_slug(
            guild_id,
            slug,
            format_filter=format_filter,
        )
        if row is None:
            raise web.HTTPNotFound()

        return site.render(
            "archetype_detail.html",
            request=request,
            archetype=row,
            selected_format=format_filter or "",
        )

    async def archetypes_api(request: web.Request) -> web.Response:
        guild_id = site._public_guild_id()
        if guild_id is None:
            return web.json_response({"error": "PUBLIC_GUILD_ID absent"}, status=503)

        sort_by = str(request.query.get("sort") or "players").strip()
        if sort_by not in {"players", "win_rate", "matches", "wins", "name"}:
            sort_by = "players"

        rows = await service.list_archetypes(
            guild_id,
            format_filter=str(request.query.get("format") or "").strip() or None,
            search=str(request.query.get("q") or "").strip() or None,
            sort_by=sort_by,
        )
        return web.json_response(
            {"items": rows, "count": len(rows)},
            headers={"Cache-Control": "no-store"},
        )

    application.router.add_get("/archetypes", archetypes_page, name="archetypes")
    application.router.add_get(
        r"/archetypes/{slug:[a-z0-9-]+}",
        archetype_detail,
        name="archetype_detail",
    )
    application.router.add_get("/api/archetypes", archetypes_api, name="archetypes_api")
    application[_REGISTER_FLAG] = True

    LOGGER.info(
        "Routes Méta/Archétypes enregistrées : /archetypes, /archetypes/<slug>, /api/archetypes"
    )
