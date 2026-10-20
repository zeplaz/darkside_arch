"""CLI for developer mapping tools (scan / tag / sync / export)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Optional

from ds_client.models import TARGETS_FILE, load_targets
from ds_client.sinks import (
    DB_FILE,
    init_db,
    sync_memory_map_from_targets,
    tag_latest_event,
    upsert_memory_map_from_target,
)
from tools.export_docs import DOCS_PATH, export_docs


def cmd_export_docs(out: Path) -> int:
    path = export_docs(out_path=out, sync_targets=True)
    print(f"[OK] Wrote {path}")
    return 0


def cmd_sync_map() -> int:
    try:
        _, targets = load_targets()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"[ERROR] Failed to load {TARGETS_FILE}: {exc}")
        return 1
    conn = init_db()
    try:
        n = sync_memory_map_from_targets(conn, targets)
        print(f"[OK] Synced {n} target(s) into {DB_FILE} memory_map")
    finally:
        conn.close()
    return 0


def cmd_tag(label: str, region: str, category: str) -> int:
    conn = init_db()
    try:
        row = tag_latest_event(conn, label, region=region, category=category)
        if row is None:
            print(
                "[ERROR] No events to tag. "
                "Run `python -m ds_client`, trigger a delta, then retry."
            )
            return 1
        print(
            f"[OK] Tagged log_id={row['log_id']} "
            f"target={row['target_id'] or '-'} "
            f"as label={label!r} "
            f"({row['prev_value'] or '?'} -> {row['value_raw']})"
        )
        target_id = row["target_id"]
        if not target_id:
            return 0
        _, targets = load_targets()
        match = next((t for t in targets if t.id == target_id), None)
        if match is None:
            return 0
        upsert_memory_map_from_target(
            conn,
            replace(
                match,
                label=label,
                region=region or match.region,
                category=category or match.category,
            ),
            verified_value=str(row["value_raw"]),
            address_hex=str(row["address_hex"]),
        )
        print(f"[OK] Updated memory_map for target_id={target_id}")
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools",
        description="darkside_arch developer tools (mapping / scan / docs)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "scan",
        help="Value scanner (python -m tools scan --help)",
    )
    exp = sub.add_parser("export-docs", help="Write docs/memory_map.md from SQLite")
    exp.add_argument(
        "path",
        nargs="?",
        default=str(DOCS_PATH),
        help=f"Output path (default: {DOCS_PATH})",
    )
    sub.add_parser("sync-map", help="Push targets.json into SQLite memory_map")

    tag_p = sub.add_parser("tag", help="Tag the latest captured delta event")
    tag_p.add_argument("label", help="Clean label (prefer Locations.py names)")
    tag_p.add_argument("--region", default="", help="Area / landmark")
    tag_p.add_argument(
        "--category",
        default="",
        help="location_flag | inventory | stat | misc",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Forward scan flags intact (argparse would eat --type otherwise).
    if argv and argv[0] == "scan":
        from tools.scanner import main as scan_main

        return scan_main(argv[1:])

    args = build_parser().parse_args(argv)
    if args.command == "export-docs":
        return cmd_export_docs(Path(args.path))
    if args.command == "sync-map":
        return cmd_sync_map()
    if args.command == "tag":
        return cmd_tag(args.label, args.region, args.category)
    return 1
