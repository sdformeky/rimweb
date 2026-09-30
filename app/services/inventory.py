from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import ConditionStatus, LifecycleStatus, PhysicalLocationType
from app.models.item_instance import ItemInstance
from app.models.item_type import ItemType
from app.models.issue_record import IssueRecord
from app.models.lab_location import LabLocation
from app.models.user import User
from app.services.audit import add_audit_log
from app.services.locations import build_location_maps
from app.utils.formatting import condition_label, lifecycle_label
from app.utils.inventory_numbers import generate_inventory_numbers
from app.utils.tags import normalize_tags, parse_tags

ABSENT_CONDITION = getattr(ConditionStatus, "ABSENT", "absent")


@dataclass
class LocationSnapshot:
    physical_location_type: PhysicalLocationType
    warehouse_location_text: str | None
    lab_location_id: int | None
    display_text: str


@dataclass
class HolderSummary:
    label: str
    count: int


@dataclass
class InventoryGroup:
    key: str
    item_type: ItemType
    physical_location_type: PhysicalLocationType
    location_display: str
    count_received: int = 0
    count_factual: int = 0
    count_available: int = 0
    count_official: int = 0
    issue_ready_count: int = 0
    instances: list[ItemInstance] = field(default_factory=list)
    type_tags: list[str] = field(default_factory=list)
    instance_tags: list[str] = field(default_factory=list)
    unique_purchase_numbers: list[str] = field(default_factory=list)
    warehouse_locations: list[str] = field(default_factory=list)
    purchase_total: Decimal = Decimal("0.00")
    type_total_all: Decimal = Decimal("0.00")
    type_total_active: Decimal = Decimal("0.00")
    holders: list[HolderSummary] = field(default_factory=list)
    condition_summaries: list[HolderSummary] = field(default_factory=list)
    lifecycle_summaries: list[HolderSummary] = field(default_factory=list)


@dataclass
class ItemTypeGroup:
    key: str
    condition_status: ConditionStatus
    lifecycle_status: LifecycleStatus
    count: int
    purchase_display: str = "—"
    location_display: str = "Не указано"
    instances: list[ItemInstance] = field(default_factory=list)
    instance_tags: list[str] = field(default_factory=list)
    unique_purchase_numbers: list[str] = field(default_factory=list)
    location_texts: list[str] = field(default_factory=list)


def item_effective_unit_price(instance: ItemInstance) -> Decimal:
    return Decimal(instance.purchase_unit_price or instance.item_type.unit_price or Decimal("0.00"))


def resolve_location_snapshot(
    instance: ItemInstance,
    location_path_map: dict[int, str],
) -> LocationSnapshot:
    if instance.physical_location_type == PhysicalLocationType.WAREHOUSE:
        display_text = instance.warehouse_location_text or "Склад без адреса"
    elif instance.physical_location_type == PhysicalLocationType.LABORATORY and instance.lab_location_id:
        display_text = location_path_map.get(instance.lab_location_id, "Лабораторное место")
    else:
        display_text = "Не указано"
    return LocationSnapshot(
        physical_location_type=instance.physical_location_type,
        warehouse_location_text=instance.warehouse_location_text,
        lab_location_id=instance.lab_location_id,
        display_text=display_text,
    )


def format_purchase_label(purchase_number: str | None) -> str:
    return (purchase_number or "").strip() or "Без сч.Фак"


def is_factual_instance(instance: ItemInstance) -> bool:
    return instance.condition_status in {ConditionStatus.WORKING, ConditionStatus.IN_REPAIR}


def is_official_instance(instance: ItemInstance) -> bool:
    return instance.condition_status == ConditionStatus.WORKING and instance.lifecycle_status != LifecycleStatus.WRITTEN_OFF


def is_issuable_instance(instance: ItemInstance) -> bool:
    return (
        instance.lifecycle_status == LifecycleStatus.ACTIVE
        and instance.current_holder_user_id is None
        and instance.condition_status != ABSENT_CONDITION
    )


def clean_store_url(store_url: str | None) -> str | None:
    cleaned = (store_url or "").strip()
    if not cleaned:
        return None
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Store URL должен начинаться с http:// или https://")
    return cleaned


