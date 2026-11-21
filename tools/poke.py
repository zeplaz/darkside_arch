"""Write a value into the running game — the "it actually does something" proof.

Two modes:

* Target mode (uses targets.json):  ``python -m tools poke --id soul_count --value 10000``
* Raw address mode:                  ``python -m tools poke --addr 0x1A2B3C4D --type float --value 500``

Target mode resolves the module-relative offset / pointer chain from a mapped
row in ``targets.json`` (inventory or stat rows only). Run
``python -m tools scan --item Soul_Count`` first to fill a real offset into the
``soul_count`` row, then poke it and watch the HUD change.

This uses the same external ``WriteProcessMemory`` path as the mem runtime
(``runtime.mem.win32``). The injected DLL has an equivalent in-process ``poke``
op — see ``runtime/dll/native/src/poke.rs``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from runtime.mem import win32
from runtime.mem.models import (
    CATEGORY_INVENTORY,
    CATEGORY_STAT,
    PROCESS_NAME,
    TARGETS_FILE,
    TYPE_SPECS,
    WatchTarget,
    _build_target,
)

_FLOAT_TYPES = frozenset({"float", "double"})


def pokable_targets(path: Path = TARGETS_FILE) -> dict[str, WatchTarget]:
    """Mapped inventory/stat rows keyed by id *and* label (disabled rows included)."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    default_module = str(data.get("module", PROCESS_NAME))
    out: dict[str, WatchTarget] = {}
    for raw in data.get("targets", []):
        if not isinstance(raw, dict):
            continue
        raw = dict(raw)
        raw["enabled"] = True  # a mapped row is pokable even while disabled
        target = _build_target(raw, default_module)
        if target is None or target.is_template:
            continue
        if target.category not in {CATEGORY_INVENTORY, CATEGORY_STAT}:
            continue
        out[target.id] = target
        if target.label:
            out[target.label] = target
    return out


def parse_value(raw: str, dtype: str) -> int | float:
    if dtype in _FLOAT_TYPES:
        return float(raw)
    if dtype == "bool":
        return 1 if raw.strip().lower() in {"1", "true", "t", "yes", "y"} else 0
    return int(raw, 0)


@dataclass
class PokeResult:
    target_id: str
    module: str
    address: int
    before: str
    after: str
    value: str


def poke_target(pid: int, target: WatchTarget, value: int | float) -> PokeResult:
    handle = win32.open_process(pid, write=True)
    try:
        base = win32.get_module_base(handle, target.module)
        addr = win32.resolve_address(handle, base, target.offsets)
        if addr is None:
            raise RuntimeError(
                f"could not resolve {target.offsets} from {target.module}+0x{base:X}"
            )
        before = _read_decoded(handle, addr, target)

        payload_value = value
        if target.bitmask is not None:
            raw = win32.read_memory(handle, addr, target.size)
            if raw is None:
                raise RuntimeError(f"read failed at 0x{addr:X}")
            current = int(target.unpacker.unpack_from(raw)[0])
            payload_value = (current & ~target.bitmask) | (int(value) & target.bitmask)

        data = target.encode(payload_value)
        if not win32.write_memory(handle, addr, data):
            raise RuntimeError(f"write failed at 0x{addr:X}")

        after = _read_decoded(handle, addr, target)
        return PokeResult(
            target_id=target.id,
            module=target.module,
            address=addr,
            before=before,
            after=after,
            value=_fmt_value(target, payload_value),
        )
    finally:
        win32.close_handle(handle)


