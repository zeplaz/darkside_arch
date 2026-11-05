"""DLL lab controller for the mapping dashboard.

Modes:
- **test** — ``python -m runtime.dll --no-ap`` (local POC, no Archipelago)
- **live** — ``python -m runtime.dll`` using ``ap_config.json`` (real LocationChecks)
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

from ap.config import read_config
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
MODES = frozenset({"test", "live"})

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
        self._mode = "test"  # UI selection
        self._host_mode: Optional[str] = None  # mode the running host was started with

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

    def _ap_summary(self) -> dict[str, Any]:
        try:
            cfg = read_config()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"ok": False, "detail": "ap_config.json unreadable"}
        slot = (cfg.slot or "").strip()
        return {
            "ok": bool(slot),
            "slot": slot or "(empty)",
            "uri": cfg.uri(),
            "detail": f"{slot}@{cfg.uri()}" if slot else "set slot in ap_config.json",
        }

    def set_mode(self, mode: str) -> dict[str, Any]:
        mode = (mode or "").strip().lower()
        if mode not in MODES:
            raise ValueError("mode must be 'test' or 'live'")
        with self._lock:
            if self._proc is not None and self._proc.poll() is None and self._host_mode != mode:
                raise RuntimeError(
                    f"host is running in {self._host_mode} mode — STOP HOST before switching to {mode}"
                )
            self._mode = mode
        self._append("lab", f"mode={mode}")
        return {"ok": True, **self.status()}

    def status(self) -> dict[str, Any]:
        with self._lock:
            proc = self._proc
            last_check = self._last_check
            last_inject = self._last_inject
            building = self._building
            log_id = self._log_id
            mode = self._mode
            host_mode = self._host_mode
        alive = proc is not None and proc.poll() is None
        pid = find_process(PROCESS_NAME)
        idents = load_location_identities()
        ap = self._ap_summary()
        return {
            "mode": mode,
            "host_mode": host_mode if alive else None,
            "ap": ap,
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
            "steps": self._steps(mode, host_mode if alive else None, alive, pid, ap),
        }

    @staticmethod
    def _stamp_states(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Mark each step done / pending / blocked (first incomplete = pending)."""
        out: list[dict[str, Any]] = []
        pending_set = False
        for step in raw:
            done = bool(step.get("ok"))
            if done:
                state = "done"
            elif not pending_set:
                state = "pending"
                pending_set = True
            else:
                state = "blocked"
            row = dict(step)
            row["state"] = state
            out.append(row)
        return out

    def _steps(
        self,
        mode: str,
        host_mode: Optional[str],
        host_alive: bool,
        game_pid: Optional[int],
        ap: dict[str, Any],
    ) -> list[dict[str, Any]]:
        dll_ok = DLL_PATH.is_file()
        injected = bool(self._last_inject and "ok" in (self._last_inject or "").lower())
        tcp = self._port_open()
        if mode == "live":
            raw = [
                {
                    "id": 1,
                    "title": "Build DLL",
                    "ok": dll_ok,
                    "hint": "Click BUILD if missing.",
                },
                {
                    "id": 2,
                    "title": "ap_config.json slot",
                    "ok": bool(ap.get("ok")),
                    "hint": ap.get("detail") or "Set host/port/slot in ap_config.json.",
                },
                {
                    "id": 3,
                    "title": "Start host (live)",
                    "ok": host_alive and tcp and host_mode == "live",
                    "hint": "START HOST — connects to Archipelago.",
                },
                {
                    "id": 4,
                    "title": "Launch Darksiders",
                    "ok": game_pid is not None,
                    "hint": "Steam launch. Wait until GAME pill lights up.",
                },
                {
                    "id": 5,
                    "title": "Inject DLL",
                    "ok": injected,
                    "hint": "INJECT — watch LOG for hello.",
                },
                {
                    "id": 6,
                    "kind": "open",
                    "title": "Open selected location in-game",
                    "ok": False,
                    "hint": "Pick an IDENTIFIED row on the left. Real LocationChecks — not SIMULATE.",
                },
            ]
        else:
            # SIMULATE is a side button — does not gate this list.
            raw = [
                {
                    "id": 1,
                    "title": "Build DLL",
                    "ok": dll_ok,
                    "hint": "Click BUILD if missing.",
                },
                {
                    "id": 2,
                    "title": "Start host (test)",
                    "ok": host_alive and tcp and host_mode == "test",
                    "hint": "START HOST — local, no Archipelago.",
                },
                {
                    "id": 3,
                    "title": "Launch Darksiders",
                    "ok": game_pid is not None,
                    "hint": "Steam launch. Wait until GAME pill lights up.",
                },
                {
                    "id": 4,
                    "title": "Inject DLL",
                    "ok": injected,
                    "hint": "INJECT after GAME is on.",
                },
                {
                    "id": 5,
                    "kind": "open",
                    "title": "Open selected location in-game",
                    "ok": False,
                    "hint": "Pick an IDENTIFIED row on the left — watch LOG.",
                },
            ]
        return self._stamp_states(raw)

    def logs(self, since: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._logs if e["id"] > since]

    def start_host(self, mode: Optional[str] = None) -> dict[str, Any]:
        if mode is not None:
            self.set_mode(mode)
        with self._lock:
            want = self._mode
            if self._proc is not None and self._proc.poll() is None:
                note = f"host already running ({self._host_mode})"
                return {"ok": True, "note": note, **self.status()}
        if want == "live":
            ap = self._ap_summary()
            if not ap.get("ok"):
                raise RuntimeError(
                    "live mode needs a slot in ap_config.json — switch to TEST or set slot first"
                )
        if self._port_open():
            raise RuntimeError(
                f"port {TCP_PORT} already in use — stop the other runtime.dll host first"
            )
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        cmd = [sys.executable, "-m", "runtime.dll"]
        if want == "test":
            cmd.append("--no-ap")
        proc = subprocess.Popen(
            cmd,
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
            self._host_mode = want
        self._reader = threading.Thread(target=self._read_stdout, args=(proc,), daemon=True)
        self._reader.start()
        tag = "--no-ap" if want == "test" else "live AP"
        self._append("lab", f"started host pid={proc.pid} ({tag})")
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
            self._host_mode = None
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

        with self._lock:
            mode = self._mode
        if mode == "live":
            self._append(
                "lab",
                "SIMULATE is test-mode only — in LIVE, open the chest in-game so the host sends LocationChecks",
            )
            raise RuntimeError(
                "SIMULATE is for TEST mode. In LIVE, inject and open a chest in-game."
            )

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
