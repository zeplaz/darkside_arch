"""Live mapping terminal over real catalog, snapshots, and SQLite.

Serves tools/static/mapping_terminal.html. Not a simulation.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from ds_client import win32
from ds_client.models import PROCESS_NAME, TARGETS_FILE
from ds_client.sinks import (
    DB_FILE,
    init_db,
    sync_memory_map_from_targets,
    telemetry_snapshot,
)
from ds_client.watcher import find_process
from tools.export_docs import DOCS_PATH, export_docs
from tools.scanner import build_target_entry, upsert_target
from tools.snapshot import diff_snapshots, take_snapshot
from tools.world_catalog import _raw_targets, is_mapped, load_catalog

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PAGE_PATH = Path(__file__).resolve().parent / "static" / "mapping_terminal.html"

_last_deltas: list[dict[str, Any]] = []
_last_slug = ""
_DASH = f"_dash_{os.getpid()}"


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


def process_status() -> dict[str, Any]:
    pid = find_process()
    base: Optional[int] = None
    if pid is not None:
        try:
            handle = win32.open_process(pid)
            try:
                base = win32.get_module_base(handle, PROCESS_NAME)
            finally:
                win32.close_handle(handle)
        except OSError:
            pass
    return {
        "attached": pid is not None,
        "pid": pid,
        "process": PROCESS_NAME,
        "module_base": f"0x{base:X}" if base else None,
    }


def _target_offset(raw: dict) -> str:
    offs = raw.get("offsets") or []
    if not offs:
        return ""
    chain = " -> ".join(str(o) for o in offs)
    return f"{raw.get('module') or PROCESS_NAME} + {chain}"


def catalog_payload() -> dict[str, Any]:
    locations = load_catalog()
    targets = _raw_targets()
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
            "offset": _target_offset(raw) if raw and mapped else "",
            "value": (raw or {}).get("notes", ""),
        }
        regions.setdefault(region, []).append(item)
    return {
        "regions": regions,
        "mapped": mapped_n,
        "total": len(locations),
        "status": process_status(),
    }


def _find_catalog_loc(slug: str):
    for loc in load_catalog():
        if loc.slug == slug or loc.name == slug:
            return loc
    return None


def capture_before(slug: str) -> dict[str, Any]:
    take_snapshot(name=f"{_DASH}_a")
    time.sleep(0.4)
    take_snapshot(name=f"{_DASH}_b")
    return {"ok": True, "id": slug, "snapshots": [f"{_DASH}_a", f"{_DASH}_b"]}


def capture_after(slug: str, *, zero_to_one: bool) -> dict[str, Any]:
    global _last_deltas, _last_slug
    take_snapshot(name=f"{_DASH}_c")
    deltas = diff_snapshots(
        f"{_DASH}_b", f"{_DASH}_c", stable=f"{_DASH}_a", only_zero_to_one=zero_to_one
    )
    _last_slug = slug
    _last_deltas = [
        {"section": d.section, "rva": d.rva, "old": d.old, "new": d.new} for d in deltas
    ]
    z2o = sum(1 for d in _last_deltas if d["old"] == 0 and d["new"] == 1)
    return {"ok": True, "id": slug, "deltas": _last_deltas, "zero_to_one": z2o}


def capture_save(slug: str) -> dict[str, Any]:
    loc = _find_catalog_loc(slug)
    if loc is None:
        raise ValueError(f"unknown location {slug!r}")
    z2o = [d for d in _last_deltas if d["old"] == 0 and d["new"] == 1]
    pick = z2o if len(z2o) == 1 else _last_deltas
    if _last_slug and _last_slug != loc.slug:
        raise ValueError("last diff was for a different location; recapture")
    if len(pick) != 1:
        raise ValueError(
            f"need exactly 1 candidate (have {len(pick)}, {len(z2o)} were 0->1)"
        )
    d = pick[0]
    entry = build_target_entry(
        target_id=loc.slug,
        label=loc.name,
        category="location_flag",
        dtype="uint8",
        module=PROCESS_NAME,
        offsets=[int(d["rva"])],
        notes=f"dashboard delta {d['old']}->{d['new']} in {d['section']}",
        region=loc.region,
    )
    action = upsert_target(entry)
    from ds_client.models import load_targets

    _, targets = load_targets()
    conn = init_db()
    try:
        sync_memory_map_from_targets(conn, targets)
    finally:
        conn.close()
    return {"ok": True, "action": action, "entry": entry}


def _make_handler(db_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                body = PAGE_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            try:
                if path == "/api/status":
                    _json_response(self, process_status())
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
                            "Use Write docs/memory_map.md after a verified mapping.)"
                        )
                    _json_response(self, {"markdown": md})
                    return
                if path == "/api/telemetry":
                    conn = init_db(db_path)
                    try:
                        payload = telemetry_snapshot(conn)
                    finally:
                        conn.close()
                    payload["status"] = process_status()
                    _json_response(self, payload)
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
                    _json_response(self, capture_save(str(body.get("id") or "")))
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
    server = ThreadingHTTPServer((host, port), _make_handler(db_path))
    url = f"http://{host}:{port}/"
    print(f"[OK] Mapping terminal at {url}")
    print(f"     UI: {PAGE_PATH}")
    print(f"     DB: {db_path.resolve()}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[OK] Dashboard stopped.")
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools dashboard",
        description="Live mapping terminal (catalog + snapshot wizard + SQLite)",
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
