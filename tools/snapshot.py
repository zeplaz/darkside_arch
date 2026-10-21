"""Snapshot / diff / capture for writable module data (chest flags, etc.).

Exact-value ``tools scan`` is for known HUD numbers (souls).
This path dumps .data/.bss-class sections, then diffs — no typed values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ds_client import win32
from ds_client.models import PROCESS_NAME
from ds_client.watcher import find_process
from tools.scanner import _emit_result, build_target_entry

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
        print("[-] No deltas. Stand still, retake, or the flag may live on the heap.")
        return
    print(f"[+] {len(deltas)} changed byte(s) in writable module data:\n")
    for i, d in enumerate(deltas[:80], start=1):
        print(
            f"  [{i:3}] {module} + 0x{d.rva:X}  "
            f"{d.old} -> {d.new}  ({d.section})"
        )
    if len(deltas) > 80:
        print(f"  … {len(deltas) - 80} more")


def _maybe_autosave(deltas: list[Delta], *, args) -> None:
    if not args.auto_save:
        return
    z2o = [d for d in deltas if d.old == 0 and d.new == 1]
    pick = z2o if len(z2o) == 1 else deltas
    if len(pick) != 1:
        print(
            f"\n[--auto-save skipped] need exactly 1 candidate "
            f"(have {len(pick)}; {len(z2o)} were 0->1). "
            "Re-capture more still, or pass --all-deltas."
        )
        return
    d = pick[0]
    entry = build_target_entry(
        target_id=args.id,
        label=args.label,
        category=args.category,
        dtype="uint8",
        module=PROCESS_NAME,
        offsets=[d.rva],
        notes=f"snapshot delta {d.old}->{d.new} in {d.section}",
        region=getattr(args, "region", "") or "",
    )
    _emit_result(entry, auto_save=True, targets_path=args.targets)


def cmd_snapshot(name: str, process_name: str) -> int:
    path = take_snapshot(name=name, process_name=process_name)
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    print(
        f"[OK] snapshot {name!r}  {meta['bytes']} bytes  "
        f"{len(meta['sections'])} section(s) -> {path}"
    )
    for s in meta["sections"]:
        print(f"     {s['name']:8} rva={s['rva']} size={s['size']}")
    return 0


def cmd_diff(before: str, after: str, *, stable: Optional[str], only_z2o: bool) -> int:
    deltas = diff_snapshots(before, after, stable=stable, only_zero_to_one=only_z2o)
    _print_deltas(deltas)
    z2o = sum(1 for d in deltas if d.old == 0 and d.new == 1)
    if deltas:
        print(f"\n    of those, {z2o} are 0->1 (typical chest/boss flags)")
        print("    Next: python -m tools capture --region Crossroads")
    return 0


def _bind_world_location(args) -> bool:
    """Fill id/label/region from the world catalog so capture is a pick, not a type-in."""
    from tools.world_catalog import resolve_location

    manual = args.target_id != "captured_flag" and not (
        args.location or args.region or args.next
    )
    if manual:
        return True
    loc = resolve_location(
        location=args.location,
        region=args.region,
        next_unmapped=args.next,
    )
    if loc is None:
        return False
    args.target_id = loc.slug
    args.id = loc.slug
    args.label = loc.name
    args.category = "location_flag"
    if not args.region:
        args.region = loc.region
    print(f"[*] Location check: {loc.name}  (AP {loc.ap_id}, {loc.region})")
    return True


def cmd_capture(args) -> int:
    """Idle pair + after-action dump. Filters ticking bytes automatically."""
    if not _bind_world_location(args):
        return 1
    print(
        "CAPTURE — location check (no HUD numbers).\n"
        f"    {args.label}\n"
        "1) Stand still at that check.\n"
        "2) Enter = BEFORE (two quiet samples).\n"
        "3) Open / trigger it.\n"
        "4) Enter = AFTER.\n"
    )
    input("BEFORE — press Enter… ")
    cap = f"_cap_{os.getpid()}"
    take_snapshot(name=f"{cap}_a", process_name=args.process)
    time.sleep(0.4)
    take_snapshot(name=f"{cap}_b", process_name=args.process)
    print("[*] Idle pair stored. Do the in-game action now.")
    input("AFTER — press Enter… ")
    take_snapshot(name=f"{cap}_c", process_name=args.process)

    deltas = diff_snapshots(
        f"{cap}_b",
        f"{cap}_c",
        stable=f"{cap}_a",
        only_zero_to_one=args.zero_to_one,
    )
    _print_deltas(deltas)
    z2o = [d for d in deltas if d.old == 0 and d.new == 1]
    print(f"\n    {len(z2o)} of {len(deltas)} are 0->1")
    _maybe_autosave(deltas, args=args)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools snapshot",
        description="Dump writable module data (.data/.bss) for before/after diffs",
    )
    p.add_argument("--name", required=True, help="Snapshot folder name under snapshots/")
    p.add_argument("--process", default=PROCESS_NAME)
    return p


def build_diff_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools diff",
        description="Diff two snapshots; optional third idle sample filters tickers",
    )
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument(
        "--stable",
        default="",
        help="Earlier idle snapshot; bytes that moved between stable and before are ignored",
    )
    p.add_argument(
        "--zero-to-one",
        action="store_true",
        help="Only keep 0 -> 1 byte changes",
    )
    return p


def build_capture_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools capture",
        description="Pick a world check, then before/after dump. Auto-save is on.",
        epilog="python -m tools capture --region Crossroads",
    )
    p.add_argument("--process", default=PROCESS_NAME)
    p.add_argument(
        "--location",
        default="",
        help="World location name or unique substring",
    )
    p.add_argument(
        "--region",
        default="",
        help="Filter the picker, e.g. Crossroads",
    )
    p.add_argument(
        "--next",
        action="store_true",
        help="First unmapped check in --region (skip the menu)",
    )
    p.add_argument("--id", dest="target_id", default="captured_flag", help=argparse.SUPPRESS)
    p.add_argument("--label", default="Captured_Flag", help=argparse.SUPPRESS)
    p.add_argument(
        "--category",
        default="location_flag",
        choices=["location_flag", "inventory", "stat", "misc"],
        help=argparse.SUPPRESS,
    )
    p.add_argument("--auto-save", action="store_true", default=True, help=argparse.SUPPRESS)
    p.add_argument(
        "--no-auto-save",
        action="store_false",
        dest="auto_save",
        help="Print the delta only; do not write targets.json",
    )
    p.add_argument("--targets", type=Path, default=None, help=argparse.SUPPRESS)
    p.add_argument("--zero-to-one", action="store_true", default=True, help=argparse.SUPPRESS)
    p.add_argument(
        "--all-deltas",
        action="store_false",
        dest="zero_to_one",
        help="Show every changed byte, not only 0->1",
    )
    return p


def main_snapshot(argv: Optional[list[str]] = None) -> int:
    if sys.platform != "win32":
        print("[ERROR] Snapshots require Windows.")
        return 1
    args = build_parser().parse_args(argv)
    try:
        return cmd_snapshot(args.name, args.process)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[-] {exc}")
        return 1


def main_diff(argv: Optional[list[str]] = None) -> int:
    args = build_diff_parser().parse_args(argv)
    try:
        return cmd_diff(
            args.before,
            args.after,
            stable=args.stable or None,
            only_z2o=args.zero_to_one,
        )
    except (OSError, ValueError, FileNotFoundError) as exc:
        print(f"[-] {exc}")
        return 1


def main_capture(argv: Optional[list[str]] = None) -> int:
    if sys.platform != "win32":
        print("[ERROR] Capture requires Windows.")
        return 1
    from ds_client.models import TARGETS_FILE

    args = build_capture_parser().parse_args(argv)
    if args.targets is None:
        args.targets = TARGETS_FILE
    args.id = args.target_id
    try:
        return cmd_capture(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[-] {exc}")
        return 1
