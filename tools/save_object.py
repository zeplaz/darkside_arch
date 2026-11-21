"""Keen WorldObject identity from a save-diff. Not a RAM address."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from tools.game_data import FLAG_KEYS, find_by_ids, find_object, hotel_chest, persist_flag, placed_objects
from tools.save_brief import load_save
from tools.save_diff import diff_saves
from tools.save_install import APP_ID, steam_userdata_roots
from tools.targets import find_row, is_template, save_target
from tools.world_catalog import WorldLocation


def parse_save_object(raw: object) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    world = str(raw.get("world") or "").strip()
    key = str(raw.get("value_key") or raw.get("key") or "").strip()
    source = str(raw.get("source") or "").strip()
    try:
        rid = int(raw.get("region_id"))
        lid = int(raw.get("layer_id"))
        oid = int(raw.get("object_id"))
    except (TypeError, ValueError):
        return None
    if not world or not key:
        return None
    return {
        "world": world,
        "region_id": rid,
        "layer_id": lid,
        "object_id": oid,
        "value_key": key,
        "source": source,
    }


def format_save_object(obj: dict[str, Any]) -> str:
    return (
        f"{obj['world']} r={obj['region_id']} L={obj['layer_id']} "
        f"obj={obj['object_id']} {obj['value_key']}"
    )


def _ids_equal(delta: dict[str, Any], placed: dict[str, Any]) -> bool:
    return (
        int(delta["region_id"]) == int(placed["region_id"])
        and int(delta["layer_id"]) == int(placed["layer_id"])
        and int(delta["object_id"]) == int(placed["object_id"])
    )


def _is_set(delta: dict[str, Any]) -> bool:
    return delta["old"] == "(absent)" and "true" in str(delta["new"]).lower()


def _is_cleared(delta: dict[str, Any]) -> bool:
    return "true" in str(delta["old"]).lower() and delta["new"] == "(absent)"


def annotate_flag(delta: dict[str, Any]) -> dict[str, Any]:
    placed = find_by_ids(int(delta["region_id"]), int(delta["layer_id"]), int(delta["object_id"]))
    if placed:
        delta = {**delta, "name": placed["name"], "classname": placed["classname"], "class_kind": placed["class_kind"]}
    if not delta.get("class_kind"):
        inferred = {"Destroyed": "breakable", "Open": "door", "Activated": "other", "Persisting": "artifact"}.get(delta["value_key"], "")
        if inferred:
            delta = {**delta, "class_kind": inferred}
    return delta


def object_flag_deltas(
    rows: list[tuple[tuple[str, ...], str, str]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, left, right in rows:
        kind, world, rid, lid, oid, field = key
        if kind != "object" or field not in (*FLAG_KEYS, "Persisting"):
            continue
        out.append(
            annotate_flag(
                {
                    "world": world,
                    "region_id": int(rid),
                    "layer_id": int(lid),
                    "object_id": int(oid),
                    "value_key": field,
                    "old": left,
                    "new": right,
                }
            )
        )
    return out


def _persist_key(loc: Optional[WorldLocation]) -> str:
    """The flag an AP kind actually persists. Chests → Triggered; artifacts mark
    their pickup ``Persisting`` (they never write Triggered)."""
    if loc and loc.kind == "artifact":
        return "Persisting"
    return persist_flag()


def filter_flags(
    flags: list[dict[str, Any]], loc: Optional[WorldLocation] = None
) -> tuple[list[dict[str, Any]], int, bool]:
    """Keep the persist key for this AP kind (chests → Triggered, artifacts → Persisting)."""
    shown = list(flags)
    if loc and loc.kind in {"chest", "artifact", "armor", "cube"}:
        key = _persist_key(loc)
        shown = [d for d in shown if d["value_key"] == key]
        if loc.kind == "chest":
            chests = [d for d in shown if d.get("class_kind") == "chest"]
            if chests:
                shown = chests
    hidden = len(flags) - len(shown)
    reversed_slots = bool(shown) and all(_is_cleared(d) for d in shown)
    return shown, hidden, reversed_slots


def pick_flag_delta(
    deltas: list[dict[str, Any]], loc: Optional[WorldLocation] = None
) -> Optional[dict[str, Any]]:
    placed = hotel_chest(loc.name) if loc else None
    if placed:
        match = [d for d in deltas if _ids_equal(d, placed)]
        if len(match) == 1:
            return match[0]
    fresh = [d for d in deltas if d["value_key"] == _persist_key(loc) and _is_set(d)]
    if len(fresh) == 1:
        return fresh[0]
    if len(deltas) == 1:
        return deltas[0]
    return None


def find_default_sav() -> Optional[Path]:
    names = ("svd_fmt_0_0.sav", "keen_savegame_0_0.sav")
    for root in steam_userdata_roots():
        if not root.is_dir():
            continue
        for user in root.iterdir():
            remote = user / APP_ID / "remote"
            for name in names:
                for path in (remote / "autocloud" / "save" / name, remote / name):
                    if path.is_file():
                        return path
    return None


def diff_sav_slots(
    sav: Path, before_slot: int, after_slot: int, loc: Optional[WorldLocation] = None
) -> dict[str, Any]:
    rows = diff_saves(load_save(sav, before_slot), load_save(sav, after_slot))
    raw = object_flag_deltas(rows)
    match, hidden, reversed_slots = filter_flags(raw, loc)
    placed = hotel_chest(loc.name) if loc else None
    stats = [
        {"field": k[5], "old": left, "new": right}
        for k, left, right in rows
        if k[0] == "stat"
        and k[5] in {"NumberOfChestsOpened", "Health", "HealthLevel", "GameTime"}
    ]
    return {
        "path": str(sav),
        "before_slot": before_slot,
        "after_slot": after_slot,
        "flags": raw,
        "match": match,
        "hidden": hidden,
        "reversed": reversed_slots,
        "placed": placed,
        "stats": stats,
        "pick": pick_flag_delta(match, loc),
        "loc_kind": loc.kind if loc else "",
    }


def identify_location(loc: WorldLocation, obj: dict[str, Any]) -> tuple[str, dict]:
    obj = {**obj, "source": str(obj.get("source") or "save-diff")}
    parsed = parse_save_object(obj)
    if parsed is None:
        raise ValueError("save_object needs world, region_id, layer_id, object_id, value_key")
    existing = find_row(loc.name) or {}
    ram = not is_template(existing.get("offsets"))
    entry = {
        "id": loc.slug,
        "enabled": bool(existing.get("enabled", True)) if ram else False,
        "event_type": "LOCATION_CHECK",
        "category": "location_flag",
        "label": loc.name,
        "region": loc.region,
        "offsets": list(existing.get("offsets") or ["0x0"]),
        "type": str(existing.get("type") or "uint8"),
        "bitmask": existing.get("bitmask", "0x01"),
        "save_object": parsed,
        "notes": (existing.get("notes") or "").strip()
        or f"Keen {format_save_object(parsed)} (from {parsed['source']}). RAM offset not mapped.",
    }
    if ram:
        entry["module"] = existing.get("module")
        entry["type"] = existing.get("type") or "uint8"
    return save_target(entry)


def identify_from_placed(loc: WorldLocation, placed: dict[str, Any]) -> tuple[str, dict]:
    """Identify a location from a game_data placed object (chest/artifact JSON)."""
    from tools.game_data import persist_flag

    obj = {
        "world": str(placed.get("world") or "overworld"),
        "region_id": int(placed["region_id"]),
        "layer_id": int(placed.get("layer_id") or 0),
        "object_id": int(placed["object_id"]),
        "value_key": str(placed.get("value_key") or persist_flag()),
        "source": str(placed.get("source") or ""),
    }
    return identify_location(loc, obj)


def write_identity(
    loc: WorldLocation,
    pick: Optional[dict[str, Any]],
    *,
    dry_run: bool = False,
    flags: Optional[list[dict[str, Any]]] = None,
) -> int:
    if parse_save_object(pick) is None:
        print("[-] Need exactly one Triggered/Destroyed/Open delta.")
        for d in flags or []:
            print(
                f"    {d['world']} r={d['region_id']} L={d['layer_id']} "
                f"obj={d['object_id']} {d['value_key']}: {d['old']} -> {d['new']}"
            )
        return 1
    if dry_run:
        print(json.dumps(pick, indent=2))
        return 0
    action, entry = identify_location(loc, pick)  # type: ignore[arg-type]
    print(f"[OK] {action} {entry['id']} Keen {entry['save_object']}")
    return 0


def write_identity_from_slots(
    loc: WorldLocation,
    sav: Optional[Path] = None,
    before: Optional[int] = None,
    after: Optional[int] = None,
    *,
    dry_run: bool = False,
) -> int:
    sav = sav or find_default_sav()
    if sav is None:
        print("[ERROR] No .sav. Pass --sav PATH")
        return 1
    if before is None or after is None:
        print("[ERROR] --slots BEFORE AFTER is required with --sav")
        return 2
    print(f"[*] {loc.name}  save-diff  {sav}  slots {before} -> {after}")
    try:
        result = diff_sav_slots(sav, before, after, loc)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[-] {exc}")
        return 1
    return write_identity(loc, result.get("pick"), dry_run=dry_run, flags=result.get("match") or result["flags"])


def _pick_placed(objs: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for i, obj in enumerate(objs, start=1):
        print(
            f"  {i:3}  [{obj['class_kind'] or '?'}] {obj['name'] or '(unnamed)'}"
            f"  r={obj['region_id']} L={obj['layer_id']} obj={obj['object_id']}"
            f"  ({obj['source']})"
        )
    raw = input("\nPick: ").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= len(objs):
        print("[-] Cancelled.")
        return None
    return objs[int(raw) - 1]


def main_identify(argv: Optional[list[str]] = None) -> int:
    """Identify a location from a game_data dump (Chests.json / Artifacts.json)
    instead of a two-slot save diff. Used when the save has no per-object flag
    (artifacts) or when you already know the Keen object."""
    from tools.world_catalog import resolve_location

    p = argparse.ArgumentParser(
        prog="python -m tools identify",
        description="Identify a location from a game_data placed object (no save diff).",
        epilog='python -m tools identify --location "Crossroads Subway Station Artifact" --object Artifact_Pawn_01',
    )
    p.add_argument("--location", required=True, help="Exact catalog name or unique substring")
    p.add_argument("--object", default="", help="game_data object Name (e.g. Artifact_Pawn_01)")
    p.add_argument("--kind", default="", choices=["", "artifact", "chest", "door", "quest"], help="Filter the object picker")
    p.add_argument("--dry-run", action="store_true", help="Print the result; do not write targets.json")
    args = p.parse_args(argv)

    loc = resolve_location(location=args.location)
    if loc is None:
        return 1

    if args.object:
        obj = find_object(args.object)
        if obj is None:
            print(f"[ERROR] No game_data object named {args.object!r}. Run with --kind to list.")
            return 1
        placed = obj
    else:
        objs = placed_objects(kind=args.kind)
        if not objs:
            print(f"[-] No placed objects in game_data (kind={args.kind or 'any'}).")
            return 1
        placed = _pick_placed(objs)
        if placed is None:
            return 1

    print(f"[*] {loc.name}  <-  {placed['name']} ({placed['source']})")
    if args.dry_run:
        print(json.dumps(placed, indent=2))
        return 0
    action, entry = identify_from_placed(loc, placed)
    print(f"[OK] {action} {entry['id']} Keen {entry['save_object']}")
    return 0