def create_item_type(
    db: Session,
    actor: User,
    name: str,
    comment: str | None,
    store_url: str | None,
    unit_label: str | None,
    unit_price: Decimal,
    tags_text: str | None,
) -> ItemType:
    existing_item_type = db.scalar(select(ItemType).where(ItemType.name == name.strip()))
    if existing_item_type is not None:
        raise ValueError("Тип предмета с таким названием уже существует.")
    item_type = ItemType(
        name=name.strip(),
        comment=(comment or "").strip() or None,
        store_url=clean_store_url(store_url),
        unit_label=(unit_label or "").strip() or "шт",
        unit_price=unit_price,
        tags_text=normalize_tags(tags_text),
    )
    db.add(item_type)
    db.flush()
    add_audit_log(
        db,
        actor,
        "item_type_created",
        "item_type",
        item_type.id,
        new_value={
            "name": item_type.name,
            "comment": item_type.comment,
            "store_url": item_type.store_url,
            "unit_label": item_type.unit_label,
            "unit_price": str(item_type.unit_price),
            "tags": parse_tags(item_type.tags_text),
        },
    )
    db.commit()
    db.refresh(item_type)
    return item_type


def update_item_type(
    db: Session,
    actor: User,
    item_type: ItemType,
    name: str,
    comment: str | None,
    store_url: str | None,
    unit_label: str | None,
    unit_price: Decimal,
    tags_text: str | None,
) -> ItemType:
    existing_item_type = db.scalar(
        select(ItemType).where(ItemType.name == name.strip(), ItemType.id != item_type.id)
    )
    if existing_item_type is not None:
        raise ValueError("Тип предмета с таким названием уже существует.")
    cleaned_store_url = clean_store_url(store_url)
    old_value = {
        "name": item_type.name,
        "comment": item_type.comment,
        "store_url": item_type.store_url,
        "unit_label": item_type.unit_label,
        "unit_price": str(item_type.unit_price),
        "tags": parse_tags(item_type.tags_text),
    }
    item_type.name = name.strip()
    item_type.comment = (comment or "").strip() or None
    item_type.store_url = cleaned_store_url
    item_type.unit_label = (unit_label or "").strip() or "шт"
    item_type.unit_price = unit_price
    item_type.tags_text = normalize_tags(tags_text)
    db.flush()
    add_audit_log(
        db,
        actor,
        "item_type_updated",
        "item_type",
        item_type.id,
        old_value=old_value,
        new_value={
            "name": item_type.name,
            "comment": item_type.comment,
            "store_url": item_type.store_url,
            "unit_label": item_type.unit_label,
            "unit_price": str(item_type.unit_price),
            "tags": parse_tags(item_type.tags_text),
        },
    )
    db.commit()
    db.refresh(item_type)
    return item_type


def ensure_valid_location(
    physical_location_type: PhysicalLocationType,
    warehouse_location_text: str | None,
    lab_location: LabLocation | None,
) -> tuple[str | None, int | None]:
    warehouse_value = (warehouse_location_text or "").strip() or None
    if physical_location_type == PhysicalLocationType.WAREHOUSE:
        return warehouse_value, None
    if physical_location_type == PhysicalLocationType.LABORATORY:
        if lab_location is None:
            raise ValueError("Для лабораторного размещения нужно выбрать лабораторное место.")
        return None, lab_location.id
    return None, None


