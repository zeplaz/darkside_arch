"""Shared data structures and target configuration loading."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROCESS_NAME = "darksiders1.exe"
TARGETS_FILE = Path("targets.json")

# name -> (byte size, struct format char)
TYPE_SPECS: dict[str, tuple[int, str]] = {
    "bool": (1, "?"),
    "uint8": (1, "B"),
    "int8": (1, "b"),
    "uint16": (2, "H"),
    "int16": (2, "h"),
    "uint32": (4, "I"),
    "int32": (4, "i"),
    "uint64": (8, "Q"),
    "int64": (8, "q"),
    "float": (4, "f"),
    "double": (8, "d"),
}

_FLOAT_TYPES = frozenset({"float", "double"})

# Categories used by docs/memory_map.md sectioning
CATEGORY_LOCATION = "location_flag"
CATEGORY_INVENTORY = "inventory"
CATEGORY_STAT = "stat"
CATEGORY_MISC = "misc"
VALID_CATEGORIES = frozenset(
    {CATEGORY_LOCATION, CATEGORY_INVENTORY, CATEGORY_STAT, CATEGORY_MISC}
)


@dataclass(frozen=True)
class WatchTarget:
    """Validated watch definition. Hot path trusts these fields."""

    id: str
    event_type: str
    module: str
    offsets: tuple[int, ...]
    size: int
    unpacker: struct.Struct
    dtype: str
    notes: str
    label: str = ""
    region: str = ""
    category: str = CATEGORY_MISC
    bitmask: Optional[int] = None

    @property
    def display_name(self) -> str:
        return self.label or self.id

    def decode(self, raw: bytes) -> str:
        value = self.unpacker.unpack_from(raw)[0]
        if self.bitmask is not None:
            value = int(value) & self.bitmask
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, float):
            return repr(value)
        return str(value)

    def format_bitmask(self) -> str:
        return "None" if self.bitmask is None else f"0x{self.bitmask:X}"


@dataclass(frozen=True)
class Event:
    session_id: int
    event_type: str
    address_hex: str
    value_raw: str
    notes: str
    target_id: str = ""
    prev_value: str = ""
    label: str = ""
    region: str = ""
    category: str = ""
    tagged: int = 0


def _parse_int(value: object, field: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise TypeError(f"{field} must be int or hex/decimal string")


def _build_target(raw: dict, default_module: str) -> Optional[WatchTarget]:
    if not bool(raw.get("enabled", True)):
        return None

    target_id = str(raw["id"])
    dtype = str(raw.get("type", "uint32"))
    if dtype not in TYPE_SPECS:
        raise ValueError(f"unsupported type {dtype!r} on target {target_id}")

    size, fmt = TYPE_SPECS[dtype]
    bitmask_raw = raw.get("bitmask")
    bitmask = _parse_int(bitmask_raw, "bitmask") if bitmask_raw is not None else None
    if bitmask is not None and dtype in _FLOAT_TYPES:
        raise ValueError(f"bitmask not supported on float types (target {target_id})")

    offsets_raw = raw.get("offsets")
    if not offsets_raw:
        raise ValueError(f"target {target_id!r} requires offsets")

    category = str(raw.get("category", CATEGORY_MISC)).strip().lower() or CATEGORY_MISC
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"unsupported category {category!r} on target {target_id}; "
            f"expected one of {sorted(VALID_CATEGORIES)}"
        )

    label = str(raw.get("label", "")).strip()
    region = str(raw.get("region", "")).strip()
    notes = str(raw.get("notes", "")).strip()

    return WatchTarget(
        id=target_id,
        event_type=str(raw.get("event_type", "MEMORY_STATE")),
        module=str(raw.get("module", default_module)),
        offsets=tuple(_parse_int(o, "offset") for o in offsets_raw),
        size=size,
        unpacker=struct.Struct("<" + fmt),
        dtype=dtype,
        notes=notes,
        label=label,
        region=region,
        category=category,
        bitmask=bitmask,
    )


def load_targets(path: Path = TARGETS_FILE) -> tuple[int, tuple[WatchTarget, ...]]:
    if not path.exists():
        print(f"[WARN] {path} missing; using empty target list.")
        return 250, ()

    data = json.loads(path.read_text(encoding="utf-8"))
    interval_ms = int(data.get("observe_interval_ms", 250))
    default_module = str(data.get("module", PROCESS_NAME))
    targets: list[WatchTarget] = []

    for raw in data.get("targets", []):
        target = _build_target(raw, default_module)
        if target is not None:
            targets.append(target)

    return interval_ms, tuple(targets)
