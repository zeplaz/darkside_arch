"""World location and item names from Sacha's world package — no hand-typed labels.

Reads the local world clone when present, else docs/world_*.json.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

from tools.targets import is_mapped as is_row_mapped
from tools.targets import raw_targets

WORLD_LOCATIONS_PY = Path("world/Archipelago-Darksiders/worlds/darksiders/Locations.py")
WORLD_ITEMS_PY = Path("world/Archipelago-Darksiders/worlds/darksiders/Items.py")
CATALOG_PATH = Path("docs") / "world_locations.json"
ITEMS_CATALOG_PATH = Path("docs") / "world_items.json"

_REGION_PREFIXES = tuple(
    sorted(
        (
            "Anvil Ford Challenge",
            "Anvil Ford",
            "The Ashlands Access Tunnel",
            "The Ashlands",
            "Broken Stair Access Tunnel",
            "Broken Stair",
            "Choking Grounds Access Cave",
            "Choking Grounds",
            "Crossroads",
            "Drowned Pass Access Tunnel",
            "Drowned Pass",
            "Dry Road Access Tunnel",
            "Dry Road",
            "The Hollows Access Tunnel",
            "The Hollows",
            "Hollows",
            "Library",
            "Scalding Gallow",
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

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_")


def infer_region(name: str) -> str:
    for prefix in _REGION_PREFIXES:
        if name.startswith(prefix):
            return prefix
    return ""


def infer_kind(name: str) -> str:
    lower = name.lower()
    if "artifact" in lower:
        return "artifact"
    if "armor" in lower:
        return "armor"
    if "cube" in lower:
        return "cube"
    if "chest" in lower:
        return "chest"
    return "location"


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _const_int(node: ast.AST | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(
        node.value, bool
    ):
        return node.value
    return None


def parse_locations_py(path: Path = WORLD_LOCATIONS_PY) -> list[WorldLocation]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    seen: dict[str, WorldLocation] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            name = _const_str(key)
            ap_id = _const_int(value)
            if name is None or ap_id is None:
                continue
            seen[name] = WorldLocation(
                name=name,
                ap_id=ap_id,
                region=infer_region(name),
                kind=infer_kind(name),
            )
    return list(seen.values())


def parse_items_py(path: Path = WORLD_ITEMS_PY) -> list[WorldItem]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    seen: dict[str, WorldItem] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        kind = ""
        if node.targets and isinstance(node.targets[0], ast.Name):
            kind = node.targets[0].id
        if kind in {"ITEM_NAME_TO_ID", "DEFAULT_ITEM_CLASSIFICATION"}:
            continue
        for key, value in zip(node.value.keys, node.value.values):
            name = _const_str(key)
            ap_id = _const_int(value)
            if name is None or ap_id is None:
                continue
            seen[name] = WorldItem(name=name, ap_id=ap_id, kind=kind)
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
        "locations": [
            {"name": loc.name, "ap_id": loc.ap_id, "region": loc.region, "kind": loc.kind}
            for loc in sorted(locations, key=lambda x: (x.region, x.ap_id, x.name))
        ]
    }
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest


def load_catalog() -> list[WorldLocation]:
    if WORLD_LOCATIONS_PY.exists():
        return parse_locations_py()
    if CATALOG_PATH.exists():
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        return [
            WorldLocation(
                name=row["name"],
                ap_id=int(row["ap_id"]),
                region=str(row.get("region") or infer_region(row["name"])),
                kind=str(row.get("kind") or infer_kind(row["name"])),
            )
            for row in data.get("locations", [])
        ]
    raise FileNotFoundError(
        "No world catalog. Clone the world repo or run: python -m tools sync-world"
    )


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
        if (not want or want in loc.region.lower() or want in loc.name.lower())
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
        print(f"  {mark:4}  {loc.ap_id:4}  [{loc.region or '?'}] {loc.name}")
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
        description=f"Refresh {CATALOG_PATH} and {ITEMS_CATALOG_PATH} from the local world clone",
    ).parse_args(argv)
    return sync_world_catalog()


def sync_world_catalog() -> int:
    if not WORLD_LOCATIONS_PY.exists():
        print(f"[ERROR] Missing {WORLD_LOCATIONS_PY}")
        print("        git clone https://github.com/Sachaqc/Archipelago-Darksiders.git world/Archipelago-Darksiders")
        return 1
    locations = parse_locations_py()
    path = write_catalog(locations)
    print(f"[OK] Wrote {len(locations)} locations -> {path}")
    if not WORLD_ITEMS_PY.exists():
        print(f"[WARN] Missing {WORLD_ITEMS_PY}; skipped items catalog")
        return 0
    items = parse_items_py()
    items_path = write_items_catalog(items)
    print(f"[OK] Wrote {len(items)} items -> {items_path}")
    return 0
