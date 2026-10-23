"""targets.json read/write shared by capture, scan and the dashboard.

One writer path: every saved offset goes through ``save_target`` so the
row id is stable, SQLite memory_map is re-synced, and nothing is duplicated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from ds_client.models import PROCESS_NAME, TARGETS_FILE, load_targets
from ds_client.sinks import DB_FILE, init_db, sync_memory_map_from_targets


def raw_targets(path: Path = TARGETS_FILE) -> list[dict]:
    """Every row as written, disabled and 0x0 templates included."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [t for t in data.get("targets", []) if isinstance(t, dict)]


def is_template(offsets: object) -> bool:
    """True for a missing offset list or the ``["0x0"]`` placeholder."""
    if not offsets:
        return True
    try:
        return [int(o, 0) if isinstance(o, str) else int(o) for o in offsets] == [0]
    except (TypeError, ValueError):
        return True


def is_mapped(raw: dict) -> bool:
    return not is_template(raw.get("offsets"))


def is_identified(raw: dict) -> bool:
    from tools.save_object import parse_save_object

    return parse_save_object(raw.get("save_object")) is not None


def find_row(label: str, rows: Sequence[dict] | None = None) -> dict | None:
    rows = raw_targets() if rows is None else rows
    return next((t for t in rows if t.get("label") == label), None)


def build_target_entry(
    *,
    target_id: str,
    label: str,
    category: str,
    dtype: str,
    offsets: Sequence[int],
    notes: str,
    region: str = "",
    module: str = PROCESS_NAME,
) -> dict:
    event_type = "LOCATION_CHECK" if category == "location_flag" else "MEMORY_STATE"
    return {
        "id": target_id,
        "enabled": True,
        "event_type": event_type,
        "category": category,
        "label": label,
        "region": region,
        "offsets": [f"0x{o:X}" for o in offsets],
        "type": dtype,
        "module": module,
        "notes": notes,
    }


def upsert_target(new_target: dict, targets_path: Path = TARGETS_FILE) -> str:
    """Insert or update by id. Keys absent from ``new_target`` keep their old value."""
    path = Path(targets_path)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path} root must be a JSON object")
    else:
        data = {"observe_interval_ms": 250, "module": PROCESS_NAME, "targets": []}

    targets = data.setdefault("targets", [])
    if not isinstance(targets, list):
        raise ValueError(f"{path}: 'targets' must be a list")

    action = "appended"
    for i, item in enumerate(targets):
        if isinstance(item, dict) and item.get("id") == new_target["id"]:
            merged = {**item, **new_target}
            if not merged.get("region"):
                merged["region"] = item.get("region", "")
            targets[i] = merged
            action = "updated"
            break
    else:
        targets.append(new_target)

    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return action


def save_target(entry: dict, targets_path: Path = TARGETS_FILE) -> tuple[str, dict]:
    """Upsert one row, reusing the id of an existing row with the same label
    (e.g. the 0x0 template). Returns (action, entry as written)."""
    existing = find_row(entry["label"], raw_targets(targets_path))
    if existing and existing.get("id"):
        entry = {**entry, "id": str(existing["id"])}
    action = upsert_target(entry, targets_path)
    sync_sqlite(targets_path)
    return action, entry


def sync_sqlite(targets_path: Path = TARGETS_FILE, db_path: Path = DB_FILE) -> int:
    """Mirror targets.json into SQLite memory_map (stale rows removed)."""
    _, targets = load_targets(targets_path)
    conn = init_db(db_path)
    try:
        return sync_memory_map_from_targets(conn, targets)
    finally:
        conn.close()
