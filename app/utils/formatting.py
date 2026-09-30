from __future__ import annotations

from decimal import Decimal

from app.models.enums import ConditionStatus, LifecycleStatus, PhysicalLocationType, UserRole


ABSENT_CONDITION_VALUE = getattr(ConditionStatus, "ABSENT", "absent")
if hasattr(ABSENT_CONDITION_VALUE, "value"):
    ABSENT_CONDITION_VALUE = ABSENT_CONDITION_VALUE.value


CONDITION_LABELS = {
    ConditionStatus.WORKING.value: "Исправно",
    ConditionStatus.IN_REPAIR.value: "В ремонте",
    ConditionStatus.BROKEN.value: "Сломано",
    ABSENT_CONDITION_VALUE: "Отсутствует",
}

LIFECYCLE_LABELS = {
    LifecycleStatus.ACTIVE.value: "Активен",
    LifecycleStatus.WRITTEN_OFF.value: "Списан",
}

LOCATION_LABELS = {
    PhysicalLocationType.NONE.value: "Не указано",
    PhysicalLocationType.WAREHOUSE.value: "Склад",
    PhysicalLocationType.LABORATORY.value: "Лаборатория",
}

ROLE_LABELS = {
    UserRole.ADMIN.value: "Администратор",
    UserRole.USER.value: "Пользователь",
}


def format_money(value: Decimal | float | int | None) -> str:
    if value is None:
        return "—"
    decimal_value = Decimal(str(value)).quantize(Decimal("0.01"))
    return f"{decimal_value:,.2f} ₽".replace(",", " ")


def _normalize_enum_value(value: object | None) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(getattr(value, "value"))
    return str(value)


def condition_label(value: ConditionStatus | str | None) -> str:
    normalized = _normalize_enum_value(value)
    if normalized is None:
        return "—"
    return CONDITION_LABELS.get(normalized, normalized)


def lifecycle_label(value: LifecycleStatus | str | None) -> str:
    normalized = _normalize_enum_value(value)
    if normalized is None:
        return "—"
    return LIFECYCLE_LABELS.get(normalized, normalized)


def location_type_label(value: PhysicalLocationType | str | None) -> str:
    normalized = _normalize_enum_value(value)
    if normalized is None:
        return "—"
    return LOCATION_LABELS.get(normalized, normalized)


def role_label(value: UserRole | str | None) -> str:
    normalized = _normalize_enum_value(value)
    if normalized is None:
        return "—"
    return ROLE_LABELS.get(normalized, normalized)
