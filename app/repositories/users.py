from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.issue_record import IssueRecord
from app.models.user import User


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_external_id(db: Session, external_id: str) -> User | None:
    return db.scalar(select(User).where(User.external_id == external_id))


def get_user_by_nickname(db: Session, nickname: str) -> User | None:
    return db.scalar(select(User).where(User.nickname == nickname))


def list_users(db: Session, query: str | None = None) -> list[User]:
    statement: Select[tuple[User]] = select(User).order_by(User.full_name.asc())
    if query:
        like_value = f"%{query.strip()}%"
        statement = statement.where(
            (User.full_name.ilike(like_value))
            | (User.nickname.ilike(like_value))
            | (User.email.ilike(like_value))
            | (User.department.ilike(like_value))
        )
    return list(db.scalars(statement).all())


def count_active_issues_for_user(db: Session, user_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(IssueRecord.id)).where(
                IssueRecord.issued_to_user_id == user_id,
                IssueRecord.returned_at.is_(None),
            )
        )
        or 0
    )


def count_admins(db: Session) -> int:
    return int(db.scalar(select(func.count(User.id)).where(User.role == UserRole.ADMIN)) or 0)
