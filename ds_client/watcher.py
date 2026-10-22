"""Orchestrator: process lifecycle, observation loop, event publishing.

This is the runtime client loop. Mapping / scan / export live under `tools/`.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from typing import Optional

import psutil

from ds_client.ap_apply import drain_apply_queue
from ds_client.ap_catalog import load_catalog
from ds_client.ap_client import ApRuntime
from ds_client.ap_config import parse_connect_target, patch_config
from ds_client.ap_sink import ApLocationSink
from ds_client.ap_state import open_state
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
    ap_runtime: Optional[ApRuntime] = None,
) -> None:
    last_values: dict[str, str] = {}
    known_ids = {t.id for t in targets}
    targets_mtime = _mtime(TARGETS_FILE)
    missing_modules: set[str] = set()

    if not targets:
        print(
            f"[{now()}] [SESSION {session_id}] No watch targets configured. "
            "Waiting for process exit, targets.json update, or Ctrl+C..."
        )

    while win32.process_alive(handle):
        # Hot-reload targets.json when it changes (capture / scan / dashboard saves).
        mtime = _mtime(TARGETS_FILE)
        if mtime != targets_mtime:
            targets_mtime = mtime
            try:
                interval_ms, targets = load_targets()
                interval_s = max(interval_ms, 1) / 1000.0
                if ap_runtime is not None:
                    ap_runtime.enqueue_pending_from_db()  # a newly mapped item can apply now
            except (OSError, ValueError, TypeError) as exc:
                print(f"[WARN] targets.json reload failed, keeping previous targets: {exc}")

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
            base = _module_base(handle, module_bases, target.module, missing_modules)
            if base is None:
                continue
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
        if ap_runtime is not None:
            try:
                drain_apply_queue(
                    handle,
                    module_bases,
                    targets,
                    ap_runtime.catalog,
                    ap_runtime.state,
                    ap_runtime.apply_queue,
                )
            except Exception as exc:  # noqa: BLE001 — never let AP kill the RAM loop
                print(f"[WARN] item apply failed: {exc}")
        bus.flush()
        time.sleep(interval_s)


def _mtime(path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _module_base(
    handle: win32.ProcessHandle,
    bases: dict[str, int],
    module: str,
    missing: set[str],
) -> Optional[int]:
    """Cached module base; a module that is not loaded is warned about once."""
    if module in bases:
        return bases[module]
    try:
        bases[module] = win32.get_module_base(handle, module)
    except OSError as exc:
        if module not in missing:
            missing.add(module)
            print(f"[WARN] module base {module}: {exc}")
        return None
    missing.discard(module)
    print(f"[BASE] {module} @ 0x{bases[module]:X}")
    return bases[module]


def attach_and_run(
    conn: sqlite3.Connection,
    bus: EventBus,
    targets: tuple[WatchTarget, ...],
    interval_s: float,
    ap_runtime: Optional[ApRuntime] = None,
) -> None:
    pid = wait_for_process()
    handle = win32.open_process(pid)
    try:
        print(f"[FOUND] Attached to PID {pid}.")
        bases: dict[str, int] = {}
        for name in sorted({PROCESS_NAME, *(t.module for t in targets)}):
            _module_base(handle, bases, name, set())

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
        if ap_runtime is not None:
            ap_runtime.enqueue_pending_from_db()

        observe_session(
            handle,
            session_id,
            bases,
            targets,
            interval_s,
            bus,
            conn,
            ap_runtime=ap_runtime,
        )

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


def run_watch_loop(*, enable_ap: bool = True) -> int:
    if sys.platform != "win32":
        print("[ERROR] This watcher requires Windows.")
        return 1

    try:
        interval_ms, targets = load_targets()
    except (OSError, ValueError, TypeError) as exc:
        print(f"[ERROR] Failed to load {TARGETS_FILE}: {exc}")
        return 1

    interval_s = max(interval_ms, 1) / 1000.0
    conn = init_db()
    ap_runtime: Optional[ApRuntime] = None
    ap_state = None
    sinks = [TerminalSink(), SqliteSink(conn)]
    if enable_ap:
        catalog = load_catalog()
        if catalog.empty:
            print("[ERROR] docs/world_locations.json / world_items.json missing. Run from the repo root.")
            conn.close()
            return 1
        ap_state = open_state()
        ap_runtime = ApRuntime(ap_state, catalog)
        sinks.append(ApLocationSink(ap_runtime, catalog))
        ap_runtime.start()
        print("[INIT] AP websocket loop started (independent of RAM attach)")
    bus = EventBus(sinks)

    print(f"[INIT] Watching {len(targets)} mapped target(s) from {TARGETS_FILE}")
    sync_memory_map_from_targets(conn, targets)

    try:
        while True:
            try:
                attach_and_run(
                    conn, bus, targets, interval_s, ap_runtime=ap_runtime
                )
            except OSError as exc:
                print(f"[ERROR] {exc}")
                time.sleep(POLL_PROCESS_SECONDS)
            bus.flush()
            try:
                interval_ms, targets = load_targets()
                interval_s = max(interval_ms, 1) / 1000.0
                sync_memory_map_from_targets(conn, targets)
            except (OSError, ValueError, TypeError) as exc:
                print(f"[WARN] targets.json reload failed: {exc}")
    except KeyboardInterrupt:
        print(f"\n[{now()}] Detached.")
    finally:
        bus.flush()
        if ap_runtime is not None:
            ap_runtime.stop()
        if ap_state is not None:
            ap_state.close()
        conn.close()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="python -m ds_client",
        description=(
            "Runtime memory watcher and Archipelago client for "
            "Darksiders Warmastered (x64)."
        ),
    )
    parser.add_argument(
        "--connect",
        default="",
        help="AP host[:port], ws://, or wss://; saved to ap_config.json",
    )
    parser.add_argument("--slot", default="", help="AP slot name")
    parser.add_argument("--password", default="", help="AP room password")
    parser.add_argument(
        "--send-goal",
        action="store_true",
        help="Send StatusUpdate CLIENT_GOAL once connected (debug)",
    )
    parser.add_argument(
        "--no-ap",
        action="store_true",
        help="RAM watcher only; do not start the websocket loop",
    )
    args = parser.parse_args(argv)
    if args.connect or args.slot or args.password or args.send_goal:
        changes = {}
        if args.connect:
            host, port, use_wss = parse_connect_target(args.connect)
            changes.update({"host": host, "use_wss": use_wss})
            if port is not None:
                changes["port"] = port
        if args.slot:
            changes["slot"] = args.slot
        if args.password:
            changes["password"] = args.password
        if args.send_goal:
            changes["request_goal"] = True
        patch_config(**changes)
    return run_watch_loop(enable_ap=not args.no_ap)
