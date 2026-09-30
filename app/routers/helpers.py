from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.models.enums import ConditionStatus


def render_template(request: Request, template_name: str, current_user, **context):
    templates = request.app.state.templates
    base_context = {
        "request": request,
        "current_user": current_user,
        "settings": get_settings(),
        "message": request.query_params.get("message"),
        "error": request.query_params.get("error"),
    }
    base_context.update(context)
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=base_context,
    )


def redirect_with_feedback(url: str, message: str | None = None, error: str | None = None) -> RedirectResponse:
    parsed = urlparse(url or "/")
    path = parsed.path or "/"
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        path = "/"
    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if message:
        query_params["message"] = message
    if error:
        query_params["error"] = error
    redirect_url = urlunparse(("", "", path, "", urlencode(query_params, doseq=True), ""))
    return RedirectResponse(redirect_url, status_code=303)


def parse_decimal(value: str | None, default: Decimal = Decimal("0.00")) -> Decimal:
    raw_value = (value or "").strip()
    if not raw_value:
        return default
    normalized = raw_value.replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation as error:
        raise ValueError("Некорректное числовое значение.") from error


def parse_optional_decimal(value: str | None) -> Decimal | None:
    raw_value = (value or "").strip()
    if not raw_value:
        return None
    return parse_decimal(raw_value)


def parse_datetime_local(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Некорректная дата и время.") from error
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date_start(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_date_end(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        date_value = datetime.fromisoformat(value).date()
    except ValueError:
        return None
    return datetime.combine(date_value, time.max, tzinfo=timezone.utc)


def parse_condition_status(value: str | None) -> ConditionStatus | None:
    raw_value = (value or "").strip()
    return ConditionStatus(raw_value) if raw_value else None
