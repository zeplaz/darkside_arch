"""Exact-value scanner for *known* HUD numbers (souls, etc.).

HUD numbers only (souls, item counts). Chests: two save slots via
``python -m tools scan --sav FILE --slots 1 2 --item NAME``
or the dashboard SAVE DIFF. Typing 0 here matches every zero byte.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from ds_client.models import PROCESS_NAME, TYPE_SPECS
from ds_client.watcher import find_process
from tools.targets import build_target_entry, find_row, raw_targets, save_target

SOULS_LABEL = "Soul_Count"

# JSON type name -> Python type for PyMemoryEditor scans
_PYTYPE: dict[str, type] = {
    "bool": bool,
    "float": float,
    "double": float,
    **{name: int for name in TYPE_SPECS if name not in {"bool", "float", "double"}},
}


def _require_pymemoryeditor() -> bool:
    try:
        from PyMemoryEditor import OpenProcess  # noqa: F401
        from PyMemoryEditor.util import NUMPY_AVAILABLE
    except ImportError as exc:
        raise SystemExit(
            "[ERROR] PyMemoryEditor not installed.\n"
            "        pip install -r requirements-dev.txt"
        ) from exc
    return bool(NUMPY_AVAILABLE)


def _find_module(process, module_name: str):
    want = module_name.lower()
    for mod in process.get_modules():
        if mod.name.lower() == want:
            return mod
    return None


def _module_relative(
    process, address: int, preferred_module: str
) -> tuple[Optional[str], Optional[int]]:
    """(module_name, offset) if address lies in a loaded module."""
    preferred = fallback = None
    want = preferred_module.lower()
    for mod in process.get_modules():
        base, size = int(mod.base_address), int(mod.size)
        if not (base <= address < base + size):
            continue
        entry = (mod.name, address - base)
        if mod.name.lower() == want:
            preferred = entry
        elif fallback is None:
            fallback = entry
    return preferred or fallback or (None, None)


def _emit_result(entry: dict, *, dry_run: bool) -> None:
    if dry_run:
        print(json.dumps(entry, indent=2))
        return
    action, entry = save_target(entry)
    print(f"[OK] {action} {entry['id']} @ {' -> '.join(entry['offsets'])}  (ds_client hot-reloads it)")


def _parse_value(raw: str, pytype: type):
    raw = raw.strip()
    if pytype is bool:
        return raw.lower() in {"1", "true", "t", "yes", "y"}
    if pytype is float:
        return float(raw)
    return int(raw, 0)


def _refine(process, pytype, width, candidates, new_value, regions) -> list[int]:
    return [
        addr
        for addr, value in process.search_by_addresses(
            pytype, width, addresses=candidates, memory_regions=regions
        )
        if value == new_value
    ]


def _pointer_paths(process, address: int, module_name: str, max_results: int = 8):
    mod = _find_module(process, module_name)
    if mod is None:
        return []
    base, size = int(mod.base_address), int(mod.size)
    try:
        return list(
            process.scan_pointer_paths(
                address,
                max_depth=3,
                max_offset=0x1000,
                static_ranges=[(base, base + size)],
                max_results=max_results,
            )
        )
    except Exception as exc:
        print(f"[WARN] Pointer scan failed: {exc}")
        return []


def _read_live(process, pytype, width, addr, regions):
    for a, v in process.search_by_addresses(
        pytype, width, addresses=[addr], memory_regions=regions
    ):
        if a == addr:
            return v
    return None


def run_value_scan(row: dict, *, dry_run: bool = False) -> int:
    """Narrow one HUD number down to an address, then save it onto ``row``
    (a targets.json row: id / label / category / type)."""
    process_name = PROCESS_NAME
    dtype = str(row.get("type") or "float")
    numpy_ok = _require_pymemoryeditor()
    from PyMemoryEditor import OpenProcess

    if dtype not in TYPE_SPECS or dtype not in _PYTYPE:
        print(f"[ERROR] unsupported type {dtype!r}; choose from {sorted(TYPE_SPECS)}")
        return 1
    width, _fmt = TYPE_SPECS[dtype]
    pytype = _PYTYPE[dtype]

    print(f"[*] Scanning for {row['label']!r} ({row['category']})")
    print(f"[*] NumPy acceleration: {numpy_ok}")
    print(f"[*] Attaching to {process_name} ({dtype}, {width} bytes)...")

    pid = find_process(process_name)
    if pid is None:
        print(
            f"[ERROR] Process {process_name!r} is not running.\n"
            "        Launch Darksiders Warmastered (Steam x64), get in-game, then retry."
        )
        return 1

    try:
        with OpenProcess(pid=pid) as process:
            print(f"[*] Attached PID {pid}")
            if not process.is_64bit:
                print("[WARN] Process does not look 64-bit — Warmastered should be x64.")

            mod = _find_module(process, process_name)
            if mod is None:
                print(f"[ERROR] Module {process_name!r} not found in process.")
                return 1
            print(
                f"[BASE] {mod.name} @ 0x{int(mod.base_address):X} "
                f"(size 0x{int(mod.size):X})"
            )

            regions = process.snapshot_memory_regions()
            print(
                "\nExact-value scan — for a known HUD number (souls).\n"
                "Chests: Ctrl+C, then python -m tools scan --sav FILE --slots 1 2 --item NAME\n"
                "Look at the HUD and type that number. Live logging is python -m ds_client.\n"
            )
            raw = input("HUD value right now (or 'q' to quit): ").strip()
            if raw.lower() == "q":
                return 0

            print("[*] Initial exact scan...")
            candidates = list(
                process.search_by_value(
                    pytype,
                    width,
                    value=_parse_value(raw, pytype),
                    writeable_only=False,
                    memory_regions=regions,
                )
            )
            print(f"[+] Found {len(candidates)} matching address(es).")
            if not candidates:
                print("[-] No hits. Check the HUD value / type width and retry.")
                return 1

            while len(candidates) > 1:
                print(f"\n[?] {len(candidates)} addresses still match.")
                print("    In-game: kill something or spend souls so the HUD number changes.")
                action = input(
                    "New HUD value (or 'q' to stop): "
                ).strip()
                if action.lower() == "q":
                    break
                candidates = _refine(
                    process,
                    pytype,
                    width,
                    candidates,
                    _parse_value(action, pytype),
                    regions,
                )
                print(f"[+] Remaining: {len(candidates)}")

            if not candidates:
                print("[-] All candidates eliminated. Restart the scan.")
                return 1

            print()
            for i, addr in enumerate(candidates[:32], start=1):
                mod_name, offset = _module_relative(process, addr, process_name)
                live = _read_live(process, pytype, width, addr, regions)
                if mod_name is not None and offset is not None:
                    print(
                        f"  [{i}] 0x{addr:X}  live={live}  "
                        f"=> {mod_name} + 0x{offset:X}"
                    )
                else:
                    print(
                        f"  [{i}] 0x{addr:X}  live={live}  "
                        f"=> (heap/dynamic — needs pointer path)"
                    )

            # Prefer a hit inside the main module image
            chosen = candidates[0]
            for addr in candidates:
                name, _ = _module_relative(process, addr, process_name)
                if name and name.lower() == process_name.lower():
                    chosen = addr
                    break

            mod_name, offset = _module_relative(process, chosen, process_name)
            print(f"\n[SUCCESS] Primary candidate: 0x{chosen:X}")

            if mod_name is not None and offset is not None:
                print(
                    f"[ASLR] Module-relative: {mod_name} + 0x{offset:X}\n"
                    "       Absolute VA is session-only; never store it."
                )
                _emit_result(_entry(row, mod_name, [offset], f"scanned absolute 0x{chosen:X}"), dry_run=dry_run)
                return 0

            print("[*] Heap address — scanning pointer paths...")
            paths = _pointer_paths(process, chosen, process_name)
            if not paths:
                print(
                    "[-] No pointer paths found.\n"
                    f"    Absolute 0x{chosen:X} is only valid until restart."
                )
                return 0

            path = paths[0]
            chain = [int(path.module_offset), *[int(o) for o in path.offsets]]
            print(f"[ASLR] Pointer chain ({len(paths)} found), best:\n       {path}")
            _emit_result(
                _entry(row, path.module or process_name, chain, f"pointer path to 0x{chosen:X}"),
                dry_run=dry_run,
            )
            return 0
    except Exception as exc:
        print(f"[-] Error during process scan: {exc}")
        return 1


def _entry(row: dict, module: str, offsets: Sequence[int], notes: str) -> dict:
    return build_target_entry(
        target_id=str(row["id"]),
        label=str(row["label"]),
        category=str(row["category"]),
        dtype=str(row["type"]),
        offsets=offsets,
        notes=notes,
        region=str(row.get("region") or ""),
        module=module,
    )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tools scan",
        description="HUD numbers by exact value, or chest identity from two save slots.",
        epilog='python -m tools scan --sav FILE.sav --slots 1 2 --item "Seraphim Hotel Life Chest 1"',
    )
    p.add_argument("--item", default="", help=f"targets.json / catalog label (default {SOULS_LABEL!r} for HUD scan)")
    p.add_argument("--type", dest="dtype", choices=sorted(TYPE_SPECS), help="Override the row's type")
    p.add_argument("--sav", type=Path, help="Warmastered .sav — chest save-diff, not a RAM scan")
    p.add_argument("--slots", nargs=2, type=int, metavar=("BEFORE", "AFTER"), help="Keen slots: -1 autosave, 0..9")
    p.add_argument("--dry-run", action="store_true", help="Print the result; do not write targets.json")
    args = p.parse_args(argv)
    if sys.platform != "win32":
        print("[ERROR] Scanner requires Windows.")
        return 1
    if args.sav or args.slots:
        from tools.save_object import diff_sav_slots, find_default_sav, identify_location, parse_save_object
        from tools.world_catalog import resolve_location

        name = args.item or ""
        loc = resolve_location(location=name)
        if loc is None:
            return 1
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
            print("[-] Need exactly one Triggered/Destroyed/Open delta.")
            for d in result["flags"]:
                print(f"    {d['world']} r={d['region_id']} L={d['layer_id']} obj={d['object_id']} {d['value_key']}: {d['old']} -> {d['new']}")
            return 1
        if args.dry_run:
            print(json.dumps(pick, indent=2))
            return 0
        action, entry = identify_location(loc, pick)
        print(f"[OK] {action} {entry['id']} Keen {entry['save_object']}")
        return 0
    item = args.item or SOULS_LABEL
    row = find_row(item)
    if row is None:
        labels = [t["label"] for t in raw_targets() if t.get("category") in {"inventory", "stat"}]
        print(f"[ERROR] No targets.json row labelled {item!r}. Known HUD: {', '.join(labels)}")
        print("        Chests: python -m tools scan --sav FILE --slots 1 2 --item NAME")
        return 1
    if str(row.get("category")) == "location_flag":
        print(
            "[ERROR] Chests are identified from two save slots, not a HUD scan.\n"
            f'        python -m tools scan --sav FILE --slots 1 2 --item "{item}"'
        )
        return 2
    if args.dtype:
        row = {**row, "type": args.dtype}
    return run_value_scan(row, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
