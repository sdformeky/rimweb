from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.enums import ConditionStatus, LifecycleStatus
from app.models.issue_record import IssueRecord
from app.models.item_instance import ItemInstance
from app.models.item_type import ItemType
from app.models.lab_location import LabLocation
from app.models.user import User
from app.models.warehouse_location import WarehouseLocation
from app.repositories import audit as audit_repo
from app.repositories import inventory as inventory_repo
from app.repositories import locations as location_repo
from app.repositories import users as user_repo
from app.schemas.api import (
    AuditLogOut,
    BulkComment,
    BulkCondition,
    BulkIssue,
    BulkMove,
    BulkResult,
    BulkReturn,
    BulkSelection,
    InstanceOut,
    InstancesCreate,
    InstanceUpdate,
    IssueRecordOut,
    ItemTypeCreate,
    ItemTypeOut,
    ItemTypeShort,
    ItemTypeUpdate,
    LabLocationCreate,
    LabLocationOut,
    LabLocationUpdate,
    LocationIn,
    LocationOut,
    UserOut,
    UserShort,
    WarehouseLocationCreate,
    WarehouseLocationOut,
)
from app.services import inventory as inventory_service
from app.services import locations as location_service
from app.utils.tags import parse_tags


router = APIRouter(prefix="/api/v1", tags=["api"])


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} не найден(о).")


def bad_request(error: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


def tags_to_text(tags: list[str] | None) -> str:
    return ", ".join(tags or [])


def to_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def location_path_map(db: Session) -> dict[int, str]:
    _, path_map = location_service.build_location_maps(location_repo.list_locations(db))
    return path_map


def resolve_lab_location(db: Session, location: LocationIn | None) -> LabLocation | None:
    if location is None or location.lab_location_id is None:
        return None
    lab_location = location_repo.get_location(db, location.lab_location_id)
    if lab_location is None:
        raise not_found("Лабораторное место")
    return lab_location


def load_instances(db: Session, instance_ids: list[int]) -> list[ItemInstance]:
    requested_ids = set(instance_ids)
    instances = inventory_repo.get_instances_by_ids(db, list(requested_ids))
    missing_ids = requested_ids - {instance.id for instance in instances}
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Экземпляры не найдены.", "missing_ids": sorted(missing_ids)},
        )
    return instances


def get_instance_or_404(db: Session, instance_id: int) -> ItemInstance:
    instance = inventory_repo.get_instance(db, instance_id)
    if instance is None:
        raise not_found("Экземпляр")
    return instance


def get_item_type_or_404(db: Session, item_type_id: int) -> ItemType:
    item_type = inventory_repo.get_item_type(db, item_type_id)
    if item_type is None:
        raise not_found("Тип предмета")
    return item_type


def get_user_or_404(db: Session, user_id: int) -> User:
    user = user_repo.get_user_by_id(db, user_id)
    if user is None:
        raise not_found("Пользователь")
    return user


def bulk_result(instances: list[ItemInstance]) -> BulkResult:
    ids = sorted({instance.id for instance in instances})
    return BulkResult(affected=len(ids), instance_ids=ids)


def user_short(user: User | None) -> UserShort | None:
    if user is None:
        return None
    return UserShort(id=user.id, full_name=user.full_name, nickname=user.nickname)


def user_out(user: User, active_issues_count: int | None = None) -> UserOut:
    return UserOut(
        id=user.id,
        full_name=user.full_name,
        nickname=user.nickname,
        email=user.email,
        department=user.department,
        role=user.role,
        active_issues_count=active_issues_count,
    )


def item_type_out(item_type: ItemType) -> ItemTypeOut:
    return ItemTypeOut(
        id=item_type.id,
        name=item_type.name,
        comment=item_type.comment,
        store_url=item_type.store_url,
        unit_label=item_type.unit_label,
        unit_price=item_type.unit_price,
        tags=parse_tags(item_type.tags_text),
        created_at=item_type.created_at,
        updated_at=item_type.updated_at,
    )


