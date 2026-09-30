from __future__ import annotations

from dataclasses import dataclass, field
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PhysicalLocationType
from app.models.item_instance import ItemInstance
from app.models.lab_location import LabLocation
from app.models.user import User
from app.models.warehouse_location import WarehouseLocation
from app.services.audit import add_audit_log


@dataclass
class LocationNode:
    location: LabLocation
    full_path: str
    children: list["LocationNode"] = field(default_factory=list)


@dataclass
class LocationOption:
    id: int
    label: str


@dataclass
class WarehouseLocationChoice:
    id: int | None
    value: str
    display_label: str
    full_label: str
    room: str | None = None
    comment: str | None = None
    is_preset: bool = True


@dataclass
class WarehouseLocationGroup:
    title: str
    options: list[WarehouseLocationChoice] = field(default_factory=list)


_NATURAL_PARTS_RE = re.compile(r"(\d+)")


def natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    parts = _NATURAL_PARTS_RE.split(value.strip())
    key: list[tuple[int, int | str]] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.lower()))
    return tuple(key)


def build_location_maps(locations: list[LabLocation]) -> tuple[dict[int, LabLocation], dict[int, str]]:
    by_id = {location.id: location for location in locations}
    path_map: dict[int, str] = {}

    def resolve_path(location: LabLocation) -> str:
        if location.id in path_map:
            return path_map[location.id]
        parts = [f"{location.type_label} {location.name}"]
        current = location.parent
        while current is not None:
            parts.append(f"{current.type_label} {current.name}")
            current = current.parent
        path = " / ".join(reversed(parts))
        path_map[location.id] = path
        return path

    for location in locations:
        resolve_path(location)
    return by_id, path_map


def build_location_tree(locations: list[LabLocation]) -> list[LocationNode]:
    by_parent: dict[int | None, list[LabLocation]] = {}
    for location in locations:
        by_parent.setdefault(location.parent_id, []).append(location)

    _, path_map = build_location_maps(locations)

    def build_children(parent_id: int | None) -> list[LocationNode]:
        nodes: list[LocationNode] = []
        for location in sorted(
            by_parent.get(parent_id, []),
            key=lambda item: (natural_sort_key(item.type_label), natural_sort_key(item.name)),
        ):
            nodes.append(
                LocationNode(
                    location=location,
                    full_path=path_map[location.id],
                    children=build_children(location.id),
                )
            )
        return nodes

    return build_children(None)


def build_location_options(locations: list[LabLocation]) -> list[LocationOption]:
    _, path_map = build_location_maps(locations)
    return [
        LocationOption(id=location.id, label=path_map[location.id])
        for location in sorted(locations, key=lambda item: natural_sort_key(path_map[item.id]))
    ]


def format_warehouse_location_label(room: str, slot_code: str) -> str:
    return f"{room.strip()} / {slot_code.strip()}"


def build_warehouse_location_groups(locations: list[WarehouseLocation]) -> list[WarehouseLocationGroup]:
    groups: dict[str, list[WarehouseLocationChoice]] = {}
    for location in locations:
        label = format_warehouse_location_label(location.room, location.slot_code)
        groups.setdefault(location.room, []).append(
            WarehouseLocationChoice(
                id=location.id,
                value=label,
                display_label=location.slot_code,
                full_label=label,
                room=location.room,
                comment=location.comment,
                is_preset=True,
            )
        )

    result: list[WarehouseLocationGroup] = []
    for room in sorted(groups, key=natural_sort_key):
        options = sorted(groups[room], key=lambda option: natural_sort_key(option.display_label))
        result.append(WarehouseLocationGroup(title=room, options=options))
    return result


def build_warehouse_location_select_groups(
    locations: list[WarehouseLocation],
    selected_label: str | None = None,
) -> list[WarehouseLocationGroup]:
    groups = build_warehouse_location_groups(locations)
    known_values = {option.value for group in groups for option in group.options}
    extra_value = (selected_label or "").strip()
    if extra_value and extra_value not in known_values:
        groups.append(
            WarehouseLocationGroup(
                title="Прочие адреса",
                options=[
                    WarehouseLocationChoice(
                        id=None,
                        value=extra_value,
                        display_label=extra_value,
                        full_label=extra_value,
                        room=None,
                        comment=None,
                        is_preset=False,
                    )
                ],
            )
        )
    return groups


def is_location_empty(db: Session, location: LabLocation) -> bool:
    has_children = any(True for _ in location.children)
    if has_children:
        return False
    item_count = db.scalar(select(ItemInstance.id).where(ItemInstance.lab_location_id == location.id).limit(1))
    return item_count is None


