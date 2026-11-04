"""Load Keen identities from targets.json for DLL-path LocationChecks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from runtime.mem.models import (
    CATEGORY_INVENTORY,
    CATEGORY_LOCATION,
    CATEGORY_STAT,
    PROCESS_NAME,
    TARGETS_FILE,
    TYPE_SPECS,
    WatchTarget,
    _parse_int,
)

IdentityKey = tuple[int, int, int, str]  # region, layer, object, value_key


@dataclass(frozen=True)
class LocationIdentity:
    target_id: str
    label: str
    region_id: int
    layer_id: int
    object_id: int
    value_key: str
    world: str = "overworld"


def _parse_save_object(raw: object) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    world = str(raw.get("world") or "").strip() or "overworld"
    key = str(raw.get("value_key") or raw.get("key") or "").strip()
    try:
        return {
            "world": world,
            "region_id": int(raw["region_id"]),
            "layer_id": int(raw["layer_id"]),
            "object_id": int(raw["object_id"]),
            "value_key": key or "Triggered",
        }
    except (KeyError, TypeError, ValueError):
        return None


def iter_raw_targets(path: Path = TARGETS_FILE) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    for raw in data.get("targets", []):
        if isinstance(raw, dict):
            yield raw


def load_location_identities(path: Path = TARGETS_FILE) -> dict[IdentityKey, LocationIdentity]:
    """All location rows that have a Keen ``save_object`` (offsets optional)."""
    out: dict[IdentityKey, LocationIdentity] = {}
    for raw in iter_raw_targets(path):
        if str(raw.get("category", "")).lower() not in {CATEGORY_LOCATION, ""}:
            if str(raw.get("event_type", "")) != "LOCATION_CHECK":
                continue
        if raw.get("enabled") is False and not raw.get("save_object"):
            continue
        so = _parse_save_object(raw.get("save_object"))
        if so is None:
            continue
        label = str(raw.get("label") or raw.get("id") or "").strip()
        if not label:
            continue
        ident = LocationIdentity(
            target_id=str(raw["id"]),
            label=label,
            region_id=so["region_id"],
            layer_id=so["layer_id"],
            object_id=so["object_id"],
            value_key=so["value_key"],
            world=so["world"],
        )
        key = (ident.region_id, ident.layer_id, ident.object_id, ident.value_key)
        out[key] = ident
    return out


def load_mapped_item_targets(path: Path = TARGETS_FILE) -> tuple[WatchTarget, ...]:
    """Inventory/stat rows with real offsets — same as mem apply needs."""
    if not path.exists():
        return ()
    data = json.loads(path.read_text(encoding="utf-8"))
    default_module = str(data.get("module", PROCESS_NAME))
    out: list[WatchTarget] = []
    for raw in data.get("targets", []):
        if not bool(raw.get("enabled", True)):
            continue
        category = str(raw.get("category", "")).strip().lower()
        if category not in {CATEGORY_INVENTORY, CATEGORY_STAT}:
            continue
        offsets_raw = raw.get("offsets") or []
        offsets = tuple(_parse_int(o, "offset") for o in offsets_raw)
        if offsets == (0,) or not offsets:
            continue
        dtype = str(raw.get("type", "uint32"))
        if dtype not in TYPE_SPECS:
            continue
        size, fmt = TYPE_SPECS[dtype]
        import struct

        bitmask_raw = raw.get("bitmask")
        bitmask = _parse_int(bitmask_raw, "bitmask") if bitmask_raw is not None else None
        out.append(
            WatchTarget(
                id=str(raw["id"]),
                event_type=str(raw.get("event_type", "MEMORY_STATE")),
                module=str(raw.get("module", default_module)),
                offsets=offsets,
                size=size,
                unpacker=struct.Struct("<" + fmt),
                dtype=dtype,
                notes=str(raw.get("notes", "")).strip(),
                label=str(raw.get("label", "")).strip(),
                region=str(raw.get("region", "")).strip(),
                category=category,
                bitmask=bitmask,
            )
        )
    return tuple(out)


def watches_payload(idents: dict[IdentityKey, LocationIdentity]) -> list[dict[str, Any]]:
    """JSON list sent to the DLL so it knows which WorldObjects to report."""
    return [
        {
            "region_id": i.region_id,
            "layer_id": i.layer_id,
            "object_id": i.object_id,
            "value_key": i.value_key,
            "label": i.label,
            "id": i.target_id,
        }
        for i in idents.values()
    ]
