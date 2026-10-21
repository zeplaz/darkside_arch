"""Exact-value scanner for *known* HUD numbers (souls, etc.).

Chests and unknown flags: use ``python -m tools capture`` (snapshot/diff).
Typing 0 into this scanner is the wrong tool — it matches every zero byte.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from ds_client.models import PROCESS_NAME, TARGETS_FILE, TYPE_SPECS
from ds_client.watcher import find_process

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


def build_target_entry(
    *,
    target_id: str,
    label: str,
    category: str,
    dtype: str,
    module: str,
    offsets: Sequence[int],
    notes: str,
    enabled: bool = True,
    region: str = "",
) -> dict:
    event_type = "LOCATION_CHECK" if category == "location_flag" else "MEMORY_STATE"
    return {
        "id": target_id,
        "enabled": enabled,
        "event_type": event_type,
        "category": category,
        "label": label,
        "region": region,
        "offsets": [f"0x{o:X}" for o in offsets],
        "type": dtype,
        "module": module,
        "notes": notes,
    }


def upsert_target(new_target: dict, targets_path: Path = TARGETS_FILE) -> str:
    """Insert or update by id in targets.json (observe_interval_ms / module / targets)."""
    path = Path(targets_path)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path} root must be a JSON object")
    else:
        data = {"observe_interval_ms": 250, "module": PROCESS_NAME, "targets": []}

    targets = data.setdefault("targets", [])
    if not isinstance(targets, list):
        raise ValueError(f"{path}: 'targets' must be a list")
    data.setdefault("observe_interval_ms", 250)
    data.setdefault("module", PROCESS_NAME)

    target_id = str(new_target["id"])
    action = "appended"
    for i, item in enumerate(targets):
        if not (isinstance(item, dict) and item.get("id") == target_id):
            continue
        merged = {**item, **new_target}
        if not merged.get("region") and item.get("region"):
            merged["region"] = item["region"]
        if "bitmask" not in new_target and "bitmask" in item:
            merged["bitmask"] = item["bitmask"]
        targets[i] = merged
        action = "updated"
        break
    else:
        targets.append(new_target)

    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return action


def _sync_sqlite_from_targets(targets_path: Path) -> None:
    """Push enabled targets into darksiders_debug.db memory_map (no manual SQL)."""
    from ds_client.models import load_targets
    from ds_client.sinks import DB_FILE, init_db, sync_memory_map_from_targets

    _, targets = load_targets(targets_path)
    conn = init_db()
    try:
        n = sync_memory_map_from_targets(conn, targets)
        print(f"[+] Synced {n} enabled target(s) into {DB_FILE}")
    finally:
        conn.close()


def _emit_result(entry: dict, *, auto_save: bool, targets_path: Path) -> None:
    pretty = json.dumps(entry, indent=2)
    if auto_save:
        action = upsert_target(entry, targets_path)
        print(f"[+] {action.capitalize()} target id={entry['id']!r} in {targets_path}")
        print(pretty)
        try:
            _sync_sqlite_from_targets(targets_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            print(f"[WARN] SQLite sync-map failed: {exc}")
        print(
            "\nNext: python -m ds_client  (hot-reloads targets.json)\n"
            "      python -m tools dashboard  (live telemetry)\n"
            "      python -m tools export-docs  (only when locked in / Obsidian)"
        )
        return
    print("\n--- targets.json entry (pass --auto-save to write) ---\n")
    print(pretty)
    print("\nNext: re-run with --auto-save, then: python -m ds_client")


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


def _finish_entry(
    *,
    module: str,
    offsets: Sequence[int],
    target_id: str,
    label: str,
    category: str,
    dtype: str,
    notes: str,
    auto_save: bool,
    targets_path: Path,
) -> None:
    entry = build_target_entry(
        target_id=target_id,
        label=label,
        category=category,
        dtype=dtype,
        module=module,
        offsets=offsets,
        notes=notes,
    )
    _emit_result(entry, auto_save=auto_save, targets_path=targets_path)


def run_value_scan(
    *,
    process_name: str = PROCESS_NAME,
    dtype: str = "float",
    writeable_only: bool = False,
    target_id: str = "soul_count",
    label: str = "Soul_Count",
    category: str = "stat",
    pointer_scan: bool = True,
    auto_save: bool = False,
    targets_path: Path = TARGETS_FILE,
) -> int:
    numpy_ok = _require_pymemoryeditor()
    from PyMemoryEditor import OpenProcess

    if dtype not in TYPE_SPECS or dtype not in _PYTYPE:
        print(f"[ERROR] unsupported type {dtype!r}; choose from {sorted(TYPE_SPECS)}")
        return 1
    width, _fmt = TYPE_SPECS[dtype]
    pytype = _PYTYPE[dtype]

    if target_id == "soul_count" and dtype == "uint32":
        print("[WARN] Keen Souls is float. This uint32 scan will miss 172.0. Use --type float.")
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
                "Chests / unknown flags: Ctrl+C, then python -m tools capture\n"
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
                    writeable_only=writeable_only,
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
                _finish_entry(
                    module=mod_name,
                    offsets=[offset],
                    target_id=target_id,
                    label=label,
                    category=category,
                    dtype=dtype,
                    notes=f"scanned absolute 0x{chosen:X} this run",
                    auto_save=auto_save,
                    targets_path=targets_path,
                )
                return 0

            if not pointer_scan:
                print(
                    f"[-] 0x{chosen:X} is dynamic and --no-pointer-scan was set."
                )
                return 1

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
            _finish_entry(
                module=path.module or process_name,
                offsets=chain,
                target_id=target_id,
                label=label,
                category=category,
                dtype=dtype,
                notes=f"pointer path to 0x{chosen:X}",
                auto_save=auto_save,
                targets_path=targets_path,
            )
            return 0
    except Exception as exc:
        print(f"[-] Error during process scan: {exc}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools scan",
        description="Exact + differential memory scanner (PyMemoryEditor)",
    )
    p.add_argument("--process", default=PROCESS_NAME)
    p.add_argument(
        "--type",
        dest="dtype",
        default="float",
        choices=sorted(TYPE_SPECS),
        help="Default float matches Keen Souls. Chest flags: uint8/bool. Health: int32.",
    )
    p.add_argument("--id", dest="target_id", default="soul_count")
    p.add_argument("--label", default="Soul_Count")
    p.add_argument(
        "--category",
        default="stat",
        choices=["location_flag", "inventory", "stat", "misc"],
    )
    p.add_argument(
        "--writeable-only",
        action="store_true",
        help="Faster; may miss read-only statics",
    )
    p.add_argument(
        "--no-pointer-scan",
        action="store_true",
        help="Skip pointer-path recovery for heap addresses",
    )
    p.add_argument(
        "--auto-save",
        action="store_true",
        help=f"Upsert into {TARGETS_FILE} (enabled: true)",
    )
    p.add_argument("--targets", type=Path, default=TARGETS_FILE)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    if sys.platform != "win32":
        print("[ERROR] Scanner requires Windows.")
        return 1
    args = build_parser().parse_args(argv)
    return run_value_scan(
        process_name=args.process,
        dtype=args.dtype,
        writeable_only=args.writeable_only,
        target_id=args.target_id,
        label=args.label,
        category=args.category,
        pointer_scan=not args.no_pointer_scan,
        auto_save=args.auto_save,
        targets_path=args.targets,
    )


if __name__ == "__main__":
    raise SystemExit(main())
