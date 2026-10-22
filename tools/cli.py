"""`python -m tools <command>` — each command owns its own argparse (`<command> --help`)."""

from __future__ import annotations

import importlib
import sys
from typing import Optional

# name -> (module:function, one-line help). Order is the order shown in --help.
COMMANDS: dict[str, tuple[str, str]] = {
    "dashboard": ("tools.dashboard:main", "Browser UI: pick a location, capture it, watch live values"),
    "capture": ("tools.snapshot:main_capture", "Terminal capture of one location flag (baseline -> open -> save)"),
    "scan": ("tools.scanner:main", "Find a HUD number (souls, item counts) by narrowing its value"),
    "locations": ("tools.world_catalog:main_locations", "List location checks with todo/done status"),
    "sync-world": ("tools.world_catalog:main_sync_world", "Refresh docs/world_*.json from the local world clone"),
    "export-docs": ("tools.export_docs:main", "Write docs/memory_map.md from targets.json"),
    "save-brief": ("tools.save_brief:main", "Summarize a Keen JSON save export"),
    "save-diff": ("tools.save_diff:main", "Diff two Keen JSON save exports"),
    "save-install": ("tools.save_install:main", "Rewrite the Steam UserId on an AP template save"),
}


def _usage() -> str:
    width = max(map(len, COMMANDS))
    rows = "\n".join(f"  {name:<{width}}  {text}" for name, (_, text) in COMMANDS.items())
    return f"usage: python -m tools <command> [--help]\n\ncommands:\n{rows}\n"


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(_usage())
        return 0
    entry = COMMANDS.get(argv[0])
    if entry is None:
        print(f"[ERROR] unknown command {argv[0]!r}\n\n{_usage()}")
        return 2
    module, func = entry[0].split(":")
    return getattr(importlib.import_module(module), func)(argv[1:])
