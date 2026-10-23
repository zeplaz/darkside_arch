"""Summarize a Keen / Darksiders Warmastered JSON save export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional


def _props(node: Any) -> dict:
    if isinstance(node, dict) and isinstance(node.get("properties"), dict):
        return node["properties"]
    return {}


def _val(node: Any) -> Any:
    if not isinstance(node, dict):
        return None
    if "value" in node:
        return node["value"]
    return None


def _walk_classnames(node: Any, into: list[str]) -> None:
    if isinstance(node, dict):
        name = node.get("classname")
        if isinstance(name, str) and name.startswith("items/"):
            into.append(name)
        for child in node.values():
            _walk_classnames(child, into)
    elif isinstance(node, list):
        for child in node:
            _walk_classnames(child, into)


def _save_values(node: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        if node.get("classname") == "SaveValue":
            p = _props(node)
            key = _val(p.get("Key"))
            val = _val(p.get("Value"))
            if isinstance(key, str):
                out.append((key, str(val)))
        for child in node.values():
            out.extend(_save_values(child))
    elif isinstance(node, list):
        for child in node:
            out.extend(_save_values(child))
    return out


def _flag_counts(flags: list[tuple[str, str]]) -> dict[str, int]:
    counts = {"Triggered": 0, "Destroyed": 0, "Open": 0, "Activated": 0}
    for key, val in flags:
        if key in counts and str(val).lower() == "true":
            counts[key] += 1
    return counts


def brief_from_data(
    data: dict[str, Any], *, file: str = "", slot: Optional[int] = None
) -> dict[str, Any]:
    p = _props(data)
    info = _props(p.get("GameInfo"))
    stats = _props(p.get("Stats"))
    items: list[str] = []
    _walk_classnames(p.get("Inventory"), items)
    seen: set[str] = set()
    unique_items: list[str] = []
    for name in items:
        if name in seen:
            continue
        seen.add(name)
        unique_items.append(name)
    flags = _save_values(data)
    counts = _flag_counts(flags)
    return {
        "file": file,
        "slot": slot,
        "classname": data.get("classname"),
        "userid": _val(info.get("UserId")),
        "difficulty": _val(info.get("DifficultyLevel")),
        "health_level": _val(info.get("HealthLevel")),
        "wrath_level": _val(info.get("WrathLevel")),
        "game_time": _val(info.get("GameTime")),
        "overview_region_id": _val(info.get("OverviewRegionID")),
        "spawn_world": _val(p.get("SpawnWorld")),
        "spawn_region": _val(p.get("SpawnRegion")),
        "spawn_point": _val(p.get("SpawnPoint")),
        "souls": _val(p.get("Souls")),
        "souls_type": (p.get("Souls") or {}).get("type"),
        "health": _val(p.get("Health")),
        "chests_opened": _val(stats.get("NumberOfChestsOpened")),
        "artifacts_collected": _val(stats.get("NumberOfArtifactsCollected")),
        "kills": _val(stats.get("NumberOfKills")),
        "inventory_item_types": unique_items,
        "save_value_count": len(flags),
        "triggered": counts["Triggered"],
        "destroyed": counts["Destroyed"],
        "open": counts["Open"],
        "activated": counts["Activated"],
        "true_flags": [k for k, v in flags if str(v).lower() == "true"],
    }


def brief_save(path: Path, slot: Optional[int] = None) -> dict[str, Any]:
    if path.suffix.lower() == ".sav":
        from tools.save_patch import decode_sav_slot

        data = decode_sav_slot(path, -1 if slot is None else slot)
        return brief_from_data(data, file=str(path), slot=-1 if slot is None else slot)
    if slot is not None:
        raise ValueError("--slot only applies to .sav files")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a Keen object dump")
    return brief_from_data(data, file=str(path), slot=slot)


def export_slot_json(sav: Path, slot: int, dest: Path) -> Path:
    from tools.save_patch import decode_sav_slot

    data = decode_sav_slot(sav, slot)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return dest


SCRATCH_SLOTS = Path("saves") / "_scratch" / "slots"


def default_export_path(slot: int) -> Path:
    name = "slot_auto.json" if slot == -1 else f"slot_{slot}.json"
    return SCRATCH_SLOTS / name


def print_brief(info: dict[str, Any]) -> None:
    slot = info.get("slot")
    slot_bit = f"  slot {slot}" if slot is not None else ""
    print(f"Keen save: {info['classname']}  ({info['file']}){slot_bit}")
    print(
        f"  spawn  {info['spawn_world']} / {info['spawn_region']} @ {info['spawn_point']}"
        f"  overview_region={info['overview_region_id']}  UserId={info.get('userid')}"
    )
    print(
        f"  souls  {info['souls']} ({info['souls_type']})  "
        f"health={info['health']}  chests={info['chests_opened']}  "
        f"artifacts={info['artifacts_collected']}"
    )
    print(
        f"  time={info['game_time']}  kills={info['kills']}  "
        f"HP stones={info['health_level']}  wrath stones={info['wrath_level']}"
    )
    print(
        f"  objects  Triggered={info.get('triggered', 0)}  "
        f"Destroyed={info.get('destroyed', 0)}  Open={info.get('open', 0)}"
    )
    print("  inventory types:")
    for name in info["inventory_item_types"]:
        if name.startswith("items/artifact"):
            continue
        print(f"    {name}")
    arts = [n for n in info["inventory_item_types"] if n.startswith("items/artifact")]
    if arts:
        print(f"    artifacts: {', '.join(arts)}")
    print(f"  SaveValue flags: {info['save_value_count']} ({len(info['true_flags'])} true)")
    interesting = [
        k
        for k in info["true_flags"]
        if any(
            s in k.lower()
            for s in ("chest", "door", "vulgrim", "quest", "crossblade", "library", "opened")
        )
    ]
    if interesting:
        print("  notable true flags:")
        for k in interesting[:40]:
            print(f"    {k}")


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tools save-brief",
        description="Summarize one Keen JSON dump, or one .sav slot (war decode).",
    )
    p.add_argument("path", type=Path, help="Keen JSON, or a Warmastered .sav with --slot")
    p.add_argument("--slot", type=int, help="Keen slot in a .sav: -1 autosave, 0..9")
    p.add_argument("--all", action="store_true", help="Brief every occupied slot in a .sav")
    p.add_argument("--export", nargs="?", const="", metavar="JSON", help="Write decoded JSON (default saves/_scratch/slots/)")
    args = p.parse_args(argv)
    if not args.path.exists():
        print(f"[ERROR] missing {args.path}")
        return 1
    try:
        if args.all:
            if args.path.suffix.lower() != ".sav":
                print("[ERROR] --all requires a .sav")
                return 2
            from tools.save_object import occupied_slots

            for slot in occupied_slots(args.path):
                info = brief_save(args.path, slot)
                print_brief(info)
                print()
            return 0
        if args.export is not None:
            if args.path.suffix.lower() != ".sav":
                print("[ERROR] --export requires a .sav")
                return 2
            slot = -1 if args.slot is None else args.slot
            dest = Path(args.export) if args.export else default_export_path(slot)
            out = export_slot_json(args.path, slot, dest)
            print(f"[OK] wrote {out}")
        print_brief(brief_save(args.path, args.slot))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}")
        return 1
    return 0
