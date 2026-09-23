"""Discover active chat-cache regions for the read-only collector.

Discovery validates a known serialized chat-string shape but writes only region
counts to its temporary result.  It deliberately does not persist text,
addresses, identifiers, or raw memory bytes.
"""

from __future__ import annotations

import argparse
import bisect
from collections import Counter
import ctypes
from ctypes import wintypes
import json
from pathlib import Path

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
    query_resident_pages,
    require_windows_x64,
)

KEY_PATTERN = b"\x22\x09strip_msg\x1a"


def read_varint(data: bytes, position: int, limit: int | None = None) -> tuple[int, int]:
    end = len(data) if limit is None else min(len(data), limit)
    value = shift = 0
    for _ in range(10):
        if position >= end:
            raise ValueError("truncated varint")
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
    raise ValueError("varint is too long")


def has_valid_strip_message(data: bytes, position: int) -> bool:
    try:
        value_size, cursor = read_varint(data, position)
        value_end = cursor + value_size
        if value_size < 2 or value_end > len(data) or data[cursor] != 0x22:
            return False
        text_size, cursor = read_varint(data, cursor + 1, value_end)
        text_end = cursor + text_size
        if text_end > value_end or not 1 <= text_size <= 4096:
            return False
        text = data[cursor:text_end].decode("utf-8", errors="strict")
        return "\x00" not in text and bool(text.strip())
    except (ValueError, UnicodeDecodeError):
        return False


def _ranges_for_region(pages: list[int], base: int, size: int) -> list[tuple[int, int]]:
    left = bisect.bisect_left(pages, base)
    right = bisect.bisect_left(pages, base + size)
    selected = pages[left:right]
    if not selected:
        return []
    ranges: list[tuple[int, int]] = []
    start = end = selected[0]
    for page in selected[1:]:
        if page == end + 0x1000:
            end = page
        else:
            ranges.append((start, end + 0x1000 - start))
            start = end = page
    ranges.append((start, end + 0x1000 - start))
    return ranges


def discover_regions(
    pid: int,
    *,
    chunk_mib: int = 1,
    max_hits: int = 10000,
    all_committed: bool = False,
) -> dict[str, object]:
    require_windows_x64()
    kernel32 = configure_kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    hit_count = 0
    region_hits: Counter[str] = Counter()
    try:
        pages = [] if all_committed else query_resident_pages(handle)
        chunk_size = max(64 * 1024, chunk_mib * 1024 * 1024)
        address = 0
        maximum = 0x00007FFFFFFFFFFF
        while address < maximum and hit_count < max_hits:
            mbi = MEMORY_BASIC_INFORMATION()
            queried = kernel32.VirtualQueryEx(
                handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
            )
            if not queried:
                address += 0x1000
                continue
            base = int(mbi.BaseAddress or 0)
            size = int(mbi.RegionSize)
            protection = int(mbi.Protect) & 0xFF
            readable = (
                mbi.State == MEM_COMMIT
                and int(mbi.Type) == MEM_PRIVATE
                and not (mbi.Protect & PAGE_GUARD)
                and protection != PAGE_NOACCESS
                and protection in READABLE
            )
            if readable and size > 0:
                ranges = [(base, size)] if all_committed else _ranges_for_region(pages, base, size)
                for range_base, range_size in ranges:
                    offset = 0
                    overlap = b""
                    while offset < range_size and hit_count < max_hits:
                        request = min(chunk_size, range_size - offset)
                        buffer = ctypes.create_string_buffer(request)
                        read = ctypes.c_size_t()
                        ok = kernel32.ReadProcessMemory(
                            handle,
                            ctypes.c_void_p(range_base + offset),
                            buffer,
                            request,
                            ctypes.byref(read),
                        )
                        if ok and read.value:
                            data = overlap + buffer.raw[: read.value]
                            start = 0
                            while hit_count < max_hits:
                                found = data.find(KEY_PATTERN, start)
                                if found < 0:
                                    break
                                if has_valid_strip_message(data, found + len(KEY_PATTERN)):
                                    region_hits[hex(base)] += 1
                                    hit_count += 1
                                start = found + len(KEY_PATTERN)
                            overlap = data[-8192:]
                        else:
                            overlap = b""
                        offset += request
            next_address = base + max(size, 0x1000)
            address = next_address if next_address > address else address + 0x1000
    finally:
        kernel32.CloseHandle(handle)
    return {
        "pid": pid,
        "hit_count": hit_count,
        "region_hit_counts": dict(region_hits.most_common()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="发现本地聊天缓存区")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--chunk-mib", type=int, default=1)
    parser.add_argument("--max-hits", type=int, default=10000)
    parser.add_argument("--all-committed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = discover_regions(
        args.pid,
        chunk_mib=args.chunk_mib,
        max_hits=args.max_hits,
        all_committed=args.all_committed,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"hit_count": result["hit_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