def create_instances(
    db: Session,
    actor: User,
    item_type: ItemType,
    quantity: int,
    manual_inventory_numbers: list[str] | None,
    auto_generate_inventory_numbers: bool,
    condition_status: ConditionStatus,
    purchase_number: str | None,
    purchase_unit_price: Decimal | None,
    tags_text: str | None,
    physical_location_type: PhysicalLocationType,
    warehouse_location_text: str | None,
    lab_location: LabLocation | None,
) -> list[ItemInstance]:
    if quantity <= 0:
        raise ValueError("Количество должно быть больше нуля.")

    warehouse_value, lab_location_id = ensure_valid_location(
        physical_location_type=physical_location_type,
        warehouse_location_text=warehouse_location_text,
        lab_location=lab_location,
    )

    inventory_numbers: list[str]
    if auto_generate_inventory_numbers:
        inventory_numbers = generate_inventory_numbers(
            db=db,
            prefix=get_settings().inventory_number_prefix,
            count=quantity,
        )
    else:
        inventory_numbers = [number.strip() for number in (manual_inventory_numbers or []) if number.strip()]
        if len(inventory_numbers) != quantity:
            raise ValueError("Количество инвентарных номеров должно совпадать с количеством экземпляров.")
        if len(set(inventory_numbers)) != len(inventory_numbers):
            raise ValueError("Инвентарные номера в партии должны быть уникальными.")

    existing_inventory_numbers = set(
        db.scalars(
            select(ItemInstance.inventory_number).where(ItemInstance.inventory_number.in_(inventory_numbers))
        ).all()
    )
    if existing_inventory_numbers:
        raise ValueError(
            "Следующие инвентарные номера уже существуют: " + ", ".join(sorted(existing_inventory_numbers))
        )

    normalized_tags = normalize_tags(tags_text)
    created_instances: list[ItemInstance] = []

    for inventory_number in inventory_numbers:
        instance = ItemInstance(
            item_type=item_type,
            inventory_number=inventory_number,
            condition_status=condition_status,
            lifecycle_status=LifecycleStatus.ACTIVE,
            purchase_number=(purchase_number or "").strip() or None,
            purchase_unit_price=purchase_unit_price,
            tags_text=normalized_tags,
            physical_location_type=physical_location_type,
            warehouse_location_text=warehouse_value,
            lab_location_id=lab_location_id,
        )
        db.add(instance)
        db.flush()
        created_instances.append(instance)
        add_audit_log(
            db,
            actor,
            "item_instance_created",
            "item_instance",
            instance.id,
            new_value={
                "inventory_number": instance.inventory_number,
                "item_type_id": instance.item_type_id,
                "condition_status": instance.condition_status.value,
                "lifecycle_status": instance.lifecycle_status.value,
                "purchase_number": instance.purchase_number,
                "tags": parse_tags(instance.tags_text),
                "physical_location_type": instance.physical_location_type.value,
                "warehouse_location_text": instance.warehouse_location_text,
                "lab_location_id": instance.lab_location_id,
            },
        )

    add_audit_log(
        db,
        actor,
        "item_instances_bulk_created",
        "item_type",
        item_type.id,
        new_value={
            "quantity": quantity,
            "inventory_numbers": inventory_numbers,
            "item_type_id": item_type.id,
        },
    )
    db.commit()
    for instance in created_instances:
        db.refresh(instance)
    return created_instances


def snapshot_instance(instance: ItemInstance) -> dict[str, object]:
    return {
        "id": instance.id,
        "inventory_number": instance.inventory_number,
        "item_type_id": instance.item_type_id,
        "condition_status": instance.condition_status.value,
        "lifecycle_status": instance.lifecycle_status.value,
        "purchase_number": instance.purchase_number,
        "purchase_unit_price": str(instance.purchase_unit_price) if instance.purchase_unit_price is not None else None,
        "tags": parse_tags(instance.tags_text),
        "current_holder_user_id": instance.current_holder_user_id,
        "physical_location_type": instance.physical_location_type.value,
        "warehouse_location_text": instance.warehouse_location_text,
        "lab_location_id": instance.lab_location_id,
    }


def move_instances(
    db: Session,
    actor: User,
    instances: list[ItemInstance],
    physical_location_type: PhysicalLocationType,
    warehouse_location_text: str | None,
    lab_location: LabLocation | None,
    comment: str | None = None,
) -> list[ItemInstance]:
    instances = unique_instances(instances)
    ensure_instances_selected(instances)
    warehouse_value, lab_location_id = ensure_valid_location(
        physical_location_type=physical_location_type,
        warehouse_location_text=warehouse_location_text,
        lab_location=lab_location,
    )
    for instance in instances:
        old_value = snapshot_instance(instance)
        instance.physical_location_type = physical_location_type
        instance.warehouse_location_text = warehouse_value
        instance.lab_location_id = lab_location_id
        db.flush()
        add_audit_log(
            db,
            actor,
            "item_instance_moved",
            "item_instance",
            instance.id,
            old_value=old_value,
            new_value=snapshot_instance(instance),
            comment=comment,
        )
    db.commit()
    return instances


def find_active_issue(instance: ItemInstance) -> IssueRecord | None:
    for record in instance.issue_records:
        if record.returned_at is None:
            return record
    return None


def unique_instances(instances: list[ItemInstance]) -> list[ItemInstance]:
    return list({instance.id: instance for instance in instances}.values())


def ensure_instances_selected(instances: list[ItemInstance]) -> None:
    if not instances:
        raise ValueError("Не выбрано ни одного экземпляра.")


