from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.lab_location import LabLocation
from app.models.warehouse_location import WarehouseLocation


def list_locations(db: Session) -> list[LabLocation]:
    return list(
        db.scalars(
            select(LabLocation)
            .options(selectinload(LabLocation.children))
            .order_by(LabLocation.parent_id.asc().nullsfirst(), LabLocation.type_label.asc(), LabLocation.name.asc())
        ).all()
    )


def get_location(db: Session, location_id: int) -> LabLocation | None:
    return db.scalar(select(LabLocation).where(LabLocation.id == location_id))


def list_warehouse_locations(db: Session) -> list[WarehouseLocation]:
    return list(
        db.scalars(
            select(WarehouseLocation).order_by(WarehouseLocation.room.asc(), WarehouseLocation.slot_code.asc())
        ).all()
    )


def get_warehouse_location(db: Session, location_id: int) -> WarehouseLocation | None:
    return db.scalar(select(WarehouseLocation).where(WarehouseLocation.id == location_id))
