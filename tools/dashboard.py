"""Mapping dashboard: catalog, guided chest capture, live watch values.

Serves tools/static/mapping_terminal.html. Not the AP runtime (that is ds_client).

A background GameMonitor owns process attach/detach and read-only live reads,
so HTTP requests never scan the process list. The page polls /api/state.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import sqlite3
import threading
import time
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from subprocess import CalledProcessError
from typing import Any, Iterator, Optional
from urllib.parse import parse_qs, urlparse

import psutil

from ds_client import win32
from ds_client.ap_catalog import (
    BLADE_ITEM,
    GOAL_LABELS,
    PROGRESSIVE_LEVEL_CAPS,
    SHARD_ITEM,
    ApCatalog,
    load_catalog as load_ap_catalog,
)
from ds_client.ap_config import read_config
from ds_client.models import PROCESS_NAME, TARGETS_FILE, WatchTarget, load_targets
from ds_client.sinks import DB_FILE, init_db
from ds_client.watcher import find_process
from tools.export_docs import DOCS_PATH, export_docs
from tools.snapshot import (
    Delta,
    RamCapture,
    describe,
    intersect_deltas,
    offsets_for,
    start_capture,
)
from tools.save_brief import brief_save, default_export_path, export_slot_json
from tools.save_patch import (
    EDITED_DIR,
    copy_into_steam,
    default_edited_path,
    find_war,
    is_steam_save_path,
    patch_sav_userid,
    steam_install_paths,
)
from tools.save_object import (
    diff_sav_slots,
    find_default_sav,
    format_save_object,
    identify_location,
    parse_save_object,
)
from tools.save_patch import occupied_slots
from tools.targets import build_target_entry, find_row, is_identified, is_template, raw_targets, save_target
from tools.world_catalog import is_mapped, load_catalog

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PAGE_PATH = Path(__file__).resolve().parent / "static" / "mapping_terminal.html"

SCAN_PROCESS_SECONDS = 1.0  # psutil.process_iter costs ~200 ms; only while detached
IDLE_TICK_SECONDS = 0.25
MAX_DELTAS_SENT = 200
FOREGROUND_HOLD_S = 7.0
DUMP_HOTKEY_VK = 0x77  # F8
DUMP_HOTKEY_ID = 1
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HISTORY_EVENTS = 8


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
    """Read-only AP config/state (read_config never writes, unlike load_config)."""
    cfg = read_config()
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
        "config_present": cfg.path.exists(),
        "slot": cfg.slot,
        "uri": cfg.uri(),
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
    catalog = load_ap_catalog()
    return [
        _inventory_fact(raw, catalog)
        for raw in raw_targets()
        if _is_item_write_row(raw)
    ]


def _is_item_write_row(raw: dict[str, Any]) -> bool:
    cat = str(raw.get("category") or "")
    event = str(raw.get("event_type") or "")
    label = str(raw.get("label") or "")
    return cat in {"inventory", "stat"} or event == "GOAL" or label in GOAL_LABELS


def _inventory_fact(raw: dict[str, Any], catalog: ApCatalog) -> dict[str, Any]:
    label = str(raw.get("label") or raw.get("id") or "")
    cat = str(raw.get("category") or "")
    event = str(raw.get("event_type") or "")
    dtype = str(raw.get("type") or "")
    mapped = not is_template(raw.get("offsets") or [])
    cap = PROGRESSIVE_LEVEL_CAPS.get(label)
    write = _item_write_kind(label, event, cat, cap, raw.get("bitmask"))
    entry = catalog.item_entry(label)
    return {
        "id": str(raw.get("id") or ""),
        "label": label,
        "category": cat or "misc",
        "event_type": event,
        "dtype": dtype,
        "mapped": mapped,
        "enabled": bool(raw.get("enabled", True)),
        "offset": _target_offset(raw) if mapped else "",
        "write": write,
        "cap": cap,
        "ap_id": entry.ap_id if entry else None,
        "ap_kind": entry.kind if entry else "",
        "apply": _item_apply(label, write, cap, dtype),
        "how": _item_how(label, write, dtype),
        "scan": _item_scan_cmd(label, write),
        "related": _item_related(label),
        "notes": str(raw.get("notes") or ""),
    }


def _item_write_kind(
    label: str,
    event: str,
    cat: str,
    cap: Optional[int],
    bitmask: object,
) -> str:
    if event == "GOAL" or label in GOAL_LABELS:
        return "goal"
    if cap is not None:
        return "level"
    if cat == "stat":
        return "stat"
    if bitmask is not None or label == BLADE_ITEM:
        return "flag"
    return "count"


def _item_apply(label: str, write: str, cap: Optional[int], dtype: str) -> str:
    if write == "goal":
        return "Watch 0→1 sends CLIENT_GOAL. Until this row is mapped, python -m ds_client --send-goal."
    if write == "level":
        return f"Received count becomes this weapon's Level ({dtype}) 1..{cap}. Extra copies past the cap do nothing."
    if write == "flag" and label == BLADE_ITEM:
        return "Written to 1. Also granted once when Armageddon Blade Shards hit 7. Extra copies do nothing if already 1."
    if write == "flag":
        return "Written to 1. Extra copies do nothing if already 1."
    if write == "stat":
        return f"HUD / souls watch ({dtype}). Not an AP ReceivedItems poke unless a matching item exists."
    if label == SHARD_ITEM:
        return "RAM is set to the received shard count. At 7, ds_client also grants Armageddon Blade once (needs that row mapped too)."
    if label in {"Beholder Key", "Heart of the Chosen"}:
        return "RAM is set to the received total. Open: these two may share one Keen inventory slot — test in-game after both are mapped."
    return "RAM is set to the received total. Reconnects cannot duplicate."


def _item_how(label: str, write: str, dtype: str) -> list[str]:
    if write == "goal":
        return [
            "This is a 0→1 watch, not a HUD number. Do not scan it as souls.",
            "Until a real Abaddon flag exists: python -m ds_client --send-goal.",
            "After a real 0→1, save the offset onto this row (RAM DUMP last resort).",
        ]
    if write == "level":
        return [
            f"Game running. HUD must show this weapon's level ({dtype}).",
            "Copy the scan command. Type the number you see.",
            "Upgrade or swap in-game so the number changes. Type the new value until one address remains.",
            "Scan writes offsets onto this row and enables it. ds_client hot-reloads.",
        ]
    if write == "stat":
        return [
            f"Game running. HUD souls ({dtype} — Keen PlayerSaveData.Souls).",
            "python -m tools scan uses this row by default. Type the soul count.",
            "Spend or gain souls. Type the new number until one address remains.",
        ]
    if write == "flag":
        return [
            f"This is a 0/1 flag ({dtype}), not a HUD count.",
            "Only scan if you can see it as 0 then 1. Copy the command if you can.",
            f"{label} still waits until this offset is real — other items are not blocked.",
        ]
    return [
        f"Game running. HUD must show this item's count ({dtype}).",
        "Copy the scan command. Type the number you see.",
        "Change the count in-game. Type the new number until one address remains.",
        "Scan writes offsets onto this row and enables it. ds_client hot-reloads.",
    ]


def _item_scan_cmd(label: str, write: str) -> str:
    if write == "goal":
        return "python -m ds_client --send-goal"
    return f'python -m tools scan --item "{label}"'


def _item_related(label: str) -> list[str]:
    if label == SHARD_ITEM:
        return [BLADE_ITEM]
    if label == BLADE_ITEM:
        return [SHARD_ITEM]
    if label == "Beholder Key":
        return ["Heart of the Chosen"]
    if label == "Heart of the Chosen":
        return ["Beholder Key"]
    return []


def catalog_payload() -> dict[str, Any]:
    locations = load_catalog()
    targets = raw_targets()
    by_id = {str(t.get("id")): t for t in targets}
    by_label = {str(t.get("label")): t for t in targets}
    regions: dict[str, list[dict[str, Any]]] = {}
    mapped_n = 0
    for loc in locations:
        region = loc.area or loc.region or "Other"
        raw = by_id.get(loc.slug) or by_label.get(loc.name)
        mapped = is_mapped(loc, targets)
        identified = is_identified(raw) if raw else False
        save_obj = parse_save_object((raw or {}).get("save_object")) if raw else None
        if mapped:
            mapped_n += 1
        item = {
            "id": loc.slug,
            "label": loc.name,
            "ap_id": loc.ap_id,
            "region": region,
            "ap_region": loc.region,
            "kind": loc.kind,
            "vanilla_item": loc.vanilla_item,
            "in_ap": loc.in_ap,
            "mapped": mapped,
            "identified": identified,
            "save_key": format_save_object(save_obj) if save_obj else "",
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


def _sav_from(path_raw: object) -> Path:
    sav = Path(str(path_raw)) if path_raw else find_default_sav()
    if sav is None or not sav.is_file():
        raise ValueError("no .sav path")
    return sav


def _public_brief(info: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in info.items() if k != "true_flags"}


# -- capture session (one at a time; survives page reloads) ----------------


@dataclass
class CaptureSession:
    slug: str = ""
    label: str = ""
    stage: str = "idle"  # idle | baseline | diffed
    pid: Optional[int] = None
    started_at: float = 0.0
    deltas: list[dict[str, Any]] = field(default_factory=list)
    raw_zero_to_one: int = 0
    ram: Optional[RamCapture] = None  # baseline held in memory between steps
    scope: str = ""  # describe(ram.stats): heap anchors or module .data
    wait: str = ""  # "" | "baseline" | "diff"
    hold_s: float = 0.0
    foreground: bool = False
    last_error: str = ""


_capture = CaptureSession()
_capture_lock = threading.Lock()
_capture_busy = ""  # "baseline" | "diff" | "save" while a dump/write runs
_foreground_since: Optional[float] = None
_firing = False
_hotkey_ok = False
_aux_stop = threading.Event()
_aux_threads: list[threading.Thread] = []
_hotkey_tid = 0


def game_is_foreground() -> bool:
    """True only when darksiders1.exe owns the foreground window."""
    pid = win32.foreground_pid()
    if not pid:
        return False
    try:
        name = psutil.Process(pid).name()
    except (psutil.Error, OSError):
        return False
    return bool(name) and name.lower() == PROCESS_NAME.lower()


def capture_payload() -> dict[str, Any]:
    s = _capture
    z2o = [d for d in s.deltas if d["old"] == 0 and d["new"] == 1]
    n = len(z2o)
    return {
        "id": s.slug,
        "label": s.label,
        "stage": s.stage,
        "busy": _capture_busy,
        "wait": s.wait,
        "hold_s": round(s.hold_s, 1),
        "foreground": s.foreground,
        "pid": s.pid,
        "age_s": round(time.time() - s.started_at, 1) if s.started_at else 0,
        "delta_count": len(s.deltas),
        "zero_to_one": n,
        "raw_zero_to_one": s.raw_zero_to_one,
        "scope": s.scope,
        "hotkey": "F8" if _hotkey_ok else "",
        "error": s.last_error,
        "deltas": s.deltas[:MAX_DELTAS_SENT],
    }


@contextmanager
def _busy(what: str) -> Iterator[None]:
    global _capture_busy
    _capture_busy = what
    try:
        yield
    finally:
        _capture_busy = ""


def capture_reset() -> dict[str, Any]:
    global _capture, _foreground_since
    with _capture_lock:
        _capture = CaptureSession()
        _foreground_since = None
        return {"ok": True, "capture": capture_payload()}


def _require_game_front() -> None:
    if not game_is_foreground():
        raise ValueError(
            "Darksiders is not in front — click the game, unpause (Esc), then press F8"
        )


def capture_select(slug: str) -> dict[str, Any]:
    loc = _find_catalog_loc(slug)
    if loc is None:
        raise ValueError(f"unknown location {slug!r}; pick one from the list")
    with _capture_lock:
        if _capture.stage == "idle" and not _capture.wait:
            _capture.slug = loc.slug
            _capture.label = loc.name
            _capture.last_error = ""
        return {"ok": True, "capture": capture_payload()}


def capture_arm(slug: str, kind: str) -> dict[str, Any]:
    """Arm a dump that fires after Darksiders stays in front for FOREGROUND_HOLD_S."""
    global _foreground_since
    if kind not in ("baseline", "diff"):
        raise ValueError("kind must be baseline or diff")
    loc = _find_catalog_loc(slug)
    if loc is None:
        raise ValueError(f"unknown location {slug!r}; pick one from the list")
    with _capture_lock:
        if kind == "diff":
            if _capture.stage == "idle":
                raise ValueError("no baseline yet; take the baseline first")
            if _capture.slug != loc.slug:
                raise ValueError(f"baseline belongs to {_capture.label!r}; select it or start over")
        elif _capture.stage != "idle" and _capture.slug and _capture.slug != loc.slug:
            raise ValueError(f"a capture is open for {_capture.label!r}; start over first")
        _capture.slug = loc.slug
        _capture.label = loc.name
        _capture.wait = kind
        _capture.hold_s = FOREGROUND_HOLD_S
        _capture.foreground = False
        _capture.last_error = ""
        _foreground_since = None
        return {"ok": True, "capture": capture_payload()}


def capture_before(slug: str, *, require_foreground: bool = False) -> dict[str, Any]:
    global _capture
    if require_foreground:
        _require_game_front()
    loc = _find_catalog_loc(slug)
    if loc is None:
        raise ValueError(f"unknown location {slug!r}; pick one from the list")
    save_object = parse_save_object((find_row(loc.name) or {}).get("save_object"))
    with _capture_lock, _busy("baseline"):
        ram = start_capture(save_object)
        _capture = CaptureSession(
            slug=loc.slug,
            label=loc.name,
            stage="baseline",
            pid=ram.pid,
            started_at=time.time(),
            ram=ram,
            scope=describe(ram.stats),
        )
    return {"ok": True, "capture": capture_payload()}


def capture_after(slug: str, *, require_foreground: bool = False) -> dict[str, Any]:
    if require_foreground:
        _require_game_front()
    with _capture_lock, _busy("diff"):
        s = _capture
        if s.stage == "idle":
            raise ValueError("no baseline yet; take the baseline first")
        if s.slug != slug:
            raise ValueError(f"baseline belongs to {s.label!r}; select it or start over")
        if s.ram is None:
            raise ValueError("baseline was lost (dashboard restarted); start over")
        deltas = s.ram.after()  # also refuses if the game restarted
        raw_n = len(deltas)
        if s.stage == "diffed" and s.deltas:
            # DIFF AGAIN narrows: keep only candidates that survived every diff.
            deltas = intersect_deltas([_delta(d) for d in s.deltas], deltas)
        s.deltas = [_delta_json(d) for d in deltas]
        s.raw_zero_to_one = raw_n
        s.stage = "diffed"
        s.wait = ""
        s.hold_s = 0.0
        s.last_error = ""
    return {"ok": True, "capture": capture_payload()}


def _delta_json(d: Delta) -> dict[str, Any]:
    return {"section": d.section, "address": d.address, "rva": d.rva, "old": d.old, "new": d.new}


def _delta(d: dict[str, Any]) -> Delta:
    rva = d.get("rva")
    return Delta(str(d["section"]), int(d["address"]), int(d["old"]), int(d["new"]), None if rva is None else int(rva))


def capture_save(slug: str, address: Optional[int] = None) -> dict[str, Any]:
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
        pick = s.deltas
        if address is not None:
            pick = [d for d in pick if int(d["address"]) == int(address)]
            if not pick:
                raise ValueError(f"0x{int(address):X} is not one of the diff candidates")
        if len(pick) != 1:
            raise ValueError(
                f"{len(pick)} candidates; pick one row or diff again to narrow it down"
            )
        d = _delta(pick[0])
        offsets = offsets_for(d, s.pid)  # heap bytes need a static pointer chain
        entry = build_target_entry(
            target_id=loc.slug,
            label=loc.name,
            category="location_flag",
            dtype="uint8",
            offsets=offsets,
            notes=f"dashboard 0->1 in {d.section}" + ("" if d.rva is not None else f" (heap 0x{d.address:X}, pointer chain)"),
            region=loc.region,
        )
        action, entry = save_target(entry)
        _capture = CaptureSession()
    return {"ok": True, "action": action, "entry": entry, "capture": capture_payload()}


def capture_dump_now(*, require_foreground: bool = True) -> dict[str, Any]:
    """Dump the armed/next step. F8 uses this while the game is in front."""
    if _firing or _capture_busy:
        return {"ok": True, "capture": capture_payload()}
    with _capture_lock:
        kind = _capture.wait or (
            "diff" if _capture.stage in ("baseline", "diffed") else "baseline"
        )
        slug = _capture.slug
    if not slug:
        raise ValueError("pick a location first")
    if kind == "baseline":
        return capture_before(slug, require_foreground=require_foreground)
    return capture_after(slug, require_foreground=require_foreground)


def _fire_wait() -> None:
    global _firing, _foreground_since
    if _firing or _capture_busy:
        return
    with _capture_lock:
        kind = _capture.wait
        slug = _capture.slug
    if not kind or not slug:
        return
    _firing = True
    try:
        if kind == "baseline":
            capture_before(slug, require_foreground=True)
        else:
            capture_after(slug, require_foreground=True)
    except ValueError as exc:
        with _capture_lock:
            _capture.last_error = str(exc)
        _foreground_since = None
    finally:
        _firing = False


def _wait_loop() -> None:
    global _foreground_since
    while not _aux_stop.wait(0.1):
        with _capture_lock:
            waiting = bool(_capture.wait)
        if not waiting:
            _foreground_since = None
            continue
        fg = game_is_foreground()
        now = time.monotonic()
        ready = False
        with _capture_lock:
            _capture.foreground = fg
            if not fg:
                _foreground_since = None
                _capture.hold_s = FOREGROUND_HOLD_S
            else:
                if _foreground_since is None:
                    _foreground_since = now
                held = now - _foreground_since
                _capture.hold_s = max(0.0, FOREGROUND_HOLD_S - held)
                ready = held >= FOREGROUND_HOLD_S
        if ready:
            _fire_wait()


def _hotkey_dump() -> None:
    try:
        capture_dump_now(require_foreground=True)
    except ValueError as exc:
        with _capture_lock:
            _capture.last_error = str(exc)


def _hotkey_loop() -> None:
    global _hotkey_ok, _hotkey_tid
    user32 = win32.user32
    user32.RegisterHotKey.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.c_int,
        ctypes.wintypes.UINT,
        ctypes.wintypes.UINT,
    ]
    user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(ctypes.wintypes.MSG),
        ctypes.wintypes.HWND,
        ctypes.wintypes.UINT,
        ctypes.wintypes.UINT,
    ]
    user32.GetMessageW.restype = ctypes.c_int
    _hotkey_tid = int(ctypes.windll.kernel32.GetCurrentThreadId())
    if not user32.RegisterHotKey(None, DUMP_HOTKEY_ID, MOD_NOREPEAT, DUMP_HOTKEY_VK):
        err = ctypes.get_last_error()
        print(f"[WARN] F8 dump hotkey unavailable (RegisterHotKey error {err})")
        _hotkey_ok = False
        return
    _hotkey_ok = True
    print("[OK] F8 dumps while Darksiders is in front (no dashboard click)")
    msg = ctypes.wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY and int(msg.wParam) == DUMP_HOTKEY_ID:
                _hotkey_dump()
    finally:
        user32.UnregisterHotKey(None, DUMP_HOTKEY_ID)
        _hotkey_ok = False


def start_capture_aux() -> None:
    global _aux_threads
    _aux_stop.clear()
    wait_t = threading.Thread(target=_wait_loop, name="capture-wait", daemon=True)
    hot_t = threading.Thread(target=_hotkey_loop, name="capture-f8", daemon=True)
    _aux_threads = [wait_t, hot_t]
    wait_t.start()
    hot_t.start()


def stop_capture_aux() -> None:
    _aux_stop.set()
    if _hotkey_tid:
        ctypes.windll.user32.PostThreadMessageW(_hotkey_tid, WM_QUIT, 0, 0)
    for t in _aux_threads:
        t.join(timeout=1.5)


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
                if path == "/api/save-slots":
                    raw_path = parse_qs(url.query).get("path", [""])[0]
                    sav = Path(raw_path) if raw_path else find_default_sav()
                    if sav is None or not sav.is_file():
                        _json_response(self, {"path": "", "slots": []})
                        return
                    _json_response(self, {"path": str(sav), "slots": occupied_slots(sav)})
                    return
                if path == "/api/save-install-preview":
                    q = parse_qs(url.query)
                    userid = int(q.get("userid", [""])[0])
                    name = str(q.get("name", ["svd_fmt_0_0.sav"])[0] or "svd_fmt_0_0.sav")
                    dests = steam_install_paths(userid, name)
                    _json_response(
                        self,
                        {
                            "userid": userid,
                            "dests": [str(p) for p in dests],
                            "attached": bool(monitor.status().get("attached")),
                        },
                    )
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
                    _json_response(self, capture_after(str(body.get("id") or "")))
                    return
                if path == "/api/capture/arm":
                    _json_response(
                        self,
                        capture_arm(str(body.get("id") or ""), str(body.get("kind") or "")),
                    )
                    return
                if path == "/api/capture/select":
                    _json_response(self, capture_select(str(body.get("id") or "")))
                    return
                if path == "/api/capture/dump":
                    _json_response(self, capture_dump_now(require_foreground=True))
                    return
                if path == "/api/capture/save":
                    address = body.get("address")
                    _json_response(
                        self,
                        capture_save(
                            str(body.get("id") or ""),
                            int(address) if address is not None else None,
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
                if path == "/api/save-brief":
                    sav = _sav_from(body.get("path"))
                    slot = int(body.get("slot"))
                    info = _public_brief(brief_save(sav, slot))
                    _json_response(self, {"path": str(sav), "brief": info})
                    return
                if path == "/api/save-brief-all":
                    sav = _sav_from(body.get("path"))
                    briefs = []
                    for slot in occupied_slots(sav):
                        briefs.append(_public_brief(brief_save(sav, slot)))
                    _json_response(self, {"path": str(sav), "briefs": briefs})
                    return
                if path == "/api/save-export":
                    sav = _sav_from(body.get("path"))
                    slot = int(body.get("slot"))
                    dest_raw = str(body.get("dest") or "")
                    dest = Path(dest_raw) if dest_raw else default_export_path(slot)
                    out = export_slot_json(sav, slot, dest)
                    _json_response(self, {"ok": True, "path": str(out), "slot": slot})
                    return
                if path == "/api/save-diff":
                    loc = _find_catalog_loc(str(body.get("id") or ""))
                    if loc is None:
                        raise ValueError("pick a location first")
                    sav = _sav_from(body.get("path"))
                    result = diff_sav_slots(sav, int(body.get("before")), int(body.get("after")), loc)
                    result["id"] = loc.slug
                    result["label"] = loc.name
                    _json_response(self, result)
                    return
                if path == "/api/save-diff/save":
                    loc = _find_catalog_loc(str(body.get("id") or ""))
                    if loc is None:
                        raise ValueError("pick a location first")
                    action, entry = identify_location(loc, body)
                    _json_response(self, {"ok": True, "action": action, "entry": entry})
                    return
                if path == "/api/save-encode":
                    sav = _sav_from(body.get("path"))
                    userid = int(body.get("userid"))
                    dest = Path(str(body.get("out"))) if body.get("out") else default_edited_path(sav)
                    dest = dest.resolve()
                    edited_root = EDITED_DIR.resolve()
                    if dest.parent != edited_root:
                        raise ValueError("encode dest must be under saves/edited/")
                    if is_steam_save_path(dest):
                        raise ValueError(
                            "encode writes saves/edited/, not Steam. Use INSTALL after encode."
                        )
                    old = patch_sav_userid(sav, userid, dest, find_war())
                    _json_response(
                        self,
                        {
                            "ok": True,
                            "old": old,
                            "userid": userid,
                            "path": str(dest),
                            "note": "war rewrote autosave only. slots 0–9 unchanged.",
                        },
                    )
                    return
                if path == "/api/save-install":
                    if str(body.get("confirm") or "") != "INSTALL":
                        raise ValueError('confirm must be the string INSTALL')
                    if monitor.status().get("attached") and not body.get("force"):
                        raise ValueError(
                            "darksiders1.exe is attached — quit the game fully, then INSTALL"
                        )
                    patched = _sav_from(body.get("path"))
                    userid = int(body.get("userid"))
                    if is_steam_save_path(patched) and not body.get("force"):
                        raise ValueError(
                            "source looks like the live Steam file. Encode to saves/edited/ first."
                        )
                    dests = copy_into_steam(patched, userid)
                    _json_response(
                        self,
                        {
                            "ok": True,
                            "copied": [str(p) for p in dests],
                            "note": "Launch from Steam. Load Game.",
                        },
                    )
                    return
            except (
                OSError,
                ValueError,
                RuntimeError,
                FileNotFoundError,
                json.JSONDecodeError,
                CalledProcessError,
            ) as exc:
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
    start_capture_aux()
    server = ThreadingHTTPServer((host, port), _make_handler(db_path, monitor))
    url = f"http://{host}:{port}/"
    print(f"[OK] Mapping dashboard at {url}")
    print(f"     UI: {PAGE_PATH}")
    print(f"     DB: {db_path.resolve()}")
    print("     Workspace: SAVE DIFF · RAM DUMP · SAVES (encode to edited/, then INSTALL).")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[OK] Dashboard stopped.")
    finally:
        stop_capture_aux()
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
