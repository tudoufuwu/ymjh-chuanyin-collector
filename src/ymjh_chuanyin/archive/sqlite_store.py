"""Durable JSONL-to-SQLite archive implementation."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable

from .retention import should_retain_event

CHANNEL_LABELS = {
    "zhaomu": ("recruit", "招募"),
    "season": ("season", "赛季"),
    "school": ("school", "门派"),
    "zongmen": ("clan", "宗门"),
    "team": ("team", "队伍"),
    "duiwu": ("team", "队伍"),
    "gang": ("guild", "帮派"),
    "bangpai": ("guild", "帮派"),
    "jieyi": ("sworn", "结义"),
    "personal": ("sworn", "结义"),
    "shili": ("faction", "势力"),
    "street": ("street", "街坊"),
    "single": ("single_server", "单服"),
}

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS chat_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    server_timestamp REAL NOT NULL,
    server_time TEXT NOT NULL,
    observed_time TEXT,
    channel TEXT NOT NULL,
    subchannel TEXT,
    category TEXT NOT NULL,
    channel_label TEXT NOT NULL,
    scope TEXT NOT NULL,
    role_id TEXT,
    role_name TEXT,
    level INTEGER,
    text TEXT NOT NULL,
    event_type_code INTEGER,
    route_code INTEGER,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_events_time_id
ON chat_events(server_timestamp DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_events_category_time_id
ON chat_events(category, server_timestamp DESC, id DESC);

CREATE TABLE IF NOT EXISTS ingest_state (
    source_path TEXT PRIMARY KEY,
    byte_offset INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_daily_counts (
    day TEXT NOT NULL,
    category TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY(day, category)
);

CREATE TRIGGER IF NOT EXISTS trg_chat_events_daily_insert
AFTER INSERT ON chat_events
BEGIN
    INSERT INTO chat_daily_counts(day, category, count)
    VALUES (date(NEW.server_timestamp, 'unixepoch', 'localtime'), NEW.category, 1)
    ON CONFLICT(day, category) DO UPDATE SET count = count + 1;
END;
"""

