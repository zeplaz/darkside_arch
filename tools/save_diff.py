"""Diff two Keen JSON save exports.

ObjectIDs are per (world, RegionID, LayerID). MapTileData is fog-of-war.
This does not write targets.json and is not a RAM scan key.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from tools.save_brief import _props, _val


def _load(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".sav":
        raise ValueError(f"{path} is binary. Export/use the matching .json.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a Keen object dump")
    return data


def flatten_save(data: dict) -> dict[tuple[str, ...], str]:
    """(kind, world, region, layer, object, field) -> value string."""
    out: dict[tuple[str, ...], str] = {}
    root = _props(data)

    souls = root.get("Souls") or {}
    out[("stat", "-", "-", "-", "-", "Souls")] = f"{_val(souls)!r}/{souls.get('type')}"
    for name in ("Health", "Wrath", "Chaos", "SpawnWorld", "SpawnRegion", "SpawnPoint"):
        out[("stat", "-", "-", "-", "-", name)] = repr(_val(root.get(name)))

    stats = _props(root.get("Stats"))
    for key in ("NumberOfChestsOpened", "NumberOfArtifactsCollected", "SoulsCollected"):
        node = stats.get(key) or {}
        out[("stat", "-", "-", "-", "-", key)] = f"{_val(node)!r}/{node.get('type')}"

    for wd in (root.get("WorldData") or {}).get("items", []):
        wp = _props(wd)
        world = str(_val(wp.get("World")) or "")
        for region in (wp.get("Regions") or {}).get("items", []):
            rp = _props(region)
            rid = str(_val(rp.get("RegionID")))
            for layer in (rp.get("Layers") or {}).get("items", []):
                lp = _props(layer)
                lid = str(_val(lp.get("LayerID")))
                for obj in (lp.get("WorldObjects") or {}).get("items", []):
                    op = _props(obj)
                    oid = str(_val(op.get("ObjectID")))
                    data_node = op.get("Data") or {}
                    cls = data_node.get("classname") or ""
                    if cls == "MapTileData":
                        for field, node in _props(data_node).items():
                            out[("map_tile", world, rid, lid, oid, field)] = repr(_val(node))
                    elif cls:
                        for field, node in _props(data_node).items():
                            if isinstance(node, dict) and "value" in node:
                                out[("object", world, rid, lid, oid, f"{cls}.{field}")] = repr(
                                    _val(node)
                                )
                    for sv in (op.get("Values") or {}).get("items", []):
                        sp = _props(sv)
                        key = _val(sp.get("Key"))
                        if not isinstance(key, str):
                            continue
                        out[("object", world, rid, lid, oid, key)] = str(_val(sp.get("Value")))
    return out


def diff_saves(before: dict, after: dict) -> list[tuple[tuple[str, ...], str, str]]:
    a = flatten_save(before)
    b = flatten_save(after)
    keys = sorted(set(a) | set(b))
    rows: list[tuple[tuple[str, ...], str, str]] = []
    for key in keys:
        left = a.get(key, "(absent)")
        right = b.get(key, "(absent)")
        if left != right:
            rows.append((key, left, right))
    return rows


def print_diff(rows: list[tuple[tuple[str, ...], str, str]], include_tiles: bool) -> None:
    shown = 0
    skipped_tiles = 0
    object_ids = []
    for key, left, right in rows:
        kind, world, rid, lid, oid, field = key
        if kind == "map_tile" and not include_tiles:
            skipped_tiles += 1
            continue
        shown += 1
        if kind == "object":
            object_ids.append(oid)
        loc = (
            f"{world} r={rid} L={lid} obj={oid}"
            if kind in {"map_tile", "object"}
            else field
        )
        print(f"  [{kind}] {loc} {field}: {left} -> {right}")
    if not shown and not skipped_tiles:
        print("  (no field changes)")
    elif not shown:
        print(f"  (no object/stat changes; {skipped_tiles} map-tile fog deltas hidden)")
    elif skipped_tiles:
        print(f"  ({skipped_tiles} MapTileData fog deltas hidden; pass --include-tiles)")
    reused = {oid for oid in object_ids if object_ids.count(oid) > 1}
    if reused or object_ids:
        print(
            "\nObjectID is not global. Key is world + RegionID + LayerID + ObjectID. "
            "Do not scan RAM for the integer."
        )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools save-diff")
    p.add_argument("before", type=Path, help="Keen JSON before the action")
    p.add_argument("after", type=Path, help="Keen JSON after the action")
    p.add_argument(
        "--include-tiles",
        action="store_true",
        help="Also print MapTileData Revealed/Visited/Hidden/Active (fog-of-war, not chests)",
    )
    args = p.parse_args(argv)
    try:
        before = _load(args.before)
        after = _load(args.after)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}")
        return 1
    rows = diff_saves(before, after)
    print(f"Keen JSON diff  {args.before}  ->  {args.after}")
    print_diff(rows, include_tiles=args.include_tiles)
    print(
        "\nThis is a save-export diff, not a location map.\n"
        "MapTileData = minimap. Values.Open = linked doors. Chests are unnamed.\n"
        "Game writes .sav; you need two JSON exports. Live flags: python -m tools capture"
    )
    return 0
