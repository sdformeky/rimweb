from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.models.enums import ConditionStatus, PhysicalLocationType, UserRole
from app.models.user import User
from app.repositories import inventory as inventory_repo
from app.repositories import locations as location_repo
from app.repositories import users as user_repo
from app.routers.helpers import parse_datetime_local, redirect_with_feedback, render_template
from app.services.audit import add_audit_log
from app.services.inventory import issue_instances
from app.services.locations import (
    build_location_maps,
    build_location_options,
    build_warehouse_location_select_groups,
)
from app.utils.formatting import condition_label


router = APIRouter(tags=["people"])


def format_instance_option_label(instance, location_path_map: dict[int, str]) -> str:
    if instance.physical_location_type.value == "warehouse":
        location_label = instance.warehouse_location_text or "Склад без адреса"
    elif instance.physical_location_type.value == "laboratory":
        location_label = location_path_map.get(instance.lab_location_id, "Лаборатория")
    else:
        location_label = "Не указано"
    return (
        f"{instance.inventory_number} — {instance.item_type.name} "
        f"({condition_label(instance.condition_status)}, {location_label})"
    )


@router.get("/people", name="people_list")
def people_page(
    request: Request,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    users = user_repo.list_users(db, q)
    issued_counts = {user.id: user_repo.count_active_issues_for_user(db, user.id) for user in users}
    return render_template(
        request,
        "people.html",
        current_user,
        users=users,
        issued_counts=issued_counts,
        query=q or "",
        can_manage=current_user.role.value == "admin",
    )


@router.get("/people/{user_id}", name="person_detail")
def person_detail(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = user_repo.get_user_by_id(db, user_id)
    if user is None:
        return redirect_with_feedback("/people", error="Пользователь не найден.")
    active_instances = inventory_repo.list_active_instances_for_user(db, user.id)
    issue_history = inventory_repo.list_issue_records_for_user(db, user.id)
    available_instances: list[dict[str, object]] = []
    context: dict[str, object] = {}
    if current_user.role.value == "admin":
        all_locations = location_repo.list_locations(db)
        _, location_path_map = build_location_maps(all_locations)
        available_instances = [
            {
                "id": instance.id,
                "label": format_instance_option_label(instance, location_path_map),
            }
            for instance in inventory_repo.list_issuable_instances(db)
        ]
        context = {
            "users": inventory_repo.list_users_for_select(db),
            "location_options": build_location_options(all_locations),
            "warehouse_location_select_groups": build_warehouse_location_select_groups(
                location_repo.list_warehouse_locations(db)
            ),
            "condition_statuses": list(ConditionStatus),
            "physical_location_types": list(PhysicalLocationType),
        }
    return render_template(
        request,
        "user_detail.html",
        current_user,
        person=user,
        active_instances=active_instances,
        issue_history=issue_history,
        available_instances=available_instances,
        can_manage=current_user.role.value == "admin",
        **context,
    )


@router.post("/people/{user_id}/issue", name="person_issue_item")
def person_issue_item(
    user_id: int,
    instance_ids: list[int] = Form(default=[]),
    issued_at: str | None = Form(default=None),
    issue_comment: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = user_repo.get_user_by_id(db, user_id)
    if user is None:
        return redirect_with_feedback("/people", error="Пользователь не найден.")
    person_url = f"/people/{user_id}"
    instances = inventory_repo.get_instances_by_ids(db, instance_ids)
    if not instances:
        return redirect_with_feedback(person_url, error="Отметьте хотя бы один экземпляр для выдачи.")
    if len(instances) != len(set(instance_ids)):
        return redirect_with_feedback(person_url, error="Часть выбранных экземпляров не найдена.")
    try:
        issue_instances(
            db=db,
            actor=current_user,
            instances=instances,
            issued_to_user=user,
            issued_at=parse_datetime_local(issued_at),
            issue_comment=issue_comment,
        )
    except ValueError as error:
        return redirect_with_feedback(person_url, error=str(error))
    return redirect_with_feedback(person_url, message=f"Выдано пользователю: {len(instances)} шт.")


@router.post("/people/{user_id}/role", name="person_change_role")
def person_change_role(
    user_id: int,
    role: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = user_repo.get_user_by_id(db, user_id)
    if user is None:
        return redirect_with_feedback("/people", error="Пользователь не найден.")
    try:
        new_role = UserRole(role)
    except ValueError:
        return redirect_with_feedback(f"/people/{user.id}", error="Неизвестная роль.")
    if user.role == new_role:
        return redirect_with_feedback(f"/people/{user.id}", message="Роль уже установлена.")
    if user.role == UserRole.ADMIN and new_role == UserRole.USER and user_repo.count_admins(db) <= 1:
        return redirect_with_feedback(f"/people/{user.id}", error="Нельзя снять роль последнего администратора.")

    old_role = user.role
    user.role = new_role
    add_audit_log(
        db,
        current_user,
        "admin_assigned" if new_role == UserRole.ADMIN else "admin_revoked",
        "user",
        user.id,
        old_value={"role": old_role.value},
        new_value={"role": new_role.value},
    )
    db.commit()
    return redirect_with_feedback(f"/people/{user.id}", message="Роль пользователя обновлена.")
