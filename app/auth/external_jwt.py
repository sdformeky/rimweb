from __future__ import annotations

import asyncio
import time
import urllib.error
import urllib.request

from typing import Any
from urllib.parse import urlsplit

import jwt

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from jwt import ExpiredSignatureError, InvalidTokenError

from app.auth.base import (
    AccessTokenExpiredError,
    AuthProvider,
    AuthServiceUnavailableError,
    AuthRequiredError,
    AuthSessionContext,
    InvalidAuthPayloadError,
)
from app.config import Settings
from app.services.auth_users import AuthIdentity


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ExternalJwtAuthProvider(AuthProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.public_key_cache: str | None = None
        self.public_key_cached_at = 0.0

    def read_access_token(self, request: Request) -> str | None:
        cookie_token = request.cookies.get(self.settings.access_cookie_name)
        if cookie_token:
            return cookie_token
        scheme, _, bearer_token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and bearer_token.strip():
            return bearer_token.strip()
        return None

    def read_refresh_token(self, request: Request) -> str | None:
        return request.cookies.get(self.settings.refresh_cookie_name)

    def read_info_token(self, request: Request) -> str | None:
        return request.cookies.get(self.settings.info_cookie_name)

    def read_return_to(self, request: Request) -> str | None:
        return request.cookies.get(self.settings.return_to_cookie_name)

    async def fetch_public_key(self) -> str:
        if self.public_key_cache is None or self._is_public_key_cache_stale():
            try:
                await self.refresh_public_key_cache()
            except (OSError, RuntimeError, ValueError) as error:
                if self.public_key_cache is None:
                    raise AuthServiceUnavailableError("Не удалось получить публичный ключ авторизации.") from error
        return self.public_key_cache or ""

    async def refresh_public_key_cache(self) -> None:
        public_key = await asyncio.to_thread(self._download_public_key)
        self.public_key_cache = public_key
        self.public_key_cached_at = time.monotonic()

    async def validate_access_token_locally(self, access_token: str) -> dict[str, Any]:
        public_key = await self.fetch_public_key()
        return dict(
            jwt.decode(
                jwt=access_token,
                key=public_key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        )

    async def validate_access_token_allow_expired(self, access_token: str) -> dict[str, Any]:
        public_key = await self.fetch_public_key()
        return dict(
            jwt.decode(
                jwt=access_token,
                key=public_key,
                algorithms=["RS256"],
                options={"verify_aud": False, "verify_exp": False},
            )
        )

    async def decode_info_token_locally(self, info_token: str) -> dict[str, Any]:
        public_key = await self.fetch_public_key()
        return dict(
            jwt.decode(
                jwt=info_token,
                key=public_key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        )

    async def authenticate_request(self, request: Request) -> AuthSessionContext:
        access_token = self.read_access_token(request)
        if not access_token:
            raise AuthRequiredError("Missing auth cookies.")

        try:
            access_payload = await self.validate_access_token_locally(access_token)
        except ExpiredSignatureError as error:
            expired_payload = await self._decode_expired_access_payload(access_token)
            raise AccessTokenExpiredError("Access token expired.", access_payload=expired_payload) from error
        except InvalidTokenError as error:
            raise AuthRequiredError("Invalid auth token.") from error

        external_id = self._extract_external_id(access_payload)
        return await self._build_session_context(
            request=request,
            external_id=external_id,
            access_payload=access_payload,
        )

    async def _build_session_context(
        self,
        request: Request,
        external_id: str,
        access_payload: dict[str, Any],
    ) -> AuthSessionContext:
        info_token = self.read_info_token(request)
        if not info_token:
            return self._build_session_context_without_profile(
                external_id=external_id,
                access_payload=access_payload,
            )

        profile_payload, profile_error = await self._decode_profile_payload(
            info_token=info_token,
        )
        if profile_error is not None:
            return self._build_session_context_without_profile(
                external_id=external_id,
                access_payload=access_payload,
                had_info_token=True,
                profile_error=profile_error,
            )

        try:
            profile_identity = self._build_identity(
                external_id=external_id,
                profile_payload=profile_payload,
            )
        except InvalidAuthPayloadError as error:
            return self._build_session_context_without_profile(
                external_id=external_id,
                access_payload=access_payload,
                had_info_token=True,
                profile_error=str(error),
            )

        return AuthSessionContext(
            external_id=external_id,
            access_payload=access_payload,
            profile_identity=profile_identity,
            had_info_token=True,
            profile_error=None,
        )

    def build_auth_login_redirect_response(self, request: Request, target_url: str) -> Response:
        callback_url = self._build_callback_url(request)
        response = RedirectResponse(self.settings.auth_login_url, status_code=302)
        self.set_return_to_cookie(response, request, target_url)
        self._set_cookie(response, self.settings.callback_cookie_name, callback_url)
        return response

    def build_local_login_redirect_response(self, request: Request, return_to: str | None = None) -> Response:
        response = RedirectResponse(str(request.url_for("login_entry")), status_code=303)
        if return_to:
            self.set_return_to_cookie(response, request, return_to)
        return response

    def finalize_login_response(self, request: Request, response: Response, clear_info: bool = False) -> Response:
        self.clear_return_to_cookie(response)
        self.clear_callback_cookie(response)
        if clear_info:
            self.clear_info_cookie(response)
        return response

    async def proxy_refresh(self, request: Request) -> dict[str, object]:
        cookie_header = request.headers.get("cookie", "")
        return await asyncio.to_thread(
            self._proxy_cookie_post_request,
            self.settings.auth_refresh_url,
            cookie_header,
        )

    async def proxy_logout(self, request: Request) -> dict[str, object]:
        cookie_header = request.headers.get("cookie", "")
        return await asyncio.to_thread(
            self._proxy_cookie_post_request,
            self.settings.auth_logout_url,
            cookie_header,
            False,
        )

    def mirror_set_cookie_headers(self, response: Response, set_cookie_headers: list[str]) -> None:
        for header in set_cookie_headers:
            response.raw_headers.append((b"set-cookie", header.encode("latin-1")))

    def clear_return_to_cookie(self, response: Response) -> None:
        self._delete_cookie_variants(response, self.settings.return_to_cookie_name)

    def clear_callback_cookie(self, response: Response) -> None:
        self._delete_cookie_variants(response, self.settings.callback_cookie_name)

    def clear_info_cookie(self, response: Response) -> None:
        self._delete_cookie_variants(response, self.settings.info_cookie_name)

    def clear_auth_cookies(self, response: Response) -> None:
        self._delete_cookie_variants(response, self.settings.access_cookie_name)
        self._delete_cookie_variants(response, self.settings.refresh_cookie_name)
        self._delete_cookie_variants(response, self.settings.info_cookie_name)

    def resolve_local_return_to(self, request: Request, fallback_url: str) -> str:
        stored_return_to = self._ensure_safe_return_to(self.read_return_to(request), request)
        if stored_return_to:
            return stored_return_to

        referer_return_to = self._ensure_safe_return_to(request.headers.get("referer"), request)
        if referer_return_to:
            return referer_return_to

        fallback_value = self._ensure_safe_return_to(fallback_url, request)
        if fallback_value:
            return fallback_value

        return self._build_default_target_url(request, fallback_url)

    def _download_public_key(self) -> str:
        with urllib.request.urlopen(self.settings.auth_public_key_url, timeout=5) as response:
            public_key = response.read().decode("utf-8").strip()
        if not public_key:
            raise RuntimeError("AUTH public key endpoint returned an empty response.")
        return public_key

    def _proxy_cookie_post_request(
        self,
        url: str,
        cookie_header: str,
        follow_redirects: bool = True,
    ) -> dict[str, object]:
        request = urllib.request.Request(
            url=url,
            data=b"",
            method="POST",
            headers={"Cookie": cookie_header},
        )

        try:
            if follow_redirects:
                response_context = urllib.request.urlopen(request, timeout=5)
            else:
                response_context = urllib.request.build_opener(_NoRedirectHandler()).open(request, timeout=5)

            with response_context as response:
                status_code = response.getcode()
                body_text = response.read().decode("utf-8", errors="replace")
                set_cookie_headers = response.headers.get_all("Set-Cookie", [])
        except urllib.error.HTTPError as error:
            status_code = error.code
            body_text = error.read().decode("utf-8", errors="replace")
            set_cookie_headers = error.headers.get_all("Set-Cookie", [])
        except OSError as error:
            status_code = 503
            body_text = f"Сервис авторизации недоступен: {error}"
            set_cookie_headers = []

        return {
            "ok": status_code < 400,
            "status_code": status_code,
            "body_text": body_text,
            "set_cookie_headers": set_cookie_headers,
        }

    def _set_cookie(self, response: Response, key: str, value: str) -> None:
        response.set_cookie(
            key=key,
            value=value,
            httponly=True,
            secure=self.settings.cookie_secure,
            samesite=self.settings.cookie_samesite,
            domain=self.settings.cookie_domain,
            path="/",
        )

    def set_return_to_cookie(self, response: Response, request: Request, return_to: str) -> None:
        if return_to.startswith("/"):
            return_to = f"{str(request.base_url).rstrip('/')}{return_to}"

        response.set_cookie(
            key=self.settings.return_to_cookie_name,
            value=return_to,
            httponly=True,
            secure=self.settings.cookie_secure,
            samesite=self.settings.cookie_samesite,
            domain=self.settings.cookie_domain,
            path="/",
        )

    def _build_callback_url(self, request: Request) -> str:
        return self.settings.auth_callback_url or str(request.url_for("login_entry"))

    def _build_default_target_url(self, request: Request, fallback_url: str) -> str:
        fallback_value = str(fallback_url or "").strip()
        if fallback_value.startswith("/"):
            return f"{str(request.base_url).rstrip('/')}{fallback_value}"
        if fallback_value:
            return fallback_value
        return str(request.base_url).rstrip("/")

    def _resolve_expected_origin(self, request: Request) -> str:
        callback_url = self._build_callback_url(request)
        parsed = urlsplit(callback_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        base_url = str(request.base_url).rstrip("/")
        parsed_base = urlsplit(base_url)
        return f"{parsed_base.scheme.lower()}://{parsed_base.netloc.lower()}"

    def _ensure_safe_return_to(self, return_to: str | None, request: Request) -> str:
        cleaned = str(return_to or "").strip()
        if not cleaned:
            return ""
        if cleaned.startswith("/"):
            if cleaned.startswith("//") or "\\" in cleaned:
                return ""
            return cleaned

        parsed = urlsplit(cleaned)
        if not parsed.scheme or not parsed.netloc:
            return ""

        expected_origin = self._resolve_expected_origin(request)
        provided_origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        if provided_origin != expected_origin:
            return ""

        return cleaned

    def _build_identity(self, external_id: str, profile_payload: dict[str, Any]) -> AuthIdentity:
        derived_full_name = self._build_profile_full_name(profile_payload)
        full_name = str(
            derived_full_name
            or profile_payload.get("full_name")
            or profile_payload.get("name")
            or profile_payload.get("fio")
            or ""
        ).strip()
        nickname = self._build_profile_nickname(profile_payload)
        email = str(profile_payload.get("email") or "").strip() or None
        department = str(profile_payload.get("department") or "").strip() or None

        if not full_name or not nickname:
            raise InvalidAuthPayloadError("Info token does not contain required profile fields.")

        return AuthIdentity(
            external_id=external_id,
            full_name=full_name,
            nickname=nickname,
            email=email,
            department=department,
        )

    def _is_public_key_cache_stale(self) -> bool:
        if self.public_key_cache is None:
            return True
        cache_age_seconds = time.monotonic() - self.public_key_cached_at
        return cache_age_seconds >= self.settings.public_key_cache_ttl_seconds

    async def _decode_expired_access_payload(self, access_token: str) -> dict[str, Any] | None:
        try:
            return await self.validate_access_token_allow_expired(access_token)
        except InvalidTokenError:
            return None

    async def _decode_profile_payload(self, info_token: str) -> tuple[dict[str, Any], str | None]:
        try:
            return await self.decode_info_token_locally(info_token), None
        except ExpiredSignatureError:
            return {}, "Info token expired."
        except InvalidTokenError:
            return {}, "Info token is invalid."

    def _extract_external_id(self, access_payload: dict[str, Any]) -> str:
        external_id = str(access_payload.get("sub") or "").strip()
        if not external_id:
            raise InvalidAuthPayloadError("Access token does not contain required subject.")
        return external_id

    def _build_session_context_without_profile(
        self,
        external_id: str,
        access_payload: dict[str, Any],
        had_info_token: bool = False,
        profile_error: str | None = None,
    ) -> AuthSessionContext:
        return AuthSessionContext(
            external_id=external_id,
            access_payload=access_payload,
            profile_identity=None,
            had_info_token=had_info_token,
            profile_error=profile_error,
        )

    def _build_profile_full_name(self, profile_payload: dict[str, Any]) -> str:
        first_name = str(profile_payload.get("first_name") or "").strip()
        last_name = str(profile_payload.get("last_name") or "").strip()
        middle_name = str(profile_payload.get("middle_name") or "").strip()
        return " ".join(part for part in [last_name, first_name, middle_name] if part).strip()

    def _build_profile_nickname(self, profile_payload: dict[str, Any]) -> str:
        return str(
            profile_payload.get("nickname")
            or profile_payload.get("nick")
            or profile_payload.get("preferred_username")
            or ""
        ).strip()

    def _delete_cookie_variants(self, response: Response, key: str) -> None:
        if self.settings.cookie_domain:
            response.delete_cookie(
                key=key,
                domain=self.settings.cookie_domain,
                path="/",
            )

        response.delete_cookie(
            key=key,
            path="/",
        )
