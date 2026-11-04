"""Load ``darkside_arch.dll`` into a running ``darksiders1.exe`` (LoadLibraryW).

Requires the DLL host already listening (``python -m runtime.dll``).
"""

from __future__ import annotations

import argparse
import ctypes
from pathlib import Path

from runtime.mem.models import PROCESS_NAME
from runtime.mem.watcher import find_process

KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04


def inject(pid: int, dll_path: Path) -> None:
    path = str(dll_path.resolve())
    handle = KERNEL32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not handle:
        raise OSError(f"OpenProcess({pid}) failed: {ctypes.get_last_error()}")
    try:
        size = (len(path) + 1) * 2
        remote = KERNEL32.VirtualAllocEx(handle, None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not remote:
            raise OSError(f"VirtualAllocEx failed: {ctypes.get_last_error()}")
        written = ctypes.c_size_t(0)
        buf = ctypes.create_unicode_buffer(path)
        if not KERNEL32.WriteProcessMemory(handle, remote, buf, size, ctypes.byref(written)):
            raise OSError(f"WriteProcessMemory failed: {ctypes.get_last_error()}")
        load_library = KERNEL32.GetProcAddress(KERNEL32.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
        if not load_library:
            raise OSError("GetProcAddress(LoadLibraryW) failed")
        thread = KERNEL32.CreateRemoteThread(handle, None, 0, load_library, remote, 0, None)
        if not thread:
            raise OSError(f"CreateRemoteThread failed: {ctypes.get_last_error()}")
        KERNEL32.WaitForSingleObject(thread, 10_000)
        KERNEL32.CloseHandle(thread)
    finally:
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
    print("[inject] LoadLibraryW issued")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
