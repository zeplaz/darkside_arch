"""Load ``darkside_arch.dll`` into a running ``darksiders1.exe`` (LoadLibraryW).

Requires the DLL host already listening (``python -m runtime.dll``).
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path

from runtime.mem.models import PROCESS_NAME
from runtime.mem.watcher import find_process

KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Vista+ process rights needed for classic LoadLibrary injection (not XP PROCESS_ALL_ACCESS).
PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_READ = 0x0010
PROCESS_INJECT_ACCESS = (
    PROCESS_CREATE_THREAD
    | PROCESS_QUERY_INFORMATION
    | PROCESS_VM_OPERATION
    | PROCESS_VM_WRITE
    | PROCESS_VM_READ
)

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
INFINITE = 0xFFFFFFFF

SIZE_T = ctypes.c_size_t
LPVOID = ctypes.c_void_p
LPCVOID = ctypes.c_void_p
HANDLE = wintypes.HANDLE
DWORD = wintypes.DWORD
BOOL = wintypes.BOOL

KERNEL32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
KERNEL32.OpenProcess.restype = HANDLE
KERNEL32.CloseHandle.argtypes = [HANDLE]
KERNEL32.CloseHandle.restype = BOOL
KERNEL32.VirtualAllocEx.argtypes = [HANDLE, LPVOID, SIZE_T, DWORD, DWORD]
KERNEL32.VirtualAllocEx.restype = LPVOID
KERNEL32.VirtualFreeEx.argtypes = [HANDLE, LPVOID, SIZE_T, DWORD]
KERNEL32.VirtualFreeEx.restype = BOOL
KERNEL32.WriteProcessMemory.argtypes = [
    HANDLE,
    LPVOID,
    LPCVOID,
    SIZE_T,
    ctypes.POINTER(SIZE_T),
]
KERNEL32.WriteProcessMemory.restype = BOOL
KERNEL32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
KERNEL32.GetModuleHandleW.restype = HANDLE
KERNEL32.GetProcAddress.argtypes = [HANDLE, ctypes.c_char_p]
KERNEL32.GetProcAddress.restype = LPVOID
KERNEL32.CreateRemoteThread.argtypes = [
    HANDLE,
    LPVOID,
    SIZE_T,
    LPVOID,
    LPVOID,
    DWORD,
    ctypes.POINTER(DWORD),
]
KERNEL32.CreateRemoteThread.restype = HANDLE
KERNEL32.WaitForSingleObject.argtypes = [HANDLE, DWORD]
KERNEL32.WaitForSingleObject.restype = DWORD
KERNEL32.GetExitCodeThread.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
KERNEL32.GetExitCodeThread.restype = BOOL


def _winerr(op: str) -> OSError:
    return OSError(f"{op} failed: {ctypes.get_last_error()}")


def inject(pid: int, dll_path: Path) -> None:
    path = str(dll_path.resolve())
    if not dll_path.is_file():
        raise FileNotFoundError(f"DLL not found: {path}")

    handle = KERNEL32.OpenProcess(PROCESS_INJECT_ACCESS, False, pid)
    if not handle:
        raise _winerr(f"OpenProcess({pid})")

    remote = None
    thread = None
    try:
        # UTF-16 path + NUL. Without c_void_p restypes, VirtualAllocEx truncates to
        # 32-bit on Win64 and WriteProcessMemory returns ERROR_NOACCESS (998).
        size = SIZE_T((len(path) + 1) * 2)
        remote = KERNEL32.VirtualAllocEx(
            handle, None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        if not remote:
            raise _winerr("VirtualAllocEx")

        written = SIZE_T(0)
        buf = ctypes.create_unicode_buffer(path)
        if not KERNEL32.WriteProcessMemory(
            handle, remote, ctypes.byref(buf), size, ctypes.byref(written)
        ):
            raise _winerr("WriteProcessMemory")

        k32 = KERNEL32.GetModuleHandleW("kernel32.dll")
        if not k32:
            raise _winerr("GetModuleHandleW(kernel32)")
        load_library = KERNEL32.GetProcAddress(k32, b"LoadLibraryW")
        if not load_library:
            raise _winerr("GetProcAddress(LoadLibraryW)")

        tid = DWORD(0)
        thread = KERNEL32.CreateRemoteThread(
            handle, None, 0, load_library, remote, 0, ctypes.byref(tid)
        )
        if not thread:
            raise _winerr("CreateRemoteThread")

        KERNEL32.WaitForSingleObject(thread, 15_000)
        exit_code = DWORD(0)
        if KERNEL32.GetExitCodeThread(thread, ctypes.byref(exit_code)):
            # LoadLibraryW returns HMODULE; 0 means the DLL failed to load.
            if exit_code.value == 0:
                raise OSError(
                    "LoadLibraryW returned NULL in the game process "
                    f"(path={path}). Check arch match / DLL deps."
                )
    finally:
        if thread:
            KERNEL32.CloseHandle(thread)
        if remote:
            KERNEL32.VirtualFreeEx(handle, remote, 0, MEM_RELEASE)
        KERNEL32.CloseHandle(handle)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Inject darkside_arch.dll into Darksiders")
    p.add_argument(
        "--dll",
        type=Path,
        default=Path("runtime/dll/native/target/release/darkside_arch.dll"),
        help="Path to darkside_arch.dll",
    )
    args = p.parse_args(argv)
    if not args.dll.is_file():
        print(f"[ERROR] DLL not found: {args.dll} (cargo build --release first)")
        return 1
    pid = find_process(PROCESS_NAME)
    if pid is None:
        print(f"[ERROR] {PROCESS_NAME} is not running")
        return 1
    print(f"[inject] pid={pid} dll={args.dll.resolve()}")
    inject(pid, args.dll)
    print("[inject] LoadLibraryW ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
