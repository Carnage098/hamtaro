from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from aiohttp import ClientSession, web

from services.boss_service import BossService


SESSION_COOKIE = "hamtaro_boss_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600


class BossRoutes:
    def __init__(self, website_cog: Any) -> None:
        self.website_cog = website_cog
        self.service = BossService()

    def guild_id(self, request: web.Request) -> str:
        requested = request.query.get("guild", "").strip()
        if requested.isdigit():
            return requested
        configured = (
            os.getenv("PUBLIC_GUILD_ID")
            or os.getenv("GUILD_ID")
            or ""
        ).strip()
        if configured.isdigit():
            return configured
        guilds = list(getattr(self.website_cog.bot, "guilds", []))
        if guilds:
            return str(guilds[0].id)
        raise ValueError("Aucun serveur public n'est configuré pour le format Boss.")

    def _session_secret(self) -> bytes:
        raw = (
            os.getenv("BOSS_WEB_SESSION_SECRET")
            or os.getenv("TEAM_WEB_SESSION_SECRET")
            or os.getenv("DISCORD_TOKEN")
            or ""
        ).strip()
        if not raw:
            raise RuntimeError("BOSS_WEB_SESSION_SECRET est manquant.")
        return hashlib.sha256(
            ("hamtaro-boss-session:" + raw).encode("utf-8")
        ).digest()

    def _sign(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        signature = hmac.new(
            self._session_secret(),
            body.encode("ascii"),
            hashlib.sha256,
        ).digest()
        sig = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        return f"{body}.{sig}"

    def _unsign(self, value: str | None) -> dict[str, Any] | None:
        if not value or "." not in value:
            return None
        body, supplied = value.split(".", 1)
        expected_raw = hmac.new(
            self._session_secret(),
            body.encode("ascii"),
            hashlib.sha256,
        ).digest()
        expected = base64.urlsafe_b64encode(expected_raw).decode("ascii").rstrip("=")
        if not hmac.compare_digest(expected, supplied):
            return None
        try:
            padded = body + "=" * (-len(body) % 4)
            payload = json.loads(
                base64.urlsafe_b64decode(padded).decode("utf-8")
            )
        except Exception:
            return None
        if int(payload.get("exp", 0) or 0) < int(time.time()):
            return None
        return payload

    def current_user(self, request: web.Request) -> dict[str, Any] | None:
        try:
            return self._unsign(request.cookies.get(SESSION_COOKIE))
        except RuntimeError:
            return None

    def _base_url(self, request: web.Request) -> str:
        configured = (os.getenv("WEBSITE_BASE_URL") or "").strip().rstrip("/")
        if configured:
            return configured
        proto = request.headers.get("X-Forwarded-Proto", request.scheme)
        host = request.headers.get("X-Forwarded-Host", request.host)
        return f"{proto}://{host}".rstrip("/")

    def _oauth_client_id(self) -> str:
        configured = (
            os.getenv("DISCORD_CLIENT_ID")
            or os.getenv("APPLICATION_ID")
            or ""
        ).strip()
        if configured.isdigit():
            return configured
        user = getattr(self.website_cog.bot, "user", None)
        return str(user.id) if user is not None else ""

    def _oauth_client_secret(self) -> str:
        return (os.getenv("DISCORD_CLIENT_SECRET") or "").strip()

    async def _member(self, guild_id: str, discord_id: str):
        bot = self.website_cog.bot
        guild = bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
        if guild is None or not discord_id.isdigit():
            return None
        member = guild.get_member(int(discord_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(discord_id))
            except Exception:
                member = None
        return member

    async def _is_staff(self, guild_id: str, discord_id: str) -> bool:
        member = await self._member(guild_id, discord_id)
        if member is None:
            return False
        configured_ids = {
            item.strip()
            for item in (os.getenv("STAFF_ROLE_IDS") or "").split(",")
            if item.strip().isdigit()
        }
        if configured_ids and any(
            str(role.id) in configured_ids for role in member.roles
        ):
            return True
        role_names = {
            str(role.name).strip().casefold()
            for role in member.roles
        }
        accepted = {
            "admin",
            "administrator",
            "staff",
            "modo",
            "modérateur",
            "moderateur",
            "tournament staff",
            "organisateur",
            "organisateur tournoi",
            "arbitre",
            "🛑modo",
            "🛑 modo",
        }
        perms = member.guild_permissions
        return bool(role_names & accepted) or bool(
            perms.administrator or perms.manage_guild
        )

    async def _require_user(self, request: web.Request):
        guild_id = self.guild_id(request)
        user = self.current_user(request)
        if not user:
            raise web.HTTPUnauthorized(
                text="Connecte-toi avec Discord pour continuer."
            )
        discord_id = str(user.get("id") or "")
        member = await self._member(guild_id, discord_id)
        if member is None:
            raise web.HTTPForbidden(
                text="Ton compte Discord n'est pas membre du serveur Hamtaro."
            )
        return guild_id, user, member

    @staticmethod
    def _csrf_ok(user: dict[str, Any], supplied: str) -> bool:
        expected = str(user.get("csrf") or "")
        return bool(
            supplied
            and expected
            and hmac.compare_digest(supplied, expected)
        )

    async def page(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        user = self.current_user(request)
        state = await self.service.state(guild_id)
        challengers = await self.service.challengers(guild_id)
        history = await self.service.history(guild_id, limit=20)
        is_staff = False
        is_registered = False

        if user:
            discord_id = str(user.get("id") or "")
            is_staff = await self._is_staff(guild_id, discord_id)
            is_registered = any(
                str(row["discord_id"]) == discord_id
                and str(row["status"]) != "removed"
                for row in challengers
            )

        return self.website_cog.render(
            "format_boss.html",
            request=request,
            guild_id=guild_id,
            state=state,
            challengers=challengers,
            history=history,
            user=user,
            is_staff=is_staff,
            is_registered=is_registered,
            saved=request.query.get("saved") == "1",
            error=request.query.get("error"),
        )

    async def login(self, request: web.Request) -> web.Response:
        client_id = self._oauth_client_id()
        client_secret = self._oauth_client_secret()
        if not client_id or not client_secret:
            raise web.HTTPServiceUnavailable(
                text=(
                    "Connexion Discord non configurée. Ajoute DISCORD_CLIENT_SECRET "
                    "sur Railway et l'URL de redirection "
                    "/formats/boss/oauth/callback dans Discord Developer Portal."
                )
            )

        state = self._sign(
            {
                "kind": "boss_oauth_state",
                "exp": int(time.time()) + 600,
                "nonce": secrets.token_urlsafe(12),
            }
        )
        redirect_uri = self._base_url(request) + "/formats/boss/oauth/callback"
        params = urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": "identify",
                "state": state,
                "prompt": "none",
            }
        )
        raise web.HTTPFound(
            location="https://discord.com/oauth2/authorize?" + params
        )

    async def oauth_callback(self, request: web.Request) -> web.Response:
        state = self._unsign(request.query.get("state"))
        if not state or state.get("kind") != "boss_oauth_state":
            raise web.HTTPBadRequest(
                text="État OAuth invalide ou expiré."
            )

        code = (request.query.get("code") or "").strip()
        if not code:
            raise web.HTTPBadRequest(text="Code Discord manquant.")

        redirect_uri = self._base_url(request) + "/formats/boss/oauth/callback"
        token_data = {
            "client_id": self._oauth_client_id(),
            "client_secret": self._oauth_client_secret(),
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }

        async with ClientSession() as session:
            async with session.post(
                "https://discord.com/api/v10/oauth2/token",
                data=token_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded"
                },
            ) as token_response:
                if token_response.status != 200:
                    raise web.HTTPBadGateway(
                        text="Discord a refusé la connexion OAuth."
                    )
                token_payload = await token_response.json()

            access_token = str(token_payload.get("access_token") or "")
            async with session.get(
                "https://discord.com/api/v10/users/@me",
                headers={
                    "Authorization": f"Bearer {access_token}"
                },
            ) as user_response:
                if user_response.status != 200:
                    raise web.HTTPBadGateway(
                        text="Impossible de récupérer le compte Discord."
                    )
                discord_user = await user_response.json()

        discord_id = str(discord_user.get("id") or "")
        if not discord_id.isdigit():
            raise web.HTTPBadGateway(
                text="Discord n'a pas retourné d'identifiant valide."
            )

        payload = {
            "kind": "boss_session",
            "id": discord_id,
            "username": str(
                discord_user.get("global_name")
                or discord_user.get("username")
                or discord_id
            ),
            "csrf": secrets.token_urlsafe(24),
            "exp": int(time.time()) + SESSION_TTL_SECONDS,
        }

        response = web.HTTPSeeOther(location="/formats/boss")
        response.set_cookie(
            SESSION_COOKIE,
            self._sign(payload),
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=self._base_url(request).startswith("https://"),
            samesite="Lax",
            path="/",
        )
        raise response

    async def logout(self, request: web.Request) -> web.Response:
        response = web.HTTPSeeOther(location="/formats/boss")
        response.del_cookie(SESSION_COOKIE, path="/")
        raise response

    async def register(self, request: web.Request) -> web.Response:
        guild_id, user, member = await self._require_user(request)
        data = await request.post()
        if not self._csrf_ok(user, str(data.get("csrf") or "")):
            raise web.HTTPForbidden(
                text="Jeton de sécurité invalide. Recharge la page."
            )
        try:
            await self.service.register_challenger(
                guild_id,
                str(member.id),
                member.display_name,
            )
        except ValueError as exc:
            raise web.HTTPSeeOther(
                location="/formats/boss?error="
                + urlencode({"x": str(exc)})[2:]
            )
        raise web.HTTPSeeOther(
            location="/formats/boss?saved=1"
        )

    async def unregister(self, request: web.Request) -> web.Response:
        guild_id, user, member = await self._require_user(request)
        data = await request.post()
        if not self._csrf_ok(user, str(data.get("csrf") or "")):
            raise web.HTTPForbidden(
                text="Jeton de sécurité invalide. Recharge la page."
            )
        try:
            await self.service.unregister_challenger(
                guild_id,
                str(member.id),
            )
        except ValueError as exc:
            raise web.HTTPSeeOther(
                location="/formats/boss?error="
                + urlencode({"x": str(exc)})[2:]
            )
        raise web.HTTPSeeOther(
            location="/formats/boss?saved=1"
        )

    async def _require_staff(self, request: web.Request):
        guild_id, user, member = await self._require_user(request)
        if not await self._is_staff(
            guild_id,
            str(member.id),
        ):
            raise web.HTTPForbidden(
                text="Cette action est réservée au staff."
            )
        return guild_id, user, member

    async def staff_move(self, request: web.Request) -> web.Response:
        guild_id, user, _ = await self._require_staff(request)
        data = await request.post()
        if not self._csrf_ok(user, str(data.get("csrf") or "")):
            raise web.HTTPForbidden(text="Jeton de sécurité invalide.")

        challenger_id = int(data.get("challenger_id") or 0)
        position = int(data.get("position") or 0)
        challenger = await self.service.challenger_by_id(
            guild_id,
            challenger_id,
        )
        if not challenger:
            raise web.HTTPNotFound(text="Challenger introuvable.")

        await self.service.move_challenger(
            guild_id,
            str(challenger["discord_id"]),
            position,
        )
        raise web.HTTPSeeOther(
            location="/formats/boss?saved=1"
        )

    async def staff_schedule(self, request: web.Request) -> web.Response:
        guild_id, user, _ = await self._require_staff(request)
        data = await request.post()
        if not self._csrf_ok(user, str(data.get("csrf") or "")):
            raise web.HTTPForbidden(text="Jeton de sécurité invalide.")

        challenger_id = int(data.get("challenger_id") or 0)
        scheduled_at = str(data.get("scheduled_at") or "").strip()
        challenger = await self.service.challenger_by_id(
            guild_id,
            challenger_id,
        )
        if not challenger:
            raise web.HTTPNotFound(text="Challenger introuvable.")

        await self.service.schedule_challenger(
            guild_id,
            str(challenger["discord_id"]),
            scheduled_at,
        )
        raise web.HTTPSeeOther(
            location="/formats/boss?saved=1"
        )

    async def staff_remove(self, request: web.Request) -> web.Response:
        guild_id, user, _ = await self._require_staff(request)
        data = await request.post()
        if not self._csrf_ok(user, str(data.get("csrf") or "")):
            raise web.HTTPForbidden(text="Jeton de sécurité invalide.")

        challenger_id = int(data.get("challenger_id") or 0)
        challenger = await self.service.challenger_by_id(
            guild_id,
            challenger_id,
        )
        if not challenger:
            raise web.HTTPNotFound(text="Challenger introuvable.")

        await self.service.unregister_challenger(
            guild_id,
            str(challenger["discord_id"]),
            force=True,
        )
        raise web.HTTPSeeOther(
            location="/formats/boss?saved=1"
        )

    async def api(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        return web.json_response(
            await self.service.public_data(guild_id),
            headers={"Cache-Control": "no-store"},
        )


def register_boss_routes(
    application: web.Application,
    website_cog: Any,
) -> None:
    routes = BossRoutes(website_cog)
    application.router.add_get(
        "/formats/boss",
        routes.page,
    )
    application.router.add_get(
        "/formats/boss/login",
        routes.login,
    )
    application.router.add_get(
        "/formats/boss/oauth/callback",
        routes.oauth_callback,
    )
    application.router.add_get(
        "/formats/boss/logout",
        routes.logout,
    )
    application.router.add_post(
        "/formats/boss/register",
        routes.register,
    )
    application.router.add_post(
        "/formats/boss/unregister",
        routes.unregister,
    )
    application.router.add_post(
        "/formats/boss/staff/move",
        routes.staff_move,
    )
    application.router.add_post(
        "/formats/boss/staff/schedule",
        routes.staff_schedule,
    )
    application.router.add_post(
        "/formats/boss/staff/remove",
        routes.staff_remove,
    )
    application.router.add_get(
        "/api/formats/boss",
        routes.api,
    )
