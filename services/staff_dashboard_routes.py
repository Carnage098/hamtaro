from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from collections import defaultdict, deque
from typing import Any

from aiohttp import web

from services.staff_dashboard_service import StaffDashboardService


LOGGER = logging.getLogger(__name__)

_COOKIE_NAME = "hamtaro_staff_session"
_LOGIN_WINDOW_SECONDS = 10 * 60
_LOGIN_MAX_ATTEMPTS = 5
_SESSION_MAX_AGE = 8 * 60 * 60


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {
        "",
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }


class StaffDashboardRoutes:
    """
    Routes du tableau de bord staff.

    Ce contrôleur est enregistré directement dans l'application aiohttp
    créée par PublicWebsiteCog. Il ne dépend d'aucun cog supplémentaire
    ni d'aucun ordre de chargement.
    """

    def __init__(self, website_cog: Any) -> None:
        self.website = website_cog
        self.bot = website_cog.bot
        self.login_attempts: dict[str, deque[float]] = defaultdict(deque)

    @staticmethod
    def enabled() -> bool:
        return _truthy(
            os.getenv("STAFF_DASHBOARD_ENABLED"),
            default=False,
        )

    @staticmethod
    def secret() -> str:
        return os.getenv("STAFF_DASHBOARD_TOKEN", "").strip()

    @staticmethod
    def session_digest(secret: str) -> str:
        return hmac.new(
            secret.encode("utf-8"),
            b"hamtaro-staff-dashboard-session-v3",
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def is_secure(request: web.Request) -> bool:
        forwarded = request.headers.get("X-Forwarded-Proto", "")
        forwarded_proto = forwarded.split(",", 1)[0].strip().lower()
        return request.scheme == "https" or forwarded_proto == "https"

    @staticmethod
    def client_key(request: web.Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        forwarded_ip = forwarded.split(",", 1)[0].strip()
        return forwarded_ip or request.remote or "unknown"

    def authorized(self, request: web.Request) -> bool:
        secret = self.secret()
        if not self.enabled() or len(secret) < 24:
            return False

        supplied = request.cookies.get(_COOKIE_NAME, "")
        expected = self.session_digest(secret)
        return bool(supplied) and hmac.compare_digest(
            supplied,
            expected,
        )

    async def record_audit(
        self,
        *,
        action: str,
        details: dict[str, Any],
    ) -> None:
        try:
            guild_id = self.website._public_guild_id() or "unknown"
            await self.bot.db.execute(
                """
                INSERT INTO audit_logs (
                    guild_id,
                    actor_id,
                    actor_name,
                    action,
                    entity_type,
                    entity_id,
                    details
                ) VALUES (
                    ?,
                    NULL,
                    'Web',
                    ?,
                    'website',
                    'staff-dashboard',
                    ?
                )
                """,
                (
                    guild_id,
                    action,
                    json.dumps(details, ensure_ascii=False),
                ),
            )
            await self.bot.db.commit()
        except Exception:
            # L'accès au tableau reste possible si le journal d'audit
            # n'est momentanément pas disponible.
            LOGGER.exception(
                "Impossible d'enregistrer l'audit du tableau de bord staff."
            )

    async def staff_page(self, request: web.Request) -> web.Response:
        if not self.enabled():
            raise web.HTTPNotFound()

        secret = self.secret()
        if len(secret) < 24:
            return self.website.render(
                "staff_login.html",
                request=request,
                error=(
                    "Le tableau de bord n'est pas configuré. "
                    "Définis STAFF_DASHBOARD_TOKEN avec au moins "
                    "24 caractères."
                ),
                status_code=503,
            )

        if not self.authorized(request):
            return self.website.render(
                "staff_login.html",
                request=request,
                error=None,
                status_code=200,
            )

        guild_id = self.website._public_guild_id()
        if guild_id is None:
            return self.website.render(
                "error.html",
                request=request,
                status=503,
                title="Serveur Discord indisponible",
                message=(
                    "Aucun GUILD_ID ou PUBLIC_GUILD_ID valide "
                    "n'est configuré."
                ),
                status_code=503,
            )

        overview = await StaffDashboardService(self.bot).overview(guild_id)

        try:
            refresh_seconds = max(
                5,
                int(
                    os.getenv(
                        "LIVE_SITE_REFRESH_SECONDS",
                        "15",
                    )
                    or "15"
                ),
            )
        except ValueError:
            refresh_seconds = 15

        return self.website.render(
            "staff_dashboard.html",
            request=request,
            overview=overview,
            refresh_seconds=refresh_seconds,
        )

    async def staff_login(self, request: web.Request) -> web.Response:
        if not self.enabled():
            raise web.HTTPNotFound()

        secret = self.secret()
        if len(secret) < 24:
            return self.website.render(
                "staff_login.html",
                request=request,
                error=(
                    "Le tableau de bord n'est pas configuré. "
                    "Définis STAFF_DASHBOARD_TOKEN avec au moins "
                    "24 caractères."
                ),
                status_code=503,
            )

        now = time.monotonic()
        client = self.client_key(request)
        queue = self.login_attempts[client]

        while queue and now - queue[0] > _LOGIN_WINDOW_SECONDS:
            queue.popleft()

        if len(queue) >= _LOGIN_MAX_ATTEMPTS:
            return self.website.render(
                "staff_login.html",
                request=request,
                error=(
                    "Trop de tentatives. "
                    "Réessaie dans quelques minutes."
                ),
                status_code=429,
            )

        form = await request.post()
        provided = str(form.get("token", "")).strip()

        if not hmac.compare_digest(provided, secret):
            queue.append(now)
            await self.record_audit(
                action="staff_dashboard_login_failed",
                details={"remote": client},
            )
            return self.website.render(
                "staff_login.html",
                request=request,
                error="Jeton incorrect.",
                status_code=401,
            )

        queue.clear()

        response = web.HTTPSeeOther(location="/staff")
        response.set_cookie(
            _COOKIE_NAME,
            self.session_digest(secret),
            max_age=_SESSION_MAX_AGE,
            httponly=True,
            secure=self.is_secure(request),
            samesite="Strict",
            path="/staff",
        )

        await self.record_audit(
            action="staff_dashboard_login_success",
            details={"remote": client},
        )
        return response

    async def staff_logout(self, request: web.Request) -> web.Response:
        response = web.HTTPSeeOther(location="/staff")
        response.del_cookie(_COOKIE_NAME, path="/staff")
        return response

    async def overview_api(
        self,
        request: web.Request,
    ) -> web.Response:
        if not self.enabled():
            raise web.HTTPNotFound()

        if not self.authorized(request):
            raise web.HTTPUnauthorized(
                text="Session staff absente ou expirée.",
                content_type="text/plain",
            )

        guild_id = self.website._public_guild_id()
        if guild_id is None:
            raise web.HTTPServiceUnavailable(
                text="Serveur Discord non configuré.",
                content_type="text/plain",
            )

        overview = await StaffDashboardService(self.bot).overview(guild_id)
        return web.json_response(
            overview,
            headers={"Cache-Control": "no-store"},
        )

    async def live_tournaments_api(
        self,
        request: web.Request,
    ) -> web.Response:
        tournaments = await self.website.service.list_tournaments(limit=100)
        normalized: list[dict[str, Any]] = []

        for raw in tournaments:
            item = dict(raw)
            normalized.append(
                {
                    "id": item.get("id"),
                    "code": item.get("code"),
                    "name": item.get("name"),
                    "format": item.get("format"),
                    "status": item.get("status"),
                    "participant_count": int(
                        item.get("participant_count") or 0
                    ),
                    "max_players": int(
                        item.get("max_players") or 0
                    ),
                    "current_round": int(
                        item.get("current_round") or 0
                    ),
                    "total_rounds": int(
                        item.get("total_rounds") or 0
                    ),
                    "updated_at": (
                        item.get("updated_at")
                        or item.get("created_at")
                    ),
                }
            )

        return web.json_response(
            {
                "tournaments": normalized,
                "generated_at": int(time.time()),
            },
            headers={"Cache-Control": "no-store"},
        )


def _route_exists(application: web.Application, path: str) -> bool:
    for resource in application.router.resources():
        if getattr(resource, "canonical", None) == path:
            return True
    return False


def register_staff_dashboard_routes(
    application: web.Application,
    website_cog: Any,
) -> StaffDashboardRoutes:
    """
    Enregistre les routes directement dans l'application du site.

    Cette fonction doit être appelée dans PublicWebsiteCog._start_server()
    avant l'ajout de la route statique. Elle ne redémarre jamais le site.
    """
    controller = StaffDashboardRoutes(website_cog)
    application["hamtaro_staff_dashboard"] = controller

    routes = (
        ("GET", "/api/tournaments/live.json", controller.live_tournaments_api),
        ("GET", "/staff", controller.staff_page),
        ("POST", "/staff/login", controller.staff_login),
        ("POST", "/staff/logout", controller.staff_logout),
        ("GET", "/staff/logout", controller.staff_logout),
        ("GET", "/staff/api/overview", controller.overview_api),
    )

    for method, path, handler in routes:
        if _route_exists(application, path):
            LOGGER.warning(
                "Route déjà présente, enregistrement ignoré : %s %s",
                method,
                path,
            )
            continue

        application.router.add_route(
            method,
            path,
            handler,
        )

    LOGGER.info(
        "Routes staff intégrées directement au site public : "
        "/staff, /staff/login, /staff/api/overview."
    )
    return controller
