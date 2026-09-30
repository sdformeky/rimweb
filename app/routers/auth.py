from __future__ import annotations

import logging

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.auth.base import AccessTokenExpiredError, AuthRequiredError, AuthSessionContext, InvalidAuthPayloadError
from app.database import get_db
from app.services.auth_users import get_local_user_by_external_id, get_or_create_local_user


router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)
LOGIN_REFRESH_ATTEMPT_COOKIE_NAME = "rim_login_refresh_attempted"


def _build_expected_callback_url(request: Request) -> str:
    settings = request.app.state.settings
    return settings.auth_callback_url or str(request.url_for("login_entry"))


def _looks_like_failed_auth_callback(request: Request) -> bool:
    settings = request.app.state.settings
    provider = request.app.state.auth_provider

    has_auth_cookies = any(
        (
            provider.read_access_token(request),
            provider.read_refresh_token(request),
            provider.read_info_token(request),
        )
    )
    if has_auth_cookies:
        return False

    referer = str(request.headers.get("referer") or "").strip()
    if not referer:
        return False

    auth_login = urlsplit(settings.auth_login_url)
    referer_parts = urlsplit(referer)
    expected_auth_origin = f"{auth_login.scheme.lower()}://{auth_login.netloc.lower()}"
    referer_origin = (
        f"{referer_parts.scheme.lower()}://{referer_parts.netloc.lower()}"
        if referer_parts.scheme and referer_parts.netloc
        else ""
    )
    if referer_origin != expected_auth_origin:
        return False

    callback_cookie = request.cookies.get(settings.callback_cookie_name)
    return_to_cookie = request.cookies.get(settings.return_to_cookie_name)
    expected_callback = _build_expected_callback_url(request)
    return callback_cookie == expected_callback or bool(return_to_cookie)


def _build_failed_auth_callback_response(request: Request) -> HTMLResponse:
    settings = request.app.state.settings
    provider = request.app.state.auth_provider

    expected_callback = _build_expected_callback_url(request)
    callback_cookie = request.cookies.get(settings.callback_cookie_name)
    return_to_cookie = request.cookies.get(settings.return_to_cookie_name)
    has_access_cookie = bool(provider.read_access_token(request))
    has_refresh_cookie = bool(provider.read_refresh_token(request))
    has_info_cookie = bool(provider.read_info_token(request))
    login_refresh_attempted = request.cookies.get(LOGIN_REFRESH_ATTEMPT_COOKIE_NAME) == "1"
    callback_error_reason = str(getattr(request.state, "callback_error_reason", "") or "").strip() or None

    logger.warning(
        "AUTH callback could not be completed. expected_callback=%r "
        "callback_cookie=%r has_return_to=%r has_access_cookie=%r has_refresh_cookie=%r has_info_cookie=%r "
        "login_refresh_attempted=%r callback_error_reason=%r cookie_domain=%r cookie_secure=%r auth_login_url=%r",
        expected_callback,
        callback_cookie,
        bool(return_to_cookie),
        has_access_cookie,
        has_refresh_cookie,
        has_info_cookie,
        login_refresh_attempted,
        callback_error_reason,
        settings.cookie_domain,
        settings.cookie_secure,
        settings.auth_login_url,
    )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="auth_callback_error.html",
        context={
            "request": request,
            "settings": settings,
            "expected_callback_url": expected_callback,
            "callback_cookie": callback_cookie,
            "has_return_to_cookie": bool(return_to_cookie),
            "has_access_cookie": has_access_cookie,
            "has_refresh_cookie": has_refresh_cookie,
            "has_info_cookie": has_info_cookie,
            "login_refresh_attempted": login_refresh_attempted,
            "callback_error_reason": callback_error_reason,
            "auth_login_url": settings.auth_login_url,
        },
        status_code=400,
    )


def _set_login_refresh_attempt_cookie(request: Request, response: Response) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=LOGIN_REFRESH_ATTEMPT_COOKIE_NAME,
        value="1",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )


def _clear_login_refresh_attempt_cookie(request: Request, response: Response) -> None:
    settings = request.app.state.settings
    response.delete_cookie(
        key=LOGIN_REFRESH_ATTEMPT_COOKIE_NAME,
        domain=settings.cookie_domain,
        path="/",
    )
    response.delete_cookie(
        key=LOGIN_REFRESH_ATTEMPT_COOKIE_NAME,
        path="/",
    )


def _login_refresh_already_attempted(request: Request) -> bool:
    return request.cookies.get(LOGIN_REFRESH_ATTEMPT_COOKIE_NAME) == "1"


async def _read_login_session_context(
    provider,
    request: Request,
) -> tuple[AuthSessionContext | None, str | None]:
    try:
        return await provider.authenticate_request(request), None
    except AccessTokenExpiredError as error:
        return None, str(error)
    except (AuthRequiredError, InvalidAuthPayloadError) as error:
        return None, str(error)


