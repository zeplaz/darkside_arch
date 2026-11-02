"""Synthetic Armageddon Blade grant after 7 shards. Shared by both runtimes."""

from __future__ import annotations

from typing import Optional

from ap.catalog import BLADE_ITEM, SHARD_ITEM, ApCatalog
from ap.state import ApState, ReceivedRow

SYNTHETIC_BLADE_INDEX = -1


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
