"""Phase 3: reuse mem-path RPM item writes while the DLL host owns AP."""

from __future__ import annotations

import threading
import time
from typing import Optional

from ap.client import ApRuntime
from runtime.dll.host.targets_index import load_mapped_item_targets
from runtime.mem import win32
from runtime.mem.apply import drain_apply_queue
from runtime.mem.models import PROCESS_NAME, TARGETS_FILE
from runtime.mem.watcher import find_process

POLL_S = 1.5
APPLY_INTERVAL_S = 0.25


def _module_bases(handle: win32.ProcessHandle, targets) -> dict[str, int]:
    bases: dict[str, int] = {}
    names = {PROCESS_NAME, *(t.module for t in targets)}
    for name in sorted(names):
        try:
            bases[name] = win32.get_module_base(handle, name)
            print(f"[dll/apply] {name} @ 0x{bases[name]:X}")
        except OSError as exc:
            print(f"[dll/apply] module {name}: {exc}")
    return bases


def run_apply_loop(ap_runtime: ApRuntime, stop: threading.Event) -> None:
    """Attach to the game when present and drain ReceivedItems onto RAM."""
    targets_mtime = 0.0
    targets = load_mapped_item_targets()
    print(f"[dll/apply] {len(targets)} mapped item/stat target(s)")

    while not stop.is_set():
        try:
            mtime = TARGETS_FILE.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime != targets_mtime:
            targets_mtime = mtime
            targets = load_mapped_item_targets()
            print(f"[dll/apply] reloaded {len(targets)} item target(s)")
            ap_runtime.enqueue_pending_from_db()

        pid = find_process()
        if pid is None:
            time.sleep(POLL_S)
            continue

        try:
            handle = win32.open_process(pid)
        except OSError as exc:
            print(f"[dll/apply] open_process: {exc}")
            time.sleep(POLL_S)
            continue

        print(f"[dll/apply] attached pid={pid}")
        ap_runtime.enqueue_pending_from_db()
        try:
            bases = _module_bases(handle, targets)
            while not stop.is_set() and win32.process_alive(handle):
                try:
                    mtime = TARGETS_FILE.stat().st_mtime
                except OSError:
                    mtime = targets_mtime
                if mtime != targets_mtime:
                    targets_mtime = mtime
                    targets = load_mapped_item_targets()
                    bases = _module_bases(handle, targets)
                    ap_runtime.enqueue_pending_from_db()
                try:
                    drain_apply_queue(
                        handle,
                        bases,
                        targets,
                        ap_runtime.catalog,
                        ap_runtime.state,
                        ap_runtime.apply_queue,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[dll/apply] warn: {exc}")
                time.sleep(APPLY_INTERVAL_S)
        finally:
            win32.close_handle(handle)
            print(f"[dll/apply] detached pid={pid}")
        time.sleep(POLL_S)


def start_apply_thread(ap_runtime: Optional[ApRuntime], stop: threading.Event) -> Optional[threading.Thread]:
    if ap_runtime is None:
        return None
    thread = threading.Thread(
        target=run_apply_loop,
        args=(ap_runtime, stop),
        name="dll-apply",
        daemon=True,
    )
    thread.start()
    return thread