def issue_instances(
    db: Session,
    actor: User,
    instances: list[ItemInstance],
    issued_to_user: User,
    issued_at: datetime,
    issue_comment: str | None,
) -> list[IssueRecord]:
    instances = unique_instances(instances)
    ensure_instances_selected(instances)
    for instance in instances:
        if instance.lifecycle_status == LifecycleStatus.WRITTEN_OFF:
            raise ValueError(f"Экземпляр {instance.inventory_number} уже списан.")
        if instance.current_holder_user_id is not None:
            raise ValueError(f"Экземпляр {instance.inventory_number} уже выдан.")
        if instance.condition_status == ABSENT_CONDITION:
            raise ValueError(f"Экземпляр {instance.inventory_number} отсутствует и не может быть выдан.")

    cleaned_comment = (issue_comment or "").strip() or None
    issue_records: list[IssueRecord] = []
    for instance in instances:
        issue_record = IssueRecord(
            item_instance=instance,
            issued_to_user=issued_to_user,
            issued_by_user=actor,
            issued_at=issued_at,
            issue_comment=cleaned_comment,
            previous_physical_location_type=instance.physical_location_type,
            previous_warehouse_location_text=instance.warehouse_location_text,
            previous_lab_location_id=instance.lab_location_id,
        )
        old_value = snapshot_instance(instance)
        instance.current_holder = issued_to_user
        db.add(issue_record)
        db.flush()
        issue_records.append(issue_record)
        add_audit_log(
            db,
            actor,
            "item_issued",
            "item_instance",
            instance.id,
            old_value=old_value,
            new_value=snapshot_instance(instance),
            comment=issue_record.issue_comment,
        )
    db.commit()
    return issue_records


def return_instances(
    db: Session,
    actor: User,
    instances: list[ItemInstance],
    returned_at: datetime,
    physical_location_type: PhysicalLocationType | None,
    warehouse_location_text: str | None,
    lab_location: LabLocation | None,
    condition_status: ConditionStatus | None,
    comment: str | None,
) -> list[IssueRecord]:
    instances = unique_instances(instances)
    ensure_instances_selected(instances)
    active_issues: list[tuple[ItemInstance, IssueRecord]] = []
    for instance in instances:
        active_issue = find_active_issue(instance)
        if active_issue is None:
            raise ValueError(f"У экземпляра {instance.inventory_number} нет активной выдачи.")
        active_issues.append((instance, active_issue))

    if physical_location_type is not None:
        target_warehouse_value, target_lab_location_id = ensure_valid_location(
            physical_location_type=physical_location_type,
            warehouse_location_text=warehouse_location_text,
            lab_location=lab_location,
        )

    cleaned_comment = (comment or "").strip() or None
    for instance, active_issue in active_issues:
        if physical_location_type is None:
            location_type = active_issue.previous_physical_location_type
            warehouse_value = active_issue.previous_warehouse_location_text
            lab_location_id = active_issue.previous_lab_location_id
        else:
            location_type = physical_location_type
            warehouse_value = target_warehouse_value
            lab_location_id = target_lab_location_id

        old_value = snapshot_instance(instance)
        active_issue.returned_by_user = actor
        active_issue.returned_at = returned_at
        active_issue.return_physical_location_type = location_type
        active_issue.return_warehouse_location_text = warehouse_value
        active_issue.return_lab_location_id = lab_location_id

        instance.current_holder = None
        instance.physical_location_type = location_type
        instance.warehouse_location_text = warehouse_value
        instance.lab_location_id = lab_location_id
        if condition_status is not None:
            instance.condition_status = condition_status
        db.flush()
        add_audit_log(
            db,
            actor,
            "item_returned",
            "item_instance",
            instance.id,
            old_value=old_value,
            new_value=snapshot_instance(instance),
            comment=cleaned_comment,
        )
    db.commit()
    return [active_issue for _, active_issue in active_issues]


def return_instance(
    db: Session,
    actor: User,
    instance: ItemInstance,
    returned_at: datetime,
    physical_location_type: PhysicalLocationType | None,
    warehouse_location_text: str | None,
    lab_location: LabLocation | None,
    condition_status: ConditionStatus | None,
    comment: str | None,
) -> IssueRecord:
    if find_active_issue(instance) is None:
        raise ValueError("У экземпляра нет активной выдачи.")
    return return_instances(
        db=db,
        actor=actor,
        instances=[instance],
        returned_at=returned_at,
        physical_location_type=physical_location_type,
        warehouse_location_text=warehouse_location_text,
        lab_location=lab_location,
        condition_status=condition_status,
        comment=comment,
    )[0]


