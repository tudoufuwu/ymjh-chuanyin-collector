"""Command-line entry point for 一梦江湖传音采集。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import __version__
from .archive.sqlite_store import import_file, rebuild_database
from .web.server import serve


def project_paths(root: Path) -> dict[str, Path]:
    root = root.resolve()
    return {
        "root": root,
        "raw": root / "var" / "raw",
        "archive": root / "var" / "archive",
        "logs": root / "var" / "logs",
        "run": root / "var" / "run",
        "database": root / "var" / "archive" / "chat-archive.db",
        "live_jsonl": root / "var" / "raw" / "chat-events.jsonl",
        "heartbeat": root / "var" / "run" / "capture-heartbeat.txt",
    }


def add_root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="项目根目录，默认当前目录")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ymjh-chuanyin", description="一梦江湖传音采集")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="创建本地运行目录")
    add_root_argument(init)

    capture = commands.add_parser("capture", help="从已获授权的 Windows 进程采集聊天")
    add_root_argument(capture)
    capture.add_argument("--pid", type=int, required=True)
    capture.add_argument("--out", type=Path)
    capture.add_argument("--heartbeat", type=Path)
    capture.add_argument("--interval", type=float, default=0.5)
    capture.add_argument("--region-count", type=int, default=3)
    capture.add_argument("--rotate-mb", type=float, default=512.0)
    capture.add_argument("--quiet", action="store_true")
    capture.add_argument("--include-system-events", action="store_true")
    capture.add_argument("--diagnostic-serial-values", action="store_true")
    capture.add_argument("--diagnostic-addresses", action="store_true")

    ingest = commands.add_parser("import", help="导入 JSONL 到 SQLite")
    add_root_argument(ingest)
    ingest.add_argument("--input", type=Path)
    ingest.add_argument("--database", type=Path)
    ingest.add_argument("--follow", action="store_true")
    ingest.add_argument("--poll-interval", type=float, default=0.5)
    ingest.add_argument("--include-system-events", action="store_true")

    rebuild = commands.add_parser("rebuild", help="从全部 JSONL 片段重建 SQLite")
    add_root_argument(rebuild)
    rebuild.add_argument("--raw-directory", type=Path)
    rebuild.add_argument("--database", type=Path)
    rebuild.add_argument("--replace", action="store_true", help="确认替换已有数据库")
    rebuild.add_argument("--include-system-events", action="store_true")

    web = commands.add_parser("serve", help="启动本地查询网页")
    add_root_argument(web)
    web.add_argument("--database", type=Path)
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8766)

    demo = commands.add_parser("demo", help="导入合成示例数据")
    add_root_argument(demo)

    status = commands.add_parser("status", help="显示本地路径和数据库状态")
    add_root_argument(status)
    return parser.parse_args()


def ensure_directories(paths: dict[str, Path]) -> None:
    for key in ("raw", "archive", "logs", "run"):
        paths[key].mkdir(parents=True, exist_ok=True)


def run_capture(args: argparse.Namespace, paths: dict[str, Path]) -> int:
    ensure_directories(paths)
    output = (args.out or paths["live_jsonl"]).resolve()
    heartbeat = (args.heartbeat or paths["heartbeat"]).resolve()
    command = [
        sys.executable,
        "-m",
        "ymjh_chuanyin.collector.watch_memory_chat",
        "--pid",
        str(args.pid),
        "--out",
        str(output),
        "--heartbeat",
        str(heartbeat),
        "--interval",
        str(args.interval),
        "--region-count",
        str(args.region_count),
        "--rotate-mb",
        str(args.rotate_mb),
    ]
    if args.quiet:
        command.append("--quiet")
    if args.include_system_events:
        command.append("--include-system-events")
    if args.diagnostic_serial_values:
        command.append("--include-serial-values")
    if args.diagnostic_addresses:
        command.append("--include-addresses")
    return subprocess.run(command, cwd=paths["root"], check=False).returncode


def run_rebuild(args: argparse.Namespace, paths: dict[str, Path]) -> int:
    raw = (args.raw_directory or paths["raw"]).resolve()
    database = (args.database or paths["database"]).resolve()
    if database.exists() and not args.replace:
        raise SystemExit("目标数据库已存在；确认要替换时请添加 --replace")
    temporary = database.with_suffix(database.suffix + ".rebuilding")
    for candidate in (temporary, temporary.with_name(temporary.name + "-wal"), temporary.with_name(temporary.name + "-shm")):
        if candidate.exists():
            candidate.unlink()
    file_count, inserted = rebuild_database(
        raw, temporary, include_system_events=args.include_system_events
    )
    for sidecar in (database.with_name(database.name + "-wal"), database.with_name(database.name + "-shm")):
        if sidecar.exists():
            sidecar.unlink()
    os.replace(temporary, database)
    print(f"已从 {file_count} 个 JSONL 文件重建数据库，新增 {inserted} 条记录：{database}")
    return 0


def main() -> int:
    args = parse_args()
    paths = project_paths(args.root)
    if args.command == "init":
        ensure_directories(paths)
        print(f"已初始化运行目录：{paths['root']}")
        return 0
    if args.command == "capture":
        return run_capture(args, paths)
    if args.command == "import":
        ensure_directories(paths)
        input_path = (args.input or paths["live_jsonl"]).resolve()
        database = (args.database or paths["database"]).resolve()
        inserted = import_file(
            input_path,
            database,
            follow=args.follow,
            poll_interval=args.poll_interval,
            include_system_events=args.include_system_events,
        )
        print(f"本次新增 {inserted} 条记录")
        return 0
    if args.command == "rebuild":
        ensure_directories(paths)
        return run_rebuild(args, paths)
    if args.command == "serve":
        ensure_directories(paths)
        return serve((args.database or paths["database"]).resolve(), args.host, args.port)
    if args.command == "demo":
        ensure_directories(paths)
        source = Path(__file__).resolve().parents[2] / "examples" / "synthetic-events.jsonl"
        destination = paths["raw"] / "synthetic-events.jsonl"
        shutil.copyfile(source, destination)
        inserted = import_file(destination, paths["database"])
        print(f"已导入合成示例，新增 {inserted} 条记录")
        return 0
    if args.command == "status":
        print(f"项目根目录：{paths['root']}")
        print(f"原始 JSONL：{paths['raw']}")
        print(f"SQLite：{paths['database']}")
        print(f"数据库存在：{'是' if paths['database'].exists() else '否'}")
        return 0
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
