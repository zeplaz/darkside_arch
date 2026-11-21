"""Smoke-test the built darkside_arch.dll without the game.

Loads the DLL into this process and verifies the real IPC handshake
(hello / watches) plus an in-process poke write. Proves the injected DLL talks
to the host and writes process memory — a fast "does it actually work" check.

Usage: python -m tools dll-selftest [--dll PATH]
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DLL = REPO_ROOT / "runtime" / "dll" / "native" / "target" / "release" / "darkside_arch.dll"


def _load_ipc_server():
    """Import runtime/dll/host/ipc.py directly (it is stdlib-only), bypassing the
    package __init__ which drags in websockets/psutil."""
    path = REPO_ROOT / "runtime" / "dll" / "host" / "ipc.py"
    spec = importlib.util.spec_from_file_location("dsh_dll_ipc", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.IpcServer


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="python -m tools dll-selftest")
    p.add_argument("--dll", type=Path, default=DEFAULT_DLL)
    args = p.parse_args(argv)
    if not args.dll.is_file():
        print(f"[ERROR] DLL not found: {args.dll} (build it first)")
        return 1

    IpcServer = _load_ipc_server()

    buf = ctypes.create_string_buffer(16)
    buf_addr = ctypes.addressof(buf)

    stop = threading.Event()
    hello_seen = False
    watches_logged = 0
    poke_results = []
    opens = []

    def on_message(line):
        nonlocal hello_seen, watches_logged
        line = line.strip()
        if not line:
            return
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print("HOST non-json:", line)
            return
        op = msg.get("op")
        if op == "hello":
            hello_seen = True
            print("HOST <- hello:", msg)
        elif op == "log":
            text = str(msg.get("msg", ""))
            if text.startswith("watches="):
                watches_logged = int(text.split("=")[1].strip() or 0)
            print("HOST <- log:", text)
        elif op == "poke_result":
            poke_results.append(msg)
            print("HOST <- poke_result:", msg)
        elif op == "open":
            opens.append(msg)
            print("HOST <- open:", msg)

    server = IpcServer(on_message=on_message, stop=stop, watches=[
        {"region_id": 2, "layer_id": 6, "object_id": 342, "value_key": "Triggered"}
    ])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.5)

    ctypes.WinDLL(str(args.dll))
    print("DLL loaded:", args.dll)

    deadline = time.time() + 10
    while time.time() < deadline and not (hello_seen and server.has_client):
        time.sleep(0.2)
    time.sleep(1.0)

    payload = bytes.fromhex("deadbeefcafebabe")
    server.send_json({"op": "poke", "address": buf_addr, "bytes": payload.hex(), "label": "selftest"})
    time.sleep(1.5)

    wrote_ok = buf.raw[: len(payload)] == payload
    poke_ok = any(r.get("ok") for r in poke_results)
    ok = hello_seen and wrote_ok and poke_ok and watches_logged == 1 and not opens

    print("\n--- results ---")
    print(f"hello={hello_seen} watches={watches_logged} poke_ok={poke_ok} wrote_ok={wrote_ok}")
    if opens:
        print("spurious opens (should be empty):", opens)
    print("RESULT:", "PASS" if ok else "FAIL")

    stop.set()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
