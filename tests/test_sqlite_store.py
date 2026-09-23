from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ymjh_chuanyin.archive.sqlite_store import (
    connect_database,
    ingest_available,
    rebuild_database,
)


class SQLiteStoreTests(unittest.TestCase):
    def event(self, event_id: str, channel: str, role_id: str | None = "demo-1") -> dict[str, object]:
        return {
            "event_id": event_id,
            "time": "2026-01-01T10:00:00+08:00",
            "channel": channel,
            "subchannel": "world_all_server" if channel == "world" else None,
            "role_id": role_id,
            "role_name": "合成角色" if role_id else None,
            "level": 99,
            "text": "合成测试消息",
            "source": "test",
        }

    def test_import_is_idempotent_and_classifies_transmit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "events.jsonl"
            source.write_text(
                "".join(
                    json.dumps(event, ensure_ascii=False) + "\n"
                    for event in [
                        self.event("one", "world"),
                        self.event("two", "xitong"),
                        self.event("three", "zhaomu"),
                    ]
                ),
                encoding="utf-8",
            )
            connection = connect_database(root / "archive.db")
            try:
                self.assertEqual(ingest_available(connection, source)[:2], (3, 2))
                rows = connection.execute(
                    "SELECT event_id, category FROM chat_events ORDER BY event_id"
                ).fetchall()
                self.assertEqual(rows, [("one", "interconnect_world"), ("two", "transmit")])
                self.assertEqual(ingest_available(connection, source)[:2], (0, 0))
            finally:
                connection.close()

    def test_rebuild_reads_multiple_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            for index in range(2):
                (raw / f"segment-{index}.jsonl").write_text(
                    json.dumps(self.event(f"event-{index}", "world"), ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            files, inserted = rebuild_database(raw, root / "rebuilt.db")
            self.assertEqual((files, inserted), (2, 2))


if __name__ == "__main__":
    unittest.main()
