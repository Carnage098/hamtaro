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

from services.team_directory_service import MAX_TEAM_IMAGE_BYTES, TeamDirectoryService


SESSION_COOKIE = "hamtaro_team_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600


class TeamRoutes:
    def __init__(self, website_cog: Any) -> None:
        self.website_cog = website_cog
        self.service = TeamDirectoryService()

    def guild_id(self, request: web.Request) -> str:
        requested = request.query.get("guild", "").strip()
        if requested.isdigit():
            return requested
        configured = (os.getenv("PUBLIC_GUILD_ID") or os.getenv("GUILD_ID") or "").strip()
        if configured.isdigit():
            return configured
        guilds = list(getattr(self.website_cog.bot, "guilds", []))
        if guilds:
            return str(guilds[0].id)
        raise ValueError("Aucun serveur public n'est configuré pour cette page.")

    def _session_secret(self) -> bytes:
        raw = (os.getenv("TEAM_WEB_SESSION_SECRET") or os.getenv("DISCORD_TOKEN") or "").strip()
        if not raw:
            raise RuntimeError("TEAM_WEB_SESSION_SECRET est manquant.")
        return hashlib.sha256(("hamtaro-team-session:" + raw).encode("utf-8")).digest()

    def _sign(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        signature = hmac.new(self._session_secret(), body.encode("ascii"), hashlib.sha256).digest()
        sig = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        return f"{body}.{sig}"

    def _unsign(self, value: str | None) -> dict[str, Any] | None:
        if not value or "." not in value:
            return None
        body, supplied = value.split(".", 1)
        expected_raw = hmac.new(self._session_secret(), body.encode("ascii"), hashlib.sha256).digest()
        expected = base64.urlsafe_b64encode(expected_raw).decode("ascii").rstrip("=")
        if not hmac.compare_digest(expected, supplied):
            return None
        try:
            padded = body + "=" * (-len(body) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
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
        configured = (os.getenv("DISCORD_CLIENT_ID") or os.getenv("APPLICATION_ID") or "").strip()
        if configured.isdigit():
            return configured
        user = getattr(self.website_cog.bot, "user", None)
        return str(user.id) if user is not None else ""

    def _oauth_client_secret(self) -> str:
        return (os.getenv("DISCORD_CLIENT_SECRET") or "").strip()

    def _safe_next(self, value: str | None) -> str:
        value = str(value or "/equipes").strip()
        if not value.startswith("/") or value.startswith("//"):
            return "/equipes"
        return value[:500]

    async def _is_staff(self, guild_id: str, discord_id: str) -> bool:
        bot = self.website_cog.bot
        guild = bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
        if guild is None:
            return False
        member = guild.get_member(int(discord_id)) if discord_id.isdigit() else None
        if member is None and discord_id.isdigit():
            try:
                member = await guild.fetch_member(int(discord_id))
            except Exception:
                member = None
        if member is None:
            return False

        configured_ids = {
            item.strip() for item in (os.getenv("STAFF_ROLE_IDS") or "").split(",") if item.strip().isdigit()
        }
        if configured_ids and any(str(role.id) in configured_ids for role in member.roles):
            return True

        role_names = {str(role.name).strip().casefold() for role in member.roles}
        accepted = {
            "admin", "administrator", "staff", "modo", "modérateur", "moderateur",
            "🛑modo", "🛑 modo", "arbitre",
        }
        return bool(role_names & accepted) or bool(getattr(member.guild_permissions, "administrator", False))

    async def _display_name(self, guild_id: str, discord_id: str, fallback: str | None) -> str:
        bot = self.website_cog.bot
        guild = bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
        if guild and discord_id.isdigit():
            member = guild.get_member(int(discord_id))
            if member is not None:
                return member.display_name
        return (fallback or discord_id).strip() or discord_id

    async def _prepare_team(self, guild_id: str, team: dict[str, Any], user: dict[str, Any] | None) -> dict[str, Any]:
        item = dict(team)
        item["member1_display"] = await self._display_name(
            guild_id, str(item["member1_id"]), item.get("member1_name")
        )
        item["member2_display"] = await self._display_name(
            guild_id, str(item["member2_id"]), item.get("member2_name")
        )
        if user:
            discord_id = str(user.get("id", ""))
            item["can_edit"] = (
                discord_id in {str(item["member1_id"]), str(item["member2_id"])}
                or await self._is_staff(guild_id, discord_id)
            )
        else:
            item["can_edit"] = False
        return item

    async def teams_redirect(self, request: web.Request) -> web.Response:
        raise web.HTTPPermanentRedirect(location="/equipes")

    async def teams_page(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        sync = await self.service.refresh_from_2v2(guild_id)
        user = self.current_user(request)
        teams = [
            await self._prepare_team(guild_id, team, user)
            for team in await self.service.rankings(guild_id)
        ]
        return self.website_cog.render(
            "teams.html",
            request=request,
            guild_id=guild_id,
            teams=teams,
            user=user,
            sync=sync,
        )

    async def team_detail(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        await self.service.refresh_from_2v2(guild_id)
        team_id = int(request.match_info["team_id"])
        team = await self.service.get_team(guild_id, team_id)
        if not team:
            raise web.HTTPNotFound(text="Équipe introuvable")
        user = self.current_user(request)
        team = await self._prepare_team(guild_id, team, user)
        rankings = await self.service.rankings(guild_id)
        rank = next((item["rank"] for item in rankings if int(item["id"]) == team_id), None)
        return self.website_cog.render(
            "team_detail.html",
            request=request,
            guild_id=guild_id,
            team=team,
            rank=rank,
            user=user,
            saved=request.query.get("saved") == "1",
            auth_error=request.query.get("auth_error") == "1",
        )

    async def image(self, request: web.Request) -> web.Response:
        team_id = int(request.match_info["team_id"])
        image = await self.service.get_image(team_id)
        if not image:
            raise web.HTTPNotFound(text="Image d'équipe introuvable")
        mime, data, digest = image
        return web.Response(
            body=data,
            content_type=mime,
            headers={
                "Cache-Control": "public, max-age=86400",
                "ETag": f'"{digest}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def login(self, request: web.Request) -> web.Response:
        client_id = self._oauth_client_id()
        client_secret = self._oauth_client_secret()
        if not client_id or not client_secret:
            raise web.HTTPServiceUnavailable(
                text=(
                    "Connexion Discord non configurée. Ajoute DISCORD_CLIENT_SECRET sur Railway "
                    "et l'URL de redirection /equipes/oauth/callback dans Discord Developer Portal."
                )
            )
        next_path = self._safe_next(request.query.get("next"))
        state = self._sign({
            "kind": "oauth_state",
            "next": next_path,
            "exp": int(time.time()) + 600,
            "nonce": secrets.token_urlsafe(12),
        })
        redirect_uri = self._base_url(request) + "/equipes/oauth/callback"
        params = urlencode({
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "identify",
            "state": state,
            "prompt": "none",
        })
        raise web.HTTPFound(location="https://discord.com/oauth2/authorize?" + params)

    async def oauth_callback(self, request: web.Request) -> web.Response:
        state = self._unsign(request.query.get("state"))
        if not state or state.get("kind") != "oauth_state":
            raise web.HTTPBadRequest(text="État OAuth invalide ou expiré.")
        code = (request.query.get("code") or "").strip()
        if not code:
            raise web.HTTPBadRequest(text="Code Discord manquant.")

        redirect_uri = self._base_url(request) + "/equipes/oauth/callback"
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
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as token_response:
                if token_response.status != 200:
                    raise web.HTTPBadGateway(text="Discord a refusé la connexion OAuth.")
                token_payload = await token_response.json()
            access_token = str(token_payload.get("access_token") or "")
            async with session.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            ) as user_response:
                if user_response.status != 200:
                    raise web.HTTPBadGateway(text="Impossible de récupérer le compte Discord.")
                discord_user = await user_response.json()

        discord_id = str(discord_user.get("id") or "")
        if not discord_id.isdigit():
            raise web.HTTPBadGateway(text="Discord n'a pas retourné d'identifiant valide.")
        payload = {
            "kind": "team_session",
            "id": discord_id,
            "username": str(discord_user.get("global_name") or discord_user.get("username") or discord_id),
            "csrf": secrets.token_urlsafe(24),
            "exp": int(time.time()) + SESSION_TTL_SECONDS,
        }
        response = web.HTTPSeeOther(location=self._safe_next(state.get("next")))
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
        response = web.HTTPSeeOther(location="/equipes")
        response.del_cookie(SESSION_COOKIE, path="/")
        raise response

    async def upload_image(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        team_id = int(request.match_info["team_id"])
        team = await self.service.get_team(guild_id, team_id)
        if not team:
            raise web.HTTPNotFound(text="Équipe introuvable")
        user = self.current_user(request)
        if not user:
            raise web.HTTPUnauthorized(text="Connecte-toi avec Discord pour modifier cette équipe.")
        discord_id = str(user.get("id", ""))
        member_allowed = discord_id in {str(team["member1_id"]), str(team["member2_id"])}
        staff_allowed = await self._is_staff(guild_id, discord_id)
        if not member_allowed and not staff_allowed:
            raise web.HTTPForbidden(text="Tu ne fais pas partie de cette équipe. Modification refusée.")

        reader = await request.multipart()
        csrf = ""
        image_data: bytes | None = None
        async for part in reader:
            if part.name == "csrf":
                csrf = (await part.text()).strip()
            elif part.name == "image":
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = await part.read_chunk(size=64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_TEAM_IMAGE_BYTES:
                        raise web.HTTPRequestEntityTooLarge(
                            max_size=MAX_TEAM_IMAGE_BYTES,
                            actual_size=total,
                        )
                    chunks.append(chunk)
                image_data = b"".join(chunks)

        expected_csrf = str(user.get("csrf", ""))
        if not csrf or not expected_csrf or not hmac.compare_digest(csrf, expected_csrf):
            raise web.HTTPForbidden(text="Jeton de sécurité invalide. Recharge la page.")
        if not image_data:
            raise web.HTTPBadRequest(text="Aucune image reçue.")

        try:
            await self.service.set_team_image(team_id, discord_id, image_data)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        raise web.HTTPSeeOther(location=f"/equipes/{team_id}?saved=1")

    async def api_teams(self, request: web.Request) -> web.Response:
        guild_id = self.guild_id(request)
        sync = await self.service.refresh_from_2v2(guild_id)
        rankings = await self.service.rankings(guild_id)
        safe_rankings = []
        for team in rankings:
            safe_rankings.append({
                "rank": team["rank"],
                "id": team["id"],
                "name": team["name"],
                "elo": team["elo"],
                "peak_elo": team["peak_elo"],
                "wins": team["wins"],
                "losses": team["losses"],
                "draws": team["draws"],
                "matches": team["matches"],
                "win_rate": team["win_rate"],
                "has_image": team["has_image"],
            })
        return web.json_response(
            {"guild_id": guild_id, "sync": sync, "teams": safe_rankings},
            headers={"Cache-Control": "no-store"},
        )


def register_team_routes(application: web.Application, website_cog: Any) -> None:
    routes = TeamRoutes(website_cog)
    application.router.add_get("/equipes", routes.teams_page)
    application.router.add_get("/teams", routes.teams_redirect)
    application.router.add_get(r"/equipes/{team_id:\d+}", routes.team_detail)
    application.router.add_get(r"/api/equipes/{team_id:\d+}/image", routes.image)
    application.router.add_post(r"/equipes/{team_id:\d+}/image", routes.upload_image)
    application.router.add_get("/equipes/login", routes.login)
    application.router.add_get("/equipes/oauth/callback", routes.oauth_callback)
    application.router.add_get("/equipes/logout", routes.logout)
    application.router.add_get("/api/equipes", routes.api_teams)
