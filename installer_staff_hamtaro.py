from __future__ import annotations

import py_compile
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


EMBEDDED_FILES = {'services/staff_dashboard_routes.py': 'from __future__ import annotations\n\nimport hashlib\nimport hmac\nimport json\nimport logging\nimport os\nimport time\nfrom collections import defaultdict, deque\nfrom typing import Any\n\nfrom aiohttp import web\n\nfrom services.staff_dashboard_service import StaffDashboardService\n\n\nLOGGER = logging.getLogger(__name__)\n\n_COOKIE_NAME = "hamtaro_staff_session"\n_LOGIN_WINDOW_SECONDS = 10 * 60\n_LOGIN_MAX_ATTEMPTS = 5\n_SESSION_MAX_AGE = 8 * 60 * 60\n\n\ndef _truthy(value: str | None, default: bool = False) -> bool:\n    if value is None:\n        return default\n    return value.strip().lower() not in {\n        "",\n        "0",\n        "false",\n        "no",\n        "off",\n        "disabled",\n    }\n\n\nclass StaffDashboardRoutes:\n    """\n    Routes du tableau de bord staff.\n\n    Ce contrôleur est enregistré directement dans l\'application aiohttp\n    créée par PublicWebsiteCog. Il ne dépend d\'aucun cog supplémentaire\n    ni d\'aucun ordre de chargement.\n    """\n\n    def __init__(self, website_cog: Any) -> None:\n        self.website = website_cog\n        self.bot = website_cog.bot\n        self.login_attempts: dict[str, deque[float]] = defaultdict(deque)\n\n    @staticmethod\n    def enabled() -> bool:\n        return _truthy(\n            os.getenv("STAFF_DASHBOARD_ENABLED"),\n            default=False,\n        )\n\n    @staticmethod\n    def secret() -> str:\n        return os.getenv("STAFF_DASHBOARD_TOKEN", "").strip()\n\n    @staticmethod\n    def session_digest(secret: str) -> str:\n        return hmac.new(\n            secret.encode("utf-8"),\n            b"hamtaro-staff-dashboard-session-v3",\n            hashlib.sha256,\n        ).hexdigest()\n\n    @staticmethod\n    def is_secure(request: web.Request) -> bool:\n        forwarded = request.headers.get("X-Forwarded-Proto", "")\n        forwarded_proto = forwarded.split(",", 1)[0].strip().lower()\n        return request.scheme == "https" or forwarded_proto == "https"\n\n    @staticmethod\n    def client_key(request: web.Request) -> str:\n        forwarded = request.headers.get("X-Forwarded-For", "")\n        forwarded_ip = forwarded.split(",", 1)[0].strip()\n        return forwarded_ip or request.remote or "unknown"\n\n    def authorized(self, request: web.Request) -> bool:\n        secret = self.secret()\n        if not self.enabled() or len(secret) < 24:\n            return False\n\n        supplied = request.cookies.get(_COOKIE_NAME, "")\n        expected = self.session_digest(secret)\n        return bool(supplied) and hmac.compare_digest(\n            supplied,\n            expected,\n        )\n\n    async def record_audit(\n        self,\n        *,\n        action: str,\n        details: dict[str, Any],\n    ) -> None:\n        try:\n            guild_id = self.website._public_guild_id() or "unknown"\n            await self.bot.db.execute(\n                """\n                INSERT INTO audit_logs (\n                    guild_id,\n                    actor_id,\n                    actor_name,\n                    action,\n                    entity_type,\n                    entity_id,\n                    details\n                ) VALUES (\n                    ?,\n                    NULL,\n                    \'Web\',\n                    ?,\n                    \'website\',\n                    \'staff-dashboard\',\n                    ?\n                )\n                """,\n                (\n                    guild_id,\n                    action,\n                    json.dumps(details, ensure_ascii=False),\n                ),\n            )\n            await self.bot.db.commit()\n        except Exception:\n            # L\'accès au tableau reste possible si le journal d\'audit\n            # n\'est momentanément pas disponible.\n            LOGGER.exception(\n                "Impossible d\'enregistrer l\'audit du tableau de bord staff."\n            )\n\n    async def staff_page(self, request: web.Request) -> web.Response:\n        if not self.enabled():\n            raise web.HTTPNotFound()\n\n        secret = self.secret()\n        if len(secret) < 24:\n            return self.website.render(\n                "staff_login.html",\n                request=request,\n                error=(\n                    "Le tableau de bord n\'est pas configuré. "\n                    "Définis STAFF_DASHBOARD_TOKEN avec au moins "\n                    "24 caractères."\n                ),\n                status_code=503,\n            )\n\n        if not self.authorized(request):\n            return self.website.render(\n                "staff_login.html",\n                request=request,\n                error=None,\n                status_code=200,\n            )\n\n        guild_id = self.website._public_guild_id()\n        if guild_id is None:\n            return self.website.render(\n                "error.html",\n                request=request,\n                status=503,\n                title="Serveur Discord indisponible",\n                message=(\n                    "Aucun GUILD_ID ou PUBLIC_GUILD_ID valide "\n                    "n\'est configuré."\n                ),\n                status_code=503,\n            )\n\n        overview = await StaffDashboardService(self.bot).overview(guild_id)\n\n        try:\n            refresh_seconds = max(\n                5,\n                int(\n                    os.getenv(\n                        "LIVE_SITE_REFRESH_SECONDS",\n                        "15",\n                    )\n                    or "15"\n                ),\n            )\n        except ValueError:\n            refresh_seconds = 15\n\n        return self.website.render(\n            "staff_dashboard.html",\n            request=request,\n            overview=overview,\n            refresh_seconds=refresh_seconds,\n        )\n\n    async def staff_login(self, request: web.Request) -> web.Response:\n        if not self.enabled():\n            raise web.HTTPNotFound()\n\n        secret = self.secret()\n        if len(secret) < 24:\n            return self.website.render(\n                "staff_login.html",\n                request=request,\n                error=(\n                    "Le tableau de bord n\'est pas configuré. "\n                    "Définis STAFF_DASHBOARD_TOKEN avec au moins "\n                    "24 caractères."\n                ),\n                status_code=503,\n            )\n\n        now = time.monotonic()\n        client = self.client_key(request)\n        queue = self.login_attempts[client]\n\n        while queue and now - queue[0] > _LOGIN_WINDOW_SECONDS:\n            queue.popleft()\n\n        if len(queue) >= _LOGIN_MAX_ATTEMPTS:\n            return self.website.render(\n                "staff_login.html",\n                request=request,\n                error=(\n                    "Trop de tentatives. "\n                    "Réessaie dans quelques minutes."\n                ),\n                status_code=429,\n            )\n\n        form = await request.post()\n        provided = str(form.get("token", "")).strip()\n\n        if not hmac.compare_digest(provided, secret):\n            queue.append(now)\n            await self.record_audit(\n                action="staff_dashboard_login_failed",\n                details={"remote": client},\n            )\n            return self.website.render(\n                "staff_login.html",\n                request=request,\n                error="Jeton incorrect.",\n                status_code=401,\n            )\n\n        queue.clear()\n\n        response = web.HTTPSeeOther(location="/staff")\n        response.set_cookie(\n            _COOKIE_NAME,\n            self.session_digest(secret),\n            max_age=_SESSION_MAX_AGE,\n            httponly=True,\n            secure=self.is_secure(request),\n            samesite="Strict",\n            path="/staff",\n        )\n\n        await self.record_audit(\n            action="staff_dashboard_login_success",\n            details={"remote": client},\n        )\n        return response\n\n    async def staff_logout(self, request: web.Request) -> web.Response:\n        response = web.HTTPSeeOther(location="/staff")\n        response.del_cookie(_COOKIE_NAME, path="/staff")\n        return response\n\n    async def overview_api(\n        self,\n        request: web.Request,\n    ) -> web.Response:\n        if not self.enabled():\n            raise web.HTTPNotFound()\n\n        if not self.authorized(request):\n            raise web.HTTPUnauthorized(\n                text="Session staff absente ou expirée.",\n                content_type="text/plain",\n            )\n\n        guild_id = self.website._public_guild_id()\n        if guild_id is None:\n            raise web.HTTPServiceUnavailable(\n                text="Serveur Discord non configuré.",\n                content_type="text/plain",\n            )\n\n        overview = await StaffDashboardService(self.bot).overview(guild_id)\n        return web.json_response(\n            overview,\n            headers={"Cache-Control": "no-store"},\n        )\n\n    async def live_tournaments_api(\n        self,\n        request: web.Request,\n    ) -> web.Response:\n        tournaments = await self.website.service.list_tournaments(limit=100)\n        normalized: list[dict[str, Any]] = []\n\n        for raw in tournaments:\n            item = dict(raw)\n            normalized.append(\n                {\n                    "id": item.get("id"),\n                    "code": item.get("code"),\n                    "name": item.get("name"),\n                    "format": item.get("format"),\n                    "status": item.get("status"),\n                    "participant_count": int(\n                        item.get("participant_count") or 0\n                    ),\n                    "max_players": int(\n                        item.get("max_players") or 0\n                    ),\n                    "current_round": int(\n                        item.get("current_round") or 0\n                    ),\n                    "total_rounds": int(\n                        item.get("total_rounds") or 0\n                    ),\n                    "updated_at": (\n                        item.get("updated_at")\n                        or item.get("created_at")\n                    ),\n                }\n            )\n\n        return web.json_response(\n            {\n                "tournaments": normalized,\n                "generated_at": int(time.time()),\n            },\n            headers={"Cache-Control": "no-store"},\n        )\n\n\ndef _route_exists(application: web.Application, path: str) -> bool:\n    for resource in application.router.resources():\n        if getattr(resource, "canonical", None) == path:\n            return True\n    return False\n\n\ndef register_staff_dashboard_routes(\n    application: web.Application,\n    website_cog: Any,\n) -> StaffDashboardRoutes:\n    """\n    Enregistre les routes directement dans l\'application du site.\n\n    Cette fonction doit être appelée dans PublicWebsiteCog._start_server()\n    avant l\'ajout de la route statique. Elle ne redémarre jamais le site.\n    """\n    controller = StaffDashboardRoutes(website_cog)\n    application["hamtaro_staff_dashboard"] = controller\n\n    routes = (\n        ("GET", "/api/tournaments/live.json", controller.live_tournaments_api),\n        ("GET", "/staff", controller.staff_page),\n        ("POST", "/staff/login", controller.staff_login),\n        ("POST", "/staff/logout", controller.staff_logout),\n        ("GET", "/staff/logout", controller.staff_logout),\n        ("GET", "/staff/api/overview", controller.overview_api),\n    )\n\n    for method, path, handler in routes:\n        if _route_exists(application, path):\n            LOGGER.warning(\n                "Route déjà présente, enregistrement ignoré : %s %s",\n                method,\n                path,\n            )\n            continue\n\n        application.router.add_route(\n            method,\n            path,\n            handler,\n        )\n\n    LOGGER.info(\n        "Routes staff intégrées directement au site public : "\n        "/staff, /staff/login, /staff/api/overview."\n    )\n    return controller\n', 'services/staff_dashboard_service.py': 'from __future__ import annotations\n\nimport logging\nimport time\nfrom typing import Any, Sequence\n\nLOGGER = logging.getLogger(__name__)\n\n\nclass StaffDashboardService:\n    """Prépare les données en lecture seule du tableau de bord staff."""\n\n    def __init__(self, bot) -> None:\n        self.bot = bot\n        self.db = bot.db\n\n    async def _table_exists(self, table_name: str) -> bool:\n        value = await self.db.fetchval(\n            """\n            SELECT 1\n            FROM sqlite_master\n            WHERE type = \'table\' AND name = ?\n            LIMIT 1\n            """,\n            (table_name,),\n        )\n        return bool(value)\n\n    async def _safe_fetchall(\n        self,\n        query: str,\n        parameters: Sequence[Any] = (),\n    ) -> list[dict[str, Any]]:\n        try:\n            rows = await self.db.fetchall(query, parameters)\n            return [dict(row) for row in rows]\n        except Exception:\n            LOGGER.exception("Requête du tableau de bord staff impossible.")\n            return []\n\n    async def _safe_count(\n        self,\n        query: str,\n        parameters: Sequence[Any] = (),\n    ) -> int:\n        try:\n            return int(await self.db.fetchval(query, parameters) or 0)\n        except Exception:\n            LOGGER.exception("Compteur du tableau de bord staff impossible.")\n            return 0\n\n    async def overview(self, guild_id: str) -> dict[str, Any]:\n        active_tournaments = await self._safe_fetchall(\n            """\n            SELECT\n                t.id,\n                t.code,\n                t.name,\n                t.format,\n                t.status,\n                t.max_players,\n                t.current_round,\n                t.total_rounds,\n                t.created_at,\n                COUNT(r.id) AS participant_count\n            FROM tournaments t\n            LEFT JOIN registrations r ON r.tournament_id = t.id\n            WHERE t.guild_id = ?\n              AND LOWER(COALESCE(t.status, \'\')) NOT IN (\n                  \'finished\', \'completed\', \'ended\', \'archived\', \'cancelled\'\n              )\n            GROUP BY t.id\n            ORDER BY t.created_at DESC, t.id DESC\n            LIMIT 30\n            """,\n            (guild_id,),\n        )\n\n        pending_results: list[dict[str, Any]] = []\n        if await self._table_exists("result_requests"):\n            pending_results = await self._safe_fetchall(\n                """\n                SELECT\n                    rr.match_kind,\n                    rr.match_id,\n                    rr.tournament_id,\n                    rr.player1_score,\n                    rr.player2_score,\n                    rr.status,\n                    rr.created_at,\n                    t.code AS tournament_code,\n                    t.name AS tournament_name\n                FROM result_requests rr\n                JOIN tournaments t ON t.id = rr.tournament_id\n                WHERE rr.guild_id = ?\n                  AND rr.status IN (\n                      \'pending\', \'confirmed\', \'contested\', \'processing\'\n                  )\n                ORDER BY\n                    CASE rr.status\n                        WHEN \'contested\' THEN 0\n                        WHEN \'confirmed\' THEN 1\n                        WHEN \'pending\' THEN 2\n                        ELSE 3\n                    END,\n                    rr.created_at ASC\n                LIMIT 50\n                """,\n                (guild_id,),\n            )\n\n        recent_audit: list[dict[str, Any]] = []\n        if await self._table_exists("audit_logs"):\n            recent_audit = await self._safe_fetchall(\n                """\n                SELECT\n                    id,\n                    actor_id,\n                    actor_name,\n                    action,\n                    entity_type,\n                    entity_id,\n                    tournament_id,\n                    details,\n                    created_at\n                FROM audit_logs\n                WHERE guild_id = ?\n                ORDER BY id DESC\n                LIMIT 30\n                """,\n                (guild_id,),\n            )\n\n        invalid_matches = await self._safe_fetchall(\n            """\n            SELECT\n                m.id,\n                m.tournament_id,\n                t.code AS tournament_code,\n                m.round,\n                m.match_number,\n                m.status,\n                m.player1_name,\n                m.player2_name,\n                m.winner_name\n            FROM matches m\n            JOIN tournaments t ON t.id = m.tournament_id\n            WHERE t.guild_id = ?\n              AND (\n                    (\n                        m.player1_id IS NOT NULL\n                        AND m.player2_id IS NOT NULL\n                        AND m.player1_id = m.player2_id\n                    )\n                 OR (\n                        m.status IN (\'validated\', \'completed\')\n                        AND COALESCE(m.is_bye, 0) = 0\n                        AND m.winner_id IS NULL\n                    )\n                 OR (\n                        m.winner_id IS NOT NULL\n                        AND m.winner_id NOT IN (m.player1_id, m.player2_id)\n                    )\n              )\n            ORDER BY m.id DESC\n            LIMIT 30\n            """,\n            (guild_id,),\n        )\n\n        totals = {\n            "active_tournaments": len(active_tournaments),\n            "registrations": await self._safe_count(\n                """\n                SELECT COUNT(*)\n                FROM registrations r\n                JOIN tournaments t ON t.id = r.tournament_id\n                WHERE t.guild_id = ?\n                """,\n                (guild_id,),\n            ),\n            "pending_results": len(pending_results),\n            "invalid_matches": len(invalid_matches),\n        }\n\n        return {\n            "totals": totals,\n            "active_tournaments": active_tournaments,\n            "pending_results": pending_results,\n            "recent_audit": recent_audit,\n            "invalid_matches": invalid_matches,\n            "generated_at": int(time.time()),\n        }\n', 'web/templates/staff_login.html': '{% extends "base.html" %}\n\n{% block title %}Connexion staff · Hamtaro{% endblock %}\n\n{% block content %}\n<section class="professional-panel professional-login">\n    <div>\n        <p class="professional-eyebrow">ACCÈS PROTÉGÉ</p>\n        <h1>Tableau de bord staff</h1>\n        <p>\n            Entre le jeton défini dans la variable Railway\n            <code>STAFF_DASHBOARD_TOKEN</code>.\n        </p>\n    </div>\n\n    {% if error %}\n    <div class="professional-alert professional-alert-error" role="alert">\n        {{ error }}\n    </div>\n    {% endif %}\n\n    <form method="post" action="/staff/login" class="professional-form">\n        <label for="staff-token">Jeton d’accès</label>\n        <input\n            id="staff-token"\n            name="token"\n            type="password"\n            autocomplete="current-password"\n            minlength="24"\n            required\n        >\n        <button type="submit">Ouvrir le tableau de bord</button>\n    </form>\n</section>\n{% endblock %}\n', 'web/templates/staff_dashboard.html': '{% extends "base.html" %}\n\n{% block title %}Tableau de bord staff · Hamtaro{% endblock %}\n\n{% block content %}\n<section\n    class="professional-dashboard"\n    data-staff-dashboard\n    data-refresh-url="/staff/api/overview"\n    data-refresh-seconds="{{ refresh_seconds }}"\n>\n    <header class="professional-dashboard-header">\n        <div>\n            <p class="professional-eyebrow">HAMTARO STAFF</p>\n            <h1>Tableau de bord du tournoi</h1>\n            <p>\n                Vue protégée des tournois actifs, résultats en attente,\n                incohérences et dernières actions sensibles.\n            </p>\n        </div>\n\n        <form method="post" action="/staff/logout">\n            <button\n                class="professional-button-secondary"\n                type="submit"\n            >\n                Se déconnecter\n            </button>\n        </form>\n    </header>\n\n    <div class="professional-live-line" aria-live="polite">\n        <span class="professional-live-dot"></span>\n        <span data-staff-last-update>\n            Mise à jour automatique toutes les\n            {{ refresh_seconds }} secondes\n        </span>\n    </div>\n\n    <section class="professional-stat-grid" data-staff-stats>\n        <article>\n            <strong>{{ overview.totals.active_tournaments }}</strong>\n            <span>Tournois actifs</span>\n        </article>\n        <article>\n            <strong>{{ overview.totals.registrations }}</strong>\n            <span>Inscriptions enregistrées</span>\n        </article>\n        <article>\n            <strong>{{ overview.totals.pending_results }}</strong>\n            <span>Résultats en attente</span>\n        </article>\n        <article class="{% if overview.totals.invalid_matches %}is-danger{% endif %}">\n            <strong>{{ overview.totals.invalid_matches }}</strong>\n            <span>Matchs incohérents</span>\n        </article>\n    </section>\n\n    <div class="professional-dashboard-grid">\n        <section class="professional-card">\n            <h2>Tournois actifs</h2>\n            <div class="professional-table-wrap">\n                <table>\n                    <thead>\n                        <tr>\n                            <th>Code</th>\n                            <th>Nom</th>\n                            <th>Format</th>\n                            <th>Statut</th>\n                            <th>Joueurs</th>\n                            <th>Ronde</th>\n                        </tr>\n                    </thead>\n                    <tbody data-staff-tournaments>\n                    {% for tournament in overview.active_tournaments %}\n                        <tr>\n                            <td><code>{{ tournament.code }}</code></td>\n                            <td>{{ tournament.name }}</td>\n                            <td>{{ tournament.format }}</td>\n                            <td>{{ tournament.status }}</td>\n                            <td>\n                                {{ tournament.participant_count }}/{{ tournament.max_players }}\n                            </td>\n                            <td>\n                                {{ tournament.current_round }}/{{ tournament.total_rounds }}\n                            </td>\n                        </tr>\n                    {% else %}\n                        <tr>\n                            <td colspan="6">Aucun tournoi actif.</td>\n                        </tr>\n                    {% endfor %}\n                    </tbody>\n                </table>\n            </div>\n        </section>\n\n        <section class="professional-card">\n            <h2>Résultats en attente</h2>\n            <div class="professional-table-wrap">\n                <table>\n                    <thead>\n                        <tr>\n                            <th>Tournoi</th>\n                            <th>Match</th>\n                            <th>Score</th>\n                            <th>Statut</th>\n                        </tr>\n                    </thead>\n                    <tbody data-staff-results>\n                    {% for result in overview.pending_results %}\n                        <tr>\n                            <td><code>{{ result.tournament_code }}</code></td>\n                            <td>{{ result.match_kind }}:{{ result.match_id }}</td>\n                            <td>\n                                {{ result.player1_score }}-{{ result.player2_score }}\n                            </td>\n                            <td>{{ result.status }}</td>\n                        </tr>\n                    {% else %}\n                        <tr>\n                            <td colspan="4">Aucun résultat en attente.</td>\n                        </tr>\n                    {% endfor %}\n                    </tbody>\n                </table>\n            </div>\n            <p class="professional-hint">\n                Les validations restent effectuées dans Discord afin de\n                conserver l’identité du membre du staff.\n            </p>\n        </section>\n\n        <section class="professional-card">\n            <h2>Incohérences détectées</h2>\n            <div data-staff-invalid>\n            {% for match in overview.invalid_matches %}\n                <article class="professional-issue">\n                    <strong>\n                        {{ match.tournament_code }} · Match #{{ match.id }}\n                    </strong>\n                    <span>\n                        {{ match.player1_name or "?" }}\n                        contre\n                        {{ match.player2_name or "?" }}\n                    </span>\n                    <code>{{ match.status }}</code>\n                </article>\n            {% else %}\n                <p>Aucune incohérence détectée.</p>\n            {% endfor %}\n            </div>\n        </section>\n\n        <section class="professional-card">\n            <h2>Journal d’audit</h2>\n            <div data-staff-audit>\n            {% for entry in overview.recent_audit %}\n                <article class="professional-audit-entry">\n                    <strong>{{ entry.action }}</strong>\n                    <span>\n                        {{ entry.actor_name or entry.actor_id or "Système" }}\n                    </span>\n                    <time>{{ entry.created_at }}</time>\n                </article>\n            {% else %}\n                <p>Aucune action enregistrée.</p>\n            {% endfor %}\n            </div>\n        </section>\n    </div>\n</section>\n\n<script src="/static/staff_dashboard.js" defer></script>\n{% endblock %}\n', 'web/static/staff_dashboard.js': '(() => {\n    "use strict";\n\n    const dashboard = document.querySelector("[data-staff-dashboard]");\n    if (!dashboard) {\n        return;\n    }\n\n    const refreshUrl =\n        dashboard.dataset.refreshUrl || "/staff/api/overview";\n\n    const configuredSeconds = Number.parseInt(\n        dashboard.dataset.refreshSeconds || "15",\n        10\n    );\n\n    const refreshMilliseconds =\n        Math.max(\n            5,\n            Number.isFinite(configuredSeconds)\n                ? configuredSeconds\n                : 15\n        ) * 1000;\n\n    const updateLabel = document.querySelector(\n        "[data-staff-last-update]"\n    );\n    const liveDot = document.querySelector(\n        ".professional-live-dot"\n    );\n\n    let running = false;\n\n    const text = (value, fallback = "") =>\n        String(value ?? fallback);\n\n    const replaceRows = (\n        selector,\n        rows,\n        emptyMessage,\n        columnCount\n    ) => {\n        const body = document.querySelector(selector);\n        if (!body) {\n            return;\n        }\n\n        body.replaceChildren();\n\n        if (!rows.length) {\n            const row = document.createElement("tr");\n            const cell = document.createElement("td");\n            cell.colSpan = columnCount;\n            cell.textContent = emptyMessage;\n            row.append(cell);\n            body.append(row);\n            return;\n        }\n\n        rows.forEach((values) => {\n            const row = document.createElement("tr");\n\n            values.forEach((value, index) => {\n                const cell = document.createElement("td");\n\n                if (index === 0) {\n                    const code = document.createElement("code");\n                    code.textContent = text(value);\n                    cell.append(code);\n                } else {\n                    cell.textContent = text(value, "—");\n                }\n\n                row.append(cell);\n            });\n\n            body.append(row);\n        });\n    };\n\n    const replaceCards = (\n        selector,\n        rows,\n        emptyMessage,\n        builder\n    ) => {\n        const container = document.querySelector(selector);\n        if (!container) {\n            return;\n        }\n\n        container.replaceChildren();\n\n        if (!rows.length) {\n            const paragraph = document.createElement("p");\n            paragraph.textContent = emptyMessage;\n            container.append(paragraph);\n            return;\n        }\n\n        rows.forEach((item) => {\n            container.append(builder(item));\n        });\n    };\n\n    const markStatus = (ok, label) => {\n        if (liveDot) {\n            liveDot.classList.toggle("is-error", !ok);\n        }\n\n        if (updateLabel) {\n            updateLabel.textContent = label;\n        }\n    };\n\n    const refresh = async () => {\n        if (running || document.hidden) {\n            return;\n        }\n\n        running = true;\n\n        try {\n            const response = await fetch(refreshUrl, {\n                cache: "no-store",\n                credentials: "same-origin",\n                headers: {\n                    "Accept": "application/json",\n                },\n            });\n\n            if (response.status === 401) {\n                window.location.assign("/staff");\n                return;\n            }\n\n            if (!response.ok) {\n                markStatus(\n                    false,\n                    "Mise à jour momentanément indisponible"\n                );\n                return;\n            }\n\n            const data = await response.json();\n            const totals = data.totals || {};\n\n            const statValues = document.querySelectorAll(\n                "[data-staff-stats] article strong"\n            );\n\n            const orderedTotals = [\n                totals.active_tournaments,\n                totals.registrations,\n                totals.pending_results,\n                totals.invalid_matches,\n            ];\n\n            statValues.forEach((element, index) => {\n                element.textContent = text(\n                    orderedTotals[index],\n                    0\n                );\n            });\n\n            replaceRows(\n                "[data-staff-tournaments]",\n                (data.active_tournaments || []).map((item) => [\n                    item.code,\n                    item.name,\n                    item.format,\n                    item.status,\n                    `${item.participant_count || 0}/${item.max_players || 0}`,\n                    `${item.current_round || 0}/${item.total_rounds || 0}`,\n                ]),\n                "Aucun tournoi actif.",\n                6\n            );\n\n            replaceRows(\n                "[data-staff-results]",\n                (data.pending_results || []).map((item) => [\n                    item.tournament_code,\n                    `${item.match_kind}:${item.match_id}`,\n                    `${item.player1_score || 0}–${item.player2_score || 0}`,\n                    item.status,\n                ]),\n                "Aucun résultat en attente.",\n                4\n            );\n\n            replaceCards(\n                "[data-staff-invalid]",\n                data.invalid_matches || [],\n                "Aucune incohérence détectée.",\n                (item) => {\n                    const article =\n                        document.createElement("article");\n                    article.className = "professional-issue";\n\n                    const strong =\n                        document.createElement("strong");\n                    strong.textContent =\n                        `${text(item.tournament_code)} · ` +\n                        `Match #${text(item.id)}`;\n\n                    const span =\n                        document.createElement("span");\n                    span.textContent =\n                        `${text(item.player1_name, "?")} ` +\n                        `contre ${text(item.player2_name, "?")}`;\n\n                    const code =\n                        document.createElement("code");\n                    code.textContent = text(item.status);\n\n                    article.append(strong, span, code);\n                    return article;\n                }\n            );\n\n            replaceCards(\n                "[data-staff-audit]",\n                data.recent_audit || [],\n                "Aucune action enregistrée.",\n                (item) => {\n                    const article =\n                        document.createElement("article");\n                    article.className =\n                        "professional-audit-entry";\n\n                    const strong =\n                        document.createElement("strong");\n                    strong.textContent =\n                        text(item.action, "Action");\n\n                    const actor =\n                        document.createElement("span");\n                    actor.textContent = text(\n                        item.actor_name || item.actor_id,\n                        "Système"\n                    );\n\n                    const date =\n                        document.createElement("time");\n                    date.textContent =\n                        text(item.created_at);\n\n                    article.append(strong, actor, date);\n                    return article;\n                }\n            );\n\n            markStatus(\n                true,\n                `Mis à jour à ${\n                    new Date().toLocaleTimeString("fr-FR")\n                }`\n            );\n        } catch (error) {\n            console.debug(\n                "Tableau de bord staff indisponible.",\n                error\n            );\n            markStatus(\n                false,\n                "Connexion au tableau de bord interrompue"\n            );\n        } finally {\n            running = false;\n        }\n    };\n\n    window.setInterval(refresh, refreshMilliseconds);\n    window.addEventListener("focus", refresh);\n\n    document.addEventListener(\n        "visibilitychange",\n        () => {\n            if (!document.hidden) {\n                refresh();\n            }\n        }\n    );\n})();\n', 'web/static/professional.css': '.staff-auth-shell {\n    min-height: 58vh;\n    display: grid;\n    place-items: center;\n    padding: 2rem 0;\n}\n\n.staff-auth-card,\n.staff-panel,\n.staff-stat-grid article {\n    border: 1px solid rgba(148, 163, 184, 0.22);\n    background: linear-gradient(\n        145deg,\n        rgba(15, 23, 42, 0.94),\n        rgba(2, 6, 23, 0.86)\n    );\n    box-shadow: 0 20px 55px rgba(2, 6, 23, 0.26);\n}\n\n.staff-auth-card {\n    width: min(100%, 560px);\n    border-radius: 24px;\n    padding: clamp(1.4rem, 4vw, 2.4rem);\n}\n\n.staff-auth-icon {\n    width: 3.25rem;\n    height: 3.25rem;\n    display: grid;\n    place-items: center;\n    margin-bottom: 1rem;\n    border-radius: 16px;\n    font-size: 1.55rem;\n    background: rgba(245, 158, 11, 0.16);\n    border: 1px solid rgba(245, 158, 11, 0.34);\n}\n\n.staff-eyebrow {\n    margin: 0 0 0.45rem;\n    color: #fbbf24;\n    font-size: 0.76rem;\n    font-weight: 900;\n    letter-spacing: 0.18em;\n}\n\n.staff-auth-card h1,\n.staff-dashboard-header h1 {\n    margin: 0;\n}\n\n.staff-auth-description,\n.staff-security-note,\n.staff-hint {\n    color: rgba(226, 232, 240, 0.76);\n}\n\n.staff-auth-form {\n    display: grid;\n    gap: 0.8rem;\n    margin-top: 1.5rem;\n}\n\n.staff-auth-form label {\n    font-weight: 800;\n}\n\n.staff-auth-form input {\n    width: 100%;\n    box-sizing: border-box;\n    padding: 0.95rem 1rem;\n    border-radius: 13px;\n    border: 1px solid rgba(148, 163, 184, 0.38);\n    background: rgba(2, 6, 23, 0.76);\n    color: inherit;\n    outline: none;\n}\n\n.staff-auth-form input:focus {\n    border-color: rgba(245, 158, 11, 0.8);\n    box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.12);\n}\n\n.staff-auth-form button,\n.staff-secondary-button {\n    border: 0;\n    border-radius: 13px;\n    padding: 0.9rem 1rem;\n    font-weight: 900;\n    cursor: pointer;\n}\n\n.staff-auth-form button {\n    background: linear-gradient(135deg, #fbbf24, #f59e0b);\n    color: #111827;\n}\n\n.staff-secondary-button {\n    background: rgba(148, 163, 184, 0.16);\n    color: inherit;\n    border: 1px solid rgba(148, 163, 184, 0.24);\n}\n\n.staff-security-note {\n    margin: 1rem 0 0;\n    font-size: 0.84rem;\n}\n\n.staff-alert {\n    margin-top: 1rem;\n    padding: 0.9rem 1rem;\n    border-radius: 13px;\n}\n\n.staff-alert-error {\n    background: rgba(220, 38, 38, 0.14);\n    border: 1px solid rgba(248, 113, 113, 0.38);\n    color: #fecaca;\n}\n\n.staff-dashboard {\n    display: grid;\n    gap: 1.2rem;\n}\n\n.staff-dashboard-header {\n    display: flex;\n    align-items: flex-start;\n    justify-content: space-between;\n    gap: 1rem;\n}\n\n.staff-dashboard-header p:last-child {\n    margin-bottom: 0;\n    color: rgba(226, 232, 240, 0.74);\n}\n\n.staff-live-line {\n    display: flex;\n    align-items: center;\n    gap: 0.6rem;\n    font-size: 0.9rem;\n    color: rgba(226, 232, 240, 0.75);\n}\n\n.staff-live-dot {\n    width: 0.72rem;\n    height: 0.72rem;\n    flex: 0 0 auto;\n    border-radius: 999px;\n    background: #22c55e;\n    box-shadow: 0 0 0 0.32rem rgba(34, 197, 94, 0.12);\n}\n\n.staff-live-dot.is-error {\n    background: #ef4444;\n    box-shadow: 0 0 0 0.32rem rgba(239, 68, 68, 0.12);\n}\n\n.staff-stat-grid {\n    display: grid;\n    grid-template-columns: repeat(4, minmax(0, 1fr));\n    gap: 1rem;\n}\n\n.staff-stat-grid article {\n    display: grid;\n    gap: 0.25rem;\n    padding: 1.15rem;\n    border-radius: 18px;\n}\n\n.staff-stat-grid strong {\n    font-size: clamp(1.7rem, 4vw, 2.25rem);\n}\n\n.staff-stat-grid span {\n    color: rgba(226, 232, 240, 0.72);\n}\n\n.staff-stat-grid article.is-danger {\n    border-color: rgba(248, 113, 113, 0.62);\n}\n\n.staff-dashboard-grid {\n    display: grid;\n    grid-template-columns: repeat(2, minmax(0, 1fr));\n    gap: 1rem;\n}\n\n.staff-panel {\n    min-width: 0;\n    padding: 1.2rem;\n    border-radius: 20px;\n}\n\n.staff-panel-wide {\n    grid-column: 1 / -1;\n}\n\n.staff-panel-heading {\n    display: flex;\n    align-items: baseline;\n    justify-content: space-between;\n    gap: 1rem;\n    margin-bottom: 0.9rem;\n}\n\n.staff-panel-heading h2 {\n    margin: 0;\n}\n\n.staff-panel-heading > span {\n    font-size: 0.84rem;\n    color: rgba(226, 232, 240, 0.64);\n}\n\n.staff-table-wrap {\n    overflow-x: auto;\n}\n\n.staff-panel table {\n    width: 100%;\n    border-collapse: collapse;\n}\n\n.staff-panel th,\n.staff-panel td {\n    padding: 0.7rem 0.6rem;\n    text-align: left;\n    border-bottom: 1px solid rgba(148, 163, 184, 0.15);\n    white-space: nowrap;\n}\n\n.staff-panel th {\n    color: rgba(226, 232, 240, 0.66);\n    font-size: 0.76rem;\n    letter-spacing: 0.06em;\n    text-transform: uppercase;\n}\n\n.staff-panel a {\n    color: inherit;\n}\n\n.staff-issue,\n.staff-audit-entry {\n    padding: 0.78rem 0;\n    border-bottom: 1px solid rgba(148, 163, 184, 0.15);\n}\n\n.staff-issue {\n    display: grid;\n    gap: 0.28rem;\n}\n\n.staff-issue code,\n.staff-audit-entry time,\n.staff-hint {\n    font-size: 0.84rem;\n}\n\n.staff-audit-entry {\n    display: flex;\n    align-items: center;\n    justify-content: space-between;\n    gap: 1rem;\n}\n\n.staff-audit-entry > div {\n    display: grid;\n    gap: 0.2rem;\n}\n\n.staff-audit-entry span,\n.staff-audit-entry time,\n.staff-hint {\n    color: rgba(226, 232, 240, 0.64);\n}\n\n.staff-empty-success {\n    color: #86efac;\n}\n\n@media (max-width: 900px) {\n    .staff-stat-grid,\n    .staff-dashboard-grid {\n        grid-template-columns: 1fr 1fr;\n    }\n}\n\n@media (max-width: 650px) {\n    .staff-dashboard-header,\n    .staff-audit-entry {\n        display: grid;\n    }\n\n    .staff-stat-grid,\n    .staff-dashboard-grid {\n        grid-template-columns: 1fr;\n    }\n\n    .staff-panel-wide {\n        grid-column: auto;\n    }\n}\n'}


