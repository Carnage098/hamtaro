from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from collections import defaultdict, deque
from typing import Any

from aiohttp import web
from discord.ext import commands

from services.staff_dashboard_service import StaffDashboardService

LOGGER = logging.getLogger(__name__)
_PATCH_MARKER = "hamtaro-professional-web-v1"
_COOKIE_NAME = "hamtaro_staff_session"
_LOGIN_WINDOW_SECONDS = 600
_LOGIN_MAX_ATTEMPTS = 5


def _enabled() -> bool:
    value = os.getenv("STAFF_DASHBOARD_ENABLED", "true").strip().lower()
    return value not in {"0", "false", "no", "off", "disabled", ""}


def _secret() -> str:
    return os.getenv("STAFF_DASHBOARD_TOKEN", "").strip()


def _cookie_digest(secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        b"hamtaro-staff-dashboard-session-v1",
        hashlib.sha256,
    ).hexdigest()


def _is_secure(request: web.Request) -> bool:
    forwarded = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
    return request.scheme == "https" or forwarded == "https"


def _client_key(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    return forwarded or request.remote or "unknown"


def _authorized(request: web.Request) -> bool:
    secret = _secret()
    if not _enabled() or len(secret) < 24:
        return False
    supplied = request.cookies.get(_COOKIE_NAME, "")
    return hmac.compare_digest(supplied, _cookie_digest(secret))


async def _staff_page(self, request: web.Request) -> web.Response:
    if not _enabled():
        raise web.HTTPNotFound()
    if not _authorized(request):
        return self.render(
            "staff_login.html",
            request=request,
            error=None,
            status_code=401,
        )
    guild_id = self._public_guild_id()
    if guild_id is None:
        return self.render(
            "error.html",
            request=request,
            status=503,
            title="Serveur Discord indisponible",
            message="Aucun GUILD_ID/PUBLIC_GUILD_ID valide n'est configuré.",
            status_code=503,
        )
    service = StaffDashboardService(self.bot)
    overview = await service.overview(guild_id)
    return self.render(
        "staff_dashboard.html",
        request=request,
        overview=overview,
        refresh_seconds=max(5, int(os.getenv("LIVE_SITE_REFRESH_SECONDS", "15") or 15)),
    )


async def _staff_login(self, request: web.Request) -> web.Response:
    if not _enabled():
        raise web.HTTPNotFound()
    secret = _secret()
    if len(secret) < 24:
        return self.render(
            "staff_login.html",
            request=request,
            error=(
                "Le tableau de bord n'est pas encore configuré. "
                "Définis STAFF_DASHBOARD_TOKEN avec au moins 24 caractères sur Railway."
            ),
            status_code=503,
        )

    attempts: dict[str, deque[float]] = getattr(self, "_professional_login_attempts", None)
    if attempts is None:
        attempts = defaultdict(deque)
        self._professional_login_attempts = attempts
    now = time.monotonic()
    key = _client_key(request)
    queue = attempts[key]
    while queue and now - queue[0] > _LOGIN_WINDOW_SECONDS:
        queue.popleft()
    if len(queue) >= _LOGIN_MAX_ATTEMPTS:
        return self.render(
            "staff_login.html",
            request=request,
            error="Trop de tentatives. Réessaie dans quelques minutes.",
            status_code=429,
        )

    form = await request.post()
    provided = str(form.get("token", "")).strip()
    if not hmac.compare_digest(provided, secret):
        queue.append(now)
        await _record_web_audit(
            self,
            action="staff_dashboard_login_failed",
            details={"remote": key},
        )
        return self.render(
            "staff_login.html",
            request=request,
            error="Jeton incorrect.",
            status_code=401,
        )

    queue.clear()
    response = web.HTTPSeeOther(location="/staff")
    response.set_cookie(
        _COOKIE_NAME,
        _cookie_digest(secret),
        max_age=8 * 60 * 60,
        httponly=True,
        secure=_is_secure(request),
        samesite="Strict",
        path="/staff",
    )
    await _record_web_audit(
        self,
        action="staff_dashboard_login_success",
        details={"remote": key},
    )
    return response


async def _staff_logout(self, request: web.Request) -> web.Response:
    response = web.HTTPSeeOther(location="/staff")
    response.del_cookie(_COOKIE_NAME, path="/staff")
    return response


async def _staff_overview_api(self, request: web.Request) -> web.Response:
    if not _authorized(request):
        raise web.HTTPUnauthorized()
    guild_id = self._public_guild_id()
    if guild_id is None:
        raise web.HTTPServiceUnavailable(text="Serveur Discord non configuré")
    overview = await StaffDashboardService(self.bot).overview(guild_id)
    return web.json_response(
        overview,
        headers={"Cache-Control": "no-store"},
    )


async def _live_tournaments_api(self, request: web.Request) -> web.Response:
    tournaments = await self.service.list_tournaments(limit=100)
    normalized: list[dict[str, Any]] = []
    for raw in tournaments:
        item = dict(raw)
        normalized.append({
            "id": item.get("id"),
            "code": item.get("code"),
            "name": item.get("name"),
            "format": item.get("format"),
            "status": item.get("status"),
            "participant_count": int(item.get("participant_count") or 0),
            "max_players": int(item.get("max_players") or 0),
            "current_round": int(item.get("current_round") or 0),
            "total_rounds": int(item.get("total_rounds") or 0),
            "updated_at": item.get("updated_at") or item.get("created_at"),
        })
    return web.json_response(
        {"tournaments": normalized, "generated_at": int(time.time())},
        headers={"Cache-Control": "no-store"},
    )


async def _record_web_audit(self, *, action: str, details: dict[str, Any]) -> None:
    try:
        guild_id = self._public_guild_id() or "unknown"
        await self.bot.db.execute(
            """
            INSERT INTO audit_logs (
                guild_id, actor_id, actor_name, action,
                entity_type, entity_id, details
            ) VALUES (?, NULL, 'Web', ?, 'website', 'staff-dashboard', ?)
            """,
            (guild_id, action, __import__("json").dumps(details, ensure_ascii=False)),
        )
        await self.bot.db.commit()
    except Exception:
        LOGGER.exception("Impossible d'enregistrer l'audit du tableau de bord.")


@web.middleware
async def _security_headers(self, request: web.Request, handler) -> web.StreamResponse:
    response = await handler(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' https: data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; "
        "base-uri 'self'; form-action 'self'",
    )
    if _is_secure(request):
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


async def _patched_start_server(self) -> None:
    if self.runner is not None:
        return
    application = web.Application(
        client_max_size=2 * 1024 * 1024,
        middlewares=[
            self._security_headers_middleware,
            self._error_middleware,
        ],
    )
    application.router.add_get("/", self.home_page)
    application.router.add_get("/tournaments", self.index_page)
    application.router.add_get(r"/tournaments/{tournament_id:\d+}", self.tournament_page)
    application.router.add_get(r"/api/tournaments/{tournament_id:\d+}/bracket.png", self.bracket_image)
    application.router.add_get(r"/api/tournaments/{tournament_id:\d+}/version.json", self.bracket_version)
    application.router.add_get("/api/tournaments/live.json", self.live_tournaments_api)
    application.router.add_get(r"/players/{discord_id:\d+}", self.player_page)
    application.router.add_get("/profiles", self.profiles_page)
    application.router.add_get("/participants", self.participants_page)
    application.router.add_get("/guide", self.guide_page)
    application.router.add_get("/results", self.results_page)
    application.router.add_get("/decks", self.decks_page)
    application.router.add_get("/archives", self.archives_page)
    application.router.add_get("/health", self.health_page)
    application.router.add_get("/staff", self.staff_page)
    application.router.add_post("/staff/login", self.staff_login)
    application.router.add_get("/staff/logout", self.staff_logout)
    application.router.add_get("/staff/api/overview", self.staff_overview_api)
    application.router.add_get("/favicon.ico", self.favicon)
    if self.static_directory.exists():
        application.router.add_static("/static/", path=str(self.static_directory), name="static")

    runner = web.AppRunner(application, access_log=LOGGER)
    await runner.setup()
    host = os.getenv("WEBSITE_HOST", "0.0.0.0")
    try:
        port = int(os.getenv("PORT", "8080"))
    except ValueError:
        port = 8080
    site = web.TCPSite(runner, host=host, port=port)
    try:
        await site.start()
    except Exception:
        await runner.cleanup()
        LOGGER.exception("Impossible de lancer le site Hamtaro sur %s:%s.", host, port)
        raise
    self.application = application
    self.runner = runner
    self.site = site
    LOGGER.info("Site Hamtaro professionnel lancé sur %s:%s.", host, port)


def apply_patch() -> None:
    from cogs.public_website import PublicWebsiteCog

    if getattr(PublicWebsiteCog, "_professional_patch", None) == _PATCH_MARKER:
        return
    PublicWebsiteCog._professional_patch = _PATCH_MARKER
    PublicWebsiteCog._start_server = _patched_start_server
    PublicWebsiteCog._security_headers_middleware = _security_headers
    PublicWebsiteCog.staff_page = _staff_page
    PublicWebsiteCog.staff_login = _staff_login
    PublicWebsiteCog.staff_logout = _staff_logout
    PublicWebsiteCog.staff_overview_api = _staff_overview_api
    PublicWebsiteCog.live_tournaments_api = _live_tournaments_api


class ProfessionalWebPatchCog(commands.Cog):
    """Applique les routes professionnelles avant le chargement du site."""


async def setup(bot: commands.Bot) -> None:
    del bot
    apply_patch()
