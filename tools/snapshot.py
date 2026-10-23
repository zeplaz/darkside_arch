"""RAM capture for location flags: baseline samples -> open it in-game -> after samples.

Two scopes:

* ``heap`` (used when the targets.json row has a ``save_object``): scan the game's
  private read-write memory for the Keen identity — the ObjectID dword with the
  RegionID and LayerID dwords close by — and diff only small windows around those
  anchors. Chest WorldObjects live on the heap; they are not in the module image.
* ``module``: the game's writable PE sections (.data/.bss). Static addresses, but
  ~34 MB where opening a chest flips ~1,500 unrelated bytes. Kept for rows that
  have no ``save_object`` yet.

A candidate must be 0 in every baseline sample and 1 in every after sample, so
bytes that tick on either side are dropped. Exact-value ``tools scan`` is for
known HUD numbers (souls).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import numpy as np

from ds_client import win32
from ds_client.models import PROCESS_NAME
from ds_client.watcher import find_process

SNAPSHOT_DIR = Path("snapshots")
DEBUG_DUMP = SNAPSHOT_DIR / "last_capture.npz"
CHUNK = 64 * 1024
SCAN_CHUNK = 16 * 1024 * 1024
IMAGE_SCN_MEM_WRITE = 0x80000000

ANCHOR_SPAN = 0x40  # RegionID / LayerID must sit within this many bytes of the ObjectID
WINDOW = 0x400  # bytes diffed on each side of an anchor
MAX_ANCHORS = 4096
BASELINE_SAMPLES = 5
BASELINE_WINDOW_S = 4.0  # long enough to catch slow tickers, not just per-frame ones
AFTER_SAMPLES = 3
AFTER_WINDOW_S = 1.5  # the flag must stay 1 while popups / animations settle

Sleep = Callable[[float], None]


@dataclass(frozen=True)
class Region:
    label: str  # ".data", ".bss", "heap"
    address: int  # absolute, this session only
    size: int
    rva: Optional[int] = None  # module-relative start; None on the heap


@dataclass(frozen=True)
class Delta:
    section: str
    address: int
    old: int
    new: int
    rva: Optional[int] = None  # set for module bytes; heap bytes need a pointer chain


def intersect_deltas(left: list[Delta], right: list[Delta]) -> list[Delta]:
    keep = {d.address for d in right}
    return [d for d in left if d.address in keep]


# -- reading --------------------------------------------------------------------


def _read_exact(handle, address: int, size: int) -> bytes:
    chunks: list[bytes] = []
    left = size
    pos = address
    while left > 0:
        n = min(CHUNK, left)
        raw = win32.read_memory(handle, pos, n)
        if raw is None:
            raise OSError(f"ReadProcessMemory failed at 0x{pos:X} ({n} bytes)")
        chunks.append(raw)
        pos += n
        left -= n
    return b"".join(chunks)


def _read_region(handle, region: Region) -> Optional[np.ndarray]:
    """Bytes of one region, or None if any page is gone (freed heap block)."""
    try:
        return np.frombuffer(_read_exact(handle, region.address, region.size), dtype=np.uint8)
    except OSError:
        return None


def _samples(handle, regions: list[Region], n: int, window_s: float, sleep: Sleep) -> Iterator[list]:
    for k in range(n):
        if k:
            sleep(window_s / (n - 1))
        yield [_read_region(handle, r) for r in regions]


def module_regions(handle, base: int) -> list[Region]:
    """Writable PE sections of the game module."""
    dos = _read_exact(handle, base, 64)
    if dos[:2] != b"MZ":
        raise ValueError("module image is not a PE (no MZ)")
    e_lfanew = int.from_bytes(dos[0x3C:0x40], "little")
    nt = _read_exact(handle, base + e_lfanew, 24)
    if nt[:4] != b"PE\x00\x00":
        raise ValueError("module image is not a PE (no PE signature)")
    n_sections = int.from_bytes(nt[6:8], "little")
    size_opt = int.from_bytes(nt[20:22], "little")
    table = _read_exact(handle, base + e_lfanew + 24 + size_opt, n_sections * 40)

    regions: list[Region] = []
    for i in range(n_sections):
        sh = table[i * 40 : (i + 1) * 40]
        name = sh[:8].split(b"\x00", 1)[0].decode("ascii", "replace")
        size = max(int.from_bytes(sh[8:12], "little"), int.from_bytes(sh[16:20], "little"))
        rva = int.from_bytes(sh[12:16], "little")
        chars = int.from_bytes(sh[36:40], "little")
        if size > 0 and (chars & IMAGE_SCN_MEM_WRITE or name.lower() in {".data", ".bss"}):
            regions.append(Region(label=name, address=base + rva, size=size, rva=rva))
    if not regions:
        raise ValueError("no writable / .data sections found")
    return regions


# -- heap anchors -----------------------------------------------------------------


def find_anchors(buf: np.ndarray, object_id: int, near: tuple[int, ...]) -> list[int]:
    """Byte offsets in ``buf`` of 4-byte-aligned ``object_id`` dwords that have every
    value in ``near`` as an aligned dword within ANCHOR_SPAN bytes (either side)."""
    words = buf[: len(buf) // 4 * 4].view("<u4")
    span = ANCHOR_SPAN // 4
    out: list[int] = []
    for h in np.nonzero(words == object_id)[0].tolist():
        around = np.concatenate((words[max(h - span, 0) : h], words[h + 1 : h + span + 1]))
        if all((around == v).any() for v in near):
            out.append(h * 4)
    return out


def heap_anchor_regions(
    handle, object_id: int, region_id: int, layer_id: int
) -> tuple[list[Region], dict[str, Any]]:
    """Windows of heap memory around the chest's Keen identity.

    Prefers ObjectID with RegionID and LayerID nearby; if that layout never
    occurs, falls back to ObjectID alone (reported in ``stats["anchor"]``).
    """
    heaps = win32.private_rw_regions(handle)
    full: list[int] = []
    id_only: list[int] = []
    scanned = 0
    for base, size in heaps:
        for off in range(0, size, SCAN_CHUNK):
            lo = max(off - ANCHOR_SPAN, 0)
            hi = min(off + SCAN_CHUNK + ANCHOR_SPAN, size)
            raw = win32.read_memory(handle, base + lo, hi - lo)
            if raw is None:
                continue  # freed or reprotected while we scanned
            buf = np.frombuffer(raw, dtype=np.uint8)
            scanned += min(SCAN_CHUNK, size - off)
            in_chunk = lambda o: off <= lo + o < off + SCAN_CHUNK  # noqa: E731
            id_only += [base + lo + o for o in find_anchors(buf, object_id, ()) if in_chunk(o)]
            full += [
                base + lo + o for o in find_anchors(buf, object_id, (region_id, layer_id)) if in_chunk(o)
            ]
    anchors, kind = (full, "object+region+layer") if full else (id_only, "object id only")
    stats = {
        "scope": "heap",
        "heap_regions": len(heaps),
        "scanned_mb": round(scanned / 2**20),
        "object_id_hits": len(id_only),
        "anchors": len(anchors),
        "anchor": kind if anchors else "none",
    }
    if not anchors:
        raise ValueError(
            f"ObjectID {object_id} not found in {stats['scanned_mb']} MB of heap. "
            "Is this the right save_object, and is the chest's area loaded?"
        )
    if len(anchors) > MAX_ANCHORS:
        raise ValueError(f"{len(anchors)} anchors for ObjectID {object_id} ({kind}); too common to narrow")
    return _windows(anchors, heaps), stats


def _windows(anchors: list[int], heaps: list[tuple[int, int]]) -> list[Region]:
    """±WINDOW around each anchor, clipped to its heap region, overlaps merged."""
    spans: list[tuple[int, int]] = []
    for a in sorted(anchors):
        base, size = next((b, s) for b, s in heaps if b <= a < b + s)
        lo, hi = max(a - WINDOW, base), min(a + WINDOW, base + size)
        if spans and lo <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], hi))
        else:
            spans.append((lo, hi))
    return [Region(label="heap", address=lo, size=hi - lo) for lo, hi in spans]


# -- capture ------------------------------------------------------------------------


@contextmanager
def _open_game(pid: Optional[int] = None) -> Iterator[tuple[int, Any]]:
    live = find_process(PROCESS_NAME)
    if live is None:
        raise RuntimeError(f"{PROCESS_NAME} is not running. Launch the game first.")
    if pid is not None and live != pid:
        raise ValueError("game restarted since the baseline; start over")
    handle = win32.open_process(live, write=False)
    try:
        yield live, handle
    finally:
        win32.close_handle(handle)


@dataclass
class RamCapture:
    """Baseline of one capture; ``after()`` returns the 0->1 candidates."""

    pid: int
    regions: list[Region]
    base: list[Optional[np.ndarray]]
    unstable: list[np.ndarray]
    stats: dict[str, Any] = field(default_factory=dict)

    def after(self, *, sleep: Sleep = time.sleep) -> list[Delta]:
        with _open_game(self.pid) as (_pid, handle):
            stays_one = [np.ones(r.size, dtype=bool) for r in self.regions]
            for sample in _samples(handle, self.regions, AFTER_SAMPLES, AFTER_WINDOW_S, sleep):
                for i, cur in enumerate(sample):
                    stays_one[i] &= False if cur is None else (cur == 1)
        deltas: list[Delta] = []
        for r, base, unstable, one in zip(self.regions, self.base, self.unstable, stays_one):
            if base is None:
                continue
            for j in np.nonzero((base == 0) & ~unstable & one)[0].tolist():
                rva = None if r.rva is None else r.rva + j
                deltas.append(Delta(section=r.label, address=r.address + j, old=0, new=1, rva=rva))
        self._save_debug(stays_one)
        return deltas

    def _save_debug(self, stays_one: list[np.ndarray]) -> None:
        """Keep the last capture for offline analysis (snapshots/ is gitignored)."""
        try:
            SNAPSHOT_DIR.mkdir(exist_ok=True)
            table = np.array([(r.address, r.size, -1 if r.rva is None else r.rva) for r in self.regions], dtype=np.int64)
            empty = np.zeros(0, dtype=np.uint8)
            np.savez(
                DEBUG_DUMP,
                regions=table,
                base=np.concatenate([b if b is not None else empty for b in self.base] or [empty]),
                unstable=np.concatenate(self.unstable or [empty.astype(bool)]),
                stays_one=np.concatenate(stays_one or [empty.astype(bool)]),
            )
        except OSError:
            pass


def start_capture(save_object: Optional[dict[str, Any]] = None, *, sleep: Sleep = time.sleep) -> RamCapture:
    """Pick the scope, then sample the baseline over BASELINE_WINDOW_S."""
    with _open_game() as (pid, handle):
        if save_object:
            regions, stats = heap_anchor_regions(
                handle, int(save_object["object_id"]), int(save_object["region_id"]), int(save_object["layer_id"])
            )
        else:
            regions = module_regions(handle, win32.get_module_base(handle, PROCESS_NAME))
            stats = {"scope": "module", "scanned_mb": round(sum(r.size for r in regions) / 2**20)}
        base: list[Optional[np.ndarray]] = []
        unstable: list[np.ndarray] = []
        for k, sample in enumerate(_samples(handle, regions, BASELINE_SAMPLES, BASELINE_WINDOW_S, sleep)):
            for i, cur in enumerate(sample):
                if k == 0:
                    base.append(cur)
                    unstable.append(np.zeros(regions[i].size, dtype=bool) if cur is not None else np.ones(regions[i].size, dtype=bool))
                elif cur is None or base[i] is None:
                    unstable[i][:] = True
                else:
                    unstable[i] |= cur != base[i]
    stats["window_kb"] = round(sum(r.size for r in regions) / 1024)
    return RamCapture(pid=pid, regions=regions, base=base, unstable=unstable, stats=stats)


def offsets_for(delta: Delta, pid: int) -> list[int]:
    """targets.json offsets for a candidate: the RVA, or a static pointer chain for heap bytes."""
    if delta.rva is not None:
        return [delta.rva]
    from tools.scanner import pointer_chain

    chain = pointer_chain(pid, delta.address)
    if not chain:
        raise ValueError(
            f"no static pointer path to heap byte 0x{delta.address:X} (depth 3); "
            "its address changes every launch, so it cannot be saved yet"
        )
    return chain


def describe(stats: dict[str, Any]) -> str:
    if stats.get("scope") == "heap":
        return (
            f"heap: {stats['anchors']} anchor(s) [{stats['anchor']}] from {stats['object_id_hits']} ObjectID hits "
            f"in {stats['scanned_mb']} MB; diffing {stats.get('window_kb', 0)} KB"
        )
    return f"module .data: {stats.get('scanned_mb', 0)} MB (chests are usually not here)"


def _print_deltas(deltas: list[Delta], module: str = PROCESS_NAME) -> None:
    if not deltas:
        print("[-] No 0->1 bytes. Did it open? Try again, standing still on both sides.")
        return
    print(f"[+] {len(deltas)} byte(s) went 0->1 and stayed 1:\n")
    for i, d in enumerate(deltas[:80], start=1):
        where = f"{module} + 0x{d.rva:X}" if d.rva is not None else f"heap 0x{d.address:X}"
        print(f"  [{i:3}] {where}  ({d.section})")
    if len(deltas) > 80:
        print(f"  … {len(deltas) - 80} more")


def main_capture(argv: Optional[list[str]] = None) -> int:
    from tools.save_object import parse_save_object
    from tools.targets import build_target_entry, find_row, save_target
    from tools.world_catalog import resolve_location

    p = argparse.ArgumentParser(
        prog="python -m tools capture",
        description="Identify a location. Chests: two in-game save slots, then a heap RAM capture.",
        epilog='python -m tools capture --sav FILE.sav --slots 1 2 --location "Seraphim Hotel Life Chest 1"',
    )
    p.add_argument("--location", default="", help="Exact name or unique substring (also recaptures a mapped one)")
    p.add_argument("--region", default="", help="Filter the picker, e.g. Crossroads")
    p.add_argument("--next", action="store_true", help="First unmapped check in --region, no menu")
    p.add_argument("--sav", type=Path, help="Warmastered .sav with two slots (closed then open)")
    p.add_argument("--slots", nargs=2, type=int, metavar=("BEFORE", "AFTER"), help="Keen slots: -1 autosave, 0..9")
    p.add_argument("--dry-run", action="store_true", help="Print the result; do not write targets.json")
    args = p.parse_args(argv)
    if sys.platform != "win32":
        print("[ERROR] Capture requires Windows.")
        return 1

    loc = resolve_location(location=args.location, region=args.region, next_unmapped=args.next)
    if loc is None:
        return 1
    if args.sav or args.slots:
        from tools.save_object import diff_sav_slots, find_default_sav, identify_location

        sav = args.sav or find_default_sav()
        if sav is None:
            print("[ERROR] No .sav. Pass --sav PATH")
            return 1
        if not args.slots:
            print("[ERROR] --slots BEFORE AFTER is required with --sav")
            return 2
        print(f"[*] {loc.name}  save-diff  {sav}  slots {args.slots[0]} -> {args.slots[1]}")
        try:
            result = diff_sav_slots(sav, args.slots[0], args.slots[1])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[-] {exc}")
            return 1
        pick = result.get("pick")
        if parse_save_object(pick) is None:
            print("[-] Need exactly one Triggered/Destroyed/Open delta. Rows:")
            for d in result["flags"]:
                print(f"    {d['world']} r={d['region_id']} L={d['layer_id']} obj={d['object_id']} {d['value_key']}: {d['old']} -> {d['new']}")
            return 1
        if args.dry_run:
            print(json.dumps(pick, indent=2))
            return 0
        action, entry = identify_location(loc, pick)
        print(f"[OK] {action} {entry['id']} Keen {entry['save_object']}")
        return 0

    save_object = parse_save_object((find_row(loc.name) or {}).get("save_object"))
    print(
        f"[*] {loc.name}  (AP {loc.ap_id}, {loc.region})\n"
        + (
            f"    Heap capture near Keen obj={save_object['object_id']} r={save_object['region_id']} L={save_object['layer_id']}.\n"
            if save_object
            else "    No save_object for this row: diffing module .data (identify it with --sav --slots first).\n"
        )
        + f"    1) Stand still next to it, closed. Enter = baseline ({BASELINE_WINDOW_S:.0f} s, keep still).\n"
        "    2) Open it, wait for popups to close, stand still. Enter = after.\n"
    )
    try:
        input("Baseline — press Enter… ")
        cap = start_capture(save_object)
        print(f"[*] {describe(cap.stats)}")
        input("Opened it and standing still? Press Enter… ")
        deltas = cap.after()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[-] {exc}")
        return 1

    _print_deltas(deltas)
    if len(deltas) != 1:
        print("\n[-] Not saved: need exactly one candidate. Retry, or use the dashboard to pick a row.")
        return 1
    d = deltas[0]
    try:
        offsets = offsets_for(d, cap.pid)
    except ValueError as exc:
        print(f"[-] {exc}")
        return 1
    entry = build_target_entry(
        target_id=loc.slug,
        label=loc.name,
        category="location_flag",
        dtype="uint8",
        offsets=offsets,
        notes=f"capture 0->1 in {d.section}",
        region=loc.region,
    )
    if args.dry_run:
        print(json.dumps(entry, indent=2))
        return 0
    action, entry = save_target(entry)
    print(f"[OK] {action} {entry['id']} @ {' -> '.join(entry['offsets'])}  (ds_client hot-reloads it)")
    return 0
