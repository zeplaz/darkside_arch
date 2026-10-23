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


def _load(path: Path, slot: Optional[int] = None) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".sav":
        from tools.save_patch import decode_sav_slot

        return decode_sav_slot(path, -1 if slot is None else slot)
    if slot is not None:
        raise ValueError("--slots only applies to .sav files")
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
    info = _props(root.get("GameInfo"))
    for name in ("HealthLevel", "HealthStones", "WrathLevel", "WrathStones", "GameTime"):
        out[("stat", "-", "-", "-", "-", name)] = repr(_val(info.get(name)))

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
    p.add_argument("before", type=Path, help="Keen JSON, or a .sav (use --slots)")
    p.add_argument("after", type=Path, nargs="?", help="Keen JSON or .sav. Omit if --slots on one .sav")
    p.add_argument(
        "--slots",
        nargs=2,
        type=int,
        metavar=("BEFORE", "AFTER"),
        help="Keen slots in a .sav: -1 autosave, 0..9 manual. war-cli only reads autosave; other slots are copied there first.",
    )
    p.add_argument(
        "--include-tiles",
        action="store_true",
        help="Also print MapTileData Revealed/Visited/Hidden/Active (fog-of-war, not chests)",
    )
    p.add_argument(
        "--location",
        default="",
        help="Write the Triggered/Destroyed/Open delta onto this catalog location",
    )
    args = p.parse_args(argv)
    after_path = args.after or args.before
    before_slot = after_slot = None
    if args.slots:
        before_slot, after_slot = args.slots
        if args.before.suffix.lower() != ".sav":
            print("[ERROR] --slots requires a .sav")
            return 2
        after_path = args.after or args.before
    try:
        before = _load(args.before, before_slot)
        after = _load(after_path, after_slot)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}")
        return 1
    rows = diff_saves(before, after)
    label = f"{args.before}"
    if before_slot is not None:
        label += f" slot {before_slot}"
    label += f"  ->  {after_path}"
    if after_slot is not None:
        label += f" slot {after_slot}"
    print(f"Keen save diff  {label}")
    print_diff(rows, include_tiles=args.include_tiles)
    print(
        "\nWorldObjects Values: Destroyed = breakables, Open = doors, "
        "Triggered = chests / one-shots.\n"
        "Key is world + RegionID + LayerID + ObjectID + field. "
        "Object records appear only after they have state."
    )
    if args.location:
        from tools.save_object import identify_location, object_flag_deltas, pick_flag_delta
        from tools.world_catalog import resolve_location

        loc = resolve_location(location=args.location)
        if loc is None:
            return 1
        pick = pick_flag_delta(object_flag_deltas(rows))
        if pick is None:
            print("[-] Not saved: need exactly one Triggered/Destroyed/Open delta, or pass the dashboard to pick.")
            return 1
        action, entry = identify_location(loc, pick)
        print(f"[OK] {action} {entry['id']} Keen {entry['save_object']}")
    return 0
