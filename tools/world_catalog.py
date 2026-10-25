"""World location and item names from Sacha's world package — no hand-typed labels.

Source of truth is worlds/darksiders/data/*.json in the local clone.
Falls back to docs/world_*.json when the clone is missing.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from tools.targets import is_mapped as is_row_mapped
from tools.targets import raw_targets

WORLD_ROOT = Path("world/Archipelago-Darksiders/worlds/darksiders")
WORLD_DATA_DIR = WORLD_ROOT / "data"
WORLD_LOCATIONS_PY = WORLD_ROOT / "Locations.py"
WORLD_ITEMS_JSON = WORLD_DATA_DIR / "Items.json"
CATALOG_PATH = Path("docs") / "world_locations.json"
ITEMS_CATALOG_PATH = Path("docs") / "world_items.json"

_LOADED_JSON_RE = re.compile(r'create_location_table_from_json\(\s*"([^"]+\.json)"\s*\)')

_REGION_PREFIXES = tuple(
    sorted(
        (
            "Anvil's Ford Challenge Area",
            "Anvil's Ford Access Tunnel",
            "Anvil's Ford",
            "Anvil Ford Challenge",
            "Anvil Ford",
            "Ashlands Access Tunnel",
            "Ashlands",
            "The Ashlands Access Tunnel",
            "The Ashlands",
            "Broken Stair Access Tunnel",
            "Broken Stair",
            "Choking Grounds Access Tunnel",
            "Choking Grounds Access Cave",
            "Choking Grounds",
            "Crossroads",
            "Drowned Pass Access Tunnel",
            "Drowned Pass",
            "Dry Road Access Tunnel",
            "Dry Road",
            "Hollows Access Tunnel",
            "Hollows",
            "The Hollows Access Tunnel",
            "The Hollows",
            "Leviathan's Drift",
            "Library",
            "Scalding Gallow",
            "Seraphim Hotel",
            "Serpent Hole to Anvil's Ford",
            "Serpent Hole to Dry Road",
            "Serpent Hole to Twilight Cathedral",
            "Twilight Cathedral",
        ),
        key=len,
        reverse=True,
    )
)


@dataclass(frozen=True)
class WorldItem:
    name: str
    ap_id: int
    kind: str


@dataclass(frozen=True)
class WorldLocation:
    name: str
    ap_id: int
    region: str
    kind: str
    vanilla_item: str = ""
    in_ap: bool = True
    area: str = ""

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_")


def infer_region(name: str) -> str:
    for prefix in _REGION_PREFIXES:
        if name.startswith(prefix):
            return prefix
    return ""


def infer_kind(name: str, vanilla_item: str = "") -> str:
    lower = name.lower()
    if "artifact" in lower:
        return "artifact"
    if "armor" in lower:
        return "armor"
    if "cube" in lower:
        return "cube"
    if "chest" in lower:
        return "chest"
    v = vanilla_item.lower()
    if "artifact" in v:
        return "artifact"
    if "armor" in v:
        return "armor"
    if v in {"currency", "health", "wrath", "hellfire", "lifestone shard", "wrath shard", "beholder key"}:
        return "chest"
    return "location"


def loaded_location_json_names(path: Path = WORLD_LOCATIONS_PY) -> set[str]:
    """JSON files Locations.py actually imports (uncommented create_location_table_from_json)."""
    if not path.exists():
        return set()
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _LOADED_JSON_RE.search(stripped)
        if match:
            names.add(match.group(1))
    return names


def parse_data_locations(data_dir: Path = WORLD_DATA_DIR) -> list[WorldLocation]:
    if not data_dir.is_dir():
        return []
    loaded = loaded_location_json_names()
    seen: dict[str, WorldLocation] = {}
    for path in sorted(data_dir.glob("*.json")):
        if path.name == "Items.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        in_ap = path.name in loaded if loaded else True
        area = path.stem
        for region in payload:
            if not isinstance(region, dict):
                continue
            region_name = str(region.get("name") or path.stem)
            locations = region.get("locations")
            if not isinstance(locations, dict):
                continue
            for name, loc_data in locations.items():
                if not isinstance(loc_data, dict):
                    continue
                ap_id = loc_data.get("ID")
                if ap_id is None:
                    continue
                vanilla = str(loc_data.get("vanilla item") or "")
                seen[str(name)] = WorldLocation(
                    name=str(name),
                    ap_id=int(ap_id),
                    region=region_name,
                    kind=infer_kind(str(name), vanilla),
                    vanilla_item=vanilla,
                    in_ap=in_ap,
                    area=area,
                )
    return list(seen.values())


def parse_items_json(path: Path = WORLD_ITEMS_JSON) -> list[WorldItem]:
    data = json.loads(path.read_text(encoding="utf-8"))
    seen: dict[str, WorldItem] = {}
    if not isinstance(data, dict):
        return []
    for kind, group in data.items():
        if not isinstance(group, dict):
            continue
        for name, item_data in group.items():
            if not isinstance(item_data, dict):
                continue
            ap_id = item_data.get("ID")
            if ap_id is None:
                continue
            seen[str(name)] = WorldItem(name=str(name), ap_id=int(ap_id), kind=str(kind))
    return list(seen.values())


def write_items_catalog(items: list[WorldItem], dest: Path = ITEMS_CATALOG_PATH) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "game": "Darksiders",
        "items": [
            {"name": item.name, "ap_id": item.ap_id, "kind": item.kind}
            for item in sorted(items, key=lambda x: (x.ap_id, x.name))
        ],
    }
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest


def write_catalog(locations: list[WorldLocation], dest: Path = CATALOG_PATH) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "game": "Darksiders",
        "source": "worlds/darksiders/data",
        "locations": [
            {
                "name": loc.name,
                "ap_id": loc.ap_id,
                "region": loc.region,
                "kind": loc.kind,
                "vanilla_item": loc.vanilla_item,
                "in_ap": loc.in_ap,
                "area": loc.area,
            }
            for loc in sorted(locations, key=lambda x: (x.region, x.ap_id, x.name))
        ],
    }
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest


def _from_cache_row(row: dict) -> WorldLocation:
    name = str(row["name"])
    vanilla = str(row.get("vanilla_item") or "")
    return WorldLocation(
        name=name,
        ap_id=int(row["ap_id"]),
        region=str(row.get("region") or infer_region(name)),
        kind=str(row.get("kind") or infer_kind(name, vanilla)),
        vanilla_item=vanilla,
        in_ap=bool(row.get("in_ap", True)),
        area=str(row.get("area") or ""),
    )


def load_catalog(*, include_deferred: bool = False) -> list[WorldLocation]:
    """AP-active locations. Pass include_deferred=True to also list JSON not loaded by Locations.py."""
    if WORLD_DATA_DIR.is_dir() and any(WORLD_DATA_DIR.glob("*.json")):
        rows = parse_data_locations()
    elif CATALOG_PATH.exists():
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        rows = [_from_cache_row(row) for row in data.get("locations", [])]
    else:
        raise FileNotFoundError(
            "No world catalog. Clone the world repo or run: python -m tools sync-world"
        )
    if include_deferred:
        return rows
    return [loc for loc in rows if loc.in_ap]


def is_mapped(loc: WorldLocation, rows: list[dict] | None = None) -> bool:
    """True when targets.json has a real (non-0x0) offset for this location."""
    rows = raw_targets() if rows is None else rows
    return any(
        is_row_mapped(r) for r in rows if r.get("label") == loc.name or r.get("id") == loc.slug
    )


def filter_locations(
    locations: list[WorldLocation],
    *,
    region: str = "",
    unmapped: bool = False,
) -> list[WorldLocation]:
    rows = raw_targets()
    want = region.lower()
    return [
        loc
        for loc in locations
        if (
            not want
            or want in loc.region.lower()
            or want in loc.area.lower()
            or want in loc.name.lower()
        )
        and not (unmapped and is_mapped(loc, rows))
    ]


def resolve_location(
    *,
    location: str = "",
    region: str = "",
    next_unmapped: bool = False,
) -> WorldLocation | None:
    """--location matches any check (so a wrong offset can be recaptured);
    the picker and --next only offer checks that still need an offset."""
    catalog = load_catalog()
    if location:
        rows = filter_locations(catalog, region=region)
        q = location.lower()
        exact = [r for r in rows if r.name.lower() == q or r.slug == q]
        if exact:
            return exact[0]
        hits = [r for r in rows if q in r.name.lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            print(f"[ERROR] No catalog match for {location!r}")
            return None
        print(f"[ERROR] {len(hits)} matches for {location!r}; be more specific:")
        for hit in hits[:20]:
            print(f"        {hit.name}")
        return None
    rows = filter_locations(catalog, region=region, unmapped=True)
    if not rows:
        print("[-] Every check in this filter already has an offset.")
        return None
    if next_unmapped:
        return rows[0]
    return _pick(rows)


def _pick(rows: list[WorldLocation]) -> WorldLocation | None:
    print(f"Unmapped location checks ({len(rows)}). Type a number.\n")
    for i, loc in enumerate(rows, start=1):
        print(f"  {i:3}  [{loc.region or '?'}] {loc.name}")
    raw = input("\nPick: ").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= len(rows):
        print("[-] Cancelled.")
        return None
    return rows[int(raw) - 1]


def print_locations(*, region: str = "", unmapped: bool = False) -> int:
    try:
        catalog = load_catalog()
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 1
    rows = filter_locations(catalog, region=region, unmapped=unmapped)
    targets = raw_targets()
    print(f"{len(rows)} location(s)  (catalog {len(catalog)} total)\n")
    for loc in rows:
        mark = "done" if is_mapped(loc, targets) else "todo"
        extra = f"  vanilla {loc.vanilla_item}" if loc.vanilla_item else ""
        print(f"  {mark:4}  {loc.ap_id:4}  [{loc.region or '?'}] {loc.name}{extra}")
    return 0


def main_locations(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tools locations",
        description="List world location checks with todo/done status",
    )
    p.add_argument("--region", default="", help="Filter, e.g. Crossroads")
    p.add_argument("--todo", action="store_true", help="Only checks without an offset")
    args = p.parse_args(argv)
    return print_locations(region=args.region, unmapped=args.todo)


def main_sync_world(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="python -m tools sync-world",
        description=f"Refresh {CATALOG_PATH} and {ITEMS_CATALOG_PATH} from worlds/darksiders/data",
    ).parse_args(argv)
    return sync_world_catalog()


def sync_world_catalog() -> int:
    if not WORLD_DATA_DIR.is_dir():
        print(f"[ERROR] Missing {WORLD_DATA_DIR}")
        print("        git clone https://github.com/Sachaqc/Archipelago-Darksiders.git world/Archipelago-Darksiders")
        return 1
    locations = parse_data_locations()
    if not locations:
        print(f"[ERROR] No locations in {WORLD_DATA_DIR}")
        return 1
    path = write_catalog(locations)
    active = sum(1 for loc in locations if loc.in_ap)
    deferred = len(locations) - active
    print(f"[OK] Wrote {len(locations)} locations ({active} in AP, {deferred} deferred) -> {path}")
    if not WORLD_ITEMS_JSON.exists():
        print(f"[WARN] Missing {WORLD_ITEMS_JSON}; skipped items catalog")
        return 0
    items = parse_items_json()
    items_path = write_items_catalog(items)
    print(f"[OK] Wrote {len(items)} items -> {items_path}")
    return 0