def instance_out(instance: ItemInstance, path_map: dict[int, str]) -> InstanceOut:
    snapshot = inventory_service.resolve_location_snapshot(instance, path_map)
    return InstanceOut(
        id=instance.id,
        inventory_number=instance.inventory_number,
        item_type=ItemTypeShort(id=instance.item_type.id, name=instance.item_type.name),
        condition_status=instance.condition_status,
        lifecycle_status=instance.lifecycle_status,
        purchase_number=instance.purchase_number,
        purchase_unit_price=instance.purchase_unit_price,
        tags=parse_tags(instance.tags_text),
        current_holder=user_short(instance.current_holder),
        location=LocationOut(
            type=snapshot.physical_location_type,
            warehouse_location_text=snapshot.warehouse_location_text,
            lab_location_id=snapshot.lab_location_id,
            display=snapshot.display_text,
        ),
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )


def issue_record_out(record: IssueRecord) -> IssueRecordOut:
    instance = record.item_instance
    return IssueRecordOut(
        id=record.id,
        instance_id=instance.id,
        inventory_number=instance.inventory_number,
        item_type=ItemTypeShort(id=instance.item_type.id, name=instance.item_type.name),
        issued_to=user_short(record.issued_to_user),
        issued_by=user_short(record.issued_by_user),
        returned_by=user_short(record.returned_by_user),
        issued_at=record.issued_at,
        returned_at=record.returned_at,
        comment=record.issue_comment,
    )


def lab_location_out(location: LabLocation, path_map: dict[int, str]) -> LabLocationOut:
    return LabLocationOut(
        id=location.id,
        parent_id=location.parent_id,
        type_label=location.type_label,
        name=location.name,
        comment=location.comment,
        path=path_map.get(location.id, f"{location.type_label} {location.name}"),
    )


def warehouse_location_out(location: WarehouseLocation) -> WarehouseLocationOut:
    return WarehouseLocationOut(
        id=location.id,
        room=location.room,
        slot_code=location.slot_code,
        label=location_service.format_warehouse_location_label(location.room, location.slot_code),
        comment=location.comment,
    )


def audit_log_out(log: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=log.id,
        actor=user_short(log.actor),
        action_type=log.action_type,
        entity_type=log.entity_type,
        entity_id=log.entity_id,
        old_value_json=log.old_value_json,
        new_value_json=log.new_value_json,
        comment=log.comment,
        created_at=log.created_at,
    )


@router.get("/me", response_model=UserOut)
def api_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return user_out(current_user, user_repo.count_active_issues_for_user(db, current_user.id))


