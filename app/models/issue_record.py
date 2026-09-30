from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import PhysicalLocationType


class IssueRecord(TimestampMixin, Base):
    __tablename__ = "issue_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_instance_id: Mapped[int] = mapped_column(ForeignKey("item_instances.id"), nullable=False, index=True)
    issued_to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    issued_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    returned_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    issue_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_physical_location_type: Mapped[PhysicalLocationType] = mapped_column(
        Enum(PhysicalLocationType),
        nullable=False,
    )
    previous_warehouse_location_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_lab_location_id: Mapped[int | None] = mapped_column(ForeignKey("lab_locations.id"), nullable=True)
    return_physical_location_type: Mapped[PhysicalLocationType | None] = mapped_column(
        Enum(PhysicalLocationType),
        nullable=True,
    )
    return_warehouse_location_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_lab_location_id: Mapped[int | None] = mapped_column(ForeignKey("lab_locations.id"), nullable=True)

    item_instance = relationship("ItemInstance", back_populates="issue_records")
    issued_to_user = relationship("User", foreign_keys=[issued_to_user_id], back_populates="issued_records_received")
    issued_by_user = relationship("User", foreign_keys=[issued_by_user_id], back_populates="issued_records_created")
    returned_by_user = relationship("User", foreign_keys=[returned_by_user_id], back_populates="issued_records_returned")
    previous_lab_location = relationship("LabLocation", foreign_keys=[previous_lab_location_id])
    return_lab_location = relationship("LabLocation", foreign_keys=[return_lab_location_id])
