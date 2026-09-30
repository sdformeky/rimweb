from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.models.enums import ConditionStatus, LifecycleStatus, PhysicalLocationType
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import inventory as inventory_repo
from app.repositories import locations as location_repo
from app.repositories import users as user_repo
from app.routers.helpers import (
    parse_condition_status,
    parse_datetime_local,
    parse_optional_decimal,
    redirect_with_feedback,
    render_template,
)
from app.services.inventory import (
    change_condition,
    change_condition_many,
    change_lifecycle,
    change_lifecycle_many,
    create_instances,
    delete_instance,
    delete_instances,
    filter_instances,
    find_active_issue,
    get_inventory_group_instances,
    group_inventory_instances,
    issue_instances,
    move_instances,
    resolve_location_snapshot,
    return_instance,
    return_instances,
    update_instance_details,
)
from app.services.locations import (
    build_location_maps,
    build_location_options,
    build_warehouse_location_select_groups,
)
from app.utils.tags import parse_tags


router = APIRouter(tags=["inventory"])


@router.get("/inventory", name="inventory_list")
def inventory_page(
    request: Request,
    q: str | None = None,
    condition_status: str | None = None,
    lifecycle_status: str | None = None,
    holder: str | None = None,
    show_written_off: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    all_instances = inventory_repo.list_instances_with_related(db)
    all_locations = location_repo.list_locations(db)
    warehouse_locations = location_repo.list_warehouse_locations(db)
    _, location_path_map = build_location_maps(all_locations)
    location_options = build_location_options(all_locations)
    filtered_instances = filter_instances(
        instances=all_instances,
        location_path_map=location_path_map,
        query=q,
        condition_status=condition_status,
        lifecycle_status=lifecycle_status,
        holder_query=holder,
        include_written_off=bool(show_written_off),
    )
    groups = group_inventory_instances(filtered_instances, all_locations)

    return render_template(
        request,
        "inventory.html",
        current_user,
        groups=groups,
        query=q or "",
        selected_condition_status=condition_status or "",
        selected_lifecycle_status=lifecycle_status or "",
        selected_holder=holder or "",
        show_written_off=bool(show_written_off),
        users=inventory_repo.list_users_for_select(db),
        location_options=location_options,
        warehouse_location_select_groups=build_warehouse_location_select_groups(warehouse_locations),
        can_manage=current_user.role.value == "admin",
        physical_location_types=list(PhysicalLocationType),
        condition_statuses=list(ConditionStatus),
        lifecycle_statuses=list(LifecycleStatus),
    )


AVAILABILITY_FILTERS = {"free", "issued"}


@router.get("/instances", name="instances_list")
def instances_page(
    request: Request,
    q: str | None = None,
    item_type_id: int | None = None,
    condition_status: str | None = None,
    lifecycle_status: str | None = None,
    holder: str | None = None,
    availability: str | None = None,
    show_written_off: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    all_locations = location_repo.list_locations(db)
    warehouse_locations = location_repo.list_warehouse_locations(db)
    _, location_path_map = build_location_maps(all_locations)
    instances = filter_instances(
        instances=inventory_repo.list_instances_with_related(db),
        location_path_map=location_path_map,
        query=q,
        condition_status=condition_status,
        lifecycle_status=lifecycle_status,
        holder_query=holder,
        include_written_off=bool(show_written_off),
    )
    if item_type_id:
        instances = [instance for instance in instances if instance.item_type_id == item_type_id]
    if availability == "free":
        instances = [instance for instance in instances if instance.current_holder_user_id is None]
    elif availability == "issued":
        instances = [instance for instance in instances if instance.current_holder_user_id is not None]
    instances.sort(key=lambda instance: (instance.item_type.name.lower(), instance.inventory_number.lower()))

    return render_template(
        request,
        "instances.html",
        current_user,
        instances=instances,
        location_display_map={
            instance.id: resolve_location_snapshot(instance, location_path_map).display_text
            for instance in instances
        },
        item_types=inventory_repo.list_item_types(db),
        query=q or "",
        selected_item_type_id=item_type_id,
        selected_condition_status=condition_status or "",
        selected_lifecycle_status=lifecycle_status or "",
        selected_holder=holder or "",
        selected_availability=availability if availability in AVAILABILITY_FILTERS else "",
        show_written_off=bool(show_written_off),
        users=inventory_repo.list_users_for_select(db),
        location_options=build_location_options(all_locations),
        warehouse_location_select_groups=build_warehouse_location_select_groups(warehouse_locations),
        can_manage=current_user.role.value == "admin",
        physical_location_types=list(PhysicalLocationType),
        condition_statuses=list(ConditionStatus),
        lifecycle_statuses=list(LifecycleStatus),
    )


@router.get("/instances/create", name="instances_create_page")
def instance_create_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    warehouse_locations = location_repo.list_warehouse_locations(db)
    return render_template(
        request,
        "item_create.html",
        current_user,
        item_types=inventory_repo.list_item_types(db),
        location_options=build_location_options(location_repo.list_locations(db)),
        warehouse_location_select_groups=build_warehouse_location_select_groups(warehouse_locations),
        condition_statuses=list(ConditionStatus),
        physical_location_types=list(PhysicalLocationType),
        can_manage=current_user.role.value == "admin",
    )


@router.post("/instances/create", name="instances_create")
def instances_create(
    item_type_id: int = Form(...),
    quantity: int = Form(...),
    auto_generate_inventory_numbers: str | None = Form(default=None),
    manual_inventory_numbers: str | None = Form(default=None),
    condition_status: str = Form(default=ConditionStatus.WORKING.value),
    purchase_number: str | None = Form(default=None),
    purchase_unit_price: str | None = Form(default=None),
    tags_text: str | None = Form(default=None),
    physical_location_type: str = Form(default=PhysicalLocationType.WAREHOUSE.value),
    warehouse_location_text: str | None = Form(default=None),
    lab_location_id: int | None = Form(default=None),
    next_url: str = Form(default="/inventory"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    item_type = inventory_repo.get_item_type(db, item_type_id)
    if item_type is None:
        return redirect_with_feedback(next_url, error="Тип предмета не найден.")
    lab_location = location_repo.get_location(db, lab_location_id) if lab_location_id else None
    manual_numbers = [line.strip() for line in (manual_inventory_numbers or "").splitlines() if line.strip()]

    try:
        create_instances(
            db=db,
            actor=current_user,
            item_type=item_type,
            quantity=quantity,
            manual_inventory_numbers=manual_numbers,
            auto_generate_inventory_numbers=bool(auto_generate_inventory_numbers),
            condition_status=ConditionStatus(condition_status),
            purchase_number=purchase_number,
            purchase_unit_price=parse_optional_decimal(purchase_unit_price),
            tags_text=tags_text,
            physical_location_type=PhysicalLocationType(physical_location_type),
            warehouse_location_text=warehouse_location_text,
            lab_location=lab_location,
        )
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))

    return redirect_with_feedback(next_url, message="Экземпляры созданы.")


@router.get("/instances/{instance_id}", name="instance_detail")
def instance_detail(
    request: Request,
    instance_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = inventory_repo.get_instance(db, instance_id)
    if instance is None:
        return redirect_with_feedback("/inventory", error="Экземпляр не найден.")

    all_locations = location_repo.list_locations(db)
    warehouse_locations = location_repo.list_warehouse_locations(db)
    _, location_path_map = build_location_maps(all_locations)
    return render_template(
        request,
        "instance_detail.html",
        current_user,
        instance=instance,
        type_tags=parse_tags(instance.item_type.tags_text),
        instance_tags=parse_tags(instance.tags_text),
        active_issue=find_active_issue(instance),
        history_logs=audit_repo.list_entity_logs(db, "item_instance", str(instance.id)),
        users=inventory_repo.list_users_for_select(db),
        location_options=build_location_options(all_locations),
        location_path_map=location_path_map,
        warehouse_location_select_groups=build_warehouse_location_select_groups(
            warehouse_locations,
            instance.warehouse_location_text,
        ),
        can_manage=current_user.role.value == "admin",
        condition_statuses=list(ConditionStatus),
        physical_location_types=list(PhysicalLocationType),
    )


@router.post("/instances/{instance_id}/edit", name="instance_edit")
def instance_edit(
    instance_id: int,
    inventory_number: str = Form(...),
    purchase_number: str | None = Form(default=None),
    purchase_unit_price: str | None = Form(default=None),
    tags_text: str | None = Form(default=None),
    next_url: str = Form(default="/inventory"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instance = inventory_repo.get_instance(db, instance_id)
    if instance is None:
        return redirect_with_feedback("/inventory", error="Экземпляр не найден.")
    try:
        update_instance_details(
            db=db,
            actor=current_user,
            instance=instance,
            inventory_number=inventory_number,
            purchase_number=purchase_number,
            purchase_unit_price=parse_optional_decimal(purchase_unit_price),
            tags_text=tags_text,
        )
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message="Учетные поля экземпляра обновлены.")


@router.post("/instances/{instance_id}/move", name="instance_move")
def instance_move(
    instance_id: int,
    physical_location_type: str = Form(...),
    warehouse_location_text: str | None = Form(default=None),
    lab_location_id: int | None = Form(default=None),
    next_url: str = Form(default="/inventory"),
    comment: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instance = inventory_repo.get_instance(db, instance_id)
    if instance is None:
        return redirect_with_feedback("/inventory", error="Экземпляр не найден.")
    lab_location = location_repo.get_location(db, lab_location_id) if lab_location_id else None
    try:
        move_instances(
            db,
            current_user,
            [instance],
            PhysicalLocationType(physical_location_type),
            warehouse_location_text,
            lab_location,
            comment=comment,
        )
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message="Место хранения обновлено.")


@router.post("/instances/{instance_id}/condition", name="instance_change_condition")
def instance_change_condition(
    instance_id: int,
    condition_status: str = Form(...),
    next_url: str = Form(default="/inventory"),
    comment: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instance = inventory_repo.get_instance(db, instance_id)
    if instance is None:
        return redirect_with_feedback("/inventory", error="Экземпляр не найден.")
    try:
        change_condition(db, current_user, instance, ConditionStatus(condition_status), comment)
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message="Состояние обновлено.")


@router.post("/instances/{instance_id}/write-off", name="instance_write_off")
def instance_write_off(
    instance_id: int,
    next_url: str = Form(default="/inventory"),
    comment: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instance = inventory_repo.get_instance(db, instance_id)
    if instance is None:
        return redirect_with_feedback("/inventory", error="Экземпляр не найден.")
    try:
        change_lifecycle(db, current_user, instance, LifecycleStatus.WRITTEN_OFF, comment)
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message="Экземпляр списан.")


@router.post("/instances/{instance_id}/delete", name="instance_delete")
def instance_delete_route(
    instance_id: int,
    next_url: str = Form(default="/inventory"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instance = inventory_repo.get_instance(db, instance_id)
    if instance is None:
        return redirect_with_feedback("/inventory", error="Экземпляр не найден.")
    delete_instance(db, current_user, instance)
    return redirect_with_feedback(next_url, message="Экземпляр удален безвозвратно.")


@router.post("/instances/{instance_id}/issue", name="instance_issue")
def instance_issue(
    instance_id: int,
    issued_to_user_id: int = Form(...),
    issued_at: str | None = Form(default=None),
    issue_comment: str | None = Form(default=None),
    next_url: str = Form(default="/inventory"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instance = inventory_repo.get_instance(db, instance_id)
    issued_to_user = user_repo.get_user_by_id(db, issued_to_user_id)
    if instance is None or issued_to_user is None:
        return redirect_with_feedback("/inventory", error="Не удалось оформить выдачу.")
    try:
        issue_instances(
            db,
            current_user,
            [instance],
            issued_to_user,
            parse_datetime_local(issued_at),
            issue_comment,
        )
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message="Выдача оформлена.")


@router.post("/instances/{instance_id}/return", name="instance_return")
def instance_return_route(
    instance_id: int,
    return_location_mode: str = Form(default="previous"),
    physical_location_type: str | None = Form(default=None),
    warehouse_location_text: str | None = Form(default=None),
    lab_location_id: int | None = Form(default=None),
    condition_status: str | None = Form(default=None),
    returned_at: str | None = Form(default=None),
    comment: str | None = Form(default=None),
    next_url: str = Form(default="/inventory"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    instance = inventory_repo.get_instance(db, instance_id)
    if instance is None:
        return redirect_with_feedback("/inventory", error="Экземпляр не найден.")

    lab_location = location_repo.get_location(db, lab_location_id) if lab_location_id else None

    try:
        selected_location_type = None if return_location_mode == "previous" else PhysicalLocationType(physical_location_type or "none")
        return_instance(
            db=db,
            actor=current_user,
            instance=instance,
            returned_at=parse_datetime_local(returned_at),
            physical_location_type=selected_location_type,
            warehouse_location_text=warehouse_location_text,
            lab_location=lab_location,
            condition_status=parse_condition_status(condition_status),
            comment=comment,
        )
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message="Возврат оформлен.")


@router.post("/inventory/groups/issue", name="inventory_group_issue")
def inventory_group_issue(
    group_key: str = Form(...),
    quantity: int = Form(...),
    issued_to_user_id: int = Form(...),
    issued_at: str | None = Form(default=None),
    issue_comment: str | None = Form(default=None),
    query: str | None = Form(default=None),
    filter_condition_status: str | None = Form(default=None),
    filter_lifecycle_status: str | None = Form(default=None),
    filter_holder: str | None = Form(default=None),
    show_written_off: int = Form(default=0),
    next_url: str = Form(default="/inventory"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    issued_to_user = user_repo.get_user_by_id(db, issued_to_user_id)
    if issued_to_user is None:
        return redirect_with_feedback(next_url, error="Пользователь для выдачи не найден.")

    all_instances = inventory_repo.list_instances_with_related(db)
    all_locations = location_repo.list_locations(db)
    _, location_path_map = build_location_maps(all_locations)
    scoped_instances = filter_instances(
        instances=all_instances,
        location_path_map=location_path_map,
        query=query,
        condition_status=filter_condition_status,
        lifecycle_status=filter_lifecycle_status,
        holder_query=filter_holder,
        include_written_off=bool(show_written_off),
    )
    selected_instances = [
        instance
        for instance in get_inventory_group_instances(scoped_instances, all_locations, group_key)
        if instance.current_holder_user_id is None and instance.lifecycle_status == LifecycleStatus.ACTIVE
    ]
    if quantity <= 0 or len(selected_instances) < quantity:
        return redirect_with_feedback(next_url, error="Недостаточно доступных экземпляров в выбранной группе.")

    try:
        issue_instances(
            db,
            current_user,
            selected_instances[:quantity],
            issued_to_user,
            parse_datetime_local(issued_at),
            issue_comment,
        )
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message="Групповая выдача выполнена.")


@router.post("/inventory/groups/move", name="inventory_group_move")
def inventory_group_move(
    group_key: str = Form(...),
    quantity: int = Form(...),
    physical_location_type: str = Form(...),
    warehouse_location_text: str | None = Form(default=None),
    lab_location_id: int | None = Form(default=None),
    comment: str | None = Form(default=None),
    query: str | None = Form(default=None),
    filter_condition_status: str | None = Form(default=None),
    filter_lifecycle_status: str | None = Form(default=None),
    filter_holder: str | None = Form(default=None),
    show_written_off: int = Form(default=0),
    next_url: str = Form(default="/inventory"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    all_instances = inventory_repo.list_instances_with_related(db)
    all_locations = location_repo.list_locations(db)
    _, location_path_map = build_location_maps(all_locations)
    scoped_instances = filter_instances(
        instances=all_instances,
        location_path_map=location_path_map,
        query=query,
        condition_status=filter_condition_status,
        lifecycle_status=filter_lifecycle_status,
        holder_query=filter_holder,
        include_written_off=bool(show_written_off),
    )
    selected_instances = get_inventory_group_instances(scoped_instances, all_locations, group_key)
    if quantity <= 0 or len(selected_instances) < quantity:
        return redirect_with_feedback(next_url, error="Недостаточно экземпляров в выбранной группе.")

    lab_location = location_repo.get_location(db, lab_location_id) if lab_location_id else None
    try:
        move_instances(
            db=db,
            actor=current_user,
            instances=selected_instances[:quantity],
            physical_location_type=PhysicalLocationType(physical_location_type),
            warehouse_location_text=warehouse_location_text,
            lab_location=lab_location,
            comment=comment,
        )
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message="Групповое перемещение выполнено.")


def load_selected_instances(db: Session, instance_ids: list[int]):
    requested_ids = set(instance_ids)
    if not requested_ids:
        raise ValueError("Не выбрано ни одного экземпляра.")
    instances = inventory_repo.get_instances_by_ids(db, list(requested_ids))
    missing_ids = requested_ids - {instance.id for instance in instances}
    if missing_ids:
        raise ValueError("Экземпляры не найдены: " + ", ".join(str(item) for item in sorted(missing_ids)))
    return instances


@router.post("/inventory/bulk/issue", name="bulk_issue")
def bulk_issue(
    instance_ids: list[int] = Form(default=[]),
    issued_to_user_id: int = Form(...),
    issued_at: str | None = Form(default=None),
    issue_comment: str | None = Form(default=None),
    next_url: str = Form(default="/instances"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    issued_to_user = user_repo.get_user_by_id(db, issued_to_user_id)
    if issued_to_user is None:
        return redirect_with_feedback(next_url, error="Пользователь для выдачи не найден.")
    try:
        instances = load_selected_instances(db, instance_ids)
        issue_instances(db, current_user, instances, issued_to_user, parse_datetime_local(issued_at), issue_comment)
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message=f"Выдано {len(instances)} шт. пользователю {issued_to_user.full_name}.")


@router.post("/inventory/bulk/return", name="bulk_return")
def bulk_return(
    instance_ids: list[int] = Form(default=[]),
    return_location_mode: str = Form(default="previous"),
    physical_location_type: str | None = Form(default=None),
    warehouse_location_text: str | None = Form(default=None),
    lab_location_id: int | None = Form(default=None),
    condition_status: str | None = Form(default=None),
    returned_at: str | None = Form(default=None),
    comment: str | None = Form(default=None),
    next_url: str = Form(default="/instances"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    lab_location = location_repo.get_location(db, lab_location_id) if lab_location_id else None
    try:
        selected_location_type = None if return_location_mode == "previous" else PhysicalLocationType(physical_location_type or "none")
        instances = load_selected_instances(db, instance_ids)
        return_instances(
            db=db,
            actor=current_user,
            instances=instances,
            returned_at=parse_datetime_local(returned_at),
            physical_location_type=selected_location_type,
            warehouse_location_text=warehouse_location_text,
            lab_location=lab_location,
            condition_status=parse_condition_status(condition_status),
            comment=comment,
        )
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message=f"Возврат оформлен: {len(instances)} шт.")


@router.post("/inventory/bulk/move", name="bulk_move")
def bulk_move(
    instance_ids: list[int] = Form(default=[]),
    physical_location_type: str = Form(...),
    warehouse_location_text: str | None = Form(default=None),
    lab_location_id: int | None = Form(default=None),
    comment: str | None = Form(default=None),
    next_url: str = Form(default="/instances"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    lab_location = location_repo.get_location(db, lab_location_id) if lab_location_id else None
    try:
        instances = load_selected_instances(db, instance_ids)
        move_instances(
            db,
            current_user,
            instances,
            PhysicalLocationType(physical_location_type),
            warehouse_location_text,
            lab_location,
            comment=comment,
        )
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message=f"Перемещено {len(instances)} шт.")


@router.post("/inventory/bulk/condition", name="bulk_condition")
def bulk_condition(
    instance_ids: list[int] = Form(default=[]),
    condition_status: str = Form(...),
    comment: str | None = Form(default=None),
    next_url: str = Form(default="/instances"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        instances = load_selected_instances(db, instance_ids)
        change_condition_many(db, current_user, instances, ConditionStatus(condition_status), comment)
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message=f"Состояние обновлено: {len(instances)} шт.")


@router.post("/inventory/bulk/write-off", name="bulk_write_off")
def bulk_write_off(
    instance_ids: list[int] = Form(default=[]),
    comment: str | None = Form(default=None),
    next_url: str = Form(default="/instances"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        instances = load_selected_instances(db, instance_ids)
        change_lifecycle_many(db, current_user, instances, LifecycleStatus.WRITTEN_OFF, comment)
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message=f"Списано {len(instances)} шт.")


@router.post("/inventory/bulk/delete", name="bulk_delete")
def bulk_delete(
    instance_ids: list[int] = Form(default=[]),
    confirm_delete: str | None = Form(default=None),
    next_url: str = Form(default="/instances"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if not confirm_delete:
        return redirect_with_feedback(next_url, error="Подтвердите безвозвратное удаление.")
    try:
        instances = load_selected_instances(db, instance_ids)
        delete_instances(db, current_user, instances)
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(next_url, message=f"Удалено безвозвратно: {len(instances)} шт.")
