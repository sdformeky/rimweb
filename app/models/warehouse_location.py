from __future__ import annotations

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WarehouseLocation(TimestampMixin, Base):
    __tablename__ = "warehouse_locations"
    __table_args__ = (
        UniqueConstraint("room", "slot_code", name="uq_warehouse_locations_room_slot_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    room: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    slot_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
