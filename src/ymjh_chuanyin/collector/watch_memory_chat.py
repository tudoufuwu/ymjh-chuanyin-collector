"""Watch newly appearing structured chat events and append a local JSONL archive.

This collector is Windows-only and opens the named process with read/query
permissions.  It never writes to the target process.  Use it only for software
and data you are authorized to inspect.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from ..archive.retention import message_kind_code, scalar_at, should_retain_event
from .chat_event_codec import scan_chat_events
from .extract_memory_chat import discover_regions
from .scan_process_markers import (
    MEM_COMMIT,
    MEM_PRIVATE,
    MEMORY_BASIC_INFORMATION,
    PAGE_GUARD,
    PAGE_NOACCESS,
    PROCESS_QUERY_INFORMATION,
    PROCESS_VM_READ,
    READABLE,
    configure_kernel32,
    require_windows_x64,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="持续读取新出现的结构化聊天事件")
    parser.add_argument("--pid", type=int, required=True, help="已获授权的目标进程 PID")
    parser.add_argument("--out", type=Path, required=True, help="本地 JSONL 输出路径")
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--duration", type=float, default=0.0, help="0 表示持续运行")
    parser.add_argument("--region-count", type=int, default=3)
    parser.add_argument("--minimum-discovery-hits", type=int, default=2)
    parser.add_argument("--channel", action="append", help="仅记录指定频道，可重复传入")
    parser.add_argument("--include-empty", action="store_true")
    parser.add_argument("--include-system-events", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--heartbeat", type=Path, help="守护用的本地心跳文件")
    parser.add_argument(
        "--include-serial-values",
        action="store_true",
        help="诊断选项：在 JSONL 写入完整序列字段；默认关闭",
    )
    parser.add_argument(
        "--include-addresses",
        action="store_true",
        help="诊断选项：在 JSONL 写入易变内存地址；默认关闭",
    )
    parser.add_argument("--rotate-mb", type=float, default=512.0)
    parser.add_argument("--discovery-retry-interval", type=float, default=10.0)
    parser.add_argument("--idle-rediscovery-seconds", type=float, default=120.0)
    return parser.parse_args()


def has_player_identity(event: dict[str, object]) -> bool:
    return event.get("role_name") not in (None, "", "$") and event.get("role_id") not in (
        None,
        "",
        "$",
    )


def query_region(
    kernel32: ctypes.WinDLL, handle: wintypes.HANDLE, base: int
) -> MEMORY_BASIC_INFORMATION:
    mbi = MEMORY_BASIC_INFORMATION()
    if not kernel32.VirtualQueryEx(
        handle, ctypes.c_void_p(base), ctypes.byref(mbi), ctypes.sizeof(mbi)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    protection = int(mbi.Protect) & 0xFF
    if not (
        mbi.State == MEM_COMMIT
        and int(mbi.Type) == MEM_PRIVATE
        and not (mbi.Protect & PAGE_GUARD)
        and protection != PAGE_NOACCESS
        and protection in READABLE
    ):
        raise RuntimeError(f"区域 0x{base:X} 已不可读")
    return mbi


def read_region(
    kernel32: ctypes.WinDLL, handle: wintypes.HANDLE, base: int
) -> tuple[int, bytes]:
    mbi = query_region(kernel32, handle, base)
    actual_base = int(mbi.BaseAddress or 0)
    size = int(mbi.RegionSize)
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t()
    if not kernel32.ReadProcessMemory(
        handle, ctypes.c_void_p(actual_base), buffer, size, ctypes.byref(bytes_read)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return actual_base, buffer.raw[: bytes_read.value]


def refresh_heartbeat(path: Path | None) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(datetime.now(timezone.utc).astimezone().isoformat(), encoding="utf-8")


def latest_recorded_server_timestamp(path: Path, tail_bytes: int = 4 * 1024 * 1024) -> float | None:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - tail_bytes))
            lines = stream.read().splitlines()
    except FileNotFoundError:
        return None
    for raw_line in reversed(lines):
        try:
            record = json.loads(raw_line)
            value = record.get("time")
            if isinstance(value, str):
                return datetime.fromisoformat(value).timestamp()
        except (AttributeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            continue
    return None


def discover_until_ready(
    args: argparse.Namespace,
    kernel32: ctypes.WinDLL,
    started: float,
) -> tuple[wintypes.HANDLE, list[int], dict[str, dict[str, object]]]:
    while not args.duration or time.monotonic() - started < args.duration:
        refresh_heartbeat(args.heartbeat)
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, args.pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            discovery = discover_regions(args.pid)
            ranked = [
                (int(base, 16), int(count))
                for base, count in dict(discovery["region_hit_counts"]).items()
                if int(count) >= args.minimum_discovery_hits
            ]
            ranked.sort(key=lambda item: item[1], reverse=True)
            if not ranked:
                raise RuntimeError("尚未发现可用聊天缓存区")
            regions = [base for base, _ in ranked[: args.region_count]]
            baseline: dict[str, dict[str, object]] = {}
            bytes_per_pass = 0
            for requested_base in regions:
                actual_base, data = read_region(kernel32, handle, requested_base)
                bytes_per_pass += len(data)
                baseline.update(scan_chat_events(data, actual_base))
            print(
                "发现聊天缓存区："
                + ", ".join(f"0x{base:X}({count} 条命中)" for base, count in ranked[: args.region_count]),
                flush=True,
            )
            print(
                f"启动基线：{len(baseline)} 条事件；每轮约读取 {bytes_per_pass / 1048576:.2f} MiB",
                flush=True,
            )
            return handle, regions, baseline
        except Exception as exc:
            kernel32.CloseHandle(handle)
            print(f"聊天缓存尚未就绪，{args.discovery_retry_interval:.0f} 秒后重试：{exc}", flush=True)
            deadline = time.monotonic() + max(1.0, args.discovery_retry_interval)
            while time.monotonic() < deadline:
                if args.duration and time.monotonic() - started >= args.duration:
                    break
                refresh_heartbeat(args.heartbeat)
                time.sleep(min(1.0, max(0.05, deadline - time.monotonic())))
    raise TimeoutError("在指定时间内未发现聊天缓存")


def rotate_output(path: Path) -> None:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    archive = path.with_name(f"{path.stem}.{stamp}{path.suffix}")
    suffix = 1
    while archive.exists():
        archive = path.with_name(f"{path.stem}.{stamp}_{suffix}{path.suffix}")
        suffix += 1
    path.replace(archive)
    print(f"已轮转 JSONL：{archive}", flush=True)


def main() -> int:
    require_windows_x64()
    args = parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    refresh_heartbeat(args.heartbeat)
    kernel32 = configure_kernel32()
    started = time.monotonic()
    last_heartbeat = 0.0
    emitted = 0
    rotate_bytes = max(0, int(args.rotate_mb * 1024 * 1024))
    handle: wintypes.HANDLE | None = None
    stream = None
    try:
        handle, regions, discovered_events = discover_until_ready(args, kernel32, started)
        resume_after = latest_recorded_server_timestamp(args.out)
        baseline_event_ids = (
            set(discovered_events)
            if resume_after is None
            else {
                event_id
                for event_id, event in discovered_events.items()
                if float(event["server_timestamp"]) <= resume_after
            }
        )
        stream = args.out.open("a", encoding="utf-8", buffering=256 * 1024)
        last_new_event_at = time.monotonic()
        while not args.duration or time.monotonic() - started < args.duration:
            now = time.monotonic()
            if args.heartbeat and now - last_heartbeat >= 10.0:
                refresh_heartbeat(args.heartbeat)
                last_heartbeat = now
            current: dict[str, dict[str, object]] = {}
            try:
                for requested_base in regions:
                    actual_base, data = read_region(kernel32, handle, requested_base)
                    for event_id, event in scan_chat_events(data, actual_base).items():
                        existing = current.get(event_id)
                        if existing is None:
                            current[event_id] = event
                        else:
                            existing["addresses"] = list(
                                dict.fromkeys([*existing["addresses"], *event["addresses"]])
                            )
            except Exception as exc:
                print(f"缓存区域改变，重新发现：{exc}", flush=True)
                kernel32.CloseHandle(handle)
                handle, regions, _ = discover_until_ready(args, kernel32, started)
                last_new_event_at = time.monotonic()
                continue

            new_event_ids = sorted(
                current.keys() - baseline_event_ids,
                key=lambda event_id: (float(current[event_id]["server_timestamp"]), event_id),
            )
            if new_event_ids:
                last_new_event_at = now
            lines: list[str] = []
            for event_id in new_event_ids:
                event = current[event_id]
                if args.channel and event["channel"] not in args.channel:
                    continue
                if not should_retain_event(event) or (
                    not args.include_system_events and not has_player_identity(event)
                ):
                    continue
                if not args.include_empty and not str(event["text"]).strip():
                    continue
                serial_values = event.get("_serial_values")
                record: dict[str, object] = {
                    "time": datetime.fromtimestamp(
                        float(event["server_timestamp"]), timezone.utc
                    ).astimezone().isoformat(),
                    "observed_time": datetime.now(timezone.utc).astimezone().isoformat(),
                    "channel": event["channel"],
                    "subchannel": event["subchannel"],
                    "role_id": event["role_id"],
                    "role_name": event["role_name"],
                    "level": event["level"],
                    "text": event["text"],
                    "source": "ymjh-local-memory-reader",
                    "event_id": event_id,
                    "message_kind_code": message_kind_code({"serial_values": serial_values}),
                    "event_type_code": scalar_at(serial_values, 14),
                    "route_code": scalar_at(serial_values, 28),
                }
                if args.include_addresses:
                    record["addresses"] = event["addresses"]
                if args.include_serial_values:
                    record["serial_values"] = serial_values
                lines.append(json.dumps(record, ensure_ascii=False))
                emitted += 1
            if lines:
                if rotate_bytes and args.out.exists() and args.out.stat().st_size >= rotate_bytes:
                    stream.close()
                    rotate_output(args.out)
                    stream = args.out.open("a", encoding="utf-8", buffering=256 * 1024)
                stream.write("\n".join(lines) + "\n")
                stream.flush()
                if not args.quiet:
                    print("\n".join(lines), flush=True)
            baseline_event_ids.update(current)
            if (
                args.idle_rediscovery_seconds > 0
                and now - last_new_event_at >= args.idle_rediscovery_seconds
            ):
                print("长时间没有新事件，重新发现缓存区", flush=True)
                kernel32.CloseHandle(handle)
                handle, regions, _ = discover_until_ready(args, kernel32, started)
                last_new_event_at = time.monotonic()
            time.sleep(max(0.05, args.interval))
    except KeyboardInterrupt:
        pass
    finally:
        if stream is not None:
            stream.close()
        if handle:
            kernel32.CloseHandle(handle)
    print(f"结束：已写入 {emitted} 条新记录到 {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
