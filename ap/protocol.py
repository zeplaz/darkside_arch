"""Thin Archipelago 0.6.7 websocket packet helpers. No world-package import."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

GAME_NAME = "Darksiders"
AP_VERSION = {"major": 0, "minor": 6, "build": 7, "class": "Version"}
ITEMS_HANDLING_ALL = 0b111
DEFAULT_TAGS = ("Darksiders",)


class ClientStatus:
    CLIENT_UNKNOWN = 0
    CLIENT_CONNECTED = 5
    CLIENT_READY = 10
    CLIENT_PLAYING = 20
    CLIENT_GOAL = 30


@dataclass(frozen=True)
class NetworkItem:
    item: int
    location: int
    player: int
    flags: int = 0
    index: int = 0


def encode_packets(packets: Sequence[Mapping[str, Any]]) -> str:
    return json.dumps(list(packets), separators=(",", ":"), ensure_ascii=False)


def decode_packets(raw: str) -> list[dict[str, Any]]:
    data = json.loads(raw)
    if isinstance(data, dict):
        return [data]
    if not isinstance(data, list):
        raise ValueError("AP payload must be a JSON object or array")
    out: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("AP packet must be an object")
        out.append(row)
    return out


def parse_network_item(obj: Any, index: int = 0) -> NetworkItem:
    if isinstance(obj, dict):
        return NetworkItem(
            item=int(obj["item"]),
            location=int(obj["location"]),
            player=int(obj["player"]),
            flags=int(obj.get("flags") or 0),
            index=index,
        )
    if isinstance(obj, (list, tuple)) and len(obj) >= 3:
        flags = int(obj[3]) if len(obj) > 3 else 0
        return NetworkItem(
            item=int(obj[0]),
            location=int(obj[1]),
            player=int(obj[2]),
            flags=flags,
            index=index,
        )
    raise TypeError(f"cannot parse NetworkItem from {type(obj)!r}")


def connect_packet(
    *,
    slot: str,
    password: str = "",
    uuid: str,
    game: str = GAME_NAME,
    items_handling: int = ITEMS_HANDLING_ALL,
    tags: Sequence[str] = DEFAULT_TAGS,
    slot_data: bool = False,
) -> dict[str, Any]:
    return {
        "cmd": "Connect",
        "password": password or None,
        "name": slot,
        "version": dict(AP_VERSION),
        "tags": list(tags),
        "items_handling": items_handling,
        "uuid": uuid,
        "game": game,
        "slot_data": slot_data,
    }


def location_checks_packet(location_ids: Sequence[int]) -> dict[str, Any]:
    return {"cmd": "LocationChecks", "locations": [int(x) for x in location_ids]}


def status_update_packet(status: int) -> dict[str, Any]:
    return {"cmd": "StatusUpdate", "status": int(status)}


def sync_packet() -> dict[str, Any]:
    return {"cmd": "Sync"}