def change_condition_many(
    db: Session,
    actor: User,
    instances: list[ItemInstance],
    condition_status: ConditionStatus,
    comment: str | None,
) -> list[ItemInstance]:
    instances = unique_instances(instances)
    ensure_instances_selected(instances)
    cleaned_comment = (comment or "").strip() or None
    for instance in instances:
        old_value = snapshot_instance(instance)
        instance.condition_status = condition_status
        db.flush()
        add_audit_log(
            db,
            actor,
            "item_condition_changed",
            "item_instance",
            instance.id,
            old_value=old_value,
            new_value=snapshot_instance(instance),
            comment=cleaned_comment,
        )
    db.commit()
    return instances


def change_condition(
    db: Session,
    actor: User,
    instance: ItemInstance,
    condition_status: ConditionStatus,
    comment: str | None,
) -> ItemInstance:
    return change_condition_many(db, actor, [instance], condition_status, comment)[0]


def change_lifecycle_many(
    db: Session,
    actor: User,
    instances: list[ItemInstance],
    lifecycle_status: LifecycleStatus,
    comment: str | None,
) -> list[ItemInstance]:
    instances = unique_instances(instances)
    ensure_instances_selected(instances)
    cleaned_comment = (comment or "").strip() or None
    for instance in instances:
        old_value = snapshot_instance(instance)
        instance.lifecycle_status = lifecycle_status
        db.flush()
        add_audit_log(
            db,
            actor,
            "item_lifecycle_changed",
            "item_instance",
            instance.id,
            old_value=old_value,
            new_value=snapshot_instance(instance),
            comment=cleaned_comment,
        )
    db.commit()
    return instances


def change_lifecycle(
    db: Session,
    actor: User,
    instance: ItemInstance,
    lifecycle_status: LifecycleStatus,
    comment: str | None,
) -> ItemInstance:
    return change_lifecycle_many(db, actor, [instance], lifecycle_status, comment)[0]


def update_instance_details(
    db: Session,
    actor: User,
    instance: ItemInstance,
    inventory_number: str,
    purchase_number: str | None,
    purchase_unit_price: Decimal | None,
    tags_text: str | None,
) -> ItemInstance:
    cleaned_inventory_number = (inventory_number or "").strip()
    if not cleaned_inventory_number:
        raise ValueError("Инвентарный номер не может быть пустым.")

    existing_instance = db.scalar(
        select(ItemInstance).where(
            ItemInstance.inventory_number == cleaned_inventory_number,
            ItemInstance.id != instance.id,
        )
    )
    if existing_instance is not None:
        raise ValueError("Экземпляр с таким инвентарным номером уже существует.")

    old_value = snapshot_instance(instance)
    instance.inventory_number = cleaned_inventory_number
    instance.purchase_number = (purchase_number or "").strip() or None
    instance.purchase_unit_price = purchase_unit_price
    instance.tags_text = normalize_tags(tags_text)
    db.flush()
    add_audit_log(
        db,
        actor,
        "item_instance_updated",
        "item_instance",
        instance.id,
        old_value=old_value,
        new_value=snapshot_instance(instance),
        comment="Обновлены учетные поля экземпляра.",
    )
    db.commit()
    db.refresh(instance)
    return instance


def delete_instances(db: Session, actor: User, instances: list[ItemInstance]) -> None:
    instances = unique_instances(instances)
    ensure_instances_selected(instances)
    for instance in instances:
        add_audit_log(
            db,
            actor,
            "item_instance_deleted",
            "item_instance",
            instance.id,
            old_value={
                **snapshot_instance(instance),
                "issue_records_count": len(instance.issue_records),
            },
            comment="Экземпляр удален безвозвратно.",
        )
        for issue_record in list(instance.issue_records):
            db.delete(issue_record)
        db.delete(instance)
    db.commit()


def delete_instance(db: Session, actor: User, instance: ItemInstance) -> None:
    delete_instances(db, actor, [instance])


