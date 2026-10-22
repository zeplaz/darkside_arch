"""Queue ReceivedItems onto mapped inventory watches. Observer-thread only."""

from __future__ import annotations

import queue
from typing import Optional, Sequence

from ds_client.ap_catalog import (
    BLADE_ITEM,
    PROGRESSIVE_LEVEL_CAPS,
    SHARD_ITEM,
    ApCatalog,
)
from ds_client.ap_state import ApState, ReceivedRow
from ds_client.models import (
    CATEGORY_INVENTORY,
    CATEGORY_STAT,
    WatchTarget,
)
from ds_client import win32

SYNTHETIC_BLADE_INDEX = -1
_reported: set[str] = set()  # item names already reported as unmappable


def target_for_item(targets: Sequence[WatchTarget], item_name: str) -> Optional[WatchTarget]:
    """``targets`` come from load_targets: enabled and mapped (no 0x0 templates)."""
    return next((t for t in targets if t.display_name == item_name), None)


def _report_once(key: str, message: str) -> None:
    if key not in _reported:
        _reported.add(key)
        print(message)


def parse_numeric(value_raw: str) -> float:
    if value_raw in {"", "None"}:
        return 0.0
    if value_raw in {"True", "true"}:
        return 1.0
    if value_raw in {"False", "false"}:
        return 0.0
    return float(value_raw)


def desired_write_value(
    *,
    item_name: str,
    received_count: int,
    current: float,
    target: WatchTarget,
) -> Optional[int | float]:
    """Return the value to poke, or None if this write is a no-op."""
    cap = PROGRESSIVE_LEVEL_CAPS.get(item_name)
    if cap is not None:
        level = max(1, min(received_count, cap))
        if current == level:
            return None
        return level

    if target.dtype == "bool" or target.bitmask is not None:
        if current:
            return None
        return 1

    if target.dtype in {"float", "double"}:
        if current == received_count:
            return None
        return float(received_count)

    if current == received_count:
        return None
    return int(received_count)


def write_target(
    handle: win32.ProcessHandle,
    module_bases: dict[str, int],
    target: WatchTarget,
    value: int | float,
) -> bool:
    base = module_bases.get(target.module)
    if base is None:
        return False
    addr = win32.resolve_address(handle, base, target.offsets)
    if addr is None:
        return False
    packed_value: int | float = value
    if target.bitmask is not None:
        raw = win32.read_memory(handle, addr, target.size)
        if raw is None:
            return False
        current = int(target.unpacker.unpack_from(raw)[0])
        packed_value = (current & ~target.bitmask) | (int(value) & target.bitmask)
    payload = target.encode(packed_value)
    return win32.write_memory(handle, addr, payload)


def maybe_synthetic_blade(
    state: ApState,
    catalog: ApCatalog,
    seed_name: str,
    team: int,
    slot: int,
) -> Optional[ReceivedRow]:
    shard_id = catalog.item_id(SHARD_ITEM)
    blade_id = catalog.item_id(BLADE_ITEM)
    if shard_id is None or blade_id is None:
        return None
    if state.blade_granted(seed_name, team, slot):
        return None
    if state.item_count(seed_name, team, slot, shard_id) < 7:
        return None
    return ReceivedRow(
        seed_name=seed_name,
        team=team,
        slot=slot,
        idx=SYNTHETIC_BLADE_INDEX,
        item_id=blade_id,
        location=0,
        player=0,
        flags=0,
        applied=0,
    )


def apply_row(
    handle: win32.ProcessHandle,
    module_bases: dict[str, int],
    targets: Sequence[WatchTarget],
    catalog: ApCatalog,
    state: ApState,
    row: ReceivedRow,
) -> Optional[bool]:
    """True = applied (or already right), False = RAM not readable yet (retry),
    None = cannot apply now (unknown item / no mapped watch); stays pending in the DB."""
    name = catalog.item_name(row.item_id)
    if name is None:
        _report_once(f"id:{row.item_id}", f"[AP] unknown item id {row.item_id}; left pending")
        return None
    target = target_for_item(targets, name)
    if target is None or target.category not in {CATEGORY_INVENTORY, CATEGORY_STAT}:
        _report_once(name, f"[AP] {name!r} has no mapped inventory watch yet; left pending")
        return None
    count = state.item_count(row.seed_name, row.team, row.slot, row.item_id)
    if name == BLADE_ITEM:
        count = max(count, 1)
    base = module_bases.get(target.module)
    if base is None:
        return False
    addr = win32.resolve_address(handle, base, target.offsets)
    if addr is None:
        return False
    raw = win32.read_memory(handle, addr, target.size)
    if raw is None:
        return False
    current = parse_numeric(target.decode(raw))
    desired = desired_write_value(
        item_name=name,
        received_count=count,
        current=current,
        target=target,
    )
    if desired is None:
        return True
    ok = write_target(handle, module_bases, target, desired)
    if ok:
        print(f"[AP] applied {name!r} -> {desired} (idx={row.idx})")
    return ok


def drain_apply_queue(
    handle: win32.ProcessHandle,
    module_bases: dict[str, int],
    targets: Sequence[WatchTarget],
    catalog: ApCatalog,
    state: ApState,
    apply_queue: queue.SimpleQueue,
) -> None:
    """Apply every queued row once. One unmappable item never blocks the rest."""
    retry: list[ReceivedRow] = []
    while True:
        try:
            row: ReceivedRow = apply_queue.get_nowait()
        except queue.Empty:
            break
        ident = (row.seed_name, row.team, row.slot)
        synthetic = row.idx == SYNTHETIC_BLADE_INDEX
        if synthetic and state.blade_granted(*ident):
            continue
        if not synthetic and not state.is_pending(*ident, row.idx):
            continue
        ok = apply_row(handle, module_bases, targets, catalog, state, row)
        if ok is None:
            continue
        if not ok:
            retry.append(row)
            continue
        if synthetic:
            state.set_blade_granted(*ident, True)
        else:
            state.mark_applied(*ident, row.idx)
        blade = maybe_synthetic_blade(state, catalog, *ident)
        if blade is not None:
            apply_queue.put(blade)
    for row in retry:
        apply_queue.put(row)
