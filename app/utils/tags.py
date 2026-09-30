from __future__ import annotations


def parse_tags(tags_text: str | None) -> list[str]:
    if not tags_text:
        return []
    raw_parts = tags_text.replace("\n", ",").split(",")
    clean_parts: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        value = " ".join(part.strip().split())
        normalized = value.lower()
        if not value or normalized in seen:
            continue
        seen.add(normalized)
        clean_parts.append(value)
    return clean_parts


def normalize_tags(tags_text: str | None) -> str:
    return ", ".join(parse_tags(tags_text))


def tags_match(tags_text: str | None, query: str) -> bool:
    query_lower = query.lower().strip()
    return any(query_lower in tag.lower() for tag in parse_tags(tags_text))