INSERT_SQL = """
INSERT OR IGNORE INTO chat_events (
    event_id, server_timestamp, server_time, observed_time,
    channel, subchannel, category, channel_label, scope,
    role_id, role_name, level, text, event_type_code, route_code,
    source, ingested_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def nonempty(value: object) -> bool:
    return value not in (None, "", "$")


def has_player_identity(record: dict[str, Any]) -> bool:
    return nonempty(record.get("role_name")) and nonempty(record.get("role_id"))


def classify_event(record: dict[str, Any]) -> tuple[str, str, str]:
    channel = str(record.get("channel") or "unknown")
    subchannel = record.get("subchannel")
    scope = {"world_all_server": "all_server", "world": "local_server"}.get(
        subchannel, "unspecified"
    )
    if channel == "world":
        return (
            ("interconnect_world", "互联世界", scope)
            if subchannel == "world_all_server"
            else ("world", "世界", scope)
        )
    if channel == "xitong":
        return (
            ("transmit", "传音", scope)
            if has_player_identity(record)
            else ("system", "系统", scope)
        )
    category, label = CHANNEL_LABELS.get(channel, ("other", channel))
    return category, label, scope


def connect_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    connection.commit()
    return connection


def insert_event(
    connection: sqlite3.Connection,
    record: dict[str, Any],
    *,
    include_system_events: bool = False,
) -> bool:
    if not should_retain_event(record):
        return False
    if not include_system_events and not has_player_identity(record):
        return False
    event_id = str(record.get("event_id") or "").strip()
    if not event_id:
        raise ValueError("event has no event_id")
    timestamp = float(record.get("server_timestamp") or 0.0)
    time_text = record.get("time")
    if not timestamp:
        if not isinstance(time_text, str):
            raise ValueError("event has no server timestamp/time")
        timestamp = datetime.fromisoformat(time_text).timestamp()
    if not isinstance(time_text, str):
        time_text = datetime.fromtimestamp(timestamp, timezone.utc).astimezone().isoformat()
    category, channel_label, scope = classify_event(record)
    before = connection.total_changes
    connection.execute(
        INSERT_SQL,
        (
            event_id,
            timestamp,
            time_text,
            record.get("observed_time"),
            str(record.get("channel") or "unknown"),
            record.get("subchannel"),
            category,
            channel_label,
            scope,
            None if not nonempty(record.get("role_id")) else str(record.get("role_id")),
            None if not nonempty(record.get("role_name")) else str(record.get("role_name")),
            record.get("level") if isinstance(record.get("level"), int) else None,
            str(record.get("text") or ""),
            record.get("event_type_code") if isinstance(record.get("event_type_code"), int) else None,
            record.get("route_code") if isinstance(record.get("route_code"), int) else None,
            str(record.get("source") or "ymjh-local-memory-reader"),
            datetime.now(timezone.utc).astimezone().isoformat(),
        ),
    )
    return connection.total_changes > before


def saved_offset(connection: sqlite3.Connection, source_path: str) -> int:
    row = connection.execute(
        "SELECT byte_offset FROM ingest_state WHERE source_path = ?", (source_path,)
    ).fetchone()
    return int(row[0]) if row else 0


def save_offset(connection: sqlite3.Connection, source_path: str, offset: int) -> None:
    connection.execute(
        """
        INSERT INTO ingest_state(source_path, byte_offset, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(source_path) DO UPDATE SET
          byte_offset = excluded.byte_offset,
          updated_at = excluded.updated_at
        """,
        (source_path, offset, datetime.now(timezone.utc).astimezone().isoformat()),
    )


def ingest_available(
    connection: sqlite3.Connection,
    input_path: Path,
    source_path: str | None = None,
    *,
    include_system_events: bool = False,
) -> tuple[int, int, int]:
    """Import complete lines currently available; return read, inserted, offset."""
    source_path = source_path or str(input_path.resolve())
    if not input_path.exists():
        return 0, 0, saved_offset(connection, source_path)
    offset = saved_offset(connection, source_path)
    if offset > input_path.stat().st_size:
        offset = 0
    read_count = inserted_count = 0
    with input_path.open("rb") as stream:
        stream.seek(offset)
        while True:
            line_start = stream.tell()
            raw = stream.readline()
            if not raw:
                break
            if not raw.endswith(b"\n"):
                stream.seek(line_start)
                break
            offset = stream.tell()
            read_count += 1
            try:
                record = json.loads(raw.decode("utf-8"))
                if not isinstance(record, dict):
                    raise ValueError("event is not an object")
                inserted_count += int(
                    insert_event(connection, record, include_system_events=include_system_events)
                )
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                print(f"跳过无法解析的第 {read_count} 条：{exc}", flush=True)
        if read_count:
            save_offset(connection, source_path, offset)
            connection.commit()
    return read_count, inserted_count, offset


def import_file(
    input_path: Path,
    database_path: Path,
    *,
    follow: bool = False,
    poll_interval: float = 0.5,
    include_system_events: bool = False,
) -> int:
    connection = connect_database(database_path)
    total_inserted = 0
    try:
        while True:
            read_count, inserted_count, _ = ingest_available(
                connection, input_path, include_system_events=include_system_events
            )
            total_inserted += inserted_count
            if read_count:
                print(f"读取 {read_count} 条，新增 {inserted_count} 条", flush=True)
            if not follow:
                break
            time.sleep(max(0.1, poll_interval))
    except KeyboardInterrupt:
        pass
    finally:
        connection.close()
    return total_inserted


def iter_jsonl_files(raw_directory: Path) -> Iterable[Path]:
    return sorted(path for path in raw_directory.rglob("*.jsonl") if path.is_file())


def rebuild_database(
    raw_directory: Path,
    destination: Path,
    *,
    include_system_events: bool = False,
) -> tuple[int, int]:
    """Create a new database from every JSONL segment under ``raw_directory``."""
    if destination.exists():
        raise FileExistsError(f"目标数据库已存在：{destination}")
    connection = connect_database(destination)
    file_count = inserted_count = 0
    try:
        for path in iter_jsonl_files(raw_directory):
            file_count += 1
            _, inserted, _ = ingest_available(
                connection,
                path,
                source_path=str(path.resolve()),
                include_system_events=include_system_events,
            )
            inserted_count += inserted
    finally:
        connection.close()
    return file_count, inserted_count
