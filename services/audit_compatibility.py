from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


class AuditCompatibilityService:
    """Relie les journaux historiques du projet au journal d'audit central."""

    def __init__(self, db) -> None:
        self.db = db

    async def install(self) -> None:
        await self._result_trigger()
        await self._undo_triggers()
        await self.db.commit()

    async def _table_exists(self, name: str) -> bool:
        row = await self.db.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        return row is not None

    async def _result_trigger(self) -> None:
        if not await self._table_exists("result_audit_logs"):
            return
        await self.db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_result_audit_to_professional
            AFTER INSERT ON result_audit_logs
            BEGIN
                INSERT INTO audit_logs (
                    guild_id, actor_id, action, entity_type,
                    entity_id, details, created_at
                ) VALUES (
                    NEW.guild_id,
                    NEW.actor_id,
                    NEW.action,
                    'match',
                    NEW.match_kind || ':' || NEW.match_id,
                    COALESCE(NEW.details, '{}'),
                    NEW.created_at
                );
            END
            """
        )

    async def _undo_triggers(self) -> None:
        if not await self._table_exists("tournament_action_snapshots"):
            return
        await self.db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_undo_capture_to_professional
            AFTER INSERT ON tournament_action_snapshots
            BEGIN
                INSERT INTO audit_logs (
                    guild_id, actor_id, action, entity_type,
                    entity_id, tournament_id, details, created_at
                ) VALUES (
                    NEW.guild_id,
                    NEW.actor_id,
                    'undo_snapshot_captured:' || NEW.action_type,
                    'match',
                    NEW.match_kind || ':' || NEW.match_id,
                    NEW.tournament_id,
                    COALESCE(NEW.metadata_json, '{}'),
                    NEW.created_at
                );
            END
            """
        )
        await self.db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_undo_apply_to_professional
            AFTER UPDATE OF status ON tournament_action_snapshots
            WHEN NEW.status = 'undone' AND OLD.status IS NOT NEW.status
            BEGIN
                INSERT INTO audit_logs (
                    guild_id, actor_id, action, entity_type,
                    entity_id, tournament_id, details, created_at
                ) VALUES (
                    NEW.guild_id,
                    NEW.undone_by,
                    'tournament_action_undone',
                    'match',
                    NEW.match_kind || ':' || NEW.match_id,
                    NEW.tournament_id,
                    json_object(
                        'reason', COALESCE(NEW.undo_reason, ''),
                        'snapshot_id', NEW.id,
                        'action_type', NEW.action_type
                    ),
                    COALESCE(NEW.undone_at, CURRENT_TIMESTAMP)
                );
            END
            """
        )
