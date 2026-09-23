"""Shared rules deciding which structured chat events belong in the archive."""

from __future__ import annotations

from typing import Any

DIRECT_RECRUITMENT_KIND = 1044
IGNORED_CHANNELS = {"zhaomu", "recruit"}


def scalar_at(values: object, index: int) -> int | None:
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    return value if isinstance(value, int) else None


def message_kind_code(record: dict[str, Any]) -> int | None:
    explicit = record.get("message_kind_code")
    if isinstance(explicit, int):
        return explicit
    return scalar_at(record.get("serial_values"), 2)


def should_retain_event(record: dict[str, Any]) -> bool:
    """Drop recruitment-channel items while retaining normal player chat."""
    channel = str(record.get("channel") or "")
    if channel in IGNORED_CHANNELS:
        return False
    return not (channel == "season" and message_kind_code(record) == DIRECT_RECRUITMENT_KIND)
