from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


class ConditionStatus(str, Enum):
    WORKING = "working"
    IN_REPAIR = "in_repair"
    BROKEN = "broken"
    ABSENT = "absent"


class LifecycleStatus(str, Enum):
    ACTIVE = "active"
    WRITTEN_OFF = "written_off"


class PhysicalLocationType(str, Enum):
    NONE = "none"
    WAREHOUSE = "warehouse"
    LABORATORY = "laboratory"
