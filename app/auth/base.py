from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from abc import ABC, abstractmethod

from fastapi import Request, Response

from app.services.auth_users import AuthIdentity


class AuthError(Exception):
    """Base auth error."""


class AuthRequiredError(AuthError):
    """User must authenticate."""


class AccessTokenExpiredError(AuthError):
    """Access token exists but is expired."""

    def __init__(self, message: str, access_payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.access_payload = access_payload or {}


class InvalidAuthPayloadError(AuthError):
    """Token payload is incomplete."""


class AuthServiceUnavailableError(AuthError):
    pass


@dataclass(frozen=True)
class AuthSessionContext:
    external_id: str
    access_payload: dict[str, Any]
    profile_identity: AuthIdentity | None = None
    had_info_token: bool = False
    profile_error: str | None = None


class AuthProvider(ABC):
    @abstractmethod
    async def authenticate_request(self, request: Request) -> AuthSessionContext:
        raise NotImplementedError

    @abstractmethod
    def build_auth_login_redirect_response(self, request: Request, target_url: str) -> Response:
        raise NotImplementedError

    @abstractmethod
    async def proxy_refresh(self, request: Request) -> dict[str, object]:
        raise NotImplementedError

    @abstractmethod
    async def proxy_logout(self, request: Request) -> dict[str, object]:
        raise NotImplementedError

    @abstractmethod
    def finalize_login_response(self, request: Request, response: Response, clear_info: bool = False) -> Response:
        raise NotImplementedError

    @abstractmethod
    def read_refresh_token(self, request: Request) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def read_access_token(self, request: Request) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def read_info_token(self, request: Request) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def resolve_local_return_to(self, request: Request, fallback_url: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def build_local_login_redirect_response(self, request: Request, return_to: str | None = None) -> Response:
        raise NotImplementedError

    @abstractmethod
    def clear_return_to_cookie(self, response: Response) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear_callback_cookie(self, response: Response) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear_info_cookie(self, response: Response) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear_auth_cookies(self, response: Response) -> None:
        raise NotImplementedError

    @abstractmethod
    def mirror_set_cookie_headers(self, response: Response, set_cookie_headers: list[str]) -> None:
        raise NotImplementedError
