"""Local-only HTTP server for browsing the SQLite chat archive."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sqlite3
import time
from urllib.parse import parse_qs, urlparse

PACKAGE_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PACKAGE_ROOT / "static"

CATEGORY_LABELS = {
    "interconnect_world": "互联世界",
    "world": "世界",
    "transmit": "传音",
    "system": "系统",
    "recruit": "招募",
    "season": "赛季",
    "school": "门派",
    "clan": "宗门",
    "team": "队伍",
    "guild": "帮派",
    "sworn": "结义",
    "street": "街坊",
    "single_server": "单服",
    "other": "其他",
}


def clamp_int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value or default)))
    except (TypeError, ValueError):
        return default


def parse_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_day(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    try:
        day = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    next_day = day + timedelta(days=1)
    return time.mktime(day.timetuple()), time.mktime(next_day.timetuple())


class ArchiveServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], database: Path, static_root: Path = STATIC_ROOT):
        super().__init__(address, ArchiveHandler)
        self.database = database.resolve()
        self.static_root = static_root.resolve()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection


class ArchiveHandler(BaseHTTPRequestHandler):
    server: ArchiveServer

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.handle_health()
        elif parsed.path == "/api/messages":
            self.handle_messages(parse_qs(parsed.query))
        elif parsed.path == "/api/dates":
            self.handle_dates(parse_qs(parsed.query))
        elif parsed.path == "/api/summary":
            self.handle_summary()
        else:
            self.serve_static(parsed.path)

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_health(self) -> None:
        connection = None
        try:
            connection = self.server.connect()
            count = connection.execute("SELECT COUNT(*) FROM chat_events").fetchone()[0]
            latest = connection.execute(
                "SELECT server_time FROM chat_events ORDER BY server_timestamp DESC, id DESC LIMIT 1"
            ).fetchone()
            self.send_json({"ok": True, "message_count": count, "latest": latest[0] if latest else None})
        except sqlite3.Error as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            if connection is not None:
                connection.close()

    def handle_summary(self) -> None:
        connection = None
        try:
            connection = self.server.connect()
            rows = connection.execute(
                "SELECT category, COUNT(*) AS count FROM chat_events GROUP BY category ORDER BY count DESC"
            ).fetchall()
            self.send_json(
                {
                    "ok": True,
                    "categories": [
                        {"category": row["category"], "label": CATEGORY_LABELS.get(row["category"], row["category"]), "count": row["count"]}
                        for row in rows
                    ],
                }
            )
        except sqlite3.Error as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            if connection is not None:
                connection.close()

    def handle_dates(self, query: dict[str, list[str]]) -> None:
        category = (query.get("category") or [""])[0].strip()
        parameters: list[object] = []
        where = ""
        if category:
            where = "WHERE category = ?"
            parameters.append(category)
        connection = None
        try:
            connection = self.server.connect()
            rows = connection.execute(
                f"""
                SELECT date(server_timestamp, 'unixepoch', 'localtime') AS day, COUNT(*) AS count
                FROM chat_events {where}
                GROUP BY day ORDER BY day DESC
                """,
                parameters,
            ).fetchall()
            self.send_json({"ok": True, "dates": [dict(row) for row in rows]})
        except sqlite3.Error as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            if connection is not None:
                connection.close()

    def handle_messages(self, query: dict[str, list[str]]) -> None:
        limit = clamp_int((query.get("limit") or [None])[0], 50, 1, 200)
        page = clamp_int((query.get("page") or [None])[0], 1, 1, 1_000_000)
        category = (query.get("category") or [""])[0].strip()
        text = (query.get("q") or [""])[0].strip()
        role_name = (query.get("role_name") or [""])[0].strip()
        role_id = (query.get("role_id") or [""])[0].strip()
        date_range = parse_day((query.get("date") or [None])[0])
        from_ts = parse_float((query.get("from_ts") or [None])[0])
        to_ts = parse_float((query.get("to_ts") or [None])[0])

        clauses: list[str] = []
        parameters: list[object] = []
        if category:
            clauses.append("category = ?")
            parameters.append(category)
        if text:
            clauses.append("text LIKE ? ESCAPE '\\'")
            parameters.append("%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if role_name:
            clauses.append("role_name LIKE ? ESCAPE '\\'")
            parameters.append("%" + role_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if role_id:
            clauses.append("role_id = ?")
            parameters.append(role_id)
        if date_range:
            clauses.extend(["server_timestamp >= ?", "server_timestamp < ?"])
            parameters.extend(date_range)
        if from_ts is not None:
            clauses.append("server_timestamp >= ?")
            parameters.append(from_ts)
        if to_ts is not None:
            clauses.append("server_timestamp <= ?")
            parameters.append(to_ts)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""

        connection = None
        try:
            connection = self.server.connect()
            total = connection.execute(f"SELECT COUNT(*) FROM chat_events {where}", parameters).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT id, event_id, server_time, channel, subchannel, category,
                       channel_label, scope, role_id, role_name, level, text, source
                FROM chat_events {where}
                ORDER BY server_timestamp DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, (page - 1) * limit],
            ).fetchall()
            self.send_json(
                {
                    "ok": True,
                    "page": page,
                    "limit": limit,
                    "total": total,
                    "total_pages": max(1, (total + limit - 1) // limit),
                    "messages": [dict(row) for row in rows],
                }
            )
        except sqlite3.Error as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            if connection is not None:
                connection.close()

    def serve_static(self, raw_path: str) -> None:
        relative = "index.html" if raw_path in ("", "/") else raw_path.lstrip("/")
        candidate = (self.server.static_root / relative).resolve()
        try:
            candidate.relative_to(self.server.static_root)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = candidate.read_bytes()
        content_type, _ = mimetypes.guess_type(candidate.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", (content_type or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def serve(database: Path, host: str = "127.0.0.1", port: int = 8766) -> int:
    if not database.exists():
        raise FileNotFoundError(f"找不到数据库：{database}")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print("警告：服务正绑定到非本机地址；请先在反向代理或 Tunnel 层配置认证。", flush=True)
    server = ArchiveServer((host, port), database)
    print(f"本地网页：http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动本地聊天归档网页")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return serve(args.database, args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
