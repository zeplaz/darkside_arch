"""Mapping dashboard: catalog, guided chest capture, live watch values.

Serves tools/static/mapping_terminal.html. Not the AP runtime (that is ds_client).

A background GameMonitor owns process attach/detach and read-only live reads,
so HTTP requests never scan the process list. The page polls /api/state.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import parse_qs, urlparse

from ds_client import win32
from ds_client.models import PROCESS_NAME, TARGETS_FILE, WatchTarget, load_targets
from ds_client.sinks import DB_FILE, init_db
from ds_client.watcher import find_process
from tools.export_docs import DOCS_PATH, export_docs
from tools.snapshot import diff_snapshots, take_snapshot
from tools.targets import build_target_entry, is_template, raw_targets, save_target
from tools.world_catalog import is_mapped, load_catalog

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PAGE_PATH = Path(__file__).resolve().parent / "static" / "mapping_terminal.html"

SCAN_PROCESS_SECONDS = 1.0  # psutil.process_iter costs ~200 ms; only while detached
IDLE_TICK_SECONDS = 0.25
MAX_DELTAS_SENT = 200
HISTORY_EVENTS = 8

# Fixed names: each capture overwrites the last, nothing piles up in snapshots/.
SNAP_A = "_dash_a"
SNAP_B = "_dash_b"
SNAP_C = "_dash_c"


def _json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    raw = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8") or "{}")


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


class GameMonitor:
    """Attach/detach + read-only live reads of mapped targets, on one thread.

    Detached: scan for the process every SCAN_PROCESS_SECONDS.
    Attached: only GetExitCodeProcess + the target reads, at observe_interval_ms.
    """

    def __init__(self, targets_path: Path = TARGETS_FILE) -> None:
        self._targets_path = targets_path
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._handle: Optional[win32.ProcessHandle] = None
        self._pid: Optional[int] = None
        self._base: Optional[int] = None
        self._bases: dict[str, int] = {}
        self._attached_at = 0.0
        self._error = ""
        self._epoch = 0  # bumps on every attach/detach so the page can react once
        self._targets: tuple[WatchTarget, ...] = ()
        self._targets_mtime = -1.0
        self._interval_s = IDLE_TICK_SECONDS
        self._live: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="game-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._detach("")

    def status(self) -> dict[str, Any]:
        with self._lock:
            attached = self._handle is not None
            return {
                "attached": attached,
                "pid": self._pid,
                "process": PROCESS_NAME,
                "module_base": f"0x{self._base:X}" if self._base else None,
                "attached_for_s": round(time.time() - self._attached_at, 1) if attached else 0,
                "error": self._error,
                "epoch": self._epoch,
                "interval_ms": int(self._interval_s * 1000),
                "targets_rev": self._targets_mtime,
            }

    def watches(self) -> list[dict[str, Any]]:
        with self._lock:
            out = []
            for t in self._targets:
                live = self._live.get(t.id, {})
                out.append(
                    {
                        "id": t.id,
                        "label": t.display_name,
                        "category": t.category,
                        "region": t.region,
                        "dtype": t.dtype,
                        "offset": " -> ".join(f"0x{o:X}" for o in t.offsets),
                        "value": live.get("value"),
                        "prev": live.get("prev"),
                        "changed_at": live.get("changed_at"),
                        "readable": live.get("readable", False),
                    }
                )
            return out

    # -- thread -----------------------------------------------------------

    def _run(self) -> None:
        next_scan = 0.0
        while not self._stop.is_set():
            self._reload_targets()
            if self._handle is None:
                if time.monotonic() >= next_scan:
                    self._try_attach()
                    next_scan = time.monotonic() + SCAN_PROCESS_SECONDS
            elif not win32.process_alive(self._handle):
                self._detach("game exited")
            else:
                self._read_live()
            wait = self._interval_s if self._handle is not None else IDLE_TICK_SECONDS
            self._stop.wait(wait)

    def _reload_targets(self) -> None:
        mtime = _mtime(self._targets_path)
        if mtime == self._targets_mtime:
            return
        try:
            interval_ms, targets = load_targets(self._targets_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            with self._lock:
                self._error = f"targets.json: {exc}"
                self._targets_mtime = mtime
            return
        with self._lock:
            self._targets = targets
            self._targets_mtime = mtime
            self._interval_s = max(interval_ms, 50) / 1000.0
            keep = {t.id for t in targets}
            self._live = {k: v for k, v in self._live.items() if k in keep}
            if self._error.startswith("targets.json"):
                self._error = ""

    def _try_attach(self) -> None:
        pid = find_process()
        if pid is None:
            with self._lock:
                if not self._error.startswith("targets.json"):
                    self._error = ""
            return
        try:
            handle = win32.open_process(pid, write=False)
        except OSError as exc:
            with self._lock:
                self._pid = pid
                self._error = f"{exc}. Run the dashboard from the same (or elevated) user as the game."
            return
        try:
            base = win32.get_module_base(handle, PROCESS_NAME)
        except OSError as exc:
            # Right after launch the module list may not be ready yet; retry next scan.
            win32.close_handle(handle)
            with self._lock:
                self._pid = pid
                self._error = f"waiting for module: {exc}"
            return
        with self._lock:
            self._handle = handle
            self._pid = pid
            self._base = base
            self._bases = {PROCESS_NAME.lower(): base}
            self._attached_at = time.time()
            self._error = ""
            self._live = {}
            self._epoch += 1

    def _detach(self, reason: str) -> None:
        with self._lock:
            handle = self._handle
            had = handle is not None
            self._handle = None
            self._pid = None
            self._base = None
            self._bases = {}
            self._live = {}
            if had:
                self._epoch += 1
                self._error = reason
        if handle is not None:
            win32.close_handle(handle)

    def _module_base(self, module: str) -> Optional[int]:
        key = module.lower()
        if key not in self._bases:
            try:
                self._bases[key] = win32.get_module_base(self._handle, module)
            except OSError:
                return None
        return self._bases[key]

    def _read_live(self) -> None:
        now = time.time()
        updates: dict[str, dict[str, Any]] = {}
        for t in self._targets:
            base = self._module_base(t.module)
            addr = win32.resolve_address(self._handle, base, t.offsets) if base else None
            raw = win32.read_memory(self._handle, addr, t.size) if addr else None
            if raw is None:
                updates[t.id] = {"readable": False}
                continue
            updates[t.id] = {"readable": True, "value": t.decode(raw)}
        with self._lock:
            for tid, upd in updates.items():
                cur = self._live.setdefault(tid, {})
                if upd["readable"] and cur.get("value") != upd["value"]:
                    if "value" in cur:
                        cur["prev"] = cur["value"]
                        cur["changed_at"] = now
                    cur["value"] = upd["value"]
                cur["readable"] = upd["readable"]


def _ap_ops() -> dict[str, Any]:
    """Read-only AP config/state. Do not call load_config — it writes uuid."""
    cfg_path = Path("ap_config.json")
    example = Path("ap_config.example.json")
    present = cfg_path.exists()
    raw: dict[str, Any] = {}
    src = cfg_path if present else example
    if src.exists():
        loaded = json.loads(src.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = loaded
    host = str(raw.get("host") or "localhost").strip()
    port = int(raw.get("port") or 38281)
    slot = str(raw.get("slot") or "").strip()
    use_wss = bool(raw.get("use_wss"))
    scheme = "wss" if use_wss else "ws"
    seed = ""
    ingested = 0
    state_path = Path("ap_state.db")
    if state_path.exists():
        conn = sqlite3.connect(str(state_path))
        try:
            row = conn.execute(
                """
                SELECT seed_name, last_ingested_index
                FROM slot_state
                ORDER BY rowid DESC
                LIMIT 1
                """
            ).fetchone()
            if row:
                seed = str(row[0] or "")
                ingested = int(row[1] or 0)
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return {
        "config_present": present,
        "slot": slot,
        "uri": f"{scheme}://{host}:{port}",
        "seed": seed,
        "ingested": ingested,
    }


def _target_offset(raw: dict) -> str:
    offs = raw.get("offsets") or []
    if not offs:
        return ""
    chain = " -> ".join(str(o) for o in offs)
    return f"{raw.get('module') or PROCESS_NAME} + {chain}"


def inventory_facts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in raw_targets():
        cat = str(raw.get("category") or "")
        event = str(raw.get("event_type") or "")
        if cat not in {"inventory", "stat"} and event != "GOAL":
            continue
        offs = raw.get("offsets") or []
        mapped = not is_template(offs)
        out.append(
            {
                "id": str(raw.get("id") or ""),
                "label": str(raw.get("label") or raw.get("id") or ""),
                "category": cat or "misc",
                "event_type": event,
                "mapped": mapped,
                "enabled": bool(raw.get("enabled", True)),
                "offset": _target_offset(raw) if mapped else "",
            }
        )
    return out


def catalog_payload() -> dict[str, Any]:
    locations = load_catalog()
    targets = raw_targets()
    by_id = {str(t.get("id")): t for t in targets}
    by_label = {str(t.get("label")): t for t in targets}
    regions: dict[str, list[dict[str, Any]]] = {}
    mapped_n = 0
    for loc in locations:
        region = loc.region or "Other"
        raw = by_id.get(loc.slug) or by_label.get(loc.name)
        mapped = is_mapped(loc, targets)
        if mapped:
            mapped_n += 1
        item = {
            "id": loc.slug,
            "label": loc.name,
            "ap_id": loc.ap_id,
            "region": region,
            "kind": loc.kind,
            "mapped": mapped,
            "enabled": bool((raw or {}).get("enabled", True)) if raw else False,
            "offset": _target_offset(raw) if raw and mapped else "",
            "target": raw,
        }
        regions.setdefault(region, []).append(item)
    inv = inventory_facts()
    inv_mapped = sum(1 for row in inv if row["mapped"])
    gate = "NO_OFFSETS" if mapped_n == 0 else ("PARTIAL" if mapped_n < len(locations) else "COMPLETE")
    return {
        "regions": regions,
        "mapped": mapped_n,
        "total": len(locations),
        "ap": _ap_ops(),
        "inventory": inv,
        "inventory_mapped": inv_mapped,
        "gate": gate,
        "targets_rev": _mtime(TARGETS_FILE),
    }


def _find_catalog_loc(slug: str):
    for loc in load_catalog():
        if loc.slug == slug or loc.name == slug:
            return loc
    return None


# -- capture session (one at a time; survives page reloads) ----------------


@dataclass
class CaptureSession:
    slug: str = ""
    label: str = ""
    stage: str = "idle"  # idle | baseline | diffed
    pid: Optional[int] = None
    started_at: float = 0.0
    deltas: list[dict[str, Any]] = field(default_factory=list)


_capture = CaptureSession()
_capture_lock = threading.Lock()
_capture_busy = ""  # "baseline" | "diff" | "save" while a dump/write runs


def capture_payload() -> dict[str, Any]:
    s = _capture
    z2o = [d for d in s.deltas if d["old"] == 0 and d["new"] == 1]
    return {
        "id": s.slug,
        "label": s.label,
        "stage": s.stage,
        "busy": _capture_busy,
        "pid": s.pid,
        "age_s": round(time.time() - s.started_at, 1) if s.started_at else 0,
        "delta_count": len(s.deltas),
        "zero_to_one": len(z2o),
        "deltas": s.deltas[:MAX_DELTAS_SENT],
    }


def _snapshot_pid(dest: Path) -> Optional[int]:
    try:
        return int(json.loads((dest / "meta.json").read_text(encoding="utf-8"))["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


@contextmanager
def _busy(what: str) -> Iterator[None]:
    global _capture_busy
    _capture_busy = what
    try:
        yield
    finally:
        _capture_busy = ""


def capture_reset() -> dict[str, Any]:
    global _capture
    with _capture_lock:
        _capture = CaptureSession()
        return {"ok": True, "capture": capture_payload()}


def capture_before(slug: str) -> dict[str, Any]:
    global _capture
    loc = _find_catalog_loc(slug)
    if loc is None:
        raise ValueError(f"unknown location {slug!r}; pick one from the list")
    with _capture_lock, _busy("baseline"):
        dest = take_snapshot(name=SNAP_A)
        time.sleep(0.4)
        take_snapshot(name=SNAP_B)
        _capture = CaptureSession(
            slug=loc.slug,
            label=loc.name,
            stage="baseline",
            pid=_snapshot_pid(dest),
            started_at=time.time(),
        )
    return {"ok": True, "capture": capture_payload()}


def capture_after(slug: str, *, zero_to_one: bool) -> dict[str, Any]:
    with _capture_lock, _busy("diff"):
        s = _capture
        if s.stage == "idle":
            raise ValueError("no baseline yet; take the baseline first")
        if s.slug != slug:
            raise ValueError(f"baseline belongs to {s.label!r}; select it or start over")
        dest = take_snapshot(name=SNAP_C)
        if s.pid is not None and _snapshot_pid(dest) != s.pid:
            raise ValueError("game restarted since the baseline; start over")
        deltas = diff_snapshots(SNAP_B, SNAP_C, stable=SNAP_A, only_zero_to_one=zero_to_one)
        s.deltas = [
            {"section": d.section, "rva": d.rva, "old": d.old, "new": d.new} for d in deltas
        ]
        s.stage = "diffed"
    return {"ok": True, "capture": capture_payload()}


def capture_save(slug: str, rva: Optional[int] = None) -> dict[str, Any]:
    global _capture
    with _capture_lock, _busy("save"):
        s = _capture
        if s.stage != "diffed":
            raise ValueError("nothing to save; take a baseline and diff first")
        if s.slug != slug:
            raise ValueError(f"last diff was for {s.label!r}, not this location; recapture")
        loc = _find_catalog_loc(slug)
        if loc is None:
            raise ValueError(f"unknown location {slug!r}")
        z2o = [d for d in s.deltas if d["old"] == 0 and d["new"] == 1]
        pick = z2o or s.deltas
        if rva is not None:
            pick = [d for d in pick if int(d["rva"]) == int(rva)]
            if not pick:
                raise ValueError(f"0x{int(rva):X} is not one of the diff candidates")
        if len(pick) != 1:
            raise ValueError(
                f"{len(pick)} candidates; pick one row or diff again to narrow it down"
            )
        d = pick[0]
        entry = build_target_entry(
            target_id=loc.slug,
            label=loc.name,
            category="location_flag",
            dtype="uint8",
            offsets=[int(d["rva"])],
            notes=f"dashboard delta {d['old']}->{d['new']} in {d['section']}",
            region=loc.region,
        )
        action, entry = save_target(entry)
        _capture = CaptureSession()
    return {"ok": True, "action": action, "entry": entry, "capture": capture_payload()}


# -- state for the page -----------------------------------------------------


def _event_rows(db_path: Path, since: Optional[int]) -> list[dict[str, Any]]:
    """New ds_client events after ``since``; with no cursor, the last few as history."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if since is None:
            rows = conn.execute(
                """
                SELECT log_id, timestamp, event_type, value_raw, prev_value,
                       target_id, label
                FROM event_logs
                WHERE event_type != 'SESSION'
                ORDER BY log_id DESC
                LIMIT ?
                """,
                (HISTORY_EVENTS,),
            ).fetchall()
            rows = list(reversed(rows))
        else:
            rows = conn.execute(
                """
                SELECT log_id, timestamp, event_type, value_raw, prev_value,
                       target_id, label
                FROM event_logs
                WHERE event_type != 'SESSION' AND log_id > ?
                ORDER BY log_id ASC
                LIMIT 100
                """,
                (since,),
            ).fetchall()
        return [{k: row[k] for k in row.keys()} for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _verified_values(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            str(tid): str(val)
            for tid, val in conn.execute(
                "SELECT target_id, verified_value FROM memory_map WHERE verified_value IS NOT NULL"
            )
        }
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def state_payload(monitor: GameMonitor, db_path: Path, since: Optional[int]) -> dict[str, Any]:
    verified = _verified_values(db_path)
    watches = monitor.watches()
    for w in watches:
        w["verified"] = verified.get(w["id"])
    # No lock: a dump holds it for ~1 s and the poll must not stall behind it.
    capture = capture_payload()
    return {
        "status": monitor.status(),
        "capture": capture,
        "watches": watches,
        "events": _event_rows(db_path, since),
        "history": since is None,
    }


def _make_handler(db_path: Path, monitor: GameMonitor):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:
            url = urlparse(self.path)
            path = url.path
            if path in ("/", "/index.html"):
                body = PAGE_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            try:
                if path == "/api/state":
                    raw = parse_qs(url.query).get("since", [""])[0]
                    since = int(raw) if raw.lstrip("-").isdigit() else None
                    _json_response(self, state_payload(monitor, db_path, since))
                    return
                if path == "/api/status":
                    _json_response(self, monitor.status())
                    return
                if path == "/api/catalog":
                    _json_response(self, catalog_payload())
                    return
                if path == "/api/targets":
                    data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
                    _json_response(self, data)
                    return
                if path == "/api/memory-map-md":
                    if DOCS_PATH.exists():
                        md = DOCS_PATH.read_text(encoding="utf-8")
                    else:
                        md = (
                            "(docs/memory_map.md is not written yet.\n"
                            "Export it after a verified mapping.)"
                        )
                    _json_response(self, {"markdown": md})
                    return
            except (OSError, ValueError, TypeError, KeyError, FileNotFoundError, sqlite3.Error) as exc:
                _json_response(self, {"error": str(exc)}, 500)
                return
            self.send_error(404)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                body = _read_json(self)
                if path == "/api/capture/before":
                    _json_response(self, capture_before(str(body.get("id") or "")))
                    return
                if path == "/api/capture/after":
                    _json_response(
                        self,
                        capture_after(
                            str(body.get("id") or ""),
                            zero_to_one=bool(body.get("zero_to_one", True)),
                        ),
                    )
                    return
                if path == "/api/capture/save":
                    rva = body.get("rva")
                    _json_response(
                        self,
                        capture_save(
                            str(body.get("id") or ""),
                            int(rva) if rva is not None else None,
                        ),
                    )
                    return
                if path == "/api/capture/reset":
                    _json_response(self, capture_reset())
                    return
                if path == "/api/export-docs":
                    out = export_docs(db_path=db_path, out_path=DOCS_PATH)
                    _json_response(self, {"ok": True, "path": str(out)})
                    return
            except (OSError, ValueError, RuntimeError, FileNotFoundError, json.JSONDecodeError) as exc:
                _json_response(self, {"error": str(exc)}, 400)
                return
            self.send_error(404)

    return Handler


def run_dashboard(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    db_path: Path = DB_FILE,
    open_browser: bool = True,
) -> int:
    if not PAGE_PATH.exists():
        print(f"[ERROR] Missing UI file {PAGE_PATH}")
        return 1
    init_db(db_path).close()
    monitor = GameMonitor()
    monitor.start()
    server = ThreadingHTTPServer((host, port), _make_handler(db_path, monitor))
    url = f"http://{host}:{port}/"
    print(f"[OK] Mapping dashboard at {url}")
    print(f"     UI: {PAGE_PATH}")
    print(f"     DB: {db_path.resolve()}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[OK] Dashboard stopped.")
    finally:
        monitor.stop()
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools dashboard",
        description="Mapping dashboard (catalog, guided chest capture, live watch values)",
    )
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--db", type=Path, default=DB_FILE)
    p.add_argument("--no-browser", action="store_true")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return run_dashboard(
        host=args.host,
        port=args.port,
        db_path=args.db,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    raise SystemExit(main())