def _ensure_local_user_for_session(db: Session, session_context: AuthSessionContext) -> str | None:
    if session_context.profile_identity is not None:
        get_or_create_local_user(db, session_context.profile_identity)
        return None

    local_user = get_local_user_by_external_id(db, session_context.external_id)
    if local_user is not None:
        return None

    return session_context.profile_error or (
        "Локальный пользователь не найден, а корректный профиль из info_token не получен."
    )


def _build_login_success_response(
    provider,
    request: Request,
    target_url: str,
    session_context: AuthSessionContext,
) -> Response:
    response = RedirectResponse(target_url, status_code=303)
    _clear_login_refresh_attempt_cookie(request, response)
    return provider.finalize_login_response(
        request=request,
        response=response,
        clear_info=session_context.had_info_token,
    )


async def _try_refresh_login_request(provider, request: Request) -> Response | None:
    access_token = provider.read_access_token(request)
    refresh_token = provider.read_refresh_token(request)
    if access_token is None or refresh_token is None:
        return None

    if _login_refresh_already_attempted(request):
        return _build_failed_auth_callback_response(request)

    refresh_result = await provider.proxy_refresh(request)
    if not bool(refresh_result.get("ok")) or not refresh_result.get("set_cookie_headers"):
        return None

    response = RedirectResponse(str(request.url), status_code=303)
    provider.mirror_set_cookie_headers(response, list(refresh_result.get("set_cookie_headers", [])))
    _set_login_refresh_attempt_cookie(request, response)
    return response


@router.get("/login", name="login_entry")
async def login_entry(request: Request, db: Session = Depends(get_db)):
    provider = request.app.state.auth_provider
    default_target = str(request.url_for("equipment_page"))
    target_url = provider.resolve_local_return_to(request, default_target)
    session_context, access_error_reason = await _read_login_session_context(provider, request)

    if session_context is not None:
        local_user_error = _ensure_local_user_for_session(db, session_context)
        if local_user_error is not None:
            request.state.callback_error_reason = local_user_error
            return _build_failed_auth_callback_response(request)

        return _build_login_success_response(
            provider=provider,
            request=request,
            target_url=target_url,
            session_context=session_context,
        )

    request.state.callback_error_reason = access_error_reason
    refresh_response = await _try_refresh_login_request(provider, request)
    if refresh_response is not None:
        return refresh_response

    if _looks_like_failed_auth_callback(request):
        return _build_failed_auth_callback_response(request)

    response = provider.build_auth_login_redirect_response(request, target_url=target_url)
    _clear_login_refresh_attempt_cookie(request, response)
    return response


@router.get("/auth/return", name="auth_return_legacy")
async def auth_return_legacy():
    return RedirectResponse("/login", status_code=303)


@router.post("/session/refresh", name="session_refresh")
async def session_refresh(request: Request):
    provider = request.app.state.auth_provider
    access_token = provider.read_access_token(request)
    refresh_token = provider.read_refresh_token(request)

    if access_token is None or refresh_token is None:
        return JSONResponse(
            content={
                "ok": False,
                "message": "Для refresh нужна пара access_token и refresh_token.",
            },
            status_code=400,
        )

    refresh_result = await provider.proxy_refresh(request)
    response = JSONResponse(
        content={
            "ok": bool(refresh_result.get("ok")),
            "message": str(refresh_result.get("body_text") or ""),
        },
        status_code=int(refresh_result.get("status_code") or 500),
    )
    provider.mirror_set_cookie_headers(response, list(refresh_result.get("set_cookie_headers", [])))
    return response


@router.post("/logout", name="logout_entry")
async def logout_entry(request: Request):
    provider = request.app.state.auth_provider
    access_token = provider.read_access_token(request)
    refresh_token = provider.read_refresh_token(request)

    if access_token is None or refresh_token is None:
        response = RedirectResponse(str(request.url_for("login_entry")), status_code=303)
        provider.clear_auth_cookies(response)
        provider.clear_return_to_cookie(response)
        provider.clear_callback_cookie(response)
        _clear_login_refresh_attempt_cookie(request, response)
        return response

    logout_result = await provider.proxy_logout(request)
    if not bool(logout_result.get("ok")):
        return PlainTextResponse(
            content=str(logout_result.get("body_text") or ""),
            status_code=int(logout_result.get("status_code") or 500),
        )

    response = RedirectResponse(str(request.url_for("login_entry")), status_code=303)
    provider.mirror_set_cookie_headers(response, list(logout_result.get("set_cookie_headers", [])))
    provider.clear_auth_cookies(response)
    provider.clear_return_to_cookie(response)
    provider.clear_callback_cookie(response)
    _clear_login_refresh_attempt_cookie(request, response)
    return response


@router.get("/health", tags=["system"])
def healthcheck():
    return PlainTextResponse("ok")
