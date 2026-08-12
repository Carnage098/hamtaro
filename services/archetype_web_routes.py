from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    from cogs.public_website import PublicWebsiteCog


def register_archetype_routes(application: web.Application, site: "PublicWebsiteCog") -> None:
    """Ajoute les routes Méta/Archétypes au site public existant."""

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

        service = site.archetype_meta
        archetypes = await service.list_archetypes(
            guild_id,
            format_filter=format_filter,
            search=search,
            sort_by=sort_by,
        )
        formats = await service.list_formats(guild_id)
        total_players = len(
            {
                player["discord_id"]
                for row in archetypes
                for player in await service.players_for_deck(
                    guild_id, row["deck"], format_filter=format_filter
                )
            }
        ) if archetypes else 0
        total_matches = sum(int(row.get("matches", 0)) for row in archetypes) // 2
        return site.render(
            "archetypes.html",
            request=request,
            archetypes=archetypes,
            formats=formats,
            selected_format=format_filter or "",
            search=search or "",
            sort_by=sort_by,
            total_players=total_players,
            total_matches=total_matches,
        )

    async def archetype_detail(request: web.Request) -> web.Response:
        guild_id = site._public_guild_id()
        if guild_id is None:
            raise ValueError("Aucun serveur Discord public n'est configuré.")
        slug = str(request.match_info.get("slug") or "").strip()
        format_filter = str(request.query.get("format") or "").strip() or None
        row = await site.archetype_meta.get_archetype_by_slug(
            guild_id, slug, format_filter=format_filter
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
        rows = await site.archetype_meta.list_archetypes(
            guild_id,
            format_filter=str(request.query.get("format") or "").strip() or None,
            search=str(request.query.get("q") or "").strip() or None,
            sort_by=str(request.query.get("sort") or "players").strip(),
        )
        return web.json_response(
            {"items": rows, "count": len(rows)},
            headers={"Cache-Control": "no-store"},
        )

    application.router.add_get("/archetypes", archetypes_page)
    application.router.add_get(r"/archetypes/{slug:[a-z0-9-]+}", archetype_detail)
    application.router.add_get("/api/archetypes", archetypes_api)