class InstallationError(RuntimeError):
    pass


def backup_file(path: Path, project_root: Path, backup_root: Path) -> None:
    if not path.exists():
        return

    relative = path.relative_to(project_root)
    destination = backup_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)


def write_embedded_files(project_root: Path, backup_root: Path) -> None:
    for relative, content in EMBEDDED_FILES.items():
        destination = project_root / relative
        backup_file(destination, project_root, backup_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def patch_public_website(path: Path) -> None:
    if not path.exists():
        raise InstallationError("cogs/public_website.py est introuvable.")

    text = path.read_text(encoding="utf-8")

    import_block = (
        "from services.staff_dashboard_routes import (\n"
        "    register_staff_dashboard_routes,\n"
        ")\n"
    )

    if "from services.staff_dashboard_routes import" not in text:
        marker = "LOGGER = logging.getLogger(__name__)"
        if marker not in text:
            raise InstallationError(
                "Impossible de trouver LOGGER dans cogs/public_website.py."
            )
        text = text.replace(marker, import_block + "\n" + marker, 1)

    if "HAMTARO_SITE_BUILD =" in text:
        text = re.sub(
            r'HAMTARO_SITE_BUILD\s*=\s*"[^"]*"',
            'HAMTARO_SITE_BUILD = "staff-integrated-2026-08-05-v2"',
            text,
            count=1,
        )
    else:
        marker = "LOGGER = logging.getLogger(__name__)"
        text = text.replace(
            marker,
            marker + '\nHAMTARO_SITE_BUILD = "staff-integrated-2026-08-05-v2"',
            1,
        )

    route_call = (
        "\n"
        "        # Tableau de bord staff intégré directement au site.\n"
        "        # Aucun autre cog ni ordre de chargement n'est nécessaire.\n"
        "        register_staff_dashboard_routes(\n"
        "            application,\n"
        "            self,\n"
        "        )\n"
    )

    code_without_import = text.replace(import_block, "", 1)

    if "register_staff_dashboard_routes(" not in code_without_import:
        marker = '        application.router.add_get("/health", self.health_page)\n'
        if marker not in text:
            raise InstallationError(
                'La route "/health" est introuvable dans public_website.py.'
            )
        text = text.replace(marker, marker + route_call, 1)

    text = text.replace(
        "Elle n'ajoute aucune administration web.",
        "Le tableau de bord staff est intégré directement à ce serveur.",
    )
    text = text.replace(
        "Site public Hamtaro lancé sur %s:%s.",
        "Site Hamtaro public + staff lancé sur %s:%s.",
    )

    path.write_text(text, encoding="utf-8")


def patch_bot(path: Path) -> None:
    if not path.exists():
        raise InstallationError("bot.py est introuvable.")

    lines = path.read_text(encoding="utf-8").splitlines()
    cleaned: list[str] = []
    seen_cogs: set[str] = set()

    for line in lines:
        match = re.match(r'^(\s*)"(?P<cog>cogs\.[^"]+)",\s*$', line)

        if match:
            cog = match.group("cog")

            # Le tableau staff est désormais intégré à public_website.
            if cog == "cogs.professional_web":
                continue

            if cog in seen_cogs:
                continue

            seen_cogs.add(cog)

        cleaned.append(line)

    path.write_text("\n".join(cleaned) + "\n", encoding="utf-8")


def patch_base_template(path: Path) -> None:
    if not path.exists():
        raise InstallationError("web/templates/base.html est introuvable.")

    text = path.read_text(encoding="utf-8")
    stylesheet = '<link rel="stylesheet" href="/static/professional.css">'

    if stylesheet not in text:
        if "</head>" not in text:
            raise InstallationError(
                "La balise </head> est introuvable dans base.html."
            )
        text = text.replace(
            "</head>",
            f"    {stylesheet}\n</head>",
            1,
        )

    path.write_text(text, encoding="utf-8")


def validate(project_root: Path) -> None:
    python_files = [
        project_root / "bot.py",
        project_root / "cogs" / "public_website.py",
        project_root / "services" / "staff_dashboard_routes.py",
        project_root / "services" / "staff_dashboard_service.py",
    ]

    for path in python_files:
        py_compile.compile(str(path), doraise=True)

    public_text = (
        project_root / "cogs" / "public_website.py"
    ).read_text(encoding="utf-8")

    bot_text = (
        project_root / "bot.py"
    ).read_text(encoding="utf-8")

    required_fragments = [
        "from services.staff_dashboard_routes import",
        "register_staff_dashboard_routes(",
        'HAMTARO_SITE_BUILD = "staff-integrated-2026-08-05-v2"',
    ]

    missing = [
        fragment
        for fragment in required_fragments
        if fragment not in public_text
    ]

    if missing:
        raise InstallationError(
            "Vérification incomplète : " + ", ".join(missing)
        )

    if '"cogs.professional_web",' in bot_text:
        raise InstallationError(
            "cogs.professional_web est encore chargé dans bot.py."
        )


def main() -> int:
    project_root = Path.cwd().resolve()

    if not (project_root / "bot.py").exists():
        raise InstallationError(
            "Place ce fichier à la racine du dépôt Hamtaro, "
            "puis lance : python3 installer_staff_hamtaro.py"
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = (
        project_root
        / "upgrade_backup"
        / f"staff_dashboard_{timestamp}"
    )

    important_files = [
        project_root / "bot.py",
        project_root / "cogs" / "public_website.py",
        project_root / "web" / "templates" / "base.html",
    ]

    for path in important_files:
        backup_file(path, project_root, backup_root)

    write_embedded_files(project_root, backup_root)
    patch_public_website(project_root / "cogs" / "public_website.py")
    patch_bot(project_root / "bot.py")
    patch_base_template(project_root / "web" / "templates" / "base.html")
    validate(project_root)

    print()
    print("✅ Installation terminée.")
    print("✅ /staff est intégré directement à public_website.py.")
    print("✅ Aucune dépendance à l'ordre des cogs.")
    print("✅ Syntaxe Python vérifiée.")
    print(f"✅ Sauvegarde créée dans : {backup_root}")
    print()
    print("Envoie ensuite les modifications sur GitHub :")
    print("git add .")
    print('git commit -m "Intégration directe du tableau staff"')
    print("git push")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallationError as error:
        print(f"❌ {error}", file=sys.stderr)
        raise SystemExit(1)
