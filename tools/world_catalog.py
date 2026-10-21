"""World location names from Sacha's Locations.py — no hand-typed labels.

Reads the local world clone when present, else docs/world_locations.json.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

from ds_client.models import TARGETS_FILE

WORLD_LOCATIONS_PY = Path("world/Archipelago-Darksiders/worlds/darksiders/Locations.py")
CATALOG_PATH = Path("docs") / "world_locations.json"

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


def _raw_targets(path: Path = TARGETS_FILE) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [t for t in data.get("targets", []) if isinstance(t, dict)]


def is_mapped(loc: WorldLocation, targets: list[dict] | None = None) -> bool:
    """True only when a real offset exists (not the 0x0 template)."""
    if targets is None:
        targets = _raw_targets()
    for raw in targets:
        if raw.get("label") != loc.name and raw.get("id") != loc.slug:
            continue
        offs = raw.get("offsets") or []
        if not offs:
            continue
        if offs in (["0x0"], [0], ["0"]):
            continue
        return True
    return False


def filter_locations(
    locations: list[WorldLocation],
    *,
    region: str = "",
    unmapped: bool = False,
) -> list[WorldLocation]:
    targets = _raw_targets()
    want = region.lower()
    out: list[WorldLocation] = []
    for loc in locations:
        if want and want not in loc.region.lower() and want not in loc.name.lower():
            continue
        if unmapped and is_mapped(loc, targets):
            continue
        out.append(loc)
    return out


def resolve_location(
    *,
    location: str = "",
    region: str = "",
    next_unmapped: bool = False,
) -> WorldLocation | None:
    catalog = load_catalog()
    mapped_filter = bool(location or region or next_unmapped)
    rows = filter_locations(catalog, region=region, unmapped=mapped_filter)
    if location:
        q = location.lower()
        exact = [r for r in rows if r.name.lower() == q]
        if exact:
            return exact[0]
        hits = [r for r in rows if q in r.name.lower() or q == r.slug]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            print(f"[ERROR] No catalog match for {location!r}")
            return None
        print(f"[ERROR] {len(hits)} matches for {location!r}; be more specific:")
        for i, hit in enumerate(hits[:20], start=1):
            print(f"  {i:3}  {hit.name}")
        return None
    if next_unmapped:
        return rows[0] if rows else None
    return _pick(rows)


def _pick(rows: list[WorldLocation]) -> WorldLocation | None:
    if not rows:
        print("[-] No unmapped locations in this filter.")
        return None
    print(f"Unmapped location checks ({len(rows)}). Type a number.\n")
    for i, loc in enumerate(rows, start=1):
        print(f"  {i:3}  [{loc.region or '?'}] {loc.name}")
    raw = input("\nPick: ").strip()
    if not raw.isdigit():
        print("[-] Cancelled.")
        return None
    idx = int(raw)
    if not (1 <= idx <= len(rows)):
        print("[-] Out of range.")
        return None
    return rows[idx - 1]


def print_locations(*, region: str = "", unmapped: bool = False) -> int:
    try:
        catalog = load_catalog()
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 1
    rows = filter_locations(catalog, region=region, unmapped=unmapped)
    targets = _raw_targets()
    print(f"{len(rows)} location(s)  (catalog {len(catalog)} total)\n")
    for loc in rows:
        mark = "done" if is_mapped(loc, targets) else "todo"
        print(f"  {mark:4}  {loc.ap_id:4}  [{loc.region or '?'}] {loc.name}")
    return 0


def sync_world_catalog() -> int:
    if not WORLD_LOCATIONS_PY.exists():
        print(f"[ERROR] Missing {WORLD_LOCATIONS_PY}")
        print("        git clone https://github.com/Sachaqc/Archipelago-Darksiders.git world/Archipelago-Darksiders")
        return 1
    locations = parse_locations_py()
    path = write_catalog(locations)
    print(f"[OK] Wrote {len(locations)} locations -> {path}")
    return 0
