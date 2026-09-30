from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth.base import AuthServiceUnavailableError
from app.auth.dependencies import AuthSessionMiddleware, build_auth_unavailable_response
from app.auth.external_jwt import ExternalJwtAuthProvider
from app.config import get_settings
from app.database import init_db
from app.routers import api, audit, auth, equipment, inventory, item_types, locations, people, profile
from app.utils.formatting import (
    CONDITION_LABELS,
    LIFECYCLE_LABELS,
    LOCATION_LABELS,
    ROLE_LABELS,
    condition_label,
    format_money,
    lifecycle_label,
    location_type_label,
    role_label,
)
from app.utils.tags import parse_tags


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
app.state.settings = settings
app.state.auth_provider = ExternalJwtAuthProvider(settings)
app.add_middleware(AuthSessionMiddleware, provider=app.state.auth_provider)
app.mount("/static", StaticFiles(directory=settings.base_dir / "app" / "static"), name="static")

templates = Jinja2Templates(directory=str(settings.base_dir / "app" / "templates"))
templates.env.filters["money"] = format_money
templates.env.filters["condition_label"] = condition_label
templates.env.filters["lifecycle_label"] = lifecycle_label
templates.env.filters["location_type_label"] = location_type_label
templates.env.filters["role_label"] = role_label
templates.env.globals["parse_tags"] = parse_tags
templates.env.globals["condition_labels"] = CONDITION_LABELS
templates.env.globals["lifecycle_labels"] = LIFECYCLE_LABELS
templates.env.globals["location_labels"] = LOCATION_LABELS
templates.env.globals["role_labels"] = ROLE_LABELS
app.state.templates = templates


@app.exception_handler(AuthServiceUnavailableError)
async def auth_unavailable_handler(request, exc):
    return build_auth_unavailable_response(request)


app.include_router(api.router)
app.include_router(auth.router)
app.include_router(equipment.router)
app.include_router(inventory.router)
app.include_router(item_types.router)
app.include_router(locations.router)
app.include_router(people.router)
app.include_router(profile.router)
app.include_router(audit.router)
