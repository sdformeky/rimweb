from __future__ import annotations

from app.models.audit_log import AuditLog
from app.models.base import utcnow
from app.models.user import User
from app.utils.serialization import dump_json


def add_audit_log(
    db,
    actor: User | None,
    action_type: str,
    entity_type: str,
    entity_id: str | int,
    old_value: object | None = None,
    new_value: object | None = None,
    comment: str | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_user_id=actor.id if actor else None,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=str(entity_id),
        old_value_json=dump_json(old_value),
        new_value_json=dump_json(new_value),
        comment=comment,
        created_at=utcnow(),
    )
    db.add(log)
    return log
