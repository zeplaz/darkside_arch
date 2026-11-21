"""Rewrite Warmastered .sav UserId through whatisaphone/war (decode → edit → encode).

war is the Keen ``.sav`` codec only. Map on **Darksiders Warmastered (Steam x64)** —
never on the 2016 32-bit retail build (ObjectIDs / regions will not match).
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from tools.save_install import (
    APP_ID,
    backup,
    default_steam_remote,
    patch_json_userid,
    read_json_userid,
)

VENDOR_WAR = Path(__file__).resolve().parent / "vendor" / "war"
WAR_REPO = "https://github.com/whatisaphone/war"
EDITED_DIR = Path("saves") / "edited"
DECODED_DIR = Path("saves") / "decoded"

WAR_INSTALL_HINT = (
    "git clone https://github.com/whatisaphone/war.git tools/vendor/war\n"
    "cargo install --path tools/vendor/war/crates/war-cli"
)


def find_war(explicit: Optional[Path] = None) -> list[str]:
    if explicit is not None:
        path = explicit.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"war binary not found: {path}")
        return [str(path)]
    for name in ("war", "war-cli"):
        found = shutil.which(name)
        if found:
            return [found]
    for rel in (
        "target/release/war.exe",
        "target/release/war-cli.exe",
        "target/release/war",
        "target/release/war-cli",
    ):
        built = VENDOR_WAR / rel
        if built.is_file():
            return [str(built)]
    cargo = shutil.which("cargo")
    if cargo and (VENDOR_WAR / "Cargo.toml").is_file():
        return [
            cargo,
            "run",
            "--quiet",
            "--release",
            "--manifest-path",
            str(VENDOR_WAR / "Cargo.toml"),
            "-p",
            "war-cli",
            "--",
        ]
    raise FileNotFoundError(
        "war not found (needed to decode Warmastered .sav for SAVE DIFF).\n"
        f"  {WAR_INSTALL_HINT.replace(chr(10), chr(10) + '  ')}\n"
        "Or pass --war PATH to a war / war-cli binary.\n"
        "Use Warmastered x64 saves only — not the 2016 32-bit build."
    )


def war_status() -> dict[str, Any]:
    """Dashboard probe: is war available for SAVE DIFF / encode?"""
    bits = struct.calcsize("P") * 8
    base: dict[str, Any] = {
        "ok": False,
        "path": "",
        "mode": "missing",
        "detail": "war not found",
        "hint": WAR_INSTALL_HINT,
        "cargo": bool(shutil.which("cargo")),
        "vendor_cloned": (VENDOR_WAR / "Cargo.toml").is_file(),
        "python_bits": bits,
        "game": "Darksiders Warmastered (Steam App 462780, x64)",
        "reject": "Do not map on the 2016 32-bit retail build — identities will not match Warmastered.",
    }
    try:
        cmd = find_war()
    except FileNotFoundError as exc:
        base["detail"] = str(exc).split("\n", 1)[0]
        return base
    if cmd and Path(cmd[0]).name.lower().startswith("cargo"):
        base.update(
            ok=True,
            path=str(VENDOR_WAR),
            mode="cargo-run",
            detail="cargo run -p war-cli (tools/vendor/war)",
        )
    else:
        base.update(
            ok=True,
            path=cmd[0],
            mode="binary",
            detail=cmd[0],
        )
    return base


def ensure_war_installed() -> dict[str, Any]:
    """Clone tools/vendor/war if needed, then cargo install war-cli."""
    cargo = shutil.which("cargo")
    if not cargo:
        raise RuntimeError(
            "cargo not found. Install Rust from https://rustup.rs then retry INSTALL WAR."
        )
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git not found — needed to clone whatisaphone/war")
    VENDOR_WAR.parent.mkdir(parents=True, exist_ok=True)
    if not (VENDOR_WAR / "Cargo.toml").is_file():
        subprocess.run(
            [git, "clone", "--depth", "1", WAR_REPO, str(VENDOR_WAR)],
            check=True,
        )
    cli = VENDOR_WAR / "crates" / "war-cli"
    if not cli.is_dir():
        raise RuntimeError(f"war-cli crate missing under {VENDOR_WAR}")
    subprocess.run(
        [cargo, "install", "--path", str(cli), "--force"],
        check=True,
    )
    return war_status()


def run_war(war: list[str], args: list[str], label: str = "") -> None:
    cmd = [*war, *args]
    if label:
        print(f"[war] {label}", flush=True)
    print("      $ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def decoded_json_path(sav: Path) -> Path:
    return sav.with_suffix(".json")


SLOTS_OFFSET = 655
SLOT_LENGTH = 0x19200
SLOT_AUTOSAVE = -1


def slot_byte_offset(slot: int) -> int:
    if slot == SLOT_AUTOSAVE:
        return SLOTS_OFFSET + SLOT_LENGTH * 10
    if 0 <= slot <= 9:
        return SLOTS_OFFSET + SLOT_LENGTH * slot
    raise ValueError(f"slot must be -1 (autosave) or 0..9, not {slot}")


def occupied_slots(sav: Path) -> list[int]:
    raw = sav.read_bytes()
    found: list[int] = []
    for slot in [-1, *range(10)]:
        off = slot_byte_offset(slot)
        chunk = raw[off : off + SLOT_LENGTH]
        if len(chunk) == SLOT_LENGTH and chunk[:4] == b"DSAV":
            found.append(slot)
    return found


def decode_sav_slot(sav: Path, slot: int, war: Optional[list[str]] = None) -> dict:
    """Decode one Keen slot. war-cli only reads autosave, so other slots are copied there first."""
    raw = sav.read_bytes()
    off = slot_byte_offset(slot)
    chunk = raw[off : off + SLOT_LENGTH]
    if len(chunk) != SLOT_LENGTH or chunk[:4] != b"DSAV":
        raise ValueError(f"{sav} slot {slot} is empty")
    buf = bytearray(raw)
    if slot != SLOT_AUTOSAVE:
        auto = slot_byte_offset(SLOT_AUTOSAVE)
        buf[auto : auto + SLOT_LENGTH] = chunk
    war = war or find_war()
    with tempfile.TemporaryDirectory(prefix="ds-sav-slot-") as tmp:
        work = Path(tmp) / "slot.sav"
        work.write_bytes(buf)
        run_war(war, ["sav", "decode", str(work)], label=f"decode slot {slot}")
        js = decoded_json_path(work)
        if not js.is_file():
            raise FileNotFoundError(f"war decode did not write {js}")
        data = json.loads(js.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{sav} slot {slot} is not a Keen object dump")
    return data


def patch_sav_userid(sav: Path, user_id: int, dest: Path, war: list[str]) -> int:
    """Decode autosave, set UserId, encode back. war only writes the autosave slot."""
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ds-save-patch-") as tmp:
        work = Path(tmp)
        work_sav = work / "slot.sav"
        shutil.copy2(sav, work_sav)
        run_war(war, ["sav", "decode", str(work_sav)], label="decode autosave")
        work_json = decoded_json_path(work_sav)
        if not work_json.is_file():
            raise FileNotFoundError(f"war decode did not write {work_json}")
        old = read_json_userid(work_json)
        if old is None:
            raise ValueError("decoded save has no GameInfo.UserId")
        print(f"[save] UserId {old} -> {user_id}", flush=True)
        patch_json_userid(work_json, user_id)
        backup(dest)
        shutil.copy2(work_sav, dest)
        run_war(war, ["sav", "encode", str(dest), str(work_json)], label=f"encode autosave -> {dest}")
        return int(old)


def encode_json_to_sav(json_path: Path, sav_target: Path, war: list[str]) -> Path:
    """Encode a Keen JSON dump into the autosave slot of a .sav (war sav encode).

    ``war sav encode`` reads the existing ``sav_target`` (preserving its manual
    slots 0-9) and overwrites only the autosave slot (-1) with the JSON content.
    The target is backed up first (timestamped) so a bad encode cannot eat the
    only copy.
    """
    json_path = json_path.resolve()
    sav_target = sav_target.resolve()
    if not json_path.is_file():
        raise FileNotFoundError(json_path)
    if not sav_target.is_file():
        raise FileNotFoundError(sav_target)
    if json_path.suffix.lower() != ".json":
        raise ValueError("encode source must be a .json Keen dump")
    if ".sav" not in sav_target.name.lower():
        raise ValueError("encode target must be a .sav")
    backup(sav_target)
    run_war(war, ["sav", "encode", str(sav_target), str(json_path)], label=f"encode {json_path} -> {sav_target}")
    print(f"[save] encoded -> {sav_target}", flush=True)
    return sav_target


def default_edited_path(sav: Path) -> Path:
    return EDITED_DIR / sav.name


def default_decoded_path(sav: Path, slot: int) -> Path:
    slot_name = "autosave" if slot == -1 else f"slot_{slot}"
    return DECODED_DIR / f"{sav.stem}.{slot_name}.json"


def is_steam_save_path(path: Path) -> bool:
    parts = {p.lower() for p in path.resolve().parts}
    return APP_ID in parts and ("remote" in parts or "autocloud" in parts)


def copy_into_steam(patched: Path, user_id: int) -> list[Path]:
    """Copy an already-encoded .sav into Steam remote + autocloud. Backs up each dest."""
    patched = patched.resolve()
    if not patched.is_file():
        raise FileNotFoundError(patched)
    dests = steam_install_paths(user_id, patched.name)
    written: list[Path] = []
    for target in dests:
        target.parent.mkdir(parents=True, exist_ok=True)
        backup(target)
        shutil.copy2(patched, target)
        print(f"[save] copied -> {target}", flush=True)
        written.append(target)
    return written


def steam_install_paths(user_id: int, sav_name: str) -> list[Path]:
    remote = default_steam_remote(user_id)
    if remote is None:
        raise FileNotFoundError(
            f"Steam remote folder not found for UserId {user_id}. Pass --dest PATH"
        )
    names = [sav_name, "svd_fmt_0_0.sav", "keen_savegame_0_0.sav"]
    unique: list[Path] = []
    for name in names:
        for folder in (remote, remote / "autocloud" / "save"):
            path = folder / name
            if path not in unique:
                unique.append(path)
    return unique


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tools save-patch",
        description=(
            "Change Warmastered .sav UserId using whatisaphone/war "
            "(sav decode → edit JSON → sav encode). "
            "Does not poke raw dwords. war only rewrites the autosave slot."
        ),
    )
    p.add_argument("--sav", type=Path, required=True, help="Source .sav (Keen / svd_fmt)")
    p.add_argument("--userid", type=int, required=True, help="Local Steam account id (userdata folder name)")
    p.add_argument("--out", type=Path, help="Write patched .sav here (default: overwrite --sav)")
    p.add_argument("--war", type=Path, help="Path to war or war-cli")
    p.add_argument(
        "--install",
        action="store_true",
        help=f"Copy patched .sav into Steam userdata/<id>/{APP_ID}/remote and autocloud/save",
    )
    p.add_argument("--dest", type=Path, help="Also copy the patched .sav into this folder")
    args = p.parse_args(argv)

    sav = args.sav.expanduser().resolve()
    if not sav.is_file():
        print(f"[ERROR] missing {sav}")
        return 1
    if sav.suffix.lower() == ".json" or ".sav" not in sav.name.lower():
        print("[ERROR] --sav must be a .sav (not the Keen JSON dump)")
        return 1

    try:
        war = find_war(args.war)
        dest = (args.out or sav).expanduser().resolve()
        print("save-patch: recode Warmastered .sav UserId via whatisaphone/war")
        print(f"  source : {sav}")
        print(f"  userid : {args.userid}")
        print(f"  output : {dest}")
        print(f"  war    : {' '.join(war)}")
        print()
        old = patch_sav_userid(sav, args.userid, dest, war)
        print(f"[OK] UserId {old} -> {args.userid}  ({dest})", flush=True)

        copies: list[Path] = []
        if args.dest:
            copies.append(args.dest / dest.name)
        if args.install:
            copies.extend(steam_install_paths(args.userid, dest.name))
        seen: set[Path] = set()
        for target in copies:
            if target in seen:
                continue
            seen.add(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            backup(target)
            shutil.copy2(dest, target)
            print(f"[OK] copied -> {target}", flush=True)
        if args.install:
            print("[OK] installed. Quit the game fully, launch from Steam, Load Game.", flush=True)
        elif args.dest:
            print(f"[OK] copied -> {args.dest}", flush=True)
        else:
            print("[OK] done. Re-run with --install (or use the dashboard SAVES tab) to copy into Steam.", flush=True)
        return 0
    except subprocess.CalledProcessError as exc:
        cmd = " ".join(str(c) for c in (exc.cmd or []))
        print(f"[ERROR] war failed (exit {exc.returncode}): {cmd}")
        print("        war is the .sav codec. Warmastered x64 saves only — not the 2016 32-bit build.")
        return 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
