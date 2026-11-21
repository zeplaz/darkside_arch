"""DLL-path AP host: LocationChecks from open identity + RPM item apply."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from typing import Optional

from ap.catalog import load_catalog
from ap.client import ApRuntime
from ap.config import default_use_wss, parse_connect_target, patch_config
from ap.state import open_state
from runtime.dll.host.apply_loop import start_apply_thread
from runtime.dll.host.handler import OpenHandler
from runtime.dll.host.ipc import TCP_HOST, TCP_PORT, IpcServer
from runtime.dll.host.targets_index import load_location_identities, watches_payload


def _apply_connect_args(args: argparse.Namespace) -> None:
    if not (args.connect or args.slot or args.password or args.send_goal):
        return
    changes: dict = {}
    if args.connect:
        host, port, use_wss = parse_connect_target(args.connect)
        changes["host"] = host
        if port is not None:
            changes["port"] = port
        if use_wss is None:
            use_wss = default_use_wss(host)
        changes["use_wss"] = use_wss
    if args.slot:
        changes["slot"] = args.slot
    if args.password:
        changes["password"] = args.password
    if args.send_goal:
        changes["request_goal"] = True
    patch_config(**changes)


def _poke_dll_loop(spec: str, server: IpcServer) -> None:
    """Resolve a targets.json row externally, then ask the DLL to write it in-process."""
    import time

    target_id, _sep, value_raw = spec.partition("=")
    target_id = target_id.strip()
    value_raw = value_raw.strip()
    if not target_id or not value_raw:
        print("[dll/poke] usage: --poke-dll ID=VALUE (e.g. soul_count=10000)")
        return

    from tools.poke import parse_value, pokable_targets, resolve_write
    from runtime.mem.watcher import find_process

    target = pokable_targets().get(target_id)
    if target is None:
        print(
            f"[dll/poke] no mapped inventory/stat row for {target_id!r}. "
            "Map it first: python -m tools scan --item Soul_Count"
        )
        return
    try:
        value = parse_value(value_raw, target.dtype)
    except ValueError as exc:
        print(f"[dll/poke] bad value {value_raw!r}: {exc}")
        return

    deadline = time.monotonic() + 120
    pid = None
    while time.monotonic() < deadline:
        pid = find_process()
        if pid is not None and server.has_client:
            break
        time.sleep(1)
    if pid is None or not server.has_client:
        print("[dll/poke] timed out waiting for the game + injected DLL")
        return

    try:
        addr, data = resolve_write(pid, target, value)
        server.send_json(
            {"op": "poke", "address": addr, "bytes": data.hex(), "label": target.id}
        )
        print(f"[dll/poke] sent {target.id} @ 0x{addr:X} ({data.hex()}) to the DLL")
    except OSError as exc:
        print(f"[dll/poke] {exc}")


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="python -m runtime.dll",
        description=(
            "DLL-path Archipelago host for Darksiders Warmastered. "
            f"Inject darkside_arch.dll after start; IPC tcp://{TCP_HOST}:{TCP_PORT}."
        ),
    )
    parser.add_argument("--connect", default="", help="AP host[:port], ws://, or wss://")
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
        help="IPC only; do not start the websocket loop",
    )
    parser.add_argument(
        "--no-apply",
        action="store_true",
        help="Do not attach for RPM item writes",
    )
    parser.add_argument(
        "--simulate-open",
        metavar="JSON",
        default="",
        help='Fire one open event then exit, e.g. '
        '\'{"region_id":2,"layer_id":6,"object_id":342}\'',
    )
    parser.add_argument(
        "--overlay",
        action="store_true",
        help="Show a topmost status overlay (DSH INJECTED + watch/check status)",
    )
    parser.add_argument(
        "--poke-dll",
        metavar="ID=VALUE",
        default="",
        help="When the DLL connects, write VALUE to a mapped target via the DLL "
        "(e.g. soul_count=10000)",
    )
    args = parser.parse_args(argv)
    _apply_connect_args(args)

    catalog = load_catalog()
    if catalog.empty and not args.no_ap:
        print("[ERROR] docs/world_locations.json / world_items.json missing. Run from repo root.")
        return 1

    identities = load_location_identities()
    print(f"[dll] {len(identities)} location identit(ies) with save_object")

    ap_state = open_state()
    ap_runtime: Optional[ApRuntime] = None
    if not args.no_ap:
        ap_runtime = ApRuntime(ap_state, catalog)
        ap_runtime.start()
        print("[dll] AP host started")
    else:
        print("[dll] --no-ap: skipping websocket")

    overlay = None
    if args.overlay:
        from tools.overlay import Overlay

        overlay = Overlay("DSH — waiting for injected DLL")

    handler = OpenHandler(catalog=catalog, runtime=ap_runtime, identities=identities, overlay=overlay)

    if args.simulate_open:
        try:
            payload = json.loads(args.simulate_open)
        except json.JSONDecodeError as exc:
            print(f"[ERROR] --simulate-open JSON: {exc}")
            if overlay is not None:
                overlay.close()
            if ap_runtime:
                ap_runtime.stop()
            ap_state.close()
            return 1
        payload.setdefault("op", "open")
        payload.setdefault("value_key", "Triggered")
        handler.handle_line(json.dumps(payload))
        if ap_runtime:
            # give the outbox a moment to flush toward the socket thread
            import time

            time.sleep(0.5)
            ap_runtime.stop()
        if overlay is not None:
            overlay.close()
        ap_state.close()
        return 0

    stop = threading.Event()
    apply_thread = None
    if ap_runtime is not None and not args.no_apply:
        apply_thread = start_apply_thread(ap_runtime, stop)

    server = IpcServer(
        on_message=handler.handle_line,
        stop=stop,
        watches=watches_payload(identities),
    )
    if args.poke_dll:
        threading.Thread(
            target=_poke_dll_loop,
            args=(args.poke_dll, server),
            name="dll-poke",
            daemon=True,
        ).start()
    print("[dll] waiting for Rust DLL (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dll] stopping")
    finally:
        stop.set()
        if apply_thread is not None:
            apply_thread.join(timeout=2.0)
        if overlay is not None:
            overlay.close()
        if ap_runtime is not None:
            ap_runtime.stop()
        ap_state.close()
    return 0