def create_location(
    db: Session,
    actor: User,
    type_label: str,
    name: str,
    comment: str | None,
    parent: LabLocation | None,
) -> LabLocation:
    location = LabLocation(
        type_label=type_label.strip(),
        name=name.strip(),
        comment=(comment or "").strip() or None,
        parent=parent,
    )
    db.add(location)
    db.flush()
    add_audit_log(
        db,
        actor,
        "lab_location_created",
        "lab_location",
        location.id,
        new_value={
            "type_label": location.type_label,
            "name": location.name,
            "comment": location.comment,
            "parent_id": location.parent_id,
        },
    )
    db.commit()
    db.refresh(location)
    return location


def update_location(
    db: Session,
    actor: User,
    location: LabLocation,
    type_label: str,
    name: str,
    comment: str | None,
    parent: LabLocation | None,
) -> LabLocation:
    if parent and parent.id == location.id:
        raise ValueError("Нельзя сделать место родителем самого себя.")
    if location.parent_id != (parent.id if parent else None) and not is_location_empty(db, location):
        raise ValueError("Перемещать можно только пустое лабораторное место.")

    old_value = {
        "type_label": location.type_label,
        "name": location.name,
        "comment": location.comment,
        "parent_id": location.parent_id,
    }
    location.type_label = type_label.strip()
    location.name = name.strip()
    location.comment = (comment or "").strip() or None
    location.parent = parent
    db.flush()
    add_audit_log(
        db,
        actor,
        "lab_location_updated",
        "lab_location",
        location.id,
        old_value=old_value,
        new_value={
            "type_label": location.type_label,
            "name": location.name,
            "comment": location.comment,
            "parent_id": location.parent_id,
        },
    )
    db.commit()
    db.refresh(location)
    return location


def delete_location(db: Session, actor: User, location: LabLocation) -> None:
    if not is_location_empty(db, location):
        raise ValueError("Удалять можно только пустое лабораторное место.")
    old_value = {
        "type_label": location.type_label,
        "name": location.name,
        "comment": location.comment,
        "parent_id": location.parent_id,
    }
    add_audit_log(
        db,
        actor,
        "lab_location_deleted",
        "lab_location",
        location.id,
        old_value=old_value,
    )
    db.delete(location)
    db.commit()


def create_warehouse_location(
    db: Session,
    actor: User,
    room: str,
    slot_code: str,
    comment: str | None,
) -> WarehouseLocation:
    cleaned_room = room.strip()
    cleaned_slot_code = slot_code.strip()
    if not cleaned_room:
        raise ValueError("Для складского места нужно указать комнату.")
    if not cleaned_slot_code:
        raise ValueError("Для складского места нужно указать номер.")

    existing = db.scalar(
        select(WarehouseLocation).where(
            WarehouseLocation.room == cleaned_room,
            WarehouseLocation.slot_code == cleaned_slot_code,
        )
    )
    if existing is not None:
        raise ValueError("Такое складское место уже существует.")

    location = WarehouseLocation(
        room=cleaned_room,
        slot_code=cleaned_slot_code,
        comment=(comment or "").strip() or None,
    )
    db.add(location)
    db.flush()
    add_audit_log(
        db,
        actor,
        "warehouse_location_created",
        "warehouse_location",
        location.id,
        new_value={
            "room": location.room,
            "slot_code": location.slot_code,
            "label": format_warehouse_location_label(location.room, location.slot_code),
            "comment": location.comment,
        },
    )
    db.commit()
    db.refresh(location)
    return location


def delete_warehouse_location(db: Session, actor: User, location: WarehouseLocation) -> None:
    location_label = format_warehouse_location_label(location.room, location.slot_code)
    in_use_instance_id = db.scalar(
        select(ItemInstance.id)
        .where(
            ItemInstance.physical_location_type == PhysicalLocationType.WAREHOUSE,
            ItemInstance.warehouse_location_text == location_label,
        )
        .limit(1)
    )
    if in_use_instance_id is not None:
        raise ValueError("Нельзя удалить складское место, пока к нему привязаны экземпляры.")

    add_audit_log(
        db,
        actor,
        "warehouse_location_deleted",
        "warehouse_location",
        location.id,
        old_value={
            "room": location.room,
            "slot_code": location.slot_code,
            "label": location_label,
            "comment": location.comment,
        },
    )
    db.delete(location)
    db.commit()
