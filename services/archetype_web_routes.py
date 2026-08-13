from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aiohttp import web

from services.archetype_meta_service import ArchetypeMetaService

if TYPE_CHECKING:
    from cogs.public_website import PublicWebsiteCog


LOGGER = logging.getLogger(__name__)
_REGISTER_FLAG = "hamtaro_archetype_routes_registered"


def _row_dict(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


async def _catalog_table_exists(site: "PublicWebsiteCog") -> bool:
    db = getattr(getattr(site, "bot", None), "db", None)
    if db is None:
        return False
    row = await db.fetchone(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'archetype_catalog'
        LIMIT 1
        """
    )
    return row is not None


async def _catalog_rows(
    site: "PublicWebsiteCog",
    guild_id: str,
    *,
    format_filter: str | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Lit les fiches ajoutées via /archetype_add.

    Le catalogue est volontairement indépendant des inscriptions : une fiche peut
    donc être renvoyée même avec 0 joueur et 0 match.
    """

    if not await _catalog_table_exists(site):
        return []

    db = site.bot.db
    where = ["guild_id = ?"]
    params: list[Any] = [guild_id]

    if format_filter:
        # Une fiche sans format est considérée comme générale et reste visible.
        where.append(
            "(TRIM(COALESCE(format, '')) = '' OR "
            "LOWER(TRIM(format)) = LOWER(TRIM(?)))"
        )
        params.append(format_filter)

    if search:
        where.append("LOWER(name) LIKE LOWER(?)")
        params.append(f"%{search.strip()}%")

    rows = await db.fetchall(
        f"""
        SELECT
            id,
            guild_id,
            name,
            normalized_name,
            description,
            playstyle,
            format,
            artwork_url,
            created_at,
            updated_at
        FROM archetype_catalog
        WHERE {' AND '.join(where)}
        ORDER BY LOWER(name) ASC
        """,
        tuple(params),
    )
    return [dict(row) for row in rows]


def _catalog_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalog_id": row.get("id"),
        "catalog_entry": True,
        "description": row.get("description"),
        "playstyle": row.get("playstyle"),
        "catalog_format": row.get("format"),
        "catalog_artwork_url": row.get("artwork_url"),
    }


async def _apply_catalog_artwork(
    service: ArchetypeMetaService,
    guild_id: str,
    result: dict[str, Any],
    catalog: dict[str, Any],
) -> None:
    """Applique l'artwork du catalogue sans écraser un artwork communautaire validé."""

    raw_url = str(catalog.get("artwork_url") or "").strip()
    if not raw_url:
        return
    if not (raw_url.startswith("https://") or raw_url.startswith("/static/")):
        return

    artwork = dict(result.get("artwork") or {})
    # Un artwork communautaire approuvé reste prioritaire.
    if str(artwork.get("source") or "").lower() == "community":
        return

    artwork.update(
        {
            "card_name": result.get("deck"),
            "image_url": raw_url,
            "remote_image_url": raw_url if raw_url.startswith("https://") else None,
            "source": "catalog",
        }
    )
    result["artwork"] = artwork


async def _new_catalog_archetype(
    service: ArchetypeMetaService,
    guild_id: str,
    catalog: dict[str, Any],
) -> dict[str, Any]:
    name = service.normalize_deck_name(catalog.get("name"))
    state = await service.ensure_default_artwork(guild_id, name)
    artwork = service._display_artwork(state)
    remote_url = str(artwork.get("image_url") or "")
    artwork["remote_image_url"] = remote_url if remote_url.startswith("https://") else None

    result: dict[str, Any] = {
        "deck": name,
        "slug": service.slugify(name),
        "players": 0,
        "matches": 0,
        "wins": 0,
        "losses": 0,
        "double_losses": 0,
        "win_rate": 0.0,
        "top4": 0,
        "tournament_wins": 0,
        "artwork": artwork,
        **_catalog_metadata(catalog),
    }
    await _apply_catalog_artwork(service, guild_id, result, catalog)
    return result


def _sort_archetypes(rows: list[dict[str, Any]], sort_by: str) -> None:
    def number(row: dict[str, Any], key: str) -> float:
        try:
            return float(row.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    if sort_by == "name":
        rows.sort(key=lambda row: str(row.get("deck") or "").casefold())
        return

    sorters = {
        "win_rate": lambda row: (
            number(row, "win_rate"),
            number(row, "matches"),
            number(row, "players"),
        ),
        "matches": lambda row: (
            number(row, "matches"),
            number(row, "win_rate"),
            number(row, "players"),
        ),
        "wins": lambda row: (
            number(row, "wins"),
            number(row, "win_rate"),
            number(row, "matches"),
        ),
        "players": lambda row: (
            number(row, "players"),
            number(row, "matches"),
            number(row, "win_rate"),
        ),
    }
    rows.sort(key=sorters.get(sort_by, sorters["players"]), reverse=True)


async def _merged_archetypes(
    site: "PublicWebsiteCog",
    service: ArchetypeMetaService,
    guild_id: str,
    *,
    format_filter: str | None = None,
    search: str | None = None,
    sort_by: str = "players",
) -> list[dict[str, Any]]:
    """Fusionne statistiques historiques + catalogue manuel Hamtaro."""

    historical = await service.list_archetypes(
        guild_id,
        format_filter=format_filter,
        search=search,
        sort_by=sort_by,
    )
    catalog_rows = await _catalog_rows(
        site,
        guild_id,
        format_filter=format_filter,
        search=search,
    )

    merged: dict[str, dict[str, Any]] = {}
    for row in historical:
        item = dict(row)
        key = service.deck_key(item.get("deck"))
        if key:
            merged[key] = item

    for catalog in catalog_rows:
        canonical_name = service.normalize_deck_name(catalog.get("name"))
        key = service.deck_key(canonical_name)
        if not key:
            continue

        if key in merged:
            item = merged[key]
            # Le nom défini par le staff devient le nom canonique d'affichage.
            item["deck"] = canonical_name
            item["slug"] = service.slugify(canonical_name)
            item.update(_catalog_metadata(catalog))
            await _apply_catalog_artwork(service, guild_id, item, catalog)
        else:
            merged[key] = await _new_catalog_archetype(
                service,
                guild_id,
                catalog,
            )

    rows = list(merged.values())
    _sort_archetypes(rows, sort_by)
    return rows


async def _merged_formats(
    site: "PublicWebsiteCog",
    service: ArchetypeMetaService,
    guild_id: str,
) -> list[str]:
    formats = set(await service.list_formats(guild_id))
    if await _catalog_table_exists(site):
        rows = await site.bot.db.fetchall(
            """
            SELECT DISTINCT TRIM(format) AS format
            FROM archetype_catalog
            WHERE guild_id = ? AND TRIM(COALESCE(format, '')) <> ''
            ORDER BY LOWER(TRIM(format)) ASC
            """,
            (guild_id,),
        )
        formats.update(str(row["format"]) for row in rows if str(row["format"] or "").strip())
    return sorted(formats, key=str.casefold)


def register_archetype_routes(
    application: web.Application,
    site: "PublicWebsiteCog",
) -> None:
    """Enregistre les pages Méta/Archétypes sur l'application aiohttp Hamtaro.

    V5 : fusionne les statistiques historiques et la table archetype_catalog
    créée par /archetype_add. Une fiche indépendante apparaît donc sur le site
    même lorsqu'aucun joueur ne l'a encore utilisée.
    """

    if application.get(_REGISTER_FLAG):
        LOGGER.info(
            "Routes Méta/Archétypes déjà enregistrées ; aucun doublon ajouté."
        )
        return

    service = getattr(site, "archetype_meta", None)
    if service is None:
        service = ArchetypeMetaService()
        setattr(site, "archetype_meta", service)

    async def archetypes_page(request: web.Request) -> web.Response:
        guild_id = site._public_guild_id()
        if guild_id is None:
            raise ValueError(
                "Aucun serveur Discord public n'est configuré. "
                "Ajoute PUBLIC_GUILD_ID dans Railway."
            )

        format_filter = str(request.query.get("format") or "").strip() or None
        search = str(request.query.get("q") or "").strip() or None
        sort_by = str(request.query.get("sort") or "players").strip()
        if sort_by not in {"players", "win_rate", "matches", "wins", "name"}:
            sort_by = "players"

        archetypes = await _merged_archetypes(
            site,
            service,
            guild_id,
            format_filter=format_filter,
            search=search,
            sort_by=sort_by,
        )
        formats = await _merged_formats(site, service, guild_id)

        player_ids: set[str] = set()
        for row in archetypes:
            # Les fiches catalogue à 0 joueur retournent naturellement [].
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

        rows = await _merged_archetypes(
            site,
            service,
            guild_id,
            format_filter=format_filter,
            sort_by="name",
        )
        row = next((item for item in rows if item.get("slug") == slug), None)
        if row is None:
            raise web.HTTPNotFound()

        row = dict(row)
        row["players_detail"] = await service.players_for_deck(
            guild_id,
            str(row["deck"]),
            format_filter=format_filter,
        )
        return site.render(
            "archetype_detail.html",
            request=request,
            archetype=row,
            selected_format=format_filter or "",
        )

    async def archetypes_api(request: web.Request) -> web.Response:
        guild_id = site._public_guild_id()
        if guild_id is None:
            return web.json_response(
                {"error": "PUBLIC_GUILD_ID absent"},
                status=503,
            )

        sort_by = str(request.query.get("sort") or "players").strip()
        if sort_by not in {"players", "win_rate", "matches", "wins", "name"}:
            sort_by = "players"

        rows = await _merged_archetypes(
            site,
            service,
            guild_id,
            format_filter=str(request.query.get("format") or "").strip() or None,
            search=str(request.query.get("q") or "").strip() or None,
            sort_by=sort_by,
        )
        return web.json_response(
            {"items": rows, "count": len(rows)},
            headers={"Cache-Control": "no-store"},
        )

    application.router.add_get(
        "/archetypes",
        archetypes_page,
        name="archetypes",
    )
    application.router.add_get(
        r"/archetypes/{slug:[a-z0-9-]+}",
        archetype_detail,
        name="archetype_detail",
    )
    application.router.add_get(
        "/api/archetypes",
        archetypes_api,
        name="archetypes_api",
    )
    application[_REGISTER_FLAG] = True

    LOGGER.info(
        "Routes Méta/Archétypes enregistrées : "
        "/archetypes, /archetypes/<slug>, /api/archetypes"
    )
