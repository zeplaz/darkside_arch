"""Orchestrator: process lifecycle, observation loop, event publishing."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from typing import Optional

import psutil

from ds_client.models import (
    PROCESS_NAME,
    TARGETS_FILE,
    Event,
    WatchTarget,
    load_targets,
)
from ds_client.sinks import (
    EventBus,
    SqliteSink,
    TerminalSink,
    init_db,
    now,
    start_session,
)
from ds_client import win32

POLL_PROCESS_SECONDS = 1.5


def find_process(name: str = PROCESS_NAME) -> Optional[int]:
    target = name.lower()
    for proc in psutil.process_iter(["pid", "name"]):
        proc_name = proc.info.get("name")
        if proc_name and proc_name.lower() == target:
            return int(proc.info["pid"])
    return None


def wait_for_process() -> int:
    print(f"[WAITING] Searching for {PROCESS_NAME}...")
    while True:
        pid = find_process()
        if pid is not None:
            return pid
        time.sleep(POLL_PROCESS_SECONDS)


def observe_session(
    handle: win32.ProcessHandle,
    session_id: int,
    module_bases: dict[str, int],
    targets: tuple[WatchTarget, ...],
    interval_s: float,
    bus: EventBus,
) -> None:
    last_values: dict[str, str] = {}

    if not targets:
        print(
            f"[{now()}] [SESSION {session_id}] No watch targets configured. "
            "Waiting for process exit or Ctrl+C..."
        )

    while win32.process_alive(handle):
        for target in targets:
            base = module_bases[target.module]
            addr = win32.resolve_address(handle, base, target.offsets)
            if addr is None:
                continue
            raw = win32.read_memory(handle, addr, target.size)
            if raw is None:
                continue
            value_raw = target.decode(raw)
            if last_values.get(target.id) == value_raw:
                continue
            last_values[target.id] = value_raw
            bus.publish(
                Event(
                    session_id=session_id,
                    event_type=target.event_type,
                    address_hex=f"0x{addr:X}",
                    value_raw=value_raw,
                    notes=target.notes or target.id,
                )
            )
        bus.flush()
        time.sleep(interval_s)


def attach_and_run(
    conn: sqlite3.Connection,
    bus: EventBus,
    targets: tuple[WatchTarget, ...],
    interval_s: float,
) -> None:
    pid = wait_for_process()
    handle = win32.open_process(pid)
    try:
        modules = {PROCESS_NAME}
        modules.update(t.module for t in targets)
        bases = {name: win32.get_module_base(handle, name) for name in modules}

        print(f"[FOUND] Attached to PID {pid} (64-bit handle acquired).")
        for name, base in sorted(bases.items()):
            print(f"[BASE] {name} @ 0x{base:X}")

        session_id = start_session(conn, pid)
        print(f"[{now()}] [SESSION {session_id}] CONNECTED pid={pid}")
        bus.publish(
            Event(
                session_id=session_id,
                event_type="SESSION",
                address_hex="-",
                value_raw=str(pid),
                notes="CONNECTED",
            )
        )
        bus.flush()

        observe_session(handle, session_id, bases, targets, interval_s, bus)

        bus.publish(
            Event(
                session_id=session_id,
                event_type="SESSION",
                address_hex="-",
                value_raw=str(pid),
                notes="SESSION_ENDED",
            )
        )
        bus.flush()
        print(f"[{now()}] [SESSION {session_id}] SESSION_ENDED pid={pid}")
    finally:
        win32.close_handle(handle)


def main() -> int:
    if sys.platform != "win32":
        print("[ERROR] This watcher requires Windows.")
        return 1

    try:
        interval_ms, targets = load_targets()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"[ERROR] Failed to load {TARGETS_FILE}: {exc}")
        return 1

    interval_s = max(interval_ms, 1) / 1000.0
    conn = init_db()
    bus = EventBus([TerminalSink(), SqliteSink(conn)])

    print(f"[INIT] Loaded {len(targets)} watch target(s) from {TARGETS_FILE}")

    try:
        while True:
            try:
                attach_and_run(conn, bus, targets, interval_s)
            except OSError as exc:
                print(f"[ERROR] {exc}")
                time.sleep(POLL_PROCESS_SECONDS)
            bus.flush()
            try:
                interval_ms, targets = load_targets()
                interval_s = max(interval_ms, 1) / 1000.0
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                print(f"[WARN] targets reload failed: {exc}")
    except KeyboardInterrupt:
        print(f"\n[{now()}] Detached.")
    finally:
        bus.flush()
        conn.close()
    return 0
