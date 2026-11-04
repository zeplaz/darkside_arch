"""Local DLL proof-of-concept controller for the mapping dashboard.

No Archipelago server. Starts ``python -m runtime.dll --no-ap``, injects
``darkside_arch.dll``, and can simulate an open from ``save_object`` identities.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional

from runtime.dll.host.handler import OpenHandler
from runtime.dll.host.ipc import TCP_HOST, TCP_PORT
from runtime.dll.host.targets_index import load_location_identities
from runtime.mem.models import PROCESS_NAME
from runtime.mem.watcher import find_process
from tools.dll_inject import inject

REPO_ROOT = Path(__file__).resolve().parent.parent
DLL_PATH = REPO_ROOT / "runtime" / "dll" / "native" / "target" / "release" / "darkside_arch.dll"
NATIVE_DIR = REPO_ROOT / "runtime" / "dll" / "native"
MAX_LOG = 400

# Hotel chest 1 — already identified in targets.json
DEFAULT_SIM = {"region_id": 2, "layer_id": 6, "object_id": 342, "value_key": "Triggered"}


class DllLab:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen[str]] = None
        self._logs: deque[dict[str, Any]] = deque(maxlen=MAX_LOG)
        self._log_id = 0
        self._reader: Optional[threading.Thread] = None
        self._last_check: Optional[str] = None
        self._last_inject: Optional[str] = None
        self._building = False

    def _append(self, source: str, text: str) -> None:
        text = text.rstrip()
        if not text:
            return
        with self._lock:
            self._log_id += 1
            entry = {
                "id": self._log_id,
                "ts": time.strftime("%H:%M:%S"),
                "source": source,
                "text": text,
            }
            self._logs.append(entry)
            low = text.lower()
            if "check " in low or '"op": "open"' in low or "op=open" in low:
                self._last_check = text

    def _read_stdout(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            self._append("host", line)
        code = proc.poll()
        self._append("lab", f"host exited code={code}")

    def _port_open(self) -> bool:
        try:
            with socket.create_connection((TCP_HOST, TCP_PORT), timeout=0.2):
                return True
        except OSError:
            return False

    def status(self) -> dict[str, Any]:
        with self._lock:
            proc = self._proc
            last_check = self._last_check
            last_inject = self._last_inject
            building = self._building
            log_id = self._log_id
        alive = proc is not None and proc.poll() is None
        pid = find_process(PROCESS_NAME)
        idents = load_location_identities()
        return {
            "host_running": alive,
            "host_pid": proc.pid if alive and proc else None,
            "tcp_open": self._port_open(),
            "tcp": f"{TCP_HOST}:{TCP_PORT}",
            "game_pid": pid,
            "game_running": pid is not None,
            "dll_exists": DLL_PATH.is_file(),
            "dll_path": str(DLL_PATH),
            "identities": len(idents),
            "last_check": last_check,
            "last_inject": last_inject,
            "building": building,
            "log_id": log_id,
            "steps": self._steps(alive, pid),
        }

    def _steps(self, host_alive: bool, game_pid: Optional[int]) -> list[dict[str, Any]]:
        dll_ok = DLL_PATH.is_file()
        return [
            {
                "id": 1,
                "title": "Start DLL host (--no-ap)",
                "ok": host_alive and self._port_open(),
                "hint": "START HOST — listens for the inject DLL; no Archipelago.",
            },
            {
                "id": 2,
                "title": "Build darkside_arch.dll",
                "ok": dll_ok,
                "hint": "BUILD DLL if missing (cargo release).",
            },
            {
                "id": 3,
                "title": "Simulate open (hotel chest 1)",
                "ok": bool(self._last_check),
                "hint": "SIMULATE — proves save_object → CHECK without the game.",
            },
            {
                "id": 4,
                "title": "Launch Darksiders (vanilla)",
                "ok": game_pid is not None,
                "hint": "Start the game normally. Do not replace Steam/version DLLs.",
            },
            {
                "id": 5,
                "title": "Inject darkside_arch.dll",
                "ok": bool(self._last_inject and "ok" in (self._last_inject or "").lower()),
                "hint": "INJECT after the game is running. Host should log hello / watches.",
            },
            {
                "id": 6,
                "title": "Open an identified chest in-game",
                "ok": False,
                "hint": "Hotel Life Chest 1. Watch HOST LOG for op=open / CHECK.",
            },
        ]

    def logs(self, since: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._logs if e["id"] > since]

    def start_host(self) -> dict[str, Any]:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return {"ok": True, "note": "host already running", **self.status()}
        if self._port_open():
            raise RuntimeError(
                f"port {TCP_PORT} already in use — stop the other runtime.dll host first"
            )
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        proc = subprocess.Popen(
            [sys.executable, "-m", "runtime.dll", "--no-ap"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            creationflags=creationflags,
        )
        with self._lock:
            self._proc = proc
        self._reader = threading.Thread(target=self._read_stdout, args=(proc,), daemon=True)
        self._reader.start()
        self._append("lab", f"started host pid={proc.pid} (--no-ap)")
        # wait briefly for bind
        for _ in range(20):
            if self._port_open():
                break
            if proc.poll() is not None:
                raise RuntimeError("host exited before opening TCP")
            time.sleep(0.1)
        return {"ok": True, **self.status()}

    def stop_host(self) -> dict[str, Any]:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None:
            return {"ok": True, "note": "no host", **self.status()}
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        self._append("lab", "host stopped")
        return {"ok": True, **self.status()}

    def inject_dll(self) -> dict[str, Any]:
        if not DLL_PATH.is_file():
            raise FileNotFoundError(f"DLL missing: {DLL_PATH} — BUILD DLL first")
        pid = find_process(PROCESS_NAME)
        if pid is None:
            raise RuntimeError(f"{PROCESS_NAME} is not running — launch the game first")
        if not (self._proc and self._proc.poll() is None):
            raise RuntimeError("start the DLL host before inject")
        inject(pid, DLL_PATH)
        msg = f"ok inject pid={pid} {DLL_PATH.name}"
        with self._lock:
            self._last_inject = msg
        self._append("lab", msg)
        return {"ok": True, "pid": pid, "dll": str(DLL_PATH), **self.status()}

    def simulate_open(
        self,
        *,
        region_id: int = DEFAULT_SIM["region_id"],  # type: ignore[arg-type]
        layer_id: int = DEFAULT_SIM["layer_id"],  # type: ignore[arg-type]
        object_id: int = DEFAULT_SIM["object_id"],  # type: ignore[arg-type]
        value_key: str = "Triggered",
    ) -> dict[str, Any]:
        from ap.catalog import load_catalog

        catalog = load_catalog()
        captured: list[str] = []

        class _Capture:
            def submit_location_checks(self, location_ids: list[int]) -> None:
                captured.append(f"LocationChecks {location_ids}")

            def submit_goal(self) -> None:
                captured.append("GOAL")

        handler = OpenHandler(catalog=catalog, runtime=_Capture())  # type: ignore[arg-type]
        payload = {
            "op": "open",
            "region_id": int(region_id),
            "layer_id": int(layer_id),
            "object_id": int(object_id),
            "value_key": value_key,
        }
        # OpenHandler prints; also mirror into lab log via capturing print is awkward —
        # call and record result from identities.
        idents = load_location_identities()
        key = (int(region_id), int(layer_id), int(object_id), value_key)
        ident = idents.get(key)
        handler.handle_line(json.dumps(payload))
        if ident is None:
            msg = f"simulate unmatched {payload}"
            self._append("lab", msg)
            return {"ok": False, "error": msg, **self.status()}
        loc_id = catalog.location_id(ident.label)
        msg = f"CHECK {ident.label} (AP {loc_id}) via simulate {key}"
        with self._lock:
            self._last_check = msg
        self._append("lab", msg)
        for c in captured:
            self._append("lab", c)
        return {
            "ok": True,
            "label": ident.label,
            "ap_id": loc_id,
            "identity": key,
            **self.status(),
        }

    def build_dll(self) -> dict[str, Any]:
        with self._lock:
            if self._building:
                return {"ok": True, "note": "build already running", **self.status()}
            self._building = True

        def _run() -> None:
            self._append("lab", "cargo build --release …")
            try:
                proc = subprocess.run(
                    ["cargo", "build", "--release"],
                    cwd=str(NATIVE_DIR),
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                if proc.stdout:
                    for line in proc.stdout.splitlines()[-30:]:
                        self._append("cargo", line)
                if proc.stderr:
                    for line in proc.stderr.splitlines()[-30:]:
                        self._append("cargo", line)
                if proc.returncode != 0:
                    self._append("lab", f"build FAILED code={proc.returncode}")
                else:
                    self._append("lab", f"build ok → {DLL_PATH}")
            except FileNotFoundError:
                self._append("lab", "cargo not found — install Rust toolchain")
            except Exception as exc:  # noqa: BLE001
                self._append("lab", f"build error: {exc}")
            finally:
                with self._lock:
                    self._building = False

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "note": "build started", **self.status()}


LAB = DllLab()
