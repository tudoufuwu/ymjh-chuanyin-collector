"""Decode the chat event shape used by the local read-only collector."""

from __future__ import annotations

import hashlib
import struct

EVENT_NAME = b"chat_rpc_receive_chat_message"
EVENT_PATTERN = b"\x0a\x1d" + EVENT_NAME
SERIAL_KEY_PATTERN = b"\x22\x0d__serial_data"


def read_varint(data: bytes, position: int, limit: int | None = None) -> tuple[int, int]:
    end = len(data) if limit is None else min(len(data), limit)
    value = 0
    shift = 0
    for _ in range(10):
        if position >= end:
            raise ValueError("truncated varint")
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
    raise ValueError("varint too long")


def parse_fields(blob: bytes) -> list[tuple[int, int, int | bytes]]:
    fields: list[tuple[int, int, int | bytes]] = []
    position = 0
    while position < len(blob):
        key, position = read_varint(blob, position)
        field_number = key >> 3
        wire_type = key & 7
        if field_number == 0:
            raise ValueError("invalid field zero")
        if wire_type == 0:
            value, position = read_varint(blob, position)
        elif wire_type == 1:
            if position + 8 > len(blob):
                raise ValueError("truncated fixed64")
            value = blob[position : position + 8]
            position += 8
        elif wire_type == 2:
            size, position = read_varint(blob, position)
            if position + size > len(blob):
                raise ValueError("truncated bytes field")
            value = blob[position : position + size]
            position += size
        elif wire_type == 5:
            if position + 4 > len(blob):
                raise ValueError("truncated fixed32")
            value = blob[position : position + 4]
            position += 4
        else:
            raise ValueError(f"unsupported wire type {wire_type}")
        fields.append((field_number, wire_type, value))
    return fields


def decode_serial_item(item: bytes) -> object:
    outer = parse_fields(item)
    for field_number, wire_type, value in outer:
        if field_number != 3 or wire_type != 2 or not isinstance(value, bytes):
            continue
        inner = parse_fields(value)
        for inner_field, inner_wire, inner_value in inner:
            if inner_field == 4 and inner_wire == 2 and isinstance(inner_value, bytes):
                return inner_value.decode("utf-8", errors="strict")
            if inner_field == 1 and inner_wire == 0 and isinstance(inner_value, int):
                return inner_value
            if inner_field == 3 and inner_wire == 1 and isinstance(inner_value, bytes):
                return struct.unpack("<d", inner_value)[0]
    if any(field == 1 and wire == 0 and value == 45 for field, wire, value in outer):
        return {"opaque_map_bytes": len(item)}
    return None


def parse_named_string(data: bytes, key: bytes, start: int, end: int) -> str | None:
    pattern = bytes([0x22, len(key)]) + key + b"\x1a"
    position = data.find(pattern, start, end)
    if position < 0:
        return None
    cursor = position + len(pattern)
    value_size, cursor = read_varint(data, cursor, end)
    value_end = cursor + value_size
    if value_end > end or cursor >= value_end or data[cursor] != 0x22:
        return None
    text_size, cursor = read_varint(data, cursor + 1, value_end)
    if cursor + text_size > value_end:
        return None
    return data[cursor : cursor + text_size].decode("utf-8", errors="strict")


def parse_chat_event_at(data: bytes, event_position: int, data_base: int = 0) -> dict[str, object]:
    search_end = min(len(data), event_position + 8192)
    serial_position = data.find(SERIAL_KEY_PATTERN, event_position, search_end)
    if serial_position < 0:
        raise ValueError("event has no serialized values")
    cursor = serial_position + len(SERIAL_KEY_PATTERN)
    field_key, cursor = read_varint(data, cursor, search_end)
    if field_key != 0x22:
        raise ValueError("unexpected serialized list field")
    list_size, cursor = read_varint(data, cursor, search_end)
    list_end = cursor + list_size
    if list_end > search_end:
        raise ValueError("truncated serialized list")
    list_fields = parse_fields(data[cursor:list_end])
    values = [
        decode_serial_item(value)
        for field, wire, value in list_fields
        if field == 2 and wire == 2 and isinstance(value, bytes)
    ]
    if len(values) < 25:
        raise ValueError(f"serialized list has only {len(values)} items")

    text = values[11]
    channel = values[15]
    role_name = values[18]
    level = values[21]
    timestamp = values[23]
    role_id = values[24]
    if not isinstance(text, str) or not isinstance(channel, str):
        raise ValueError("message text/channel are not strings")
    if not isinstance(timestamp, (float, int)):
        raise ValueError("message timestamp is not numeric")

    subchannel = parse_named_string(data, b"sub_c", list_end, search_end)
    identity_source = "\x1f".join(
        [str(timestamp), str(values[0]), channel, str(role_id), text]
    ).encode("utf-8")
    return {
        "event_id": hashlib.blake2s(identity_source, digest_size=12).hexdigest(),
        "event_address": hex(data_base + event_position),
        "server_timestamp": float(timestamp),
        "channel": channel,
        "subchannel": subchannel,
        "role_id": None if role_id in (None, "$") else str(role_id),
        "role_name": None if role_name in (None, "$") else str(role_name),
        "level": None if level in (None, "$") else level,
        "text": text,
        "_serial_values": values,
    }


def scan_chat_events(data: bytes, data_base: int = 0) -> dict[str, dict[str, object]]:
    events: dict[str, dict[str, object]] = {}
    cursor = 0
    while True:
        position = data.find(EVENT_PATTERN, cursor)
        if position < 0:
            break
        try:
            event = parse_chat_event_at(data, position, data_base)
        except (ValueError, UnicodeDecodeError):
            cursor = position + 1
            continue
        event_id = str(event["event_id"])
        existing = events.get(event_id)
        if existing is None:
            event["addresses"] = [event.pop("event_address")]
            events[event_id] = event
        else:
            address = event["event_address"]
            if address not in existing["addresses"]:
                existing["addresses"].append(address)
        cursor = position + len(EVENT_PATTERN)
    return events
