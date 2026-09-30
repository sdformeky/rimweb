from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ConditionStatus, LifecycleStatus
from app.models.item_instance import ItemInstance
from app.repositories.inventory import (
    count_instances,
    count_instances_by_filter,
    count_item_types,
    list_recent_audit_logs,
)


def get_dashboard_stats(db: Session) -> dict[str, int]:
    return {
        "item_types_total": count_item_types(db),
        "instances_total": count_instances(db),
        "instances_active": count_instances_by_filter(db, ItemInstance.lifecycle_status == LifecycleStatus.ACTIVE),
        "instances_written_off": count_instances_by_filter(db, ItemInstance.lifecycle_status == LifecycleStatus.WRITTEN_OFF),
        "instances_issued": count_instances_by_filter(db, ItemInstance.current_holder_user_id.is_not(None)),
        "instances_broken": count_instances_by_filter(db, ItemInstance.condition_status == ConditionStatus.BROKEN),
        "instances_in_repair": count_instances_by_filter(db, ItemInstance.condition_status == ConditionStatus.IN_REPAIR),
    }


def get_recent_activity(db: Session, limit: int = 10):
    return list_recent_audit_logs(db, limit=limit)
