from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class LabLocation(TimestampMixin, Base):
    __tablename__ = "lab_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("lab_locations.id"), nullable=True, index=True)
    type_label: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    parent = relationship("LabLocation", remote_side=[id], back_populates="children")
    children = relationship("LabLocation", back_populates="parent")
    items = relationship("ItemInstance", back_populates="lab_location")
