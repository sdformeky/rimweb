from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ItemType(TimestampMixin, Base):
    __tablename__ = "item_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    store_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    unit_label: Mapped[str] = mapped_column(String(64), default="шт", nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    tags_text: Mapped[str] = mapped_column(Text, default="", nullable=False)

    instances = relationship("ItemInstance", back_populates="item_type")
