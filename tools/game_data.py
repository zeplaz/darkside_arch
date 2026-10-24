"""Keen dumps in ``game_data/``. Packed identity is ObjectID, RegionID, LayerID.

``.s`` scripts persist chests with ``setSaveValue("Triggered", true)``.
Hotel names: ``SB_G_Chest_HealthChest_01`` (r=2 L=6 obj=342),
``CI_SB_Exit_Chest_HealthChest`` (r=260 L=1 obj=16).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

GAME_DATA = Path(__file__).resolve().parent.parent / "game_data"
FLAG_KEYS = ("Triggered", "Destroyed", "Open", "Activated")
PERSIST_FLAG = "Triggered"
HOTEL_CHEST_NAMES = {
    "Seraphim Hotel Life Chest 1": "SB_G_Chest_HealthChest_01",
    "Seraphim Hotel Life Chest 2": "CI_SB_Exit_Chest_HealthChest",
}
_SAVE_VALUE = re.compile(
    r'string "([^"]+)"\s+bool true\s+int 2\s+identifier this\s+method setSaveValue',
    re.MULTILINE,
)


@lru_cache(maxsize=1)
def persist_flag() -> str:
    keys: set[str] = set()
    if GAME_DATA.is_dir():
        for path in GAME_DATA.glob("*.s"):
            keys.update(_SAVE_VALUE.findall(path.read_text(encoding="utf-8")))
    return next(iter(keys)) if len(keys) == 1 else PERSIST_FLAG


@lru_cache(maxsize=1)
def _objects() -> list[dict[str, Any]]:
    objs: list[dict[str, Any]] = []
    if not GAME_DATA.is_dir():
        return objs
    for path in GAME_DATA.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("classname") != "RegionLayer":
            continue
        root = data.get("properties", {}).get("Root", {})
        objs.extend(root.get("properties", {}).get("Objects") or [])
    return objs


def class_kind(classname: str) -> str:
    low = classname.lower()
    if "chest" in low:
        return "chest"
    if "door" in low:
        return "door"
    if "artifact" in low:
        return "artifact"
    return ""


def _placed(obj: dict[str, Any]) -> Optional[dict[str, Any]]:
    props = obj.get("properties") or {}
    try:
        classname = str(obj.get("classname") or "")
        return {
            "name": str(props.get("Name") or ""),
            "classname": classname,
            "class_kind": class_kind(classname),
            "world": "overworld",
            "region_id": int(props["RegionID"]),
            "layer_id": int(props["LayerID"]),
            "object_id": int(props["ObjectID"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def find_object(name: str) -> Optional[dict[str, Any]]:
    for obj in _objects():
        props = obj.get("properties") or {}
        if props.get("Name") == name:
            return _placed(obj)
    return None


def find_by_ids(region_id: int, layer_id: int, object_id: int) -> Optional[dict[str, Any]]:
    for obj in _objects():
        placed = _placed(obj)
        if (
            placed
            and placed["region_id"] == region_id
            and placed["layer_id"] == layer_id
            and placed["object_id"] == object_id
        ):
            return placed
    return None


def hotel_chest(label: str) -> Optional[dict[str, Any]]:
    name = HOTEL_CHEST_NAMES.get(label)
    return find_object(name) if name else None