def delete_item_type(db: Session, actor: User, item_type: ItemType) -> None:
    active_instances_count = db.scalar(
        select(ItemInstance.id)
        .where(
            ItemInstance.item_type_id == item_type.id,
            ItemInstance.lifecycle_status == LifecycleStatus.ACTIVE,
        )
        .limit(1)
    )
    if active_instances_count is not None:
        raise ValueError("Тип можно удалить только если у него нет активных экземпляров.")
    written_off_instances = list(item_type.instances)
    add_audit_log(
        db,
        actor,
        "item_type_deleted",
        "item_type",
        item_type.id,
        old_value={
            "name": item_type.name,
            "comment": item_type.comment,
            "store_url": item_type.store_url,
            "unit_label": item_type.unit_label,
            "unit_price": str(item_type.unit_price),
            "tags": parse_tags(item_type.tags_text),
            "deleted_written_off_instances": [instance.inventory_number for instance in written_off_instances],
        },
    )
    for instance in written_off_instances:
        add_audit_log(
            db,
            actor,
            "item_instance_deleted",
            "item_instance",
            instance.id,
            old_value={
                **snapshot_instance(instance),
                "issue_records_count": len(instance.issue_records),
            },
            comment="Списанный экземпляр удален вместе с типом.",
        )
        for issue_record in list(instance.issue_records):
            db.delete(issue_record)
        db.delete(instance)
    db.flush()
    db.delete(item_type)
    db.commit()


def filter_instances(
    instances: list[ItemInstance],
    location_path_map: dict[int, str],
    query: str | None,
    condition_status: str | None,
    lifecycle_status: str | None,
    holder_query: str | None,
    include_written_off: bool,
) -> list[ItemInstance]:
    query_text = (query or "").strip().lower()
    holder_text = (holder_query or "").strip().lower()
    filtered: list[ItemInstance] = []
    for instance in instances:
        if not include_written_off and instance.lifecycle_status == LifecycleStatus.WRITTEN_OFF:
            continue
        if condition_status and instance.condition_status.value != condition_status:
            continue
        if lifecycle_status and instance.lifecycle_status.value != lifecycle_status:
            continue
        if holder_text:
            holder_name = instance.current_holder.full_name.lower() if instance.current_holder else ""
            if holder_text not in holder_name:
                continue
        if query_text:
            searchable_parts = [
                instance.item_type.name,
                instance.inventory_number,
                instance.item_type.tags_text,
                instance.tags_text,
                instance.warehouse_location_text or "",
                location_path_map.get(instance.lab_location_id, "") if instance.lab_location_id else "",
                instance.current_holder.full_name if instance.current_holder else "",
                instance.purchase_number or "",
                instance.condition_status.value,
                instance.lifecycle_status.value,
            ]
            if not any(query_text in (part or "").lower() for part in searchable_parts):
                continue
        filtered.append(instance)
    return filtered


def summarize_named_counts(values: list[str]) -> list[HolderSummary]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return [HolderSummary(label=label, count=count) for label, count in counts.items() if count > 0]


def group_inventory_instances(instances: list[ItemInstance], all_locations: list[LabLocation]) -> list[InventoryGroup]:
    _, location_path_map = build_location_maps(all_locations)
    grouped: dict[str, InventoryGroup] = {}
    totals_by_type: dict[int, dict[str, Decimal]] = {}

    for instance in instances:
        effective_price = item_effective_unit_price(instance)
        type_totals = totals_by_type.setdefault(
            instance.item_type_id,
            {"all": Decimal("0.00"), "active": Decimal("0.00")},
        )
        type_totals["all"] += effective_price
        if instance.lifecycle_status == LifecycleStatus.ACTIVE:
            type_totals["active"] += effective_price

    for instance in instances:
        key = str(instance.item_type_id)
        if key not in grouped:
            grouped[key] = InventoryGroup(
                key=key,
                item_type=instance.item_type,
                physical_location_type=PhysicalLocationType.NONE,
                location_display="Не указано",
            )

        group = grouped[key]
        group.instances.append(instance)
        group.purchase_total += item_effective_unit_price(instance)
        group.type_total_all = totals_by_type[instance.item_type_id]["all"]
        group.type_total_active = totals_by_type[instance.item_type_id]["active"]
        if instance.purchase_number:
            group.unique_purchase_numbers.append(instance.purchase_number)

        location = resolve_location_snapshot(instance, location_path_map)
        group.warehouse_locations.append(location.display_text)

    for group in grouped.values():
        holder_labels: list[str] = []
        condition_counts = {status: 0 for status in ConditionStatus}
        lifecycle_counts = {status: 0 for status in LifecycleStatus}
        instance_tag_set: list[str] = []
        seen_instance_tags: set[str] = set()

        group.instances.sort(key=lambda item: item.inventory_number.lower())
        group.count_received = len(group.instances)
        group.count_factual = sum(1 for instance in group.instances if is_factual_instance(instance))
        group.count_available = sum(
            1
            for instance in group.instances
            if is_factual_instance(instance) and instance.current_holder_user_id is None
        )
        group.count_official = sum(1 for instance in group.instances if is_official_instance(instance))
        group.issue_ready_count = sum(1 for instance in group.instances if is_issuable_instance(instance))

        for instance in group.instances:
            holder_labels.append(instance.current_holder.full_name if instance.current_holder else "Не выдано")
            condition_counts[instance.condition_status] += 1
            lifecycle_counts[instance.lifecycle_status] += 1
            for tag in parse_tags(instance.tags_text):
                normalized = tag.lower()
                if normalized not in seen_instance_tags:
                    seen_instance_tags.add(normalized)
                    instance_tag_set.append(tag)

        group.type_tags = parse_tags(group.item_type.tags_text)
        group.instance_tags = instance_tag_set
        group.unique_purchase_numbers = list(dict.fromkeys(group.unique_purchase_numbers))
        group.holders = summarize_named_counts(holder_labels)
        group.condition_summaries = [
            HolderSummary(label=condition_label(status), count=count)
            for status, count in condition_counts.items()
            if count > 0
        ]
        group.lifecycle_summaries = [
            HolderSummary(label=lifecycle_label(status), count=count)
            for status, count in lifecycle_counts.items()
            if count > 0
        ]
        group.warehouse_locations = list(dict.fromkeys(group.warehouse_locations))
        group.location_display = ", ".join(group.warehouse_locations) if group.warehouse_locations else "Не указано"

    return sorted(
        grouped.values(),
        key=lambda group: (
            group.item_type.name.lower(),
        ),
    )


