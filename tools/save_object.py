"""Keen WorldObject identity from a save-diff. Not a RAM address."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from tools.game_data import FLAG_KEYS, find_by_ids, hotel_chest, persist_flag
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
        inferred = {"Destroyed": "breakable", "Open": "door", "Activated": "other"}.get(delta["value_key"], "")
        if inferred:
            delta = {**delta, "class_kind": inferred}
    return delta


def object_flag_deltas(
    rows: list[tuple[tuple[str, ...], str, str]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, left, right in rows:
        kind, world, rid, lid, oid, field = key
        if kind != "object" or field not in FLAG_KEYS:
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


def filter_flags(
    flags: list[dict[str, Any]], loc: Optional[WorldLocation] = None
) -> tuple[list[dict[str, Any]], int, bool]:
    """Keep the persist key for this AP kind (chests → Triggered). Drop doors/breakables."""
    shown = list(flags)
    if loc and loc.kind in {"chest", "artifact", "armor", "cube"}:
        key = persist_flag()
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
    fresh = [d for d in deltas if d["value_key"] == persist_flag() and _is_set(d)]
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
        or f"Keen {format_save_object(parsed)}. RAM offset not mapped.",
    }
    if ram:
        entry["module"] = existing.get("module")
        entry["type"] = existing.get("type") or "uint8"
    return save_target(entry)


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
