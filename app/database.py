from __future__ import annotations

from importlib import import_module
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.base import Base


import_module("app.models")


settings = get_settings()

connect_args: dict[str, object] = {}
if settings.is_sqlite:
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    future=True,
    echo=settings.debug,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()


def run_lightweight_migrations() -> None:
    inspector = inspect(engine)
    if "item_types" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("item_types")}
    statements: list[str] = []
    if "store_url" not in column_names:
        statements.append("ALTER TABLE item_types ADD COLUMN store_url VARCHAR(500)")
    if "unit_label" not in column_names:
        statements.append("ALTER TABLE item_types ADD COLUMN unit_label VARCHAR(64) NOT NULL DEFAULT 'шт'")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
