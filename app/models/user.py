from __future__ import annotations

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import UserRole


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    nickname: Mapped[str] = mapped_column(String(100), index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER, nullable=False, index=True)

    held_items = relationship("ItemInstance", back_populates="current_holder")
    issued_records_received = relationship("IssueRecord", foreign_keys="IssueRecord.issued_to_user_id")
    issued_records_created = relationship("IssueRecord", foreign_keys="IssueRecord.issued_by_user_id")
    issued_records_returned = relationship("IssueRecord", foreign_keys="IssueRecord.returned_by_user_id")
    audit_logs = relationship("AuditLog", back_populates="actor")
