from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.enums import ConditionStatus, LifecycleStatus
from app.models.user import User
from app.repositories import inventory as inventory_repo
from app.routers.helpers import render_template
from app.utils.tags import parse_tags


router = APIRouter(tags=["equipment"])


@router.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse("/equipment", status_code=303)


@router.get("/equipment", name="equipment_page")
def equipment_page(
    request: Request,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item_types = inventory_repo.list_item_types(db, q)
    all_instances = inventory_repo.list_instances_with_related(db)
    instances_by_type_id: dict[int, list] = {}
    for instance in all_instances:
        instances_by_type_id.setdefault(instance.item_type_id, []).append(instance)

    cards: list[dict[str, object]] = []
    for item_type in item_types:
        instances = instances_by_type_id.get(item_type.id, [])
        total = len(instances)
        active_total = sum(1 for instance in instances if instance.lifecycle_status == LifecycleStatus.ACTIVE)
        issued_total = sum(1 for instance in instances if instance.current_holder_user_id is not None)
        broken_total = sum(1 for instance in instances if instance.condition_status == ConditionStatus.BROKEN)
        total_value = sum(
            Decimal(instance.purchase_unit_price or item_type.unit_price or 0)
            for instance in instances
        )
        cards.append(
            {
                "item_type": item_type,
                "tags": parse_tags(item_type.tags_text),
                "total": total,
                "active_total": active_total,
                "issued_total": issued_total,
                "broken_total": broken_total,
                "total_value": total_value,
            }
        )

    return render_template(
        request,
        "equipment.html",
        current_user,
        cards=cards,
        query=q or "",
        can_manage=current_user.role.value == "admin",
    )
