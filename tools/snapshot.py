"""Snapshot / diff / capture for writable module data (chest flags, etc.).

Exact-value ``tools scan`` is for known HUD numbers (souls).
This path dumps .data/.bss-class sections, then diffs — no typed values.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ds_client import win32
from ds_client.models import PROCESS_NAME
from ds_client.watcher import find_process

SNAPSHOT_DIR = Path("snapshots")
CHUNK = 64 * 1024
IMAGE_SCN_MEM_WRITE = 0x80000000


@dataclass(frozen=True)
class Section:
    name: str
    rva: int
    size: int
    file_offset: int


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


def _pe_writable_sections(handle, base: int) -> list[Section]:
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

    sections: list[Section] = []
    blob_off = 0
    for i in range(n_sections):
        sh = table[i * 40 : (i + 1) * 40]
        name = sh[:8].split(b"\x00", 1)[0].decode("ascii", "replace")
        vsize = int.from_bytes(sh[8:12], "little")
        rva = int.from_bytes(sh[12:16], "little")
        rawsize = int.from_bytes(sh[16:20], "little")
        chars = int.from_bytes(sh[36:40], "little")
        size = max(vsize, rawsize)
        prefer_name = name.lower() in {".data", ".bss", ".idata"}
        if size <= 0 or not ((chars & IMAGE_SCN_MEM_WRITE) or prefer_name):
            continue
        sections.append(Section(name=name, rva=rva, size=size, file_offset=blob_off))
        blob_off += size
    if not sections:
        raise ValueError("no writable / .data sections found")
    return sections


def take_snapshot(*, name: str, process_name: str = PROCESS_NAME) -> Path:
    pid = find_process(process_name)
    if pid is None:
        raise RuntimeError(
            f"Process {process_name!r} is not running. Launch the game first."
        )
    handle = win32.open_process(pid)
    try:
        base = win32.get_module_base(handle, process_name)
        sections = _pe_writable_sections(handle, base)
        parts = [_read_exact(handle, base + s.rva, s.size) for s in sections]
    finally:
        win32.close_handle(handle)

    dest = SNAPSHOT_DIR / name
    dest.mkdir(parents=True, exist_ok=True)
    blob = b"".join(parts)
    (dest / "dump.bin").write_bytes(blob)
    meta = {
        "name": name,
        "process": process_name,
        "pid": pid,
        "module_base": f"0x{base:X}",
        "bytes": len(blob),
        "sections": [
            {"name": s.name, "rva": f"0x{s.rva:X}", "size": s.size, "file_offset": s.file_offset}
            for s in sections
        ],
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return dest


def _load(name: str) -> tuple[dict, bytes]:
    dest = SNAPSHOT_DIR / name
    meta_path = dest / "meta.json"
    dump_path = dest / "dump.bin"
    if not meta_path.exists() or not dump_path.exists():
        raise FileNotFoundError(f"snapshot {name!r} not found under {SNAPSHOT_DIR}/")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return meta, dump_path.read_bytes()


@dataclass(frozen=True)
class Delta:
    section: str
    rva: int
    old: int
    new: int


def diff_snapshots(
    before: str,
    after: str,
    *,
    stable: Optional[str] = None,
    only_zero_to_one: bool = False,
) -> list[Delta]:
    meta_b, data_b = _load(before)
    meta_a, data_a = _load(after)
    if meta_b.get("sections") != meta_a.get("sections"):
        raise ValueError(
            "snapshot section maps differ; retake both in one session. "
            "PE headers do not drift from GC — a mismatch means a reload or different build."
        )
    if len(data_b) != len(data_a):
        raise ValueError("snapshot sizes differ")

    stable_bytes: Optional[bytes] = None
    if stable:
        _meta_s, stable_bytes = _load(stable)
        if len(stable_bytes) != len(data_b):
            raise ValueError("stable snapshot size differs")

    deltas: list[Delta] = []
    for sec in meta_b["sections"]:
        off = int(sec["file_offset"])
        size = int(sec["size"])
        rva0 = int(sec["rva"], 0)
        sb = data_b[off : off + size]
        sa = data_a[off : off + size]
        ss = stable_bytes[off : off + size] if stable_bytes is not None else None
        for i, (old, new) in enumerate(zip(sb, sa)):
            if old == new:
                continue
            if ss is not None and ss[i] != old:
                continue  # ticking / unstable between idle samples
            if only_zero_to_one and not (old == 0 and new == 1):
                continue
            deltas.append(Delta(section=sec["name"], rva=rva0 + i, old=old, new=new))
    return deltas


def _print_deltas(deltas: list[Delta], module: str = PROCESS_NAME) -> None:
    if not deltas:
        print("[-] No 0->1 bytes. Did it open? If it never shows, the flag lives on the heap (needs a pointer path).")
        return
    print(f"[+] {len(deltas)} byte(s) went 0->1:\n")
    for i, d in enumerate(deltas[:80], start=1):
        print(
            f"  [{i:3}] {module} + 0x{d.rva:X}  "
            f"{d.old} -> {d.new}  ({d.section})"
        )
    if len(deltas) > 80:
        print(f"  … {len(deltas) - 80} more")


CAPTURE_SNAPSHOTS = ("_cap_a", "_cap_b", "_cap_c")


def capture_deltas(wait_before, wait_after) -> list[Delta]:
    """Idle pair (a, b) 0.4 s apart, then c after the in-game action.

    Keeps only bytes that went 0 -> 1 between b and c and were steady a -> b.
    Fixed snapshot names: each capture overwrites the last.
    """
    a, b, c = CAPTURE_SNAPSHOTS
    wait_before()
    take_snapshot(name=a)
    time.sleep(0.4)
    take_snapshot(name=b)
    wait_after()
    take_snapshot(name=c)
    return diff_snapshots(b, c, stable=a, only_zero_to_one=True)


def main_capture(argv: Optional[list[str]] = None) -> int:
    from tools.targets import build_target_entry, save_target
    from tools.world_catalog import resolve_location

    p = argparse.ArgumentParser(
        prog="python -m tools capture",
        description="Pick a world location, dump before/after opening it, save the 0->1 flag.",
        epilog="python -m tools capture --region Crossroads",
    )
    p.add_argument("--location", default="", help="Exact name or unique substring (also recaptures a mapped one)")
    p.add_argument("--region", default="", help="Filter the picker, e.g. Crossroads")
    p.add_argument("--next", action="store_true", help="First unmapped check in --region, no menu")
    p.add_argument("--dry-run", action="store_true", help="Print the result; do not write targets.json")
    args = p.parse_args(argv)
    if sys.platform != "win32":
        print("[ERROR] Capture requires Windows.")
        return 1

    loc = resolve_location(location=args.location, region=args.region, next_unmapped=args.next)
    if loc is None:
        return 1
    print(
        f"[*] {loc.name}  (AP {loc.ap_id}, {loc.region})\n"
        "    1) Stand still next to it while it is still closed.\n"
        "    2) Enter = baseline.  3) Open it in-game.  4) Enter = after.\n"
    )
    try:
        deltas = capture_deltas(
            lambda: input("Baseline — press Enter… "),
            lambda: input("Opened it? Press Enter… "),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[-] {exc}")
        return 1

    _print_deltas(deltas)
    if len(deltas) != 1:
        print("\n[-] Not saved: need exactly one 0->1 byte. Retry, or use the dashboard to pick a row.")
        return 1
    d = deltas[0]
    entry = build_target_entry(
        target_id=loc.slug,
        label=loc.name,
        category="location_flag",
        dtype="uint8",
        offsets=[d.rva],
        notes=f"capture delta {d.old}->{d.new} in {d.section}",
        region=loc.region,
    )
    if args.dry_run:
        print(json.dumps(entry, indent=2))
        return 0
    action, entry = save_target(entry)
    print(f"[OK] {action} {entry['id']} @ {entry['offsets'][0]}  (ds_client hot-reloads it)")
    return 0
