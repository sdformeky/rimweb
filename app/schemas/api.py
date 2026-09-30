from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import ConditionStatus, LifecycleStatus, PhysicalLocationType, UserRole


class UserShort(BaseModel):
    id: int
    full_name: str
    nickname: str


class UserOut(UserShort):
    email: str | None
    department: str | None
    role: UserRole
    active_issues_count: int | None = None


class ItemTypeShort(BaseModel):
    id: int
    name: str


class LocationIn(BaseModel):
    type: PhysicalLocationType
    warehouse_location_text: str | None = None
    lab_location_id: int | None = None


class LocationOut(LocationIn):
    display: str


class MessageOut(BaseModel):
    detail: str


class ItemTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    comment: str | None = None
    store_url: str | None = None
    unit_label: str = "шт"
    unit_price: Decimal = Decimal("0.00")
    tags: list[str] = Field(default_factory=list)


class ItemTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    comment: str | None = None
    store_url: str | None = None
    unit_label: str | None = None
    unit_price: Decimal | None = None
    tags: list[str] | None = None


class ItemTypeOut(BaseModel):
    id: int
    name: str
    comment: str | None
    store_url: str | None
    unit_label: str
    unit_price: Decimal
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class InstanceOut(BaseModel):
    id: int
    inventory_number: str
    item_type: ItemTypeShort
    condition_status: ConditionStatus
    lifecycle_status: LifecycleStatus
    purchase_number: str | None
    purchase_unit_price: Decimal | None
    tags: list[str]
    current_holder: UserShort | None
    location: LocationOut
    created_at: datetime
    updated_at: datetime


class InstancesCreate(BaseModel):
    item_type_id: int
    quantity: int = Field(default=1, ge=1, le=10000)
    inventory_numbers: list[str] | None = Field(
        default=None,
        description="Инвентарные номера вручную. Если не заданы — генерируются автоматически.",
    )
    condition_status: ConditionStatus = ConditionStatus.WORKING
    purchase_number: str | None = None
    purchase_unit_price: Decimal | None = None
    tags: list[str] = Field(default_factory=list)
    location: LocationIn = Field(default_factory=lambda: LocationIn(type=PhysicalLocationType.WAREHOUSE))


class InstanceUpdate(BaseModel):
    inventory_number: str | None = None
    purchase_number: str | None = None
    purchase_unit_price: Decimal | None = None
    tags: list[str] | None = None
    condition_status: ConditionStatus | None = None
    lifecycle_status: LifecycleStatus | None = None
    comment: str | None = Field(default=None, description="Комментарий в журнал для смены состояния/статуса.")


class BulkSelection(BaseModel):
    instance_ids: list[int] = Field(min_length=1)


class BulkIssue(BulkSelection):
    user_id: int
    issued_at: datetime | None = None
    comment: str | None = None


class BulkReturn(BulkSelection):
    location: LocationIn | None = Field(
        default=None,
        description="Куда вернуть. Если не задано — каждый экземпляр возвращается на своё прежнее место.",
    )
    condition_status: ConditionStatus | None = None
    returned_at: datetime | None = None
    comment: str | None = None


class BulkMove(BulkSelection):
    location: LocationIn
    comment: str | None = None


class BulkCondition(BulkSelection):
    condition_status: ConditionStatus
    comment: str | None = None


class BulkComment(BulkSelection):
    comment: str | None = None


class BulkResult(BaseModel):
    affected: int
    instance_ids: list[int]


class IssueRecordOut(BaseModel):
    id: int
    instance_id: int
    inventory_number: str
    item_type: ItemTypeShort
    issued_to: UserShort
    issued_by: UserShort
    returned_by: UserShort | None
    issued_at: datetime
    returned_at: datetime | None
    comment: str | None


class LabLocationCreate(BaseModel):
    type_label: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    comment: str | None = None
    parent_id: int | None = None


class LabLocationUpdate(BaseModel):
    type_label: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    comment: str | None = None
    parent_id: int | None = None


class LabLocationOut(BaseModel):
    id: int
    parent_id: int | None
    type_label: str
    name: str
    comment: str | None
    path: str


class WarehouseLocationCreate(BaseModel):
    room: str = Field(min_length=1, max_length=128)
    slot_code: str = Field(min_length=1, max_length=128)
    comment: str | None = None


class WarehouseLocationOut(BaseModel):
    id: int
    room: str
    slot_code: str
    label: str
    comment: str | None


class AuditLogOut(BaseModel):
    id: int
    actor: UserShort | None
    action_type: str
    entity_type: str
    entity_id: str
    old_value_json: str | None
    new_value_json: str | None
    comment: str | None
    created_at: datetime
