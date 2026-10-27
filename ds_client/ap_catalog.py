"""Name ↔ AP id lookups from committed world catalogs. IDs never live in targets.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LOCATIONS_PATH = Path("docs") / "world_locations.json"
ITEMS_PATH = Path("docs") / "world_items.json"

SHARD_ITEM = "Armageddon Blade Shards"
BLADE_ITEM = "Armageddon Blade"
PROGRESSIVE_LEVEL_CAPS = {
    "Progressive Chaoseater": 4,
    "Progressive Scythe": 4,
    "Progressive Gauntlet": 4,
}


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    ap_id: int
    kind: str = ""
    region: str = ""


class ApCatalog:
    def __init__(
        self,
        *,
        locations: dict[str, CatalogEntry],
        items: dict[str, CatalogEntry],
    ) -> None:
        self._locations = locations
        self._items = items
        self._items_by_id = {e.ap_id: e for e in items.values()}

    @property
    def empty(self) -> bool:
        return not self._locations or not self._items

    def location_id(self, name: str) -> Optional[int]:
        entry = self._locations.get(name)
        return entry.ap_id if entry else None

    def item_id(self, name: str) -> Optional[int]:
        entry = self.item_entry(name)
        return entry.ap_id if entry else None

    def item_entry(self, name: str) -> Optional[CatalogEntry]:
        return self._items.get(name)

    def item_name(self, ap_id: int) -> Optional[str]:
        entry = self._items_by_id.get(ap_id)
        return entry.name if entry else None

    def is_goal_label(self, name: str) -> bool:
        if name == "Victory":
            return True
        entry = self._locations.get(name)
        if entry is not None and entry.kind == "goal":
            return True
        want = name.casefold()
        return any(e.kind == "goal" and e.name.casefold() == want for e in self._locations.values())


def _load_entries(path: Path, key: str) -> dict[str, CatalogEntry]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get(key, [])
    out: dict[str, CatalogEntry] = {}
    for row in rows:
        name = str(row["name"])
        out[name] = CatalogEntry(
            name=name,
            ap_id=int(row["ap_id"]),
            kind=str(row.get("kind") or ""),
            region=str(row.get("region") or ""),
        )
    return out


def load_catalog(
    *,
    locations_path: Path = LOCATIONS_PATH,
    items_path: Path = ITEMS_PATH,
) -> ApCatalog:
    return ApCatalog(
        locations=_load_entries(locations_path, "locations"),
        items=_load_entries(items_path, "items"),
    )
