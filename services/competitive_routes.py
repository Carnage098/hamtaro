from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any

from aiohttp import WSMsgType, web

from services.meta_center_service import MetaCenterService
from services.player_identity_service import PlayerIdentityService
from services.tournament_live_service import TournamentLiveService

if TYPE_CHECKING:
    from cogs.public_website import PublicWebsiteCog


_REGISTER_FLAG = "hamtaro_competitive_routes"


def register_competitive_routes(
    application: web.Application,
    site: "PublicWebsiteCog",
) -> None:
    if application.get(_REGISTER_FLAG):
        return

    meta = getattr(site, "meta_center", None) or MetaCenterService()
    live = getattr(site, "tournament_live", None) or TournamentLiveService()
    identity = getattr(site, "player_identity", None) or PlayerIdentityService()
    site.meta_center = meta
    site.tournament_live = live
    site.player_identity = identity

    async def meta_api(request: web.Request) -> web.Response:
        guild_id = site._public_guild_id()
        if guild_id is None:
            return web.json_response({"error": "PUBLIC_GUILD_ID absent"}, status=503)
        period = str(request.query.get("period") or "30d")
        if period not in {"7d", "30d", "season", "all"}:
            period = "30d"
        payload = await meta.overview(
            guild_id,
            period=period,
            format_filter=str(request.query.get("format") or "").strip() or None,
        )
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def meta_deck_api(request: web.Request) -> web.Response:
        guild_id = site._public_guild_id()
        if guild_id is None:
            return web.json_response({"error": "PUBLIC_GUILD_ID absent"}, status=503)
        payload = await meta.deck_detail(
            guild_id,
            request.match_info["deck"],
            period=str(request.query.get("period") or "30d"),
            format_filter=str(request.query.get("format") or "").strip() or None,
        )
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def identity_api(request: web.Request) -> web.Response:
        guild_id = site._public_guild_id()
        if guild_id is None:
            return web.json_response({"error": "PUBLIC_GUILD_ID absent"}, status=503)
        player_id = str(request.match_info["discord_id"])
        payload = await identity.build(guild_id, player_id)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def _resolve_tournament_id(request: web.Request) -> int | None:
        raw = str(request.query.get("tournament") or "").strip()
        if raw.isdigit():
            return int(raw)
        guild_id = site._public_guild_id()
        if guild_id is None:
            return None
        tournament = await site.analytics.get_latest_tournament(
            guild_id, active_first=True
        )
        return int(tournament["id"]) if tournament else None

    async def live_home(request: web.Request) -> web.Response:
        tournament_id = await _resolve_tournament_id(request)
        if tournament_id is None:
            return site.render(
                "live.html",
                request=request,
                center=None,
                error="Aucun tournoi disponible.",
            )
        try:
            center = await live.live_center(tournament_id)
        except ValueError as error:
            return site.render(
                "live.html", request=request, center=None, error=str(error)
            )
        return site.render(
            "live.html", request=request, center=center, error=None
        )

    async def live_tournament(request: web.Request) -> web.Response:
        tournament_id = int(request.match_info["tournament_id"])
        center = await live.live_center(tournament_id)
        return site.render(
            "live.html", request=request, center=center, error=None
        )

    async def live_center_api(request: web.Request) -> web.Response:
        tournament_id = int(request.match_info["tournament_id"])
        try:
            center = await live.live_center(tournament_id)
        except ValueError as error:
            return web.json_response({"error": str(error)}, status=404)
        return web.json_response(center, headers={"Cache-Control": "no-store"})

    async def live_match_page(request: web.Request) -> web.Response:
        kind = request.match_info["kind"]
        match_id = int(request.match_info["match_id"])
        match = await live.match(kind, match_id)
        if match is None:
            raise web.HTTPNotFound()
        return site.render(
            "live_match.html",
            request=request,
            match=match,
            stream_kind=kind,
            obs=False,
        )

    async def obs_page(request: web.Request) -> web.Response:
        tournament_id = await _resolve_tournament_id(request)
        if tournament_id is None:
            raise web.HTTPNotFound()
        featured = await live.featured(tournament_id)
        if not featured or not featured.get("match"):
            center = await live.live_center(tournament_id)
            candidate = next(iter(center["live_matches"]), None)
            if not candidate:
                return site.render(
                    "stream_obs.html",
                    request=request,
                    match=None,
                    stream_kind="bracket",
                )
            match = await live.match(candidate["kind"], int(candidate["id"]))
            kind = candidate["kind"]
        else:
            match = featured["match"]
            kind = str(featured["match_kind"])
        return site.render(
            "stream_obs.html",
            request=request,
            match=match,
            stream_kind=kind,
        )

    async def publish_page(request: web.Request) -> web.Response:
        token = str(request.match_info["token"])
        payload = await live.validate_publish_token(token)
        if payload is None:
            raise web.HTTPNotFound()
        match = await live.match(
            str(payload["match_kind"]), int(payload["match_id"])
        )
        if match is None:
            raise web.HTTPNotFound()
        slot = int(payload["slot"])
        return site.render(
            "live_publish.html",
            request=request,
            token=token,
            token_data=payload,
            match=match,
            player_name=match.get(f"player{slot}_name") or payload["player_id"],
        )

    async def publisher_ws(request: web.Request) -> web.StreamResponse:
        token = str(request.match_info["token"])
        payload = await live.validate_publish_token(token)
        if payload is None:
            raise web.HTTPForbidden()
        key = live.hub.stream_key(
            str(payload["match_kind"]),
            int(payload["match_id"]),
            int(payload["slot"]),
        )
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        await live.hub.add_publisher(key, ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = msg.json()
                    except Exception:
                        continue
                    viewer_id = str(data.get("viewer_id") or "")
                    if not viewer_id:
                        continue
                    if data.get("type") in {"offer", "ice"}:
                        await live.hub.to_watcher(key, viewer_id, data)
                elif msg.type in {WSMsgType.ERROR, WSMsgType.CLOSE}:
                    break
        finally:
            await live.hub.remove_publisher(key, ws)
        return ws

    async def watcher_ws(request: web.Request) -> web.StreamResponse:
        kind = str(request.match_info["kind"])
        match_id = int(request.match_info["match_id"])
        slot = int(request.match_info["slot"])
        if slot not in {1, 2}:
            raise web.HTTPBadRequest()
        if await live.match(kind, match_id) is None:
            raise web.HTTPNotFound()
        key = live.hub.stream_key(kind, match_id, slot)
        viewer_id = secrets.token_urlsafe(10)
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        await live.hub.add_watcher(key, viewer_id, ws)
        await ws.send_json({"type": "viewer_ready", "viewer_id": viewer_id})
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = msg.json()
                    except Exception:
                        continue
                    if data.get("type") in {"answer", "ice"}:
                        data["viewer_id"] = viewer_id
                        await live.hub.to_publisher(key, data)
                elif msg.type in {WSMsgType.ERROR, WSMsgType.CLOSE}:
                    break
        finally:
            await live.hub.remove_watcher(key, viewer_id)
        return ws

    application.router.add_get("/api/competitive/meta", meta_api)
    application.router.add_get(r"/api/competitive/meta/{deck:.+}", meta_deck_api)
    application.router.add_get(
        r"/api/competitive/players/{discord_id:\d+}/identity", identity_api
    )
    application.router.add_get("/live", live_home)
    application.router.add_get(
        r"/live/tournament/{tournament_id:\d+}", live_tournament
    )
    application.router.add_get(
        r"/api/competitive/tournaments/{tournament_id:\d+}/live", live_center_api
    )
    application.router.add_get(
        r"/live/match/{kind:bracket|swiss}/{match_id:\d+}",
        live_match_page,
    )
    application.router.add_get("/live/publish/{token}", publish_page)
    application.router.add_get("/stream/obs", obs_page)
    application.router.add_get("/ws/live/publish/{token}", publisher_ws)
    application.router.add_get(
        r"/ws/live/watch/{kind:bracket|swiss}/{match_id:\d+}/{slot:[12]}",
        watcher_ws,
    )

    application[_REGISTER_FLAG] = True
