"""Convert a Keen-container save to the user's ``svd_fmt_0_0.sav``.

The 2026 Darksiders Warmastered update renamed the save file from
``keen_savegame_0_0.sav`` to ``svd_fmt_0_0.sav`` but kept the **same Keen
container** format: a 655-byte header (name + version + CRC32 + padding) followed
by 11 fixed DSAV slots (autosave + manual 0-9), with a CRC32 of the whole file
stored at offset 0x84.

``war sav encode`` only rewrites the autosave slot, so this script decodes and
re-encodes **every occupied slot** (so each slot's ``GameInfo.UserId`` is
rewritten), rebuilds the container, and recomputes the header CRC32.

Usage::

    python -m tools save-to-svd --sav saves\\keen_savegame_0_0.sav --userid 8457083 --install
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path
from typing import Optional

from tools.save_install import backup, default_steam_remote, patch_json_userid, read_json_userid
from tools.save_patch import SLOT_LENGTH, find_war, occupied_slots, slot_byte_offset

CRC_OFF = 0x84
CRC_LEN = 0x11_4AC8  # == the full 1,133,256-byte container (same as the game)
DEFAULT_OUT = Path("saves") / "edited" / "svd_fmt_0_0.sav"


def _crc32(raw: bytes) -> int:
    return zlib.crc32(raw) & 0xFFFFFFFF


def build_svd(src_sav: Path, user_id: int, dest: Path, war: list[str]) -> Path:
    """Patch every occupied slot's UserId and rebuild the Keen container."""
    src_sav = src_sav.resolve()
    if not src_sav.is_file():
        raise FileNotFoundError(src_sav)
    if src_sav.suffix.lower() == ".json":
        raise ValueError("--sav must be a .sav Keen container, not a JSON dump")

    raw = bytearray(src_sav.read_bytes())
    slots = occupied_slots(src_sav)
    if not slots:
        raise ValueError(f"{src_sav} has no occupied DSAV slots")

    scratch = Path(".tmp") / f"svd_{os.getpid()}_{int(time.time() * 1000)}"
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        for slot in slots:
            off = slot_byte_offset(slot)
            work = scratch / f"slot_{slot}.sav"
            work.write_bytes(bytes(raw[off : off + SLOT_LENGTH]))
            js = work.with_suffix(".json")
            subprocess.run([*war, "dsav", "decode", str(work), str(js)], check=True)
            old = read_json_userid(js)
            if old is None:
                raise ValueError(f"slot {slot} has no GameInfo.UserId")
            patch_json_userid(js, user_id)
            out = scratch / f"out_{slot}.sav"
            subprocess.run([*war, "dsav", "encode", str(js), str(out)], check=True)
            dsa = out.read_bytes()
            raw[off : off + SLOT_LENGTH] = b"\x00" * SLOT_LENGTH
            raw[off : off + len(dsa)] = dsa
            print(f"[slot {slot:>2}] UserId {old} -> {user_id}  ({len(dsa)} bytes)", flush=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    # Recompute the header CRC32 exactly like KeenSaveGameManager::write_save.
    raw[CRC_OFF : CRC_OFF + 4] = b"\x00\x00\x00\x00"
    crc = _crc32(bytes(raw[:CRC_LEN]))
    raw[CRC_OFF : CRC_OFF + 4] = struct.pack("<I", crc)

    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    backup(dest)
    dest.write_bytes(bytes(raw))
    print(
        f"[OK] wrote {dest}  ({len(raw)} bytes, {len(slots)} slots, CRC 0x{crc:08X})",
        flush=True,
    )
    return dest


def install_svd(patched: Path, user_id: int) -> list[Path]:
    """Copy the converted save to the single 2026 location the game reads."""
    remote = default_steam_remote(user_id)
    if remote is None:
        raise FileNotFoundError(f"Steam remote folder not found for UserId {user_id}")
    targets = [remote / "autocloud" / "save" / "svd_fmt_0_0.sav"]
    written: list[Path] = []
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        backup(t)
        shutil.copy2(patched, t)
        print(f"[OK] copied -> {t}", flush=True)
        written.append(t)
    return written


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tools save-to-svd",
        description=(
            "Rewrite every slot's UserId in a Keen-container .sav and rebuild it "
            "as svd_fmt_0_0.sav (the 2026 Warmastered save filename)."
        ),
    )
    p.add_argument("--sav", type=Path, required=True, help="Source .sav (keen_savegame_0_0.sav or svd_fmt_0_0.sav)")
    p.add_argument("--userid", type=int, required=True, help="Target Steam account id (userdata folder name)")
    p.add_argument("--out", type=Path, help="Output .sav (default saves/edited/svd_fmt_0_0.sav)")
    p.add_argument("--war", type=Path, help="Path to war / war-cli binary")
    p.add_argument(
        "--install",
        action="store_true",
        help="Copy the output to Steam remote/autocloud/save/svd_fmt_0_0.sav",
    )
    args = p.parse_args(argv)

    try:
        war = find_war(args.war)
        dest = (args.out or DEFAULT_OUT).expanduser().resolve()
        build_svd(args.sav, args.userid, dest, war)
        if args.install:
            install_svd(dest, args.userid)
            print("[OK] installed. Quit the game fully, launch from Steam, Load Game.", flush=True)
        else:
            print("[OK] done. Re-run with --install to copy into Steam.", flush=True)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
