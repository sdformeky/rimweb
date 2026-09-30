from __future__ import annotations

import os

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    base_dir: Path
    database_path: Path
    database_url: str
    debug: bool
    host: str
    port: int
    first_admin_nick: str
    inventory_number_prefix: str
    auth_base_url: str
    auth_login_url: str
    auth_refresh_url: str
    auth_logout_url: str
    auth_public_key_url: str
    auth_callback_url: str | None
    access_cookie_name: str
    refresh_cookie_name: str
    info_cookie_name: str
    callback_cookie_name: str
    return_to_cookie_name: str
    cookie_domain: str | None
    cookie_secure: bool
    cookie_samesite: str
    public_key_cache_ttl_seconds: int

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    base_dir = BASE_DIR
    database_path = Path(os.getenv("DATABASE_PATH", str(base_dir / "data" / "app.sqlite3"))).expanduser()
    if not database_path.is_absolute():
        database_path = (base_dir / database_path).resolve()

    database_url = os.getenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")

    auth_base_url = os.getenv("AUTH_BASE_URL", "http://127.0.0.1:8000")
    auth_login_url = os.getenv("AUTH_LOGIN_URL", f"{auth_base_url.rstrip('/')}/login")
    auth_refresh_url = os.getenv("AUTH_REFRESH_URL", f"{auth_base_url.rstrip('/')}/refresh")
    auth_logout_url = os.getenv("AUTH_LOGOUT_URL", f"{auth_base_url.rstrip('/')}/logout")
    auth_public_key_url = os.getenv("AUTH_PUBLIC_KEY_URL", f"{auth_base_url.rstrip('/')}/keys/public")

    return Settings(
        app_name=os.getenv("APP_NAME", "RIM"),
        base_dir=base_dir,
        database_path=database_path,
        database_url=database_url,
        debug=_bool_env("DEBUG", False),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8010")),
        first_admin_nick=os.getenv("FIRST_ADMIN_NICK", "admin"),
        inventory_number_prefix=os.getenv("INVENTORY_NUMBER_PREFIX", "INV"),
        auth_base_url=auth_base_url,
        auth_login_url=auth_login_url,
        auth_refresh_url=auth_refresh_url,
        auth_logout_url=auth_logout_url,
        auth_public_key_url=auth_public_key_url,
        auth_callback_url=os.getenv("AUTH_CALLBACK_URL"),
        access_cookie_name=os.getenv("ACCESS_COOKIE_NAME", "access_token"),
        refresh_cookie_name=os.getenv("REFRESH_COOKIE_NAME", "refresh_token"),
        info_cookie_name=os.getenv("INFO_COOKIE_NAME", "info_token"),
        callback_cookie_name=os.getenv("CALLBACK_COOKIE_NAME", "callback_url"),
        return_to_cookie_name=os.getenv("RETURN_TO_COOKIE_NAME", "rim_return_to"),
        cookie_domain=os.getenv("COOKIE_DOMAIN"),
        cookie_secure=_bool_env("COOKIE_SECURE", False),
        cookie_samesite=os.getenv("COOKIE_SAMESITE", "lax"),
        public_key_cache_ttl_seconds=int(os.getenv("PUBLIC_KEY_CACHE_TTL_SECONDS", "300")),
    )