def group_item_type_instances(
    instances: list[ItemInstance],
    all_locations: list[LabLocation],
    group_by: str = "purchase",
) -> list[ItemTypeGroup]:
    _, location_path_map = build_location_maps(all_locations)
    grouped: dict[str, ItemTypeGroup] = {}

    for instance in instances:
        location = resolve_location_snapshot(instance, location_path_map)
        purchase_label = format_purchase_label(instance.purchase_number)
        if group_by == "location":
            key = "|".join(
                [
                    instance.condition_status.value,
                    instance.lifecycle_status.value,
                    location.physical_location_type.value,
                    location.warehouse_location_text or "",
                    str(location.lab_location_id or ""),
                ]
            )
        else:
            key = "|".join(
                [
                    instance.condition_status.value,
                    instance.lifecycle_status.value,
                    purchase_label,
                ]
            )

        if key not in grouped:
            grouped[key] = ItemTypeGroup(
                key=key,
                condition_status=instance.condition_status,
                lifecycle_status=instance.lifecycle_status,
                count=0,
            )

        group = grouped[key]
        group.count += 1
        group.instances.append(instance)
        group.location_texts.append(location.display_text)
        group.unique_purchase_numbers.append(purchase_label)

    for group in grouped.values():
        instance_tag_set: list[str] = []
        seen_instance_tags: set[str] = set()
        for instance in group.instances:
            for tag in parse_tags(instance.tags_text):
                normalized = tag.lower()
                if normalized not in seen_instance_tags:
                    seen_instance_tags.add(normalized)
                    instance_tag_set.append(tag)

        group.instance_tags = instance_tag_set
        group.location_texts = list(dict.fromkeys(group.location_texts))
        group.unique_purchase_numbers = list(dict.fromkeys(group.unique_purchase_numbers))
        group.location_display = ", ".join(group.location_texts) if group.location_texts else "Не указано"
        group.purchase_display = ", ".join(group.unique_purchase_numbers) if group.unique_purchase_numbers else "Без сч.Фак"
        group.instances.sort(key=lambda item: item.inventory_number.lower())

    return sorted(
        grouped.values(),
        key=lambda group: (
            group.condition_status.value,
            group.lifecycle_status.value,
            group.location_display.lower(),
            group.purchase_display.lower(),
        ),
    )


def get_inventory_group_instances(
    instances: list[ItemInstance],
    all_locations: list[LabLocation],
    group_key: str,
) -> list[ItemInstance]:
    groups = {group.key: group for group in group_inventory_instances(instances, all_locations)}
    if group_key not in groups:
        return []
    return sorted(groups[group_key].instances, key=lambda item: item.id)
