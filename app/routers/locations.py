from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.models.user import User
from app.repositories import inventory as inventory_repo
from app.repositories import locations as location_repo
from app.routers.helpers import redirect_with_feedback, render_template
from app.services.locations import (
    build_location_maps,
    build_location_options,
    build_location_tree,
    build_warehouse_location_groups,
    create_location,
    create_warehouse_location,
    delete_location,
    delete_warehouse_location,
    update_location,
)


router = APIRouter(tags=["locations"])


@router.get("/locations", name="locations_page")
def locations_page(
    request: Request,
    selected_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    locations = location_repo.list_locations(db)
    warehouse_locations = location_repo.list_warehouse_locations(db)
    location_by_id, path_map = build_location_maps(locations)
    selected_location = location_by_id.get(selected_id) if selected_id else None
    items_in_selected = []
    if selected_location is not None:
        items_in_selected = [
            instance
            for instance in inventory_repo.list_instances_with_related(db)
            if instance.lab_location_id == selected_location.id
        ]

    return render_template(
        request,
        "locations.html",
        current_user,
        tree=build_location_tree(locations),
        location_options=build_location_options(locations),
        warehouse_location_groups=build_warehouse_location_groups(warehouse_locations),
        selected_location=selected_location,
        selected_location_path=path_map.get(selected_location.id) if selected_location else None,
        items_in_selected=items_in_selected,
        can_manage=current_user.role.value == "admin",
    )


@router.post("/locations/create", name="location_create")
def location_create_route(
    type_label: str = Form(...),
    name: str = Form(...),
    comment: str | None = Form(default=None),
    parent_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    parent = location_repo.get_location(db, parent_id) if parent_id else None
    location = create_location(db, current_user, type_label, name, comment, parent)
    return redirect_with_feedback(f"/locations?selected_id={location.id}", message="Лабораторное место создано.")


@router.post("/locations/{location_id}/edit", name="location_edit")
def location_edit_route(
    location_id: int,
    type_label: str = Form(...),
    name: str = Form(...),
    comment: str | None = Form(default=None),
    parent_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    location = location_repo.get_location(db, location_id)
    if location is None:
        return redirect_with_feedback("/locations", error="Лабораторное место не найдено.")
    parent = location_repo.get_location(db, parent_id) if parent_id else None
    try:
        update_location(db, current_user, location, type_label, name, comment, parent)
    except ValueError as error:
        return redirect_with_feedback(f"/locations?selected_id={location.id}", error=str(error))
    return redirect_with_feedback(f"/locations?selected_id={location.id}", message="Лабораторное место обновлено.")


@router.post("/locations/{location_id}/delete", name="location_delete")
def location_delete_route(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    location = location_repo.get_location(db, location_id)
    if location is None:
        return redirect_with_feedback("/locations", error="Лабораторное место не найдено.")
    try:
        delete_location(db, current_user, location)
    except ValueError as error:
        return redirect_with_feedback(f"/locations?selected_id={location.id}", error=str(error))
    return redirect_with_feedback("/locations", message="Лабораторное место удалено.")


@router.post("/warehouse-locations/create", name="warehouse_location_create")
def warehouse_location_create_route(
    room: str = Form(...),
    slot_code: str = Form(...),
    comment: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        create_warehouse_location(db, current_user, room, slot_code, comment)
    except ValueError as error:
        return redirect_with_feedback("/locations", error=str(error))
    return redirect_with_feedback("/locations", message="Складское место создано.")


@router.post("/warehouse-locations/{location_id}/delete", name="warehouse_location_delete")
def warehouse_location_delete_route(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    location = location_repo.get_warehouse_location(db, location_id)
    if location is None:
        return redirect_with_feedback("/locations", error="Складское место не найдено.")
    try:
        delete_warehouse_location(db, current_user, location)
    except ValueError as error:
        return redirect_with_feedback("/locations", error=str(error))
    return redirect_with_feedback("/locations", message="Складское место удалено.")
