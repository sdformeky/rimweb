from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from app.models.audit_log import AuditLog


def list_audit_logs(
    db: Session,
    actor_user_id: int | None = None,
    action_type: str | None = None,
    entity_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[AuditLog]:
    statement: Select[tuple[AuditLog]] = (
        select(AuditLog)
        .options(joinedload(AuditLog.actor))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    if actor_user_id:
        statement = statement.where(AuditLog.actor_user_id == actor_user_id)
    if action_type:
        statement = statement.where(AuditLog.action_type == action_type)
    if entity_type:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if date_from:
        statement = statement.where(AuditLog.created_at >= date_from)
    if date_to:
        statement = statement.where(AuditLog.created_at <= date_to)
    return list(db.scalars(statement).all())


def list_entity_logs(db: Session, entity_type: str, entity_id: str) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .options(joinedload(AuditLog.actor))
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        ).all()
    )
