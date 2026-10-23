"""Keen dumps in ``game_data/``: WorldObject identity order and chest persist writes.

``Chests.json`` is a RegionLayer dump. Every object ends with ObjectID, RegionID,
LayerID (then Name). Heap capture uses that packed triple as the first-choice
anchor. It is an arena layer (r=295 L=25), not Seraphim Hotel — the *layout*
is what we take, not those ObjectIDs.

The ``.s`` scripts are chest ``onOpen`` bytecode. They call
``this.setSaveValue("Triggered", true)`` when ``AutoPersist`` is set. That is
the save flag name, not a RAM RVA. Bytecode PCs (``0x02a4``) are instruction
addresses, not heap offsets.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

GAME_DATA = Path(__file__).resolve().parent.parent / "game_data"
IDENTITY_FIELDS = ("ObjectID", "RegionID", "LayerID")
HEALTH_CHEST_CLASS = "special_casket/chest_healthchest"

_SAVE_VALUE = re.compile(
    r'string "([^"]+)"\s+bool true\s+int 2\s+identifier this\s+method setSaveValue',
    re.MULTILINE,
)


def _objects() -> list[dict[str, Any]]:
    path = GAME_DATA / "Chests.json"
    if not path.is_file():
        return []
    root = json.loads(path.read_text(encoding="utf-8"))
    return root["properties"]["Root"]["properties"]["Objects"]


@lru_cache(maxsize=1)
def identity_fields() -> tuple[str, ...]:
    """Property order of the identity ints, taken from the first dumped object."""
    for obj in _objects():
        keys = tuple(k for k in obj.get("properties", {}) if k in IDENTITY_FIELDS)
        if keys == IDENTITY_FIELDS:
            return keys
    return IDENTITY_FIELDS


@lru_cache(maxsize=1)
def persist_flag() -> str:
    """Save-value key written by every chest ``onOpen`` in ``game_data/*.s``."""
    keys: set[str] = set()
    if GAME_DATA.is_dir():
        for path in GAME_DATA.glob("*.s"):
            keys.update(_SAVE_VALUE.findall(path.read_text(encoding="utf-8")))
    if keys == {"Triggered"}:
        return "Triggered"
    if len(keys) == 1:
        return next(iter(keys))
    return "Triggered"


def chest_classnames() -> set[str]:
    return {
        str(obj.get("classname") or "")
        for obj in _objects()
        if str(obj.get("classname") or "").startswith("special_casket/chest_")
    }
