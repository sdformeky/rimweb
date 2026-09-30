from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.audit_log import AuditLog
from app.models.enums import ConditionStatus, LifecycleStatus
from app.models.item_instance import ItemInstance
from app.models.item_type import ItemType
from app.models.issue_record import IssueRecord
from app.models.user import User


def list_item_types(db: Session, query: str | None = None) -> list[ItemType]:
    statement: Select[tuple[ItemType]] = select(ItemType).order_by(ItemType.name.asc())
    if query:
        like_value = f"%{query.strip()}%"
        statement = statement.where(
            ItemType.name.ilike(like_value)
            | ItemType.comment.ilike(like_value)
            | ItemType.tags_text.ilike(like_value)
            | ItemType.store_url.ilike(like_value)
            | ItemType.unit_label.ilike(like_value)
        )
    return list(db.scalars(statement).all())


def get_item_type(db: Session, item_type_id: int) -> ItemType | None:
    return db.scalar(select(ItemType).where(ItemType.id == item_type_id))


def list_instances_with_related(db: Session) -> list[ItemInstance]:
    statement = (
        select(ItemInstance)
        .options(
            joinedload(ItemInstance.item_type),
            joinedload(ItemInstance.current_holder),
            joinedload(ItemInstance.lab_location),
            selectinload(ItemInstance.issue_records).joinedload(IssueRecord.issued_to_user),
            selectinload(ItemInstance.issue_records).joinedload(IssueRecord.issued_by_user),
            selectinload(ItemInstance.issue_records).joinedload(IssueRecord.returned_by_user),
        )
        .order_by(ItemInstance.id.asc())
    )
    return list(db.scalars(statement).unique().all())


def get_instance(db: Session, instance_id: int) -> ItemInstance | None:
    statement = (
        select(ItemInstance)
        .options(
            joinedload(ItemInstance.item_type),
            joinedload(ItemInstance.current_holder),
            joinedload(ItemInstance.lab_location),
            selectinload(ItemInstance.issue_records).joinedload(IssueRecord.issued_to_user),
            selectinload(ItemInstance.issue_records).joinedload(IssueRecord.issued_by_user),
            selectinload(ItemInstance.issue_records).joinedload(IssueRecord.returned_by_user),
            selectinload(ItemInstance.issue_records).joinedload(IssueRecord.previous_lab_location),
            selectinload(ItemInstance.issue_records).joinedload(IssueRecord.return_lab_location),
        )
        .where(ItemInstance.id == instance_id)
    )
    return db.scalar(statement)


def get_instances_by_ids(db: Session, instance_ids: list[int]) -> list[ItemInstance]:
    if not instance_ids:
        return []
    statement = (
        select(ItemInstance)
        .options(
            joinedload(ItemInstance.item_type),
            joinedload(ItemInstance.current_holder),
            joinedload(ItemInstance.lab_location),
            selectinload(ItemInstance.issue_records),
        )
        .where(ItemInstance.id.in_(set(instance_ids)))
        .order_by(ItemInstance.id.asc())
    )
    return list(db.scalars(statement).unique().all())


def count_item_types(db: Session) -> int:
    return int(db.scalar(select(func.count(ItemType.id))) or 0)


def count_instances(db: Session) -> int:
    return int(db.scalar(select(func.count(ItemInstance.id))) or 0)


def count_instances_by_filter(db: Session, *conditions: object) -> int:
    statement = select(func.count(ItemInstance.id))
    for condition in conditions:
        statement = statement.where(condition)
    return int(db.scalar(statement) or 0)


def list_issue_records_for_user(db: Session, user_id: int) -> list[IssueRecord]:
    return list(
        db.scalars(
            select(IssueRecord)
            .options(
                joinedload(IssueRecord.item_instance).joinedload(ItemInstance.item_type),
                joinedload(IssueRecord.issued_by_user),
                joinedload(IssueRecord.returned_by_user),
            )
            .where(IssueRecord.issued_to_user_id == user_id)
            .order_by(IssueRecord.issued_at.desc())
        ).all()
    )


def list_active_instances_for_user(db: Session, user_id: int) -> list[ItemInstance]:
    return list(
        db.scalars(
            select(ItemInstance)
            .options(joinedload(ItemInstance.item_type), joinedload(ItemInstance.lab_location))
            .where(ItemInstance.current_holder_user_id == user_id)
            .order_by(ItemInstance.updated_at.desc())
        ).all()
    )


def list_recent_audit_logs(db: Session, limit: int = 10) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .options(joinedload(AuditLog.actor))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        ).all()
    )


def list_users_for_select(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.full_name.asc())).all())


def list_issuable_instances(db: Session) -> list[ItemInstance]:
    statement = (
        select(ItemInstance)
        .join(ItemInstance.item_type)
        .options(
            joinedload(ItemInstance.item_type),
            joinedload(ItemInstance.lab_location),
        )
        .where(
            ItemInstance.lifecycle_status == LifecycleStatus.ACTIVE,
            ItemInstance.current_holder_user_id.is_(None),
            ItemInstance.condition_status != ConditionStatus.ABSENT,
        )
        .order_by(ItemType.name.asc(), ItemInstance.inventory_number.asc())
    )
    return list(db.scalars(statement).all())
