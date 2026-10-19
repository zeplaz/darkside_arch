"""Passive Darksiders Warmastered Edition process watcher.

Attaches to darksiders1.exe, reads configured memory targets via
ReadProcessMemory, and logs value changes to stdout and SQLite.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil

PROCESS_NAME = "darksiders1.exe"
DB_FILE = Path("darksiders_debug.db")
POLL_PROCESS_SECONDS = 1.5
OBSERVE_INTERVAL_SECONDS = 0.25

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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


@dataclass(frozen=True)
class WatchTarget:
    """A single memory location to observe. Add mapped offsets here."""

    event_type: str
    address: int
    size: int
    notes: str


# Populated once addresses are mapped. Empty list = attach + session only.
WATCH_TARGETS: tuple[WatchTarget, ...] = ()


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def init_db(db_path: Path = DB_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pid INTEGER,
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS event_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            event_type TEXT,
            address_hex TEXT,
            value_raw TEXT,
            notes TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
        """
    )
    conn.commit()
    return conn


def start_session(conn: sqlite3.Connection, pid: int) -> int:
    cur = conn.execute("INSERT INTO sessions (pid) VALUES (?)", (pid,))
    conn.commit()
    return int(cur.lastrowid)


def log_event(
    conn: sqlite3.Connection,
    session_id: int,
    event_type: str,
    address_hex: str,
    value_raw: str,
    notes: str,
) -> None:
    conn.execute(
        """
        INSERT INTO event_logs (session_id, event_type, address_hex, value_raw, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, event_type, address_hex, value_raw, notes),
    )
    conn.commit()
    print(
        f"[{_now()}] [EVENT] {event_type} | Address: {address_hex} "
        f"| Val: {value_raw} | {notes}"
    )


def find_process(name: str = PROCESS_NAME) -> Optional[int]:
    target = name.lower()
    for proc in psutil.process_iter(["pid", "name"]):
        proc_name = proc.info.get("name")
        if proc_name and proc_name.lower() == target:
            return int(proc.info["pid"])
    return None


def open_process(pid: int) -> ctypes.wintypes.HANDLE:
    access = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
    handle = kernel32.OpenProcess(access, False, pid)
    if not handle:
        err = ctypes.get_last_error()
        raise OSError(f"OpenProcess failed for pid={pid} (error {err})")
    return handle


def read_memory(
    handle: ctypes.wintypes.HANDLE, address: int, size: int
) -> Optional[bytes]:
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


def wait_for_process() -> int:
    print(f"[WAITING] Searching for {PROCESS_NAME}...")
    while True:
        pid = find_process()
        if pid is not None:
            return pid
        time.sleep(POLL_PROCESS_SECONDS)


def observe_loop(
    conn: sqlite3.Connection,
    session_id: int,
    handle: ctypes.wintypes.HANDLE,
    targets: tuple[WatchTarget, ...],
) -> None:
    last_values: dict[int, bytes] = {}

    if not targets:
        print(
            f"[{_now()}] [SESSION {session_id}] No watch targets configured. "
            "Waiting (Ctrl+C to exit)..."
        )
        while True:
            time.sleep(1.0)

    while True:
        for target in targets:
            raw = read_memory(handle, target.address, target.size)
            if raw is None:
                continue
            prev = last_values.get(target.address)
            if prev == raw:
                continue
            last_values[target.address] = raw
            value_raw = raw.hex() if target.size > 8 else str(int.from_bytes(raw, "little"))
            log_event(
                conn,
                session_id,
                target.event_type,
                f"0x{target.address:X}",
                value_raw,
                target.notes,
            )
        time.sleep(OBSERVE_INTERVAL_SECONDS)


def main() -> int:
    if sys.platform != "win32":
        print("[ERROR] This watcher requires Windows.")
        return 1

    conn = init_db()
    pid = wait_for_process()

    try:
        handle = open_process(pid)
    except OSError as exc:
        print(f"[ERROR] {exc}")
        return 1

    print(f"[FOUND] Attached to PID {pid} (64-bit handle acquired).")
    session_id = start_session(conn, pid)
    print(f"[{_now()}] [SESSION {session_id}] CONNECTED pid={pid}")

    try:
        observe_loop(conn, session_id, handle, WATCH_TARGETS)
    except KeyboardInterrupt:
        print(f"\n[{_now()}] [SESSION {session_id}] Detached.")
    finally:
        kernel32.CloseHandle(handle)
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
