"""Keen dumps in ``game_data/``. Packed identity is ObjectID, RegionID, LayerID.

Each ``*.json`` ``RegionLayer`` dump is a source of *placed objects* (chests,
artifacts, doors, …). Every placed object records which file it came from
(``source``), so the dashboard / database can keep clear provenance:
``Chests.json`` vs ``Artifacts.json`` vs "save-diff" vs missing.

``.s`` scripts persist chests with ``setSaveValue("Triggered", true)``.
Hotel names: ``SB_G_Chest_HealthChest_01`` (r=2 L=6 obj=342),
``CI_SB_Exit_Chest_HealthChest`` (r=260 L=1 obj=16).

Artifacts are ``ItemActor`` objects whose ``ItemType`` starts with
``artifact_`` (``artifact_pawn`` / ``artifact_master`` / ``artifact_general``).
They carry ``ObjectID`` + ``RegionID`` but no ``LayerID``, so their identity
uses ``layer_id = 0`` until a region dump provides one.
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
def _objects() -> list[tuple[str, dict[str, Any]]]:
    """``(source_filename, raw_object)`` for every object in every RegionLayer dump."""
    objs: list[tuple[str, dict[str, Any]]] = []
    if not GAME_DATA.is_dir():
        return objs
    for path in sorted(GAME_DATA.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("classname") != "RegionLayer":
            continue
        root = data.get("properties", {}).get("Root", {})
        for obj in root.get("properties", {}).get("Objects") or []:
            if isinstance(obj, dict):
                objs.append((path.name, obj))
    return objs


def class_kind(classname: str, item_type: str = "") -> str:
    """chest / door / artifact / "" from the object's classname (and ItemType)."""
    low = f"{classname} {item_type}".lower()
    if "artifact" in low:
        return "artifact"
    if "chest" in low or "casket" in low:
        return "chest"
    if "door" in low:
        return "door"
    return ""


def _flag_names(obj: dict[str, Any]) -> list[str]:
    """Quest flag names anywhere in the object (``SaveDataModule.FlagInfoList[].FlagName``).

    Sword pieces / quest objects persist this way instead of a WorldObject
    ``Values`` key (e.g. ``SwordPiece_05`` under ``QuestItems``)."""
    names: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("classname") == "FlagInfo":
                props = node.get("properties") or {}
                name = props.get("FlagName")
                if isinstance(name, str) and name:
                    names.append(name)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(obj)
    return names


def _placed(obj: dict[str, Any], source: str) -> Optional[dict[str, Any]]:
    props = obj.get("properties") or {}
    try:
        classname = str(obj.get("classname") or "")
        item_type = str(props.get("ItemType") or "")
        flags = _flag_names(obj)
        kind = class_kind(classname, item_type)
        if not kind and flags:
            kind = "quest"
        return {
            "name": str(props.get("Name") or ""),
            "classname": classname,
            "item_type": item_type,
            "class_kind": kind,
            "flag_names": flags,
            "world": "overworld",
            "region_id": int(props["RegionID"]),
            # Artifact dumps omit LayerID; default to 0 until a dump provides it.
            "layer_id": int(props.get("LayerID", 0)),
            "object_id": int(props["ObjectID"]),
            "source": source,
        }
    except (KeyError, TypeError, ValueError):
        return None


def placed_objects(*, kind: str = "") -> list[dict[str, Any]]:
    """Every placed object in game_data, optionally filtered by ``kind``."""
    out: list[dict[str, Any]] = []
    for source, obj in _objects():
        placed = _placed(obj, source)
        if placed and (not kind or placed["class_kind"] == kind):
            out.append(placed)
    return out


def find_object(name: str) -> Optional[dict[str, Any]]:
    for source, obj in _objects():
        placed = _placed(obj, source)
        if placed and placed["name"] == name:
            return placed
    return None


def find_by_ids(region_id: int, layer_id: int, object_id: int) -> Optional[dict[str, Any]]:
    for source, obj in _objects():
        placed = _placed(obj, source)
        if (
            placed
            and placed["region_id"] == region_id
            and placed["layer_id"] == layer_id
            and placed["object_id"] == object_id
        ):
            return placed
    return None


def find_object_by_id(object_id: int, region_id: Optional[int] = None) -> Optional[dict[str, Any]]:
    for source, obj in _objects():
        placed = _placed(obj, source)
        if (
            placed
            and placed["object_id"] == object_id
            and (region_id is None or placed["region_id"] == region_id)
        ):
            return placed
    return None


def hotel_chest(label: str) -> Optional[dict[str, Any]]:
    name = HOTEL_CHEST_NAMES.get(label)
    return find_object(name) if name else None
