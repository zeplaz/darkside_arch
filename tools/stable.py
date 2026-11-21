"""Cross-session pointer-chain scan.

Find a pointer chain that survives a save reload. The normal auto-scan finds
*a* path through whatever heap object is handy at that moment; this tool finds
the *stable* path by the standard technique:

1. find the value, enumerate pointer chains,
2. reload the save, find the value again,
3. keep only chains whose offset signature resolves in **both** sessions.

    python -m tools stable --item Soul_Count
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from runtime.mem.models import PROCESS_NAME, TYPE_SPECS
from runtime.mem.watcher import find_process
from tools.scanner import (
    _PYTYPE,
    _entry,
    _emit_result,
    _find_module,
    _parse_value,
    _pointer_paths,
    _refine,
    _require_pymemoryeditor,
)
from tools.targets import find_row

STABLE_DEPTH = 5
STABLE_MAX_OFFSET = 0x2000
STABLE_MAX_RESULTS = 64


def _find_address(process, pytype, width) -> Optional[int]:
    """Exact-value scan for a HUD number, narrowed to one address."""
    regions = process.snapshot_memory_regions()
    raw = input("HUD value right now: ").strip()
    value = _parse_value(raw, pytype)
    candidates = list(
        process.search_by_value(
            pytype, width, value=value, writeable_only=False, memory_regions=regions
        )
    )
    print(f"[+] {len(candidates)} match(es).")
    if not candidates:
        print("[-] No hits. Check the HUD value / type.")
        return None
    while len(candidates) > 1:
        print(
            f"[?] {len(candidates)} still match. Change the value in-game, then type the new HUD value (q to stop):"
        )
        raw = input("> ").strip()
        if raw.lower() == "q":
            return None
        candidates = _refine(process, pytype, width, candidates, _parse_value(raw, pytype), regions)
        print(f"[+] {len(candidates)} remain.")
    return candidates[0]


def _chain_signatures(process, address: int, module_name: str) -> set[tuple[int, tuple[int, ...]]]:
    paths = _pointer_paths(
        process,
        address,
        module_name,
        max_results=STABLE_MAX_RESULTS,
        max_depth=STABLE_DEPTH,
        max_offset=STABLE_MAX_OFFSET,
    )
    sigs: set[tuple[int, tuple[int, ...]]] = set()
    for p in paths:
        if p.module_offset is not None:
            sigs.add((int(p.module_offset), tuple(int(o) for o in p.offsets)))
    return sigs


def run_stable_scan(row: dict, *, dry_run: bool = False) -> int:
    dtype = str(row.get("type") or "float")
    if dtype not in TYPE_SPECS or dtype not in _PYTYPE:
        print(f"[ERROR] unsupported type {dtype!r}")
        return 1
    width, _fmt = TYPE_SPECS[dtype]
    pytype = _PYTYPE[dtype]
    _require_pymemoryeditor()
    from PyMemoryEditor import OpenProcess

    pid = find_process(PROCESS_NAME)
    if pid is None:
        print(f"[ERROR] {PROCESS_NAME} is not running — launch the game first.")
        return 1

    with OpenProcess(pid=pid) as process:
        if _find_module(process, PROCESS_NAME) is None:
            print(f"[ERROR] module {PROCESS_NAME!r} not found.")
            return 1

        print(f"[*] Session 1 — find {row['label']!r} and its pointer chains.")
        addr_a = _find_address(process, pytype, width)
        if addr_a is None:
            print("[-] Could not pin the value in session 1.")
            return 1
        print(f"[*] Value at 0x{addr_a:X}. Enumerating chains (depth {STABLE_DEPTH})...")
        sigs_a = _chain_signatures(process, addr_a, PROCESS_NAME)
        print(f"[+] {len(sigs_a)} pointer chain(s) in session 1.")

        input(
            "\nReload the save now (quit to menu, load, get back in-game).\n"
            "Press Enter when ready for session 2... "
        )

        print(f"[*] Session 2 — find {row['label']!r} again.")
        addr_b = _find_address(process, pytype, width)
        if addr_b is None:
            print("[-] Could not pin the value in session 2.")
            return 1
        print(f"[*] Value now at 0x{addr_b:X}. Enumerating chains...")
        sigs_b = _chain_signatures(process, addr_b, PROCESS_NAME)
        print(f"[+] {len(sigs_b)} pointer chain(s) in session 2.")

        stable = sorted(sigs_a & sigs_b, key=lambda s: (len(s[1]), s[0]))
        if not stable:
            print(
                f"[-] No chain survived the reload at depth {STABLE_DEPTH}. "
                "The stable path is deeper; raise STABLE_DEPTH or run a third session."
            )
            return 1
        print(f"\n[+] {len(stable)} stable chain(s) survived the reload:")
        for i, (off, chain) in enumerate(stable[:16], start=1):
            hops = " -> ".join(f"0x{o:X}" for o in chain)
            print(f"  [{i}] {PROCESS_NAME} + 0x{off:X} -> {hops}")

    off, chain = stable[0]
    _emit_result(
        _entry(row, PROCESS_NAME, [off, *chain], "stable pointer chain (survives save reload)"),
        dry_run=dry_run,
    )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tools stable",
        description="Find a pointer chain that survives save reloads.",
    )
    p.add_argument("--item", default="Soul_Count", help="targets.json label (default Soul_Count)")
    p.add_argument("--type", dest="dtype", choices=sorted(TYPE_SPECS), help="Override the row's type")
    p.add_argument("--dry-run", action="store_true", help="Print the result; do not write targets.json")
    args = p.parse_args(argv)
    if sys.platform != "win32":
        print("[ERROR] Stable scan requires Windows.")
        return 1
    row = find_row(args.item)
    if row is None:
        print(f"[ERROR] No targets.json row labelled {args.item!r}")
        return 1
    if args.dtype:
        row = {**row, "type": args.dtype}
    return run_stable_scan(row, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
