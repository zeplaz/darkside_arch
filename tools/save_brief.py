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


def brief_save(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    p = _props(data)
    info = _props(p.get("GameInfo"))
    stats = _props(p.get("Stats"))
    items: list[str] = []
    _walk_classnames(p.get("Inventory"), items)
    # unique, keep order
    seen: set[str] = set()
    unique_items: list[str] = []
    for name in items:
        if name in seen:
            continue
        seen.add(name)
        unique_items.append(name)
    flags = _save_values(data)
    return {
        "file": str(path),
        "classname": data.get("classname"),
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
        "true_flags": [k for k, v in flags if str(v).lower() == "true"],
    }


def print_brief(info: dict[str, Any]) -> None:
    print(f"Keen save: {info['classname']}  ({info['file']})")
    print(
        f"  spawn  {info['spawn_world']} / {info['spawn_region']} @ {info['spawn_point']}"
        f"  overview_region={info['overview_region_id']}"
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
    p = argparse.ArgumentParser(prog="python -m tools save-brief")
    p.add_argument("path", type=Path, help="Keen JSON export (not the binary .sav)")
    args = p.parse_args(argv)
    if not args.path.exists():
        print(f"[ERROR] missing {args.path}")
        return 1
    if args.path.suffix.lower() == ".sav":
        print("[ERROR] .sav is binary. Export/use the matching .json.")
        return 1
    print_brief(brief_save(args.path))
    print(
        "\nInstall the .sav into the game save folder, load it, then:\n"
        "  python -m tools scan\n"
        "  (Souls is float; that is the scan default)"
    )
    return 0
