from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.repositories import inventory as inventory_repo
from app.routers.helpers import render_template


router = APIRouter(tags=["profile"])


@router.get("/me", name="profile_page")
def profile_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return render_template(
        request,
        "profile.html",
        current_user,
        active_instances=inventory_repo.list_active_instances_for_user(db, current_user.id),
        issue_history=inventory_repo.list_issue_records_for_user(db, current_user.id),
    )
