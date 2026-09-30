from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import ConditionStatus, LifecycleStatus, PhysicalLocationType


class ItemInstance(TimestampMixin, Base):
    __tablename__ = "item_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_type_id: Mapped[int] = mapped_column(ForeignKey("item_types.id"), nullable=False, index=True)
    inventory_number: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    condition_status: Mapped[ConditionStatus] = mapped_column(
        Enum(ConditionStatus),
        default=ConditionStatus.WORKING,
        nullable=False,
        index=True,
    )
    lifecycle_status: Mapped[LifecycleStatus] = mapped_column(
        Enum(LifecycleStatus),
        default=LifecycleStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    purchase_number: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    purchase_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tags_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    current_holder_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    physical_location_type: Mapped[PhysicalLocationType] = mapped_column(
        Enum(PhysicalLocationType),
        default=PhysicalLocationType.NONE,
        nullable=False,
        index=True,
    )
    warehouse_location_text: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    lab_location_id: Mapped[int | None] = mapped_column(ForeignKey("lab_locations.id"), nullable=True, index=True)

    item_type = relationship("ItemType", back_populates="instances")
    current_holder = relationship("User", back_populates="held_items")
    lab_location = relationship("LabLocation", back_populates="items")
    issue_records = relationship("IssueRecord", back_populates="item_instance", order_by="IssueRecord.issued_at.desc()")
