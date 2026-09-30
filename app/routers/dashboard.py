from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.routers.helpers import render_template
from app.services.dashboard import get_dashboard_stats, get_recent_activity


router = APIRouter(tags=["dashboard"])


@router.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/equipment", status_code=303)


@router.get("/dashboard", name="dashboard_home")
def dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return render_template(
        request,
        "dashboard.html",
        current_user,
        stats=get_dashboard_stats(db),
        recent_logs=get_recent_activity(db),
    )
