"""Minimal Windows read-only memory helpers used by the local collector.

The module only opens a process with query and read permissions.  It never
writes to the target process, injects code, changes memory protection, or
handles credentials.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import platform

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def require_windows_x64() -> None:
    if os.name != "nt" or platform.architecture()[0] != "64bit":
        raise SystemExit("采集器需要 64 位 Windows 和 64 位 Python")


def configure_kernel32() -> ctypes.WinDLL:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.VirtualQueryEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(MEMORY_BASIC_INFORMATION),
        ctypes.c_size_t,
    ]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel32


def query_resident_pages(handle: wintypes.HANDLE) -> list[int]:
    """Return resident page bases for efficient, read-only discovery."""
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.QueryWorkingSet.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.QueryWorkingSet.restype = wintypes.BOOL
    size = 2 * 1024 * 1024
    while size <= 128 * 1024 * 1024:
        buffer = ctypes.create_string_buffer(size)
        if psapi.QueryWorkingSet(handle, buffer, size):
            word_size = ctypes.sizeof(ctypes.c_size_t)
            count = ctypes.c_size_t.from_buffer(buffer).value
            maximum = (size - word_size) // word_size
            if count > maximum:
                size *= 2
                continue
            values_type = ctypes.c_size_t * count
            values = values_type.from_buffer(buffer, word_size)
            return sorted({int(value) & ~0xFFF for value in values})
        size *= 2
    raise ctypes.WinError(ctypes.get_last_error())
