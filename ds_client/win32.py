"""Windows process/memory helpers (ctypes)."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
from typing import Optional, Sequence

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
STILL_ACTIVE = 259
LIST_MODULES_DEFAULT = 0x03

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

kernel32.OpenProcess.argtypes = (
    ctypes.wintypes.DWORD,
    ctypes.wintypes.BOOL,
    ctypes.wintypes.DWORD,
)
kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
kernel32.ReadProcessMemory.argtypes = (
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.LPCVOID,
    ctypes.wintypes.LPVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
)
kernel32.ReadProcessMemory.restype = ctypes.wintypes.BOOL
kernel32.CloseHandle.argtypes = (ctypes.wintypes.HANDLE,)
kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
kernel32.GetExitCodeProcess.argtypes = (
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(ctypes.wintypes.DWORD),
)
kernel32.GetExitCodeProcess.restype = ctypes.wintypes.BOOL

psapi.EnumProcessModulesEx.argtypes = (
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(ctypes.wintypes.HMODULE),
    ctypes.wintypes.DWORD,
    ctypes.POINTER(ctypes.wintypes.DWORD),
    ctypes.wintypes.DWORD,
)
psapi.EnumProcessModulesEx.restype = ctypes.wintypes.BOOL
psapi.GetModuleBaseNameW.argtypes = (
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HMODULE,
    ctypes.wintypes.LPWSTR,
    ctypes.wintypes.DWORD,
)
psapi.GetModuleBaseNameW.restype = ctypes.wintypes.DWORD

ProcessHandle = ctypes.wintypes.HANDLE


def open_process(pid: int) -> ProcessHandle:
    access = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
    handle = kernel32.OpenProcess(access, False, pid)
    if not handle:
        err = ctypes.get_last_error()
        raise OSError(f"OpenProcess failed for pid={pid} (error {err})")
    return handle


def close_handle(handle: ProcessHandle) -> None:
    kernel32.CloseHandle(handle)


def process_alive(handle: ProcessHandle) -> bool:
    code = ctypes.wintypes.DWORD()
    if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
        return False
    return code.value == STILL_ACTIVE


def get_module_base(handle: ProcessHandle, module_name: str) -> int:
    needed = ctypes.wintypes.DWORD()
    arr = (ctypes.wintypes.HMODULE * 1024)()
    if not psapi.EnumProcessModulesEx(
        handle,
        arr,
        ctypes.sizeof(arr),
        ctypes.byref(needed),
        LIST_MODULES_DEFAULT,
    ):
        err = ctypes.get_last_error()
        raise OSError(f"EnumProcessModulesEx failed (error {err})")

    want = module_name.lower()
    name_buf = ctypes.create_unicode_buffer(260)
    count = needed.value // ctypes.sizeof(ctypes.wintypes.HMODULE)
    for i in range(min(count, len(arr))):
        mod = arr[i]
        if not mod:
            continue
        if psapi.GetModuleBaseNameW(handle, mod, name_buf, len(name_buf)) == 0:
            continue
        if name_buf.value.lower() == want:
            return int(ctypes.cast(mod, ctypes.c_void_p).value)

    raise OSError(f"module {module_name!r} not found in process")


def read_memory(handle: ProcessHandle, address: int, size: int) -> Optional[bytes]:
    if address <= 0 or size <= 0:
        return None
    buf = (ctypes.c_ubyte * size)()
    read = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(
        handle,
        ctypes.c_void_p(address),
        buf,
        size,
        ctypes.byref(read),
    )
    if not ok or read.value != size:
        return None
    return bytes(buf)


def resolve_address(
    handle: ProcessHandle,
    module_base: int,
    offsets: Sequence[int],
) -> Optional[int]:
    """Resolve module-relative offset or multi-level pointer chain.

    offsets=[A]       -> module_base + A
    offsets=[A, B, C] -> [[module_base + A] + B] + C
    """
    if not offsets:
        return None

    addr = module_base + offsets[0]
    for off in offsets[1:]:
        raw = read_memory(handle, addr, 8)
        if raw is None:
            return None
        addr = int.from_bytes(raw, "little") + off
        if addr <= 0:
            return None
    return addr
