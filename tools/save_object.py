"""Keen WorldObject identity from a save-diff — chests, doors, breakables.

Not a RAM address. ds_client still skips the row until offsets are mapped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from tools.game_data import persist_flag
from tools.save_diff import diff_saves, _load
from tools.save_install import steam_userdata_roots, APP_ID
from tools.save_patch import SLOT_LENGTH, slot_byte_offset
from tools.targets import find_row, is_template, save_target
from tools.world_catalog import WorldLocation

FLAG_KEYS = ("Triggered", "Destroyed", "Open", "Activated")


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


def is_identified(raw: dict) -> bool:
    return parse_save_object(raw.get("save_object")) is not None


def object_flag_deltas(
    rows: list[tuple[tuple[str, ...], str, str]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, left, right in rows:
        kind, world, rid, lid, oid, field = key
        if kind != "object" or field not in FLAG_KEYS:
            continue
        out.append(
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
    return out


def pick_flag_delta(deltas: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Prefer a new persist-flag record (chest ``setSaveValue``). Else the only flag delta."""
    key = persist_flag()
    fresh = [
        d
        for d in deltas
        if d["value_key"] == key and d["old"] == "(absent)" and "true" in d["new"].lower()
    ]
    if len(fresh) == 1:
        return fresh[0]
    if len(deltas) == 1:
        return deltas[0]
    return None


def occupied_slots(sav: Path) -> list[int]:
    raw = sav.read_bytes()
    found: list[int] = []
    for slot in [-1, *range(10)]:
        off = slot_byte_offset(slot)
        chunk = raw[off : off + SLOT_LENGTH]
        if len(chunk) == SLOT_LENGTH and chunk[:4] == b"DSAV":
            found.append(slot)
    return found


def find_default_sav() -> Optional[Path]:
    names = ("svd_fmt_0_0.sav", "keen_savegame_0_0.sav")
    for root in steam_userdata_roots():
        if not root.is_dir():
            continue
        for user in root.iterdir():
            remote = user / APP_ID / "remote"
            for name in names:
                for path in (
                    remote / "autocloud" / "save" / name,
                    remote / name,
                ):
                    if path.is_file():
                        return path
    return None


def diff_sav_slots(sav: Path, before_slot: int, after_slot: int) -> dict[str, Any]:
    before = _load(sav, before_slot)
    after = _load(sav, after_slot)
    rows = diff_saves(before, after)
    flags = object_flag_deltas(rows)
    stats = [
        {"field": k[5], "old": left, "new": right}
        for k, left, right in rows
        if k[0] == "stat"
        and k[5] in {"NumberOfChestsOpened", "Health", "HealthLevel", "GameTime"}
    ]
    pick = pick_flag_delta(flags)
    return {
        "path": str(sav),
        "before_slot": before_slot,
        "after_slot": after_slot,
        "flags": flags,
        "stats": stats,
        "pick": pick,
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
        "notes": (
            existing.get("notes") or ""
        ).strip()
        or f"Keen {format_save_object(parsed)}. RAM offset not mapped.",
    }
    if ram:
        entry["module"] = existing.get("module")
        entry["type"] = existing.get("type") or "uint8"
    return save_target(entry)