@router.get("/users", response_model=list[UserOut])
def api_users(
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return [user_out(user, user_repo.count_active_issues_for_user(db, user.id)) for user in user_repo.list_users(db, q)]


@router.get("/users/{user_id}", response_model=UserOut)
def api_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user = get_user_or_404(db, user_id)
    return user_out(user, user_repo.count_active_issues_for_user(db, user.id))


@router.get("/users/{user_id}/instances", response_model=list[InstanceOut])
def api_user_instances(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_or_404(db, user_id)
    path_map = location_path_map(db)
    instances = inventory_repo.get_instances_by_ids(
        db, [instance.id for instance in inventory_repo.list_active_instances_for_user(db, user_id)]
    )
    return [instance_out(instance, path_map) for instance in instances]


@router.get("/users/{user_id}/issues", response_model=list[IssueRecordOut])
def api_user_issues(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_or_404(db, user_id)
    return [issue_record_out(record) for record in inventory_repo.list_issue_records_for_user(db, user_id)]


@router.get("/item-types", response_model=list[ItemTypeOut])
def api_item_types(
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return [item_type_out(item_type) for item_type in inventory_repo.list_item_types(db, q)]


@router.post("/item-types", response_model=ItemTypeOut, status_code=status.HTTP_201_CREATED)
def api_item_type_create(
    payload: ItemTypeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        item_type = inventory_service.create_item_type(
            db=db,
            actor=current_user,
            name=payload.name,
            comment=payload.comment,
            store_url=payload.store_url,
            unit_label=payload.unit_label,
            unit_price=payload.unit_price,
            tags_text=tags_to_text(payload.tags),
        )
    except ValueError as error:
        raise bad_request(error) from error
    return item_type_out(item_type)


@router.get("/item-types/{item_type_id}", response_model=ItemTypeOut)
def api_item_type(item_type_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return item_type_out(get_item_type_or_404(db, item_type_id))


@router.patch("/item-types/{item_type_id}", response_model=ItemTypeOut)
def api_item_type_update(
    item_type_id: int,
    payload: ItemTypeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    item_type = get_item_type_or_404(db, item_type_id)
    fields = payload.model_fields_set
    try:
        item_type = inventory_service.update_item_type(
            db=db,
            actor=current_user,
            item_type=item_type,
            name=payload.name if "name" in fields and payload.name else item_type.name,
            comment=payload.comment if "comment" in fields else item_type.comment,
            store_url=payload.store_url if "store_url" in fields else item_type.store_url,
            unit_label=payload.unit_label if "unit_label" in fields else item_type.unit_label,
            unit_price=payload.unit_price if "unit_price" in fields and payload.unit_price is not None else item_type.unit_price,
            tags_text=tags_to_text(payload.tags) if "tags" in fields else item_type.tags_text,
        )
    except ValueError as error:
        raise bad_request(error) from error
    return item_type_out(item_type)


@router.delete("/item-types/{item_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_item_type_delete(
    item_type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    item_type = get_item_type_or_404(db, item_type_id)
    try:
        inventory_service.delete_item_type(db, current_user, item_type)
    except ValueError as error:
        raise bad_request(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/instances/issue", response_model=BulkResult)
def api_instances_issue(
    payload: BulkIssue,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = get_user_or_404(db, payload.user_id)
    instances = load_instances(db, payload.instance_ids)
    try:
        inventory_service.issue_instances(db, current_user, instances, user, to_utc(payload.issued_at), payload.comment)
    except ValueError as error:
        raise bad_request(error) from error
    return bulk_result(instances)


@router.post("/instances/return", response_model=BulkResult)
def api_instances_return(
    payload: BulkReturn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instances = load_instances(db, payload.instance_ids)
    lab_location = resolve_lab_location(db, payload.location)
    try:
        inventory_service.return_instances(
            db=db,
            actor=current_user,
            instances=instances,
            returned_at=to_utc(payload.returned_at),
            physical_location_type=payload.location.type if payload.location else None,
            warehouse_location_text=payload.location.warehouse_location_text if payload.location else None,
            lab_location=lab_location,
            condition_status=payload.condition_status,
            comment=payload.comment,
        )
    except ValueError as error:
        raise bad_request(error) from error
    return bulk_result(instances)


@router.post("/instances/move", response_model=BulkResult)
def api_instances_move(
    payload: BulkMove,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instances = load_instances(db, payload.instance_ids)
    lab_location = resolve_lab_location(db, payload.location)
    try:
        inventory_service.move_instances(
            db,
            current_user,
            instances,
            payload.location.type,
            payload.location.warehouse_location_text,
            lab_location,
            comment=payload.comment,
        )
    except ValueError as error:
        raise bad_request(error) from error
    return bulk_result(instances)


@router.post("/instances/condition", response_model=BulkResult)
def api_instances_condition(
    payload: BulkCondition,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instances = load_instances(db, payload.instance_ids)
    try:
        inventory_service.change_condition_many(db, current_user, instances, payload.condition_status, payload.comment)
    except ValueError as error:
        raise bad_request(error) from error
    return bulk_result(instances)


@router.post("/instances/write-off", response_model=BulkResult)
def api_instances_write_off(
    payload: BulkComment,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instances = load_instances(db, payload.instance_ids)
    try:
        inventory_service.change_lifecycle_many(db, current_user, instances, LifecycleStatus.WRITTEN_OFF, payload.comment)
    except ValueError as error:
        raise bad_request(error) from error
    return bulk_result(instances)


@router.post("/instances/delete", response_model=BulkResult)
def api_instances_delete(
    payload: BulkSelection,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instances = load_instances(db, payload.instance_ids)
    result = bulk_result(instances)
    try:
        inventory_service.delete_instances(db, current_user, instances)
    except ValueError as error:
        raise bad_request(error) from error
    return result


@router.get("/instances", response_model=list[InstanceOut])
def api_instances(
    response: Response,
    q: str | None = None,
    item_type_id: int | None = None,
    holder_user_id: int | None = None,
    condition_status: ConditionStatus | None = None,
    lifecycle_status: LifecycleStatus | None = None,
    available: bool | None = Query(default=None, description="true — только свободные, false — только выданные"),
    include_written_off: bool = True,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    path_map = location_path_map(db)
    instances = inventory_service.filter_instances(
        instances=inventory_repo.list_instances_with_related(db),
        location_path_map=path_map,
        query=q,
        condition_status=condition_status.value if condition_status else None,
        lifecycle_status=lifecycle_status.value if lifecycle_status else None,
        holder_query=None,
        include_written_off=include_written_off,
    )
    if item_type_id is not None:
        instances = [instance for instance in instances if instance.item_type_id == item_type_id]
    if holder_user_id is not None:
        instances = [instance for instance in instances if instance.current_holder_user_id == holder_user_id]
    if available is True:
        instances = [instance for instance in instances if instance.current_holder_user_id is None]
    elif available is False:
        instances = [instance for instance in instances if instance.current_holder_user_id is not None]
    response.headers["X-Total-Count"] = str(len(instances))
    return [instance_out(instance, path_map) for instance in instances[offset : offset + limit]]


@router.post("/instances", response_model=list[InstanceOut], status_code=status.HTTP_201_CREATED)
def api_instances_create(
    payload: InstancesCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    item_type = get_item_type_or_404(db, payload.item_type_id)
    lab_location = resolve_lab_location(db, payload.location)
    manual_numbers = payload.inventory_numbers or []
    quantity = len(manual_numbers) if manual_numbers else payload.quantity
    try:
        created = inventory_service.create_instances(
            db=db,
            actor=current_user,
            item_type=item_type,
            quantity=quantity,
            manual_inventory_numbers=manual_numbers,
            auto_generate_inventory_numbers=not manual_numbers,
            condition_status=payload.condition_status,
            purchase_number=payload.purchase_number,
            purchase_unit_price=payload.purchase_unit_price,
            tags_text=tags_to_text(payload.tags),
            physical_location_type=payload.location.type,
            warehouse_location_text=payload.location.warehouse_location_text,
            lab_location=lab_location,
        )
    except ValueError as error:
        raise bad_request(error) from error
    path_map = location_path_map(db)
    return [instance_out(instance, path_map) for instance in load_instances(db, [item.id for item in created])]


@router.get("/instances/{instance_id}", response_model=InstanceOut)
def api_instance(instance_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return instance_out(get_instance_or_404(db, instance_id), location_path_map(db))


@router.patch("/instances/{instance_id}", response_model=InstanceOut)
def api_instance_update(
    instance_id: int,
    payload: InstanceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instance = get_instance_or_404(db, instance_id)
    fields = payload.model_fields_set
    try:
        if fields & {"inventory_number", "purchase_number", "purchase_unit_price", "tags"}:
            inventory_service.update_instance_details(
                db=db,
                actor=current_user,
                instance=instance,
                inventory_number=payload.inventory_number if "inventory_number" in fields else instance.inventory_number,
                purchase_number=payload.purchase_number if "purchase_number" in fields else instance.purchase_number,
                purchase_unit_price=(
                    payload.purchase_unit_price if "purchase_unit_price" in fields else instance.purchase_unit_price
                ),
                tags_text=tags_to_text(payload.tags) if "tags" in fields else instance.tags_text,
            )
        if payload.condition_status is not None and payload.condition_status != instance.condition_status:
            inventory_service.change_condition(db, current_user, instance, payload.condition_status, payload.comment)
        if payload.lifecycle_status is not None and payload.lifecycle_status != instance.lifecycle_status:
            inventory_service.change_lifecycle(db, current_user, instance, payload.lifecycle_status, payload.comment)
    except ValueError as error:
        db.rollback()
        raise bad_request(error) from error
    return instance_out(get_instance_or_404(db, instance_id), location_path_map(db))


@router.delete("/instances/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_instance_delete(
    instance_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    inventory_service.delete_instance(db, current_user, get_instance_or_404(db, instance_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/instances/{instance_id}/issues", response_model=list[IssueRecordOut])
def api_instance_issues(instance_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    instance = get_instance_or_404(db, instance_id)
    return [issue_record_out(record) for record in instance.issue_records]


@router.get("/lab-locations", response_model=list[LabLocationOut])
def api_lab_locations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    locations = location_repo.list_locations(db)
    _, path_map = location_service.build_location_maps(locations)
    return [lab_location_out(location, path_map) for location in locations]


@router.post("/lab-locations", response_model=LabLocationOut, status_code=status.HTTP_201_CREATED)
def api_lab_location_create(
    payload: LabLocationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    parent = None
    if payload.parent_id is not None:
        parent = location_repo.get_location(db, payload.parent_id)
        if parent is None:
            raise not_found("Родительское место")
    location = location_service.create_location(db, current_user, payload.type_label, payload.name, payload.comment, parent)
    return lab_location_out(location, location_path_map(db))


@router.patch("/lab-locations/{location_id}", response_model=LabLocationOut)
def api_lab_location_update(
    location_id: int,
    payload: LabLocationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    location = location_repo.get_location(db, location_id)
    if location is None:
        raise not_found("Лабораторное место")
    fields = payload.model_fields_set
    parent = location.parent
    if "parent_id" in fields:
        parent = None
        if payload.parent_id is not None:
            parent = location_repo.get_location(db, payload.parent_id)
            if parent is None:
                raise not_found("Родительское место")
    try:
        location = location_service.update_location(
            db,
            current_user,
            location,
            type_label=payload.type_label if "type_label" in fields and payload.type_label else location.type_label,
            name=payload.name if "name" in fields and payload.name else location.name,
            comment=payload.comment if "comment" in fields else location.comment,
            parent=parent,
        )
    except ValueError as error:
        raise bad_request(error) from error
    return lab_location_out(location, location_path_map(db))


@router.delete("/lab-locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_lab_location_delete(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    location = location_repo.get_location(db, location_id)
    if location is None:
        raise not_found("Лабораторное место")
    try:
        location_service.delete_location(db, current_user, location)
    except ValueError as error:
        raise bad_request(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/warehouse-locations", response_model=list[WarehouseLocationOut])
def api_warehouse_locations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [warehouse_location_out(location) for location in location_repo.list_warehouse_locations(db)]


@router.post("/warehouse-locations", response_model=WarehouseLocationOut, status_code=status.HTTP_201_CREATED)
def api_warehouse_location_create(
    payload: WarehouseLocationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        location = location_service.create_warehouse_location(
            db, current_user, payload.room, payload.slot_code, payload.comment
        )
    except ValueError as error:
        raise bad_request(error) from error
    return warehouse_location_out(location)


@router.delete("/warehouse-locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_warehouse_location_delete(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    location = location_repo.get_warehouse_location(db, location_id)
    if location is None:
        raise not_found("Складское место")
    try:
        location_service.delete_warehouse_location(db, current_user, location)
    except ValueError as error:
        raise bad_request(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/audit", response_model=list[AuditLogOut])
def api_audit(
    actor_user_id: int | None = None,
    action_type: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if entity_type and entity_id:
        logs = audit_repo.list_entity_logs(db, entity_type, entity_id)
    else:
        logs = audit_repo.list_audit_logs(
            db=db,
            actor_user_id=actor_user_id,
            action_type=action_type,
            entity_type=entity_type,
        )
    return [audit_log_out(log) for log in logs[:limit]]
