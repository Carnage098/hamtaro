from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AuditEntry:
    id: int
    guild_id: str
    actor_id: str | None
    actor_name: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    tournament_id: int | None
    details: dict[str, Any]
    created_at: str | None


class AuditService:
    """Journal d'audit central pour toutes les actions sensibles."""

    def __init__(self, db) -> None:
        self.db = db

    async def record(
        self,
        *,
        guild_id: str,
        action: str,
        actor_id: str | None = None,
        actor_name: str | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        tournament_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        payload = json.dumps(
            details or {},
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
        return await self.db.insert(
            """
            INSERT INTO audit_logs (
                guild_id,
                actor_id,
                actor_name,
                action,
                entity_type,
                entity_id,
                tournament_id,
                details
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                actor_id,
                actor_name,
                action,
                entity_type,
                None if entity_id is None else str(entity_id),
                tournament_id,
                payload,
            ),
        )

    async def recent(
        self,
        *,
        guild_id: str,
        limit: int = 25,
        tournament_id: int | None = None,
    ) -> list[AuditEntry]:
        limit = max(1, min(100, int(limit)))
        if tournament_id is None:
            rows = await self.db.fetchall(
                """
                SELECT *
                FROM audit_logs
                WHERE guild_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (guild_id, limit),
            )
        else:
            rows = await self.db.fetchall(
                """
                SELECT *
                FROM audit_logs
                WHERE guild_id = ? AND tournament_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (guild_id, tournament_id, limit),
            )

        entries: list[AuditEntry] = []
        for row in rows:
            data = dict(row)
            try:
                details = json.loads(data.get("details") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                details = {"raw": data.get("details")}
            entries.append(
                AuditEntry(
                    id=int(data["id"]),
                    guild_id=str(data["guild_id"]),
                    actor_id=data.get("actor_id"),
                    actor_name=data.get("actor_name"),
                    action=str(data["action"]),
                    entity_type=data.get("entity_type"),
                    entity_id=data.get("entity_id"),
                    tournament_id=data.get("tournament_id"),
                    details=details,
                    created_at=(
                        str(data["created_at"])
                        if data.get("created_at") is not None
                        else None
                    ),
                )
            )
        return entries
