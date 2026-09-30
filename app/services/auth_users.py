from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import UserRole
from app.models.user import User
from app.repositories import users as user_repo
from app.services.audit import add_audit_log


@dataclass(frozen=True)
class AuthIdentity:
    external_id: str
    full_name: str
    nickname: str
    email: str | None = None
    department: str | None = None


def get_local_user_by_external_id(db: Session, external_id: str) -> User | None:
    return user_repo.get_user_by_external_id(db, external_id)


def get_or_create_local_user(db: Session, identity: AuthIdentity) -> User:
    settings = get_settings()
    user = user_repo.get_user_by_external_id(db, identity.external_id)

    if user is None:
        is_first_admin = identity.nickname == settings.first_admin_nick and user_repo.count_admins(db) == 0
        assigned_role = UserRole.ADMIN if is_first_admin else UserRole.USER
        user = User(
            external_id=identity.external_id,
            full_name=identity.full_name,
            nickname=identity.nickname,
            email=identity.email,
            department=identity.department,
            role=assigned_role,
        )
        db.add(user)
        db.flush()
        add_audit_log(
            db=db,
            actor=user,
            action_type="user_auto_created",
            entity_type="user",
            entity_id=user.id,
            new_value={
                "external_id": user.external_id,
                "full_name": user.full_name,
                "nickname": user.nickname,
                "role": user.role.value,
            },
            comment="Пользователь создан автоматически при первом входе.",
        )
        if assigned_role == UserRole.ADMIN:
            add_audit_log(
                db=db,
                actor=user,
                action_type="admin_assigned",
                entity_type="user",
                entity_id=user.id,
                new_value={"role": assigned_role.value},
                comment="Первый администратор назначен по FIRST_ADMIN_NICK.",
            )
        db.commit()
        db.refresh(user)
        return user

    has_changes = False
    old_value = {
        "full_name": user.full_name,
        "nickname": user.nickname,
        "email": user.email,
        "department": user.department,
    }
    if user.full_name != identity.full_name:
        user.full_name = identity.full_name
        has_changes = True
    if user.nickname != identity.nickname:
        user.nickname = identity.nickname
        has_changes = True
    if identity.email is not None and user.email != identity.email:
        user.email = identity.email
        has_changes = True
    if identity.department is not None and user.department != identity.department:
        user.department = identity.department
        has_changes = True

    if has_changes:
        add_audit_log(
            db=db,
            actor=user,
            action_type="user_synced_from_auth",
            entity_type="user",
            entity_id=user.id,
            old_value=old_value,
            new_value={
                "full_name": user.full_name,
                "nickname": user.nickname,
                "email": user.email,
                "department": user.department,
            },
            comment="Профиль обновлен из внешней авторизации.",
        )
        db.commit()
        db.refresh(user)

    return user
