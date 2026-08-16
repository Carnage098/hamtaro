from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from aiohttp import web

from services.deck_builder_service import DeckBuilderService


def _bool_arg(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "oui", "on"}


def _int_arg(value: str | None, *, minimum: int, maximum: int) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return max(minimum, min(maximum, int(raw)))
    except ValueError:
        return None


class DeckBuilderRoutes:
    def __init__(self, website_cog: Any) -> None:
        self.website_cog = website_cog
        project_root = Path(__file__).resolve().parent.parent
        self.service = DeckBuilderService(project_root)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _client_key(self, request: web.Request) -> str:
        # X-Forwarded-For est utilisé sur Railway ; on ne conserve rien en base.
        forwarded = str(request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        return forwarded or str(request.remote or "unknown")

    def _rate_limit(
        self, request: web.Request, *, scope: str = "heavy", max_calls: int = 18, window: int = 60
    ) -> None:
        key = f"{scope}:{self._client_key(request)}"
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= max_calls:
            raise web.HTTPTooManyRequests(
                text='{"error":"Trop de recherches en peu de temps. Réessaie dans quelques instants."}',
                content_type="application/json",
                headers={"Retry-After": str(window)},
            )
        bucket.append(now)
        # Évite une croissance infinie du dictionnaire sur un site public.
        if len(self._hits) > 4000:
            stale = [client for client, values in self._hits.items() if not values or now - values[-1] > window * 4]
            for client in stale[:2000]:
                self._hits.pop(client, None)

    async def page(self, request: web.Request) -> web.Response:
        return self.website_cog.render(
            "deck_builder.html",
            request=request,
            quick_decks=[
                "Blue-Eyes",
                "Primite Blue-Eyes",
                "Yummy",
                "Sky Striker",
                "X-Saber",
                "Mitsurugi",
                "Cyber Dragon",
                "Branded",
                "Ryzeal",
                "Maliss",
                "Traptrix",
                "Fire King",
                "D/D/D",
                "P.U.N.K.",
            ],
        )

    async def suggestions(self, request: web.Request) -> web.Response:
        self._rate_limit(request, scope="suggestions", max_calls=36)
        query = str(request.query.get("q") or "").strip()
        values = await self.service.suggestions(query)
        return web.json_response(
            {"query": query, "suggestions": values},
            headers={"Cache-Control": "public, max-age=300"},
        )

    def _common_options(self, request: web.Request) -> dict[str, Any]:
        return {
            "max_decks": _int_arg(request.query.get("limit"), minimum=6, maximum=60),
            "tournament_only": _bool_arg(request.query.get("tournament_only")),
            "days": _int_arg(request.query.get("days"), minimum=1, maximum=3650),
            "variant": str(request.query.get("variant") or "").strip() or None,
        }

    async def analyze(self, request: web.Request) -> web.Response:
        self._rate_limit(request)
        query = str(request.query.get("q") or "").strip()
        try:
            payload = await self.service.analyze(query, **self._common_options(request))
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    @staticmethod
    def _parse_budget(value: Any) -> float | None:
        raw = str(value if value is not None else "").strip().replace(",", ".")
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError as exc:
            raise ValueError("Le budget doit être un nombre valide.") from exc

    @staticmethod
    def _owned_cards(payload: Any) -> dict[int, int]:
        if not isinstance(payload, dict):
            return {}
        result: dict[int, int] = {}
        for card_id, count in payload.items():
            try:
                cid = int(card_id)
                qty = max(0, min(3, int(count)))
            except (TypeError, ValueError):
                continue
            if cid > 0 and qty > 0:
                result[cid] = qty
        return result

    @staticmethod
    def _printing_selections(payload: Any) -> dict[int, str]:
        if not isinstance(payload, dict):
            return {}
        result: dict[int, str] = {}
        for card_id, item in list(payload.items())[:30]:
            try:
                cid = int(card_id)
            except (TypeError, ValueError):
                continue
            if cid <= 0 or not isinstance(item, dict):
                continue
            printing_id = str(item.get("printing_id") or "").strip()
            if printing_id:
                result[cid] = printing_id[:220]
        return result

    async def _resolve_printing_selections(self, payload: Any) -> dict[int, dict[str, Any]]:
        selections = self._printing_selections(payload)
        if not selections:
            return {}

        async def one(card_id: int, printing_id: str) -> tuple[int, dict[str, Any] | None]:
            try:
                data = await self.service.card_printings(card_id)
            except Exception:
                return card_id, None
            match = next((row for row in data.get("printings") or [] if str(row.get("printing_id") or "") == printing_id), None)
            if not match or match.get("price_eur") is None:
                return card_id, None
            return card_id, {
                "printing_id": printing_id,
                "set_name": match.get("set_name"),
                "set_code": match.get("set_code"),
                "rarity": match.get("rarity"),
                "price_eur": float(match["price_eur"]),
                "price_source": match.get("price_source"),
                "market_url": match.get("market_url"),
            }

        resolved = await asyncio.gather(*(one(cid, pid) for cid, pid in selections.items()))
        return {cid: row for cid, row in resolved if row is not None}

    @staticmethod
    def _locked_cards(payload: Any) -> dict[str, dict[int, int]]:
        result: dict[str, dict[int, int]] = {"main": {}, "extra": {}, "side": {}}
        if not isinstance(payload, dict):
            return result
        for zone in result:
            values = payload.get(zone)
            if not isinstance(values, dict):
                continue
            for card_id, count in values.items():
                try:
                    cid = int(card_id)
                    qty = max(1, min(3, int(count)))
                except (TypeError, ValueError):
                    continue
                if cid > 0:
                    result[zone][cid] = qty
        return result

    @staticmethod
    def _excluded_cards(payload: Any) -> dict[str, list[int]]:
        result: dict[str, list[int]] = {"main": [], "extra": [], "side": []}
        if not isinstance(payload, dict):
            return result
        for zone in result:
            values = payload.get(zone)
            if not isinstance(values, (list, tuple, set)):
                continue
            seen: set[int] = set()
            for card_id in values:
                try:
                    cid = int(card_id)
                except (TypeError, ValueError):
                    continue
                if cid > 0 and cid not in seen:
                    seen.add(cid)
                    result[zone].append(cid)
        return result

    async def generate(self, request: web.Request) -> web.Response:
        """GET conservé pour les anciens liens ; POST est utilisé par la V5."""
        self._rate_limit(request)
        query = str(request.query.get("q") or "").strip()
        mode = str(request.query.get("mode") or "standard").strip().lower()
        try:
            budget = self._parse_budget(request.query.get("budget"))
            payload = await self.service.generate(
                query,
                mode=mode,
                budget=budget,
                freespot_profile=str(request.query.get("freespot_profile") or "auto").strip().lower(),
                **self._common_options(request),
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def generate_post(self, request: web.Request) -> web.Response:
        self._rate_limit(request)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Corps JSON invalide."}, status=400)
        query = str(body.get("q") or "").strip()
        mode = str(body.get("mode") or "standard").strip().lower()
        try:
            budget = self._parse_budget(body.get("budget"))
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        # Les filtres restent dans le JSON afin que la collection du joueur ne soit
        # jamais exposée dans l'URL partagée.
        max_decks = body.get("limit")
        days = body.get("days")
        try:
            max_decks = max(6, min(60, int(max_decks))) if max_decks not in (None, "") else None
        except (TypeError, ValueError):
            max_decks = None
        try:
            days = max(1, min(3650, int(days))) if days not in (None, "") else None
        except (TypeError, ValueError):
            days = None
        try:
            printing_selections = await self._resolve_printing_selections(body.get("selected_printings"))
            payload = await self.service.generate(
                query,
                mode=mode,
                budget=budget,
                max_decks=max_decks,
                tournament_only=bool(body.get("tournament_only")),
                days=days,
                variant=str(body.get("variant") or "").strip() or None,
                owned_cards=self._owned_cards(body.get("owned_cards")),
                locked_cards=self._locked_cards(body.get("locked_cards")),
                excluded_cards=self._excluded_cards(body.get("excluded_cards")),
                freespot_profile=str(body.get("freespot_profile") or "auto").strip().lower(),
                printing_selections=printing_selections,
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def compare(self, request: web.Request) -> web.Response:
        self._rate_limit(request, scope="compare", max_calls=12)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Corps JSON invalide."}, status=400)
        query = str(body.get("q") or "").strip()
        deck_input = str(body.get("deck_input") or "").strip()
        if len(deck_input) > 30000:
            return web.json_response({"error": "La liste importée est trop longue."}, status=400)
        max_decks = body.get("limit")
        days = body.get("days")
        try:
            max_decks = max(6, min(60, int(max_decks))) if max_decks not in (None, "") else None
        except (TypeError, ValueError):
            max_decks = None
        try:
            days = max(1, min(3650, int(days))) if days not in (None, "") else None
        except (TypeError, ValueError):
            days = None
        try:
            payload = await self.service.compare_imported_deck(
                query,
                deck_input,
                max_decks=max_decks,
                tournament_only=bool(body.get("tournament_only")),
                days=days,
                variant=str(body.get("variant") or "").strip() or None,
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def alternatives(self, request: web.Request) -> web.Response:
        self._rate_limit(request, scope="alternatives", max_calls=24)
        query = str(request.query.get("q") or "").strip()
        zone = str(request.query.get("zone") or "").strip().lower()
        try:
            card_id = int(request.query.get("card_id") or 0)
        except (TypeError, ValueError):
            card_id = 0
        if card_id <= 0:
            return web.json_response({"error": "Carte invalide."}, status=400)
        try:
            payload = await self.service.alternatives(
                query, card_id, zone, **self._common_options(request)
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def synergy(self, request: web.Request) -> web.Response:
        self._rate_limit(request, scope="synergy", max_calls=18)
        query = str(request.query.get("q") or "").strip()
        zone = str(request.query.get("zone") or "main").strip().lower()
        try:
            card_id = int(request.query.get("card_id") or 0)
        except (TypeError, ValueError):
            card_id = 0
        if card_id <= 0:
            return web.json_response({"error": "Carte source invalide."}, status=400)
        try:
            payload = await self.service.synergies(
                query, card_id, zone, **self._common_options(request)
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def printings(self, request: web.Request) -> web.Response:
        self._rate_limit(request, scope="printings", max_calls=24)
        try:
            card_id = int(request.query.get("card_id") or 0)
        except (TypeError, ValueError):
            card_id = 0
        if card_id <= 0:
            return web.json_response({"error": "Carte invalide."}, status=400)
        try:
            payload = await self.service.card_printings(card_id)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def card_image(self, request: web.Request) -> web.StreamResponse:
        self._rate_limit(request, scope="images", max_calls=90)
        try:
            card_id = int(request.match_info["card_id"])
        except (KeyError, TypeError, ValueError):
            raise web.HTTPNotFound()
        path = await self.service.card_image_path(card_id)
        if not path or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(
            path,
            headers={"Cache-Control": "public, max-age=2592000, immutable"},
        )

    async def catalog(self, request: web.Request) -> web.Response:
        self._rate_limit(request, scope="catalog", max_calls=60)
        return web.json_response(
            await self.service.catalog_stats(),
            headers={"Cache-Control": "public, max-age=120"},
        )

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "service": "hamtaro-deck-builder",
                "version": "8.3",
                "page": "/deck-builder",
                "price_source": "Cardmarket data via YGOPRODeck · TCG only",
                "catalog": await self.service.catalog_stats(),
                "card_language": self.service.card_language,
                "features": [
                    "main-extra-side-usage",
                    "budget-standard-optimal",
                    "hard-budget-rebalancing",
                    "owned-cards-aware-generation",
                    "real-price-fetch-date",
                    "localized-card-names",
                    "engine-detection",
                    "confidence-score",
                    "local-card-image-cache",
                    "price-history",
                    "ydke-export",
                    "source-weighting",
                    "duplicate-deck-detection",
                    "public-rate-limiting",
                    "global-tcg-legality",
                    "ydke-ydk-deck-comparison",
                    "upgrade-paths",
                    "role-composition",
                    "official-banlist-cross-check",
                    "locked-and-excluded-card-constraints",
                    "observed-card-alternatives",
                    "deck-readiness-score",
                    "beginner-purchase-plan",
                    "statistical-card-packages",
                    "card-cooccurrence-synergy",
                    "engine-with-without-comparison",
                    "ratio-stability",
                    "opening-hand-probabilities",
                    "dynamic-freespot-analysis",
                    "generic-staple-categories",
                    "freespot-generation-profiles",
                    "deck-specific-handtrap-spell-trap-radar",
                    "explicit-sqlite-connection-closing",
                    "rarity-and-printing-selector",
                    "per-printing-price-display",
                    "cardmarket-version-floor-fallback",
                    "tcg-only-card-filtering",
                    "self-enriching-deck-catalog",
                    "persistent-learned-decklists",
                    "punctuation-tolerant-archetype-aliases",
                ],
            },
            headers={"Cache-Control": "no-store"},
        )


def register_deck_builder_routes(application: web.Application, website_cog: Any) -> DeckBuilderRoutes:
    routes = DeckBuilderRoutes(website_cog)
    application.router.add_get("/deck-builder", routes.page)
    application.router.add_get("/generateur-deck", routes.page)
    application.router.add_get("/api/deck-builder/suggestions", routes.suggestions)
    application.router.add_get("/api/deck-builder/catalog", routes.catalog)
    application.router.add_get("/api/deck-builder/analyze", routes.analyze)
    application.router.add_get("/api/deck-builder/generate", routes.generate)
    application.router.add_post("/api/deck-builder/generate", routes.generate_post)
    application.router.add_post("/api/deck-builder/compare", routes.compare)
    application.router.add_get("/api/deck-builder/alternatives", routes.alternatives)
    application.router.add_get("/api/deck-builder/synergy", routes.synergy)
    application.router.add_get("/api/deck-builder/printings", routes.printings)
    application.router.add_get(r"/api/deck-builder/card-image/{card_id:\d+}.jpg", routes.card_image)
    application.router.add_get("/api/deck-builder/health", routes.health)
    return routes
