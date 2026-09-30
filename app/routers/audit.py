from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import users as user_repo
from app.routers.helpers import parse_date_end, parse_date_start, render_template


router = APIRouter(tags=["audit"])


@router.get("/audit", name="audit_log")
def audit_log_page(
    request: Request,
    actor_user_id: int | None = None,
    action_type: str | None = None,
    entity_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    logs = audit_repo.list_audit_logs(
        db=db,
        actor_user_id=actor_user_id,
        action_type=(action_type or "").strip() or None,
        entity_type=(entity_type or "").strip() or None,
        date_from=parse_date_start(date_from),
        date_to=parse_date_end(date_to),
    )
    return render_template(
        request,
        "audit_log.html",
        current_user,
        logs=logs,
        users=user_repo.list_users(db),
        selected_actor_user_id=actor_user_id,
        selected_action_type=action_type or "",
        selected_entity_type=entity_type or "",
        selected_date_from=date_from or "",
        selected_date_to=date_to or "",
    )
