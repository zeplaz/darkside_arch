"""Install an AP start save: rewrite Steam UserId, refuse late-game bags."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import sys
from pathlib import Path
from typing import Any, Optional

from tools.save_brief import brief_save

APP_ID = "462780"
LATE_INVENTORY = frozenset(
    {
        "items/item_armageddonsword",
        "items/item_swordpiece",
    }
)
EXPECTED_WORLD = "overworld"
EXPECTED_REGION_PREFIX = "CI_01"


def _set_userid_node(node: Any, user_id: int) -> int:
    hits = 0
    if isinstance(node, dict):
        if "UserId" in node and isinstance(node["UserId"], dict) and "value" in node["UserId"]:
            node["UserId"]["value"] = int(user_id)
            hits += 1
        for child in node.values():
            hits += _set_userid_node(child, user_id)
    elif isinstance(node, list):
        for child in node:
            hits += _set_userid_node(child, user_id)
    return hits


def patch_json_userid(path: Path, user_id: int, dest: Optional[Path] = None) -> Path:
    data = json.loads(path.read_text(encoding="utf-8"))
    hits = _set_userid_node(data, user_id)
    if not hits:
        raise ValueError(f"no GameInfo.UserId field in {path}")
    out = dest or path
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return out


def read_json_userid(path: Path) -> Optional[int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    info = (data.get("properties") or {}).get("GameInfo") or {}
    props = info.get("properties") or {}
    node = props.get("UserId") or {}
    value = node.get("value")
    return int(value) if value is not None else None


def patch_sav_userid(path: Path, old_id: int, new_id: int, dest: Optional[Path] = None) -> int:
    data = bytearray(path.read_bytes())
    old = struct.pack("<I", int(old_id) & 0xFFFFFFFF)
    new = struct.pack("<I", int(new_id) & 0xFFFFFFFF)
    count = data.count(old)
    if count == 0:
        raise ValueError(f"old UserId {old_id} not found in {path}")
    patched = data.replace(old, new)
    out = dest or path
    out.write_bytes(bytes(patched))
    return count


def backup(path: Path) -> None:
    """Keep one ``<name>.bak`` copy before a file is overwritten."""
    if path.exists():
        bak = path.with_name(path.name + ".bak")
        shutil.copy2(path, bak)
        print(f"[OK] backup {bak}")


def is_late_game_save(info: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    region = str(info.get("spawn_region") or "")
    world = str(info.get("spawn_world") or "")
    items = set(info.get("inventory_item_types") or [])
    if world and world != EXPECTED_WORLD:
        reasons.append(f"spawn_world={world!r} (want {EXPECTED_WORLD})")
    if region and not region.startswith(EXPECTED_REGION_PREFIX):
        reasons.append(f"spawn_region={region!r} (want {EXPECTED_REGION_PREFIX} Crossroads)")
    overlap = sorted(items & LATE_INVENTORY)
    if overlap:
        reasons.append("late inventory: " + ", ".join(overlap))
    chests = info.get("chests_opened")
    if isinstance(chests, int) and chests > 8:
        reasons.append(f"chests_opened={chests} (template should be early Crossroads)")
    return reasons


def steam_userdata_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
                roots.append(Path(str(steam_path)) / "userdata")
        except OSError:
            pass
        roots.append(Path(r"C:\Program Files (x86)\Steam\userdata"))
        roots.append(Path(r"C:\Program Files\Steam\userdata"))
    home = Path.home()
    roots.append(home / ".steam" / "steam" / "userdata")
    seen: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.append(root)
    return seen


def default_steam_remote(user_id: int) -> Optional[Path]:
    uid = str(int(user_id))
    for root in steam_userdata_roots():
        candidate = root / uid / APP_ID / "remote"
        if candidate.is_dir():
            return candidate
        parent = root / uid / APP_ID
        if parent.is_dir():
            return candidate
    env = os.environ.get("STEAM")
    if env:
        return Path(env) / "userdata" / uid / APP_ID / "remote"
    return None


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tools save-install",
        description=(
            "Rewrite Keen UserId onto a Crossroads-after-Vulgrim AP template. "
            "Does not accept the late-game keen_savegame_0_0 bag."
        ),
    )
    p.add_argument("--json", type=Path, help="Keen JSON export (schema dump)")
    p.add_argument("--sav", type=Path, help="Matching keen_savegame_*.sav")
    p.add_argument("--userid", type=int, required=True, help="Local Steam UserId")
    p.add_argument(
        "--old-userid",
        type=int,
        default=None,
        help="Template author Steam id (default: read from --json)",
    )
    p.add_argument("--out-json", type=Path, help="Write patched JSON here")
    p.add_argument("--out-sav", type=Path, help="Write patched .sav here")
    p.add_argument(
        "--dest",
        type=Path,
        help="Copy patched .sav into this folder (Steam remote)",
    )
    p.add_argument(
        "--install",
        action="store_true",
        help=f"Copy patched .sav into Steam userdata/<id>/{APP_ID}/remote/",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Allow late-game bags (not for AP skip-intro)",
    )
    args = p.parse_args(argv)

    if args.json is None and args.sav is None:
        print("[ERROR] provide --json and/or --sav")
        return 1
    if (args.install or args.dest) and args.sav is None:
        print("[ERROR] --install / --dest copy the patched .sav; pass --sav too")
        return 1
    try:
        return _run(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}")
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.json:
        if not args.json.exists():
            print(f"[ERROR] missing {args.json}")
            return 1
        if args.json.suffix.lower() == ".sav":
            print("[ERROR] --json expects the Keen JSON export")
            return 1
        info = brief_save(args.json)
        reasons = is_late_game_save(info)
        if reasons and not args.force:
            print("[ERROR] this is not a Crossroads-after-Vulgrim AP template:")
            for reason in reasons:
                print(f"        {reason}")
            print("        Capture a new game at Crossroads after Vulgrim. Use --force only for mapping.")
            return 2
        old_id = args.old_userid
        if old_id is None:
            old_id = read_json_userid(args.json)
        dest_json = args.out_json or args.json
        backup(dest_json)
        patch_json_userid(args.json, args.userid, dest_json)
        print(f"[OK] JSON UserId {old_id} -> {args.userid} ({dest_json})")
        args.old_userid = old_id

    if args.sav:
        if not args.sav.exists():
            print(f"[ERROR] missing {args.sav}")
            return 1
        old_id = args.old_userid
        if old_id is None:
            print("[ERROR] --old-userid required when patching .sav without --json")
            return 1
        dest_sav = args.out_sav or args.sav
        backup(dest_sav)
        n = patch_sav_userid(args.sav, old_id, args.userid, dest_sav)
        print(f"[OK] .sav replaced {n} UserId dword(s) ({dest_sav})")
        copy_to = args.dest
        if args.install and copy_to is None:
            copy_to = default_steam_remote(args.userid)
            if copy_to is None:
                print(
                    f"[ERROR] Steam remote folder not found for UserId {args.userid}. "
                    "Pass --dest PATH"
                )
                return 1
        if copy_to is not None:
            copy_to.mkdir(parents=True, exist_ok=True)
            target = copy_to / dest_sav.name
            backup(target)
            shutil.copy2(dest_sav, target)
            print(f"[OK] copied {dest_sav.name} -> {target}")
            print("     Load this slot in-game.")
    return 0
