"""Diff-based value scanner for HUD numbers (souls, item counts).

Finds a changing value (a float / int that moves when you kill or spend)
*without* typing exact HUD numbers — Cheat-Engine style "unknown initial
value" plus increased / decreased / unchanged / changed refinement.

    python -m tools scan --item Soul_Count --diff

Unlike exact-value ``scan``, this snapshots every writable slot of the chosen
width, then narrows by *how* it changed between two moments. Souls is a float;
use this when the exact HUD number is unreadable or does not match the stored
float bit-for-bit.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

import numpy as np

from runtime.mem import win32
from runtime.mem.models import PROCESS_NAME, TYPE_SPECS
from runtime.mem.watcher import find_process
from tools.scanner import _emit_result, _entry, _pointer_paths, _require_pymemoryeditor
from tools.snapshot import CHUNK, module_regions

# dtype name -> numpy dtype string (signedness preserved for </> comparisons).
_NUMPY_DTYPE: dict[str, str] = {
    "bool": "u1",
    "uint8": "u1",
    "int8": "i1",
    "uint16": "u2",
    "int16": "i2",
    "uint32": "u4",
    "int32": "i4",
    "uint64": "u8",
    "int64": "i8",
    "float": "f4",
    "double": "f8",
}

_FLOAT_TYPES = frozenset({"float", "double"})
MAX_SHOW = 32


@dataclass(frozen=True)
class SlotRegion:
    """A contiguous writable region, decoded as ``width``-byte slots."""

    address: int
    size: int  # bytes
    rva: Optional[int]  # module-relative start, or None on the heap
    width: int
    dtype: str


def enumerate_regions(handle, dtype: str) -> list[SlotRegion]:
    """Writable memory only: private heaps + the game module's writable PE
    sections. Read-only memory never changes, so it is not a diff candidate."""
    width, _fmt = TYPE_SPECS[dtype]
    base = win32.get_module_base(handle, PROCESS_NAME)
    regions: list[SlotRegion] = []
    for addr, size in win32.private_rw_regions(handle):
        regions.append(SlotRegion(addr, size, None, width, dtype))
    for r in module_regions(handle, base):
        regions.append(SlotRegion(r.address, r.size, r.rva, width, dtype))
    regions.sort(key=lambda r: r.address)
    return regions


def _read_slots(handle, region: SlotRegion) -> Optional[np.ndarray]:
    """One typed array of all width-aligned slots in ``region``, or None if any
    page vanished (freed heap block)."""
    width = region.width
    n = region.size // width
    total = n * width
    buf = np.empty(total, dtype=np.uint8)
    pos = 0
    while pos < total:
        chunk = min(CHUNK, total - pos)
        raw = win32.read_memory(handle, region.address + pos, chunk)
        if raw is None:
            return None
        buf[pos : pos + chunk] = np.frombuffer(raw, dtype=np.uint8)
        pos += chunk
    return buf.view(_NUMPY_DTYPE[region.dtype])


def _snapshot(handle, regions: list[SlotRegion]) -> list[Optional[np.ndarray]]:
    return [_read_slots(handle, r) for r in regions]


def _initial_mask(values: list[Optional[np.ndarray]], dtype: str) -> list[Optional[np.ndarray]]:
    """Every finite slot is a candidate (NaN slots are not a plausible HUD number)."""
    masks: list[Optional[np.ndarray]] = []
    for v in values:
        if v is None:
            masks.append(None)
        elif dtype in _FLOAT_TYPES:
            masks.append(np.isfinite(v))
        else:
            masks.append(np.ones(v.shape, dtype=bool))
    return masks


def _count(masks: list[Optional[np.ndarray]]) -> int:
    return sum(int(np.count_nonzero(m)) for m in masks if m is not None)


def _refine(
    prev: list[Optional[np.ndarray]],
    cur: list[Optional[np.ndarray]],
    masks: list[Optional[np.ndarray]],
    action: str,
    dtype: str,
) -> tuple[list[Optional[np.ndarray]], int]:
    """Keep candidate slots whose value changed as ``action`` describes, relative
    to the previous snapshot."""
    out: list[Optional[np.ndarray]] = []
    count = 0
    for p, c, m in zip(prev, cur, masks):
        if p is None or c is None or m is None or not m.any() or p.shape != c.shape:
            out.append(None)
            continue
        if action == "+":
            keep = c > p
        elif action == "-":
            keep = c < p
        elif action == "~":
            keep = c == p
        elif action == "c":
            keep = c != p
        else:
            raise ValueError(f"unknown diff action {action!r}")
        if dtype in _FLOAT_TYPES and action != "~":
            # NaN is never <, >, or ==; drop non-finite slots so "changed"
            # does not latch onto NaN bit patterns.
            keep = keep & np.isfinite(c) & np.isfinite(p)
        keep = keep & m
        out.append(keep)
        count += int(np.count_nonzero(keep))
    return out, count


def _exact_filter(
    cur: list[Optional[np.ndarray]],
    masks: list[Optional[np.ndarray]],
    value: int | float,
    dtype: str,
) -> tuple[list[Optional[np.ndarray]], int]:
    out: list[Optional[np.ndarray]] = []
    count = 0
    for c, m in zip(cur, masks):
        if c is None or m is None:
            out.append(None)
            continue
        if dtype in _FLOAT_TYPES:
            # HUD shows an integer; the stored float is usually within ±0.5 of it.
            keep = (np.abs(c - value) <= 0.5) & m
        else:
            keep = (c == value) & m
        out.append(keep)
        count += int(np.count_nonzero(keep))
    return out, count


def _materialize(regions: list[SlotRegion], masks: list[Optional[np.ndarray]]) -> list[tuple[int, Optional[int]]]:
    """Candidate slots as ``(address, module_rva_or_None)``."""
    out: list[tuple[int, Optional[int]]] = []
    for r, m in zip(regions, masks):
        if m is None:
            continue
        for idx in np.nonzero(m)[0].tolist():
            addr = r.address + int(idx) * r.width
            rva = None if r.rva is None else r.rva + int(idx) * r.width
            out.append((addr, rva))
    return out


def _live(handle, addr: int, dtype: str) -> str:
    width, fmt = TYPE_SPECS[dtype]
    raw = win32.read_memory(handle, addr, width)
    if raw is None:
        return "<unreadable>"
    value = struct.unpack("<" + fmt, raw)[0]
    return repr(value) if dtype in _FLOAT_TYPES or isinstance(value, bool) else str(value)


def _show(handle, regions: list[SlotRegion], masks: list[Optional[np.ndarray]], dtype: str) -> None:
    cands = _materialize(regions, masks)
    if not cands:
        print("[-] No candidates.")
        return
    print(f"[*] {len(cands)} candidate(s):")
    for i, (addr, rva) in enumerate(cands[:MAX_SHOW], start=1):
        where = f"{PROCESS_NAME} + 0x{rva:X}" if rva is not None else f"heap 0x{addr:X}"
        print(f"  [{i}] 0x{addr:X}  live={_live(handle, addr, dtype)}  => {where}")
    if len(cands) > MAX_SHOW:
        print(f"  … {len(cands) - MAX_SHOW} more")


def _finalize(pid: int, row: dict, addr: int, rva: Optional[int], *, dry_run: bool) -> int:
    """Save one candidate: module-relative RVA directly, else a static pointer chain."""
    if rva is not None:
        _emit_result(_entry(row, PROCESS_NAME, [rva], f"diff-scanned absolute 0x{addr:X}"), dry_run=dry_run)
        return 0

    _require_pymemoryeditor()
    from PyMemoryEditor import OpenProcess

    with OpenProcess(pid=pid) as process:
        paths = _pointer_paths(process, addr, PROCESS_NAME)
    if not paths:
        print(
            f"[-] No static pointer path to heap 0x{addr:X} (depth 3). "
            "Its address changes every launch, so it cannot be saved yet."
        )
        return 1
    path = paths[0]
    chain = [int(path.module_offset), *[int(o) for o in path.offsets]]
    _emit_result(
        _entry(row, path.module or PROCESS_NAME, chain, f"diff-scanned pointer path to 0x{addr:X}"),
        dry_run=dry_run,
    )
    return 0


def run_diff_scan(row: dict, *, dry_run: bool = False) -> int:
    dtype = str(row.get("type") or "float")
    if dtype not in TYPE_SPECS or dtype not in _NUMPY_DTYPE:
        print(f"[ERROR] unsupported type {dtype!r}; choose from {sorted(TYPE_SPECS)}")
        return 1
    width, _fmt = TYPE_SPECS[dtype]

    pid = find_process(PROCESS_NAME)
    if pid is None:
        print(
            f"[ERROR] Process {PROCESS_NAME!r} is not running.\n"
            "        Launch Darksiders Warmastered (Steam x64), get in-game, then retry."
        )
        return 1

    handle = win32.open_process(pid, write=False)
    try:
        regions = enumerate_regions(handle, dtype)
        total_mb = sum(r.size for r in regions) / 2**20
        slots = sum(r.size // width for r in regions)
        print(f"[*] Diff scan for {row['label']!r} ({dtype}, {width} bytes)")
        print(f"[*] Attached PID {pid}; {len(regions)} writable region(s), {total_mb:.0f} MB, {slots:,} slots")

        prev = _snapshot(handle, regions)
        masks = _initial_mask(prev, dtype)
        candidates = _count(masks)
        print(f"[+] Baseline: {candidates:,} candidate slot(s)")

        print(
            "\nChange the value in-game (kill something / spend souls), then say how it\n"
            "changed compared to the last snapshot:\n"
            "  + increased   - decreased   ~ unchanged   c changed\n"
            "  = exact HUD value (e.g. = 191)   s show   r re-baseline   q quit\n"
            "Type a candidate number (1, 2, …) to select and save it."
        )

        while True:
            prompt = f"[?] {candidates:,} candidate(s). Action: "
            action = input(prompt).strip()

            if action in {"q", "quit"}:
                break
            if action in {"r", "reset"}:
                prev = _snapshot(handle, regions)
                masks = _initial_mask(prev, dtype)
                candidates = _count(masks)
                print(f"[*] Re-baselined: {candidates:,} candidate(s)")
                continue
            if action in {"s", "show"}:
                if candidates > MAX_SHOW:
                    print(f"[-] {candidates:,} candidates — too many to list; narrow it down first.")
                else:
                    _show(handle, regions, masks, dtype)
                continue

            # Number selection is only meaningful once the list is short.
            if action.isdigit() and candidates <= MAX_SHOW:
                cands = _materialize(regions, masks)
                n = int(action)
                if 1 <= n <= len(cands):
                    addr, rva = cands[n - 1]
                    return _finalize(pid, row, addr, rva, dry_run=dry_run)
                print(f"[-] no such candidate (1..{len(cands)})")
                continue

            if action == "=" or action.startswith("="):
                raw = action[1:].strip()
                if not raw:
                    raw = input("Value right now: ").strip()
                try:
                    value: int | float = float(raw) if dtype in _FLOAT_TYPES else int(raw, 0)
                except ValueError:
                    print(f"[-] bad number {raw!r}; use = 191 (value on the same line)")
                    continue
                cur = _snapshot(handle, regions)
                masks, candidates = _exact_filter(cur, masks, value, dtype)
                prev = cur
                print(f"[+] exact match: {candidates:,} candidate(s)")
            elif action in {"+", "-", "~", "c"}:
                cur = _snapshot(handle, regions)
                masks, candidates = _refine(prev, cur, masks, action, dtype)
                prev = cur
                print(f"[+] after {action!r}: {candidates:,} candidate(s)")
            else:
                print("[-] unknown action; use + - ~ c = s r q, or a candidate number")
                continue

            if candidates == 0:
                print("[-] All candidates eliminated. Re-baseline (r) or restart the scan.")
            elif candidates <= MAX_SHOW:
                _show(handle, regions, masks, dtype)
    finally:
        win32.close_handle(handle)

    if candidates == 1:
        addr, rva = _materialize(regions, masks)[0]
        return _finalize(pid, row, addr, rva, dry_run=dry_run)
    if candidates == 0:
        print("[-] No candidates left.")
        return 1
    print(f"[-] {candidates:,} candidate(s) remain; refine further or pick one. Not saved.")
    return 1
