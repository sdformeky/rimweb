from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse, Response

from app.auth.base import (
    AccessTokenExpiredError,
    AuthProvider,
    AuthRequiredError,
    AuthServiceUnavailableError,
    AuthSessionContext,
    InvalidAuthPayloadError,
)
from app.database import SessionLocal, get_db
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.users import get_user_by_id
from app.services.auth_users import get_local_user_by_external_id, get_or_create_local_user


PUBLIC_PATH_PREFIXES = ("/static",)
PUBLIC_PATHS = {"/login", "/logout", "/health", "/healthcheck", "/session/refresh", "/auth/return"}
API_PATH_PREFIX = "/api/"


AUTH_UNAVAILABLE_MESSAGE = "Сервис авторизации временно недоступен. Попробуйте позже."


def build_auth_unavailable_response(request: Request) -> Response:
    if request.url.path.startswith(API_PATH_PREFIX):
        return JSONResponse({"detail": AUTH_UNAVAILABLE_MESSAGE}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return HTMLResponse(
        "<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"UTF-8\"><title>Вход недоступен</title></head>"
        f"<body style=\"font-family: sans-serif; padding: 40px;\"><h1>Вход недоступен</h1><p>{AUTH_UNAVAILABLE_MESSAGE}</p></body></html>",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


class AuthSessionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, provider: AuthProvider) -> None:
        super().__init__(app)
        self.provider = provider

    @staticmethod
    def _build_return_to(request: Request) -> str | None:
        if request.method.upper() != "GET":
            return None
        return str(request.url)

    def _build_login_redirect(self, request: Request) -> Response:
        if request.url.path.startswith(API_PATH_PREFIX):
            return JSONResponse(
                {"detail": "Требуется авторизация."},
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return self.provider.build_local_login_redirect_response(
            request,
            return_to=self._build_return_to(request),
        )

    @staticmethod
    def _build_session_from_expired_access(
        external_id: str,
        access_payload: dict[str, object],
        had_info_token: bool,
    ) -> AuthSessionContext:
        return AuthSessionContext(
            external_id=external_id,
            access_payload=access_payload,
            profile_identity=None,
            had_info_token=had_info_token,
            profile_error=None,
        )

    async def _try_restore_expired_session(
        self,
        request: Request,
        error: AccessTokenExpiredError,
    ) -> tuple[AuthSessionContext | None, list[str]]:
        refresh_token = self.provider.read_refresh_token(request)
        if not refresh_token:
            return None, []

        refresh_result = await self.provider.proxy_refresh(request)
        if not bool(refresh_result.get("ok")):
            return None, []

        expired_access_payload = getattr(error, "access_payload", {}) or {}
        external_id = str(expired_access_payload.get("sub") or "").strip()
        if not external_id:
            return None, []

        session_context = self._build_session_from_expired_access(
            external_id=external_id,
            access_payload=expired_access_payload,
            had_info_token=bool(self.provider.read_info_token(request)),
        )
        mirrored_set_cookie_headers = list(refresh_result.get("set_cookie_headers", []))
        return session_context, mirrored_set_cookie_headers

    @staticmethod
    def _attach_user_to_request(request: Request, session_context: AuthSessionContext) -> bool:
        with SessionLocal() as db:
            if session_context.profile_identity is not None:
                user = get_or_create_local_user(db, session_context.profile_identity)
            else:
                user = get_local_user_by_external_id(db, session_context.external_id)
                if user is None:
                    return False
            request.state.current_user_id = user.id
            request.state.current_user_role = user.role.value
            request.state.current_access_payload = session_context.access_payload
        return True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith(PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        try:
            session_context = await self.provider.authenticate_request(request)
        except AccessTokenExpiredError as error:
            session_context, mirrored_set_cookie_headers = await self._try_restore_expired_session(
                request=request,
                error=error,
            )
            if session_context is None:
                return self._build_login_redirect(request)
        except (AuthRequiredError, InvalidAuthPayloadError):
            return self._build_login_redirect(request)
        except AuthServiceUnavailableError:
            return build_auth_unavailable_response(request)
        else:
            mirrored_set_cookie_headers = []

        if not self._attach_user_to_request(request, session_context):
            return self._build_login_redirect(request)

        response = await call_next(request)
        if session_context.had_info_token:
            self.provider.clear_info_cookie(response)
        if mirrored_set_cookie_headers:
            self.provider.mirror_set_cookie_headers(response, mirrored_set_cookie_headers)
        return response


def get_current_user(request: Request, db=Depends(get_db)) -> User:
    user_id = getattr(request.state, "current_user_id", None)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется авторизация.")
    user = get_user_by_id(db, int(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден.")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Требуются права администратора.")
    return current_user
