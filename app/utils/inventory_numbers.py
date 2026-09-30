from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item_instance import ItemInstance


NUMERIC_SUFFIX_PATTERN = re.compile(r"^(?P<prefix>.+?)-(?P<number>\d+)$")


def generate_inventory_numbers(db: Session, prefix: str, count: int) -> list[str]:
    prefix = prefix.strip().upper()
    existing_numbers = db.scalars(
        select(ItemInstance.inventory_number).where(ItemInstance.inventory_number.like(f"{prefix}-%"))
    ).all()

    max_number = 0
    for number in existing_numbers:
        match = NUMERIC_SUFFIX_PATTERN.match(number)
        if not match:
            continue
        if match.group("prefix") != prefix:
            continue
        max_number = max(max_number, int(match.group("number")))

    return [f"{prefix}-{str(index).zfill(4)}" for index in range(max_number + 1, max_number + count + 1)]