def resolve_write(pid: int, target: WatchTarget, value: int | float) -> tuple[int, bytes]:
    """Resolve a target to ``(absolute_address, encoded_bytes)`` without writing.

    The bytes are ready for either write path: external WriteProcessMemory
    (``poke_target``) or the injected DLL's in-process ``poke`` op.
    """
    handle = win32.open_process(pid, write=True)
    try:
        base = win32.get_module_base(handle, target.module)
        addr = win32.resolve_address(handle, base, target.offsets)
        if addr is None:
            raise RuntimeError(
                f"could not resolve {target.offsets} from {target.module}+0x{base:X}"
            )
        payload_value = value
        if target.bitmask is not None:
            raw = win32.read_memory(handle, addr, target.size)
            if raw is None:
                raise RuntimeError(f"read failed at 0x{addr:X}")
            current = int(target.unpacker.unpack_from(raw)[0])
            payload_value = (current & ~target.bitmask) | (int(value) & target.bitmask)
        return addr, target.encode(payload_value)
    finally:
        win32.close_handle(handle)


def _read_decoded(handle: win32.ProcessHandle, addr: int, target: WatchTarget) -> str:
    raw = win32.read_memory(handle, addr, target.size)
    if raw is None:
        return "<unreadable>"
    return target.decode(raw)


def _fmt_value(target: WatchTarget, value: int | float) -> str:
    if target.dtype in _FLOAT_TYPES:
        return repr(float(value))
    if target.bitmask is not None:
        return f"0x{int(value):X}"
    return str(int(value))


def poke_raw(pid: int, address: int, dtype: str, value: int | float) -> PokeResult:
    if dtype not in TYPE_SPECS:
        raise ValueError(f"unsupported type {dtype!r}; choose from {sorted(TYPE_SPECS)}")
    size, _fmt = TYPE_SPECS[dtype]
    # Build an ephemeral target for encode/decode.
    import struct

    target = WatchTarget(
        id="raw",
        event_type="MEMORY_STATE",
        module=PROCESS_NAME,
        offsets=(0,),
        size=size,
        unpacker=struct.Struct("<" + _fmt),
        dtype=dtype,
        notes="raw address poke",
        category=CATEGORY_STAT,
    )
    handle = win32.open_process(pid, write=True)
    try:
        before = _read_decoded(handle, address, target)
        if not win32.write_memory(handle, address, target.encode(value)):
            raise RuntimeError(f"write failed at 0x{address:X}")
        after = _read_decoded(handle, address, target)
        return PokeResult("raw", PROCESS_NAME, address, before, after, _fmt_value(target, value))
    finally:
        win32.close_handle(handle)


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(
        prog="python -m tools poke",
        description="Write a value into the running game (Souls / item counts / raw address).",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--id", default="", help="targets.json id or label (e.g. soul_count)")
    src.add_argument("--addr", default="", help="raw absolute address (hex) to write")
    p.add_argument("--value", required=True, help="value to write (hex ints with 0x, floats ok)")
    p.add_argument("--type", dest="dtype", default="float", choices=sorted(TYPE_SPECS),
                   help="type for --addr mode (default float)")
    p.add_argument("--pid", type=int, default=0, help="game PID (auto-detected if omitted)")
    p.add_argument("--json", action="store_true", help="print one JSON result line")
    args = p.parse_args(argv)

    if sys.platform != "win32":
        print("[ERROR] poke requires Windows (game memory write).")
        return 1

    from runtime.mem.watcher import find_process  # psutil, only needed to auto-detect

    pid = args.pid or find_process(PROCESS_NAME)
    if pid is None:
        print(f"[ERROR] {PROCESS_NAME} is not running — launch the game first.")
        return 1

    try:
        if args.addr:
            result = poke_raw(pid, int(args.addr, 0), args.dtype, parse_value(args.value, args.dtype))
        else:
            targets = pokable_targets()
            target = targets.get(args.id)
            if target is None:
                print(
                    f"[ERROR] no mapped inventory/stat row for {args.id!r}.\n"
                    "        Map one first: python -m tools scan --item Soul_Count"
                )
                return 1
            result = poke_target(pid, target, parse_value(args.value, target.dtype))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        return 1

    if args.json:
        print(json.dumps(vars(result)))
    else:
        print(
            f"[OK] {result.target_id} @ 0x{result.address:X} "
            f"({result.module}): {result.before} -> {result.after} (wrote {result.value})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
