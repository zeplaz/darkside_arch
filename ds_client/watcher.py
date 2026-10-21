"""Orchestrator: process lifecycle, observation loop, event publishing.

This is the runtime client loop. Mapping / scan / export live under `tools/`.
"""

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
    sync_memory_map_from_targets,
    upsert_memory_map_from_target,
)
from ds_client import win32

POLL_PROCESS_SECONDS = 1.5

# Old flag names that moved to `python -m tools ...`
_DEV_FLAG_HINTS = (
    "--scan",
    "--export-docs",
    "--sync-map",
    "--tag",
)


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
    conn: sqlite3.Connection,
) -> None:
    last_values: dict[str, str] = {}
    known_ids = {t.id for t in targets}

    if not targets:
        print(
            f"[{now()}] [SESSION {session_id}] No watch targets configured. "
            "Waiting for process exit, targets.json update, or Ctrl+C..."
        )

    while win32.process_alive(handle):
        # Hot-reload targets.json so scan --auto-save is picked up without restart.
        try:
            interval_ms, targets = load_targets()
            interval_s = max(interval_ms, 1) / 1000.0
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            print(f"[WARN] targets reload failed: {exc}")

        new_ids = {t.id for t in targets}
        if new_ids != known_ids:
            added = new_ids - known_ids
            removed = known_ids - new_ids
            known_ids = new_ids
            if added:
                print(f"[{now()}] [TARGETS] +{sorted(added)}")
            if removed:
                print(f"[{now()}] [TARGETS] -{sorted(removed)}")
            sync_memory_map_from_targets(conn, targets)

        for target in targets:
            if target.module not in module_bases:
                try:
                    module_bases[target.module] = win32.get_module_base(
                        handle, target.module
                    )
                    print(
                        f"[BASE] {target.module} @ 0x{module_bases[target.module]:X}"
                    )
                except OSError as exc:
                    print(f"[WARN] module base {target.module}: {exc}")
                    continue

            base = module_bases[target.module]
            addr = win32.resolve_address(handle, base, target.offsets)
            if addr is None:
                continue
            raw = win32.read_memory(handle, addr, target.size)
            if raw is None:
                continue
            value_raw = target.decode(raw)
            prev = last_values.get(target.id)
            if prev == value_raw:
                continue
            last_values[target.id] = value_raw

            notes = target.notes or target.display_name
            if prev is not None:
                notes = f"{prev} -> {value_raw} | {notes}"

            bus.publish(
                Event(
                    session_id=session_id,
                    event_type=target.event_type,
                    address_hex=f"0x{addr:X}",
                    value_raw=value_raw,
                    prev_value=prev or "",
                    notes=notes,
                    target_id=target.id,
                    label=target.display_name,
                    region=target.region,
                    category=target.category,
                )
            )
            if prev is not None:
                upsert_memory_map_from_target(
                    conn,
                    target,
                    verified_value=value_raw,
                    address_hex=f"0x{addr:X}",
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

        observe_session(handle, session_id, bases, targets, interval_s, bus, conn)

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


def run_watch_loop() -> int:
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
    if targets:
        sync_memory_map_from_targets(conn, targets)
        print(f"[INIT] Synced {len(targets)} target(s) into memory_map")

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
                if targets:
                    sync_memory_map_from_targets(conn, targets)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                print(f"[WARN] targets reload failed: {exc}")
    except KeyboardInterrupt:
        print(f"\n[{now()}] Detached.")
    finally:
        bus.flush()
        conn.close()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for flag in _DEV_FLAG_HINTS:
        if flag in argv or any(a.startswith(flag + "=") for a in argv):
            print(
                f"[ERROR] {flag} moved to the developer tools package.\n"
                "        pip install -r requirements-dev.txt\n"
                "        python -m tools --help\n"
                "        See tools/README.md"
            )
            return 2
    if argv in (["-h"], ["--help"]):
        print(
            "usage: python -m ds_client\n\n"
            "Runtime memory watcher for Darksiders Warmastered (x64).\n"
            "Reads targets.json, attaches to darksiders1.exe, logs deltas.\n\n"
            "Developer mapping tools (scan / tag / export):\n"
            "  python -m tools --help\n"
            "  See ds_client/README.md and tools/README.md"
        )
        return 0
    if argv:
        print(f"[ERROR] Unexpected arguments: {' '.join(argv)}")
        print("        Runtime client takes no flags. Try: python -m tools --help")
        return 2
    return run_watch_loop()
