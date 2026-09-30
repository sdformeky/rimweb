from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.models.enums import ConditionStatus, PhysicalLocationType
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import inventory as inventory_repo
from app.repositories import locations as location_repo
from app.routers.helpers import parse_decimal, redirect_with_feedback, render_template
from app.services.inventory import create_item_type, delete_item_type, group_item_type_instances, update_item_type
from app.services.locations import (
    build_location_maps,
    build_location_options,
    build_warehouse_location_select_groups,
)
from app.utils.tags import parse_tags


router = APIRouter(tags=["item-types"])


@router.get("/item-types", name="item_types_list")
def item_types_page(
    request: Request,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item_types = inventory_repo.list_item_types(db, q)
    instances = inventory_repo.list_instances_with_related(db)
    totals_by_type: dict[int, dict[str, Decimal | int]] = defaultdict(
        lambda: {"count": 0, "active_count": 0, "all_total": Decimal("0.00"), "active_total": Decimal("0.00")}
    )
    for instance in instances:
        effective_price = Decimal(instance.purchase_unit_price or instance.item_type.unit_price or 0)
        totals = totals_by_type[instance.item_type_id]
        totals["count"] += 1
        totals["all_total"] += effective_price
        if instance.lifecycle_status.value == "active":
            totals["active_count"] += 1
            totals["active_total"] += effective_price

    return render_template(
        request,
        "item_types.html",
        current_user,
        item_types=item_types,
        totals_by_type=totals_by_type,
        query=q or "",
        can_manage=current_user.role.value == "admin",
    )


@router.post("/item-types/create", name="item_type_create")
def item_type_create(
    name: str = Form(...),
    comment: str | None = Form(default=None),
    store_url: str | None = Form(default=None),
    unit_label: str | None = Form(default="шт"),
    unit_price: str = Form(default="0"),
    tags_text: str | None = Form(default=None),
    next_url: str = Form(default="/item-types"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        item_type = create_item_type(
            db=db,
            actor=current_user,
            name=name,
            comment=comment,
            store_url=store_url,
            unit_label=unit_label,
            unit_price=parse_decimal(unit_price),
            tags_text=tags_text,
        )
    except ValueError as error:
        return redirect_with_feedback(next_url, error=str(error))
    return redirect_with_feedback(f"/item-types/{item_type.id}", message="Тип предмета создан.")


@router.get("/item-types/{item_type_id}", name="item_type_detail")
def item_type_detail(
    request: Request,
    item_type_id: int,
    group_by: str = "purchase",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item_type = inventory_repo.get_item_type(db, item_type_id)
    if item_type is None:
        return redirect_with_feedback("/item-types", error="Тип предмета не найден.")

    all_locations = location_repo.list_locations(db)
    warehouse_locations = location_repo.list_warehouse_locations(db)
    all_instances = inventory_repo.list_instances_with_related(db)
    instances = [instance for instance in all_instances if instance.item_type_id == item_type.id]
    _, location_path_map = build_location_maps(all_locations)
    location_options = build_location_options(all_locations)
    selected_group_by = group_by if group_by in {"purchase", "location"} else "purchase"
    grouped_instances = group_item_type_instances(instances, all_locations, selected_group_by)

    return render_template(
        request,
        "item_type_detail.html",
        current_user,
        item_type=item_type,
        tags=parse_tags(item_type.tags_text),
        grouped_instances=grouped_instances,
        all_instances=sorted(instances, key=lambda instance: instance.inventory_number.lower()),
        location_path_map=location_path_map,
        location_options=location_options,
        warehouse_location_select_groups=build_warehouse_location_select_groups(warehouse_locations),
        condition_statuses=list(ConditionStatus),
        physical_location_types=list(PhysicalLocationType),
        selected_group_by=selected_group_by,
        history_logs=audit_repo.list_entity_logs(db, "item_type", str(item_type.id)),
        users=inventory_repo.list_users_for_select(db),
        can_manage=current_user.role.value == "admin",
    )


@router.post("/item-types/{item_type_id}/edit", name="item_type_edit")
def item_type_edit(
    item_type_id: int,
    name: str = Form(...),
    comment: str | None = Form(default=None),
    store_url: str | None = Form(default=None),
    unit_label: str | None = Form(default="шт"),
    unit_price: str = Form(default="0"),
    tags_text: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    item_type = inventory_repo.get_item_type(db, item_type_id)
    if item_type is None:
        return redirect_with_feedback("/item-types", error="Тип предмета не найден.")

    try:
        update_item_type(
            db=db,
            actor=current_user,
            item_type=item_type,
            name=name,
            comment=comment,
            store_url=store_url,
            unit_label=unit_label,
            unit_price=parse_decimal(unit_price),
            tags_text=tags_text,
        )
    except ValueError as error:
        return redirect_with_feedback(f"/item-types/{item_type.id}", error=str(error))
    return redirect_with_feedback(f"/item-types/{item_type.id}", message="Тип предмета обновлен.")


@router.post("/item-types/{item_type_id}/delete", name="item_type_delete")
def item_type_delete_route(
    item_type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    item_type = inventory_repo.get_item_type(db, item_type_id)
    if item_type is None:
        return redirect_with_feedback("/item-types", error="Тип предмета не найден.")
    try:
        delete_item_type(db, current_user, item_type)
    except ValueError as error:
        return redirect_with_feedback(f"/item-types/{item_type.id}", error=str(error))
    return redirect_with_feedback("/item-types", message="Тип предмета удален.")
