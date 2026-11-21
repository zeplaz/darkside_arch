# Mapping dashboard

**This is the mapper entry.** Other `python -m tools` commands are CLI backups of the same steps.

```powershell
pip install -r requirements-dev.txt
python -m tools dashboard
```

Opens `http://127.0.0.1:8765/`. Flags: `--host`, `--port` (default `8765`), `--db`, `--no-browser`.

It is a workspace for writing [targets.json](../targets.json). Player runtimes are separate: [runtime.mem](../runtime/mem/README.md) or [runtime.dll](../runtime/dll/README.md).

**Target build:** Darksiders **Warmastered** Steam **x64** only. Do not SAVE DIFF / inject on the 2016 32-bit retail game.

First open shows a **START** splash (navigates only — Map a check / DLL LAB). Reopen with **START** in the header. Center **WORK MODE** bar switches the middle panel. Header pill **WAR** must be green before DIFF SAVES (install from the SAVE DIFF setup card if missing). DLL checklist rows are tinted **DONE** / **PENDING** / **BLOCKED**.

| Tab | Does | Writes |
|-----|------|--------|
| **SAVE DIFF** | Two in-game slots → which Keen WorldObject this AP name is | `save_object` only. Row stays disabled. |
| **RAM DUMP** | Closed then open F8 → live 0→1 byte | RAM `offsets` (mem path). |
| **SAVES** | Decode / encode (JSON + UserId), copy into Steam | Files under `saves/decoded/`, `saves/edited/`, then Steam remote. |
| **DLL LAB** | **TEST** / **LIVE** host + build + inject | Nothing in `targets.json` from this tab. |

### DLL LAB

Step-by-step (TEST vs LIVE, CLI, success checks): **[runtime/dll/README.md](../runtime/dll/README.md)**.

Short: open **DLL LAB** → pick TEST or LIVE → follow the on-page checklist. Stop the host before switching modes. Inject after launch — not sideload.

`save_object` is not a live watch. `runtime.mem` skips `offsets: ["0x0"]` until RAM DUMP saves a real one.

Press **?** on the page for the same guide.

## Left list

Pick the AP name here. Never type labels — they must match [WORLD.md](WORLD.md).

- Region + search
- Status: OPEN (no identity, no RAM) · IDENTIFIED (has `save_object`) · MAPPED (has a RAM offset)
- Kind: chest / artifact / armor / cube / other
- Chest loot: health / currency / wrath / lifestone / key / rare (from vanilla item)
- Sort: name, AP id, status, loot

**ITEM WRITES** is inventory / stats / goal (HUD `scan`), not chests.

## SAVE DIFF — identify

Requires **war** (`whatisaphone/war`) to decode `.sav`. If the **WAR** pill is red: open SAVE DIFF → **INSTALL WAR** (needs [Rust](https://rustup.rs) + git), or copy the commands on that card. war is a save codec here — not a 32-bit in-game mod.

Game can be closed. Warmastered x64 saves only. Slots: `-1` autosave, `0`–`9` the list.

1. Pause. **Save** while the object is still untouched. Note the slot.
2. Open / collect it. **Save** in a different slot.
3. **BRIEF ALL** if you are not sure which slot is before vs after (spawn, chests opened, Triggered count).
4. Pick the AP name. Set CLOSED / OPENED. **DIFF SAVES**.
5. **MATCH** keeps the persist type for that row (chest / artifact → `Triggered`). Click **ALL** or **DESTROYED** / **OPEN** / **ACTIVATED** to unhide doors and breakables.
6. Highlight the matching row. **SAVE IDENTITY**.

| Keen key | Object |
|----------|--------|
| `Triggered` | Chests / one-shots |
| `Destroyed` | Breakables |
| `Open` | Doors |

Identity is `world` + RegionID + LayerID + ObjectID + key. ObjectID is not global. Details: [SAVES.md](SAVES.md).

**SWAP** if the table says `true → (absent)` (you set open slot first). **EXPORT … JSON** writes `saves/_scratch/slots/`.

**Artifacts / armor / cubes have no save flag**, so SAVE DIFF finds nothing for them. Identify those from a `game_data` dump instead — **GAME DATA…** in the SAVE DIFF panel (or `python -m tools identify --location NAME --kind artifact`). Every identity records a `source` (`Chests.json` / `Artifacts.json` / `save-diff`), shown in the location card and stored in the `target_index` table of `darksiders_debug.db` alongside each row's stage (`open` / `identified` / `mapped`).

## RAM DUMP — live flag

Do this after SAVE IDENTITY. Those flags live on the heap, not in `.data`.

1. Load a save where it is still **untouched**. Stand next to it. Unpause.
2. **RAM DUMP** tab. **F8** or BASELINE — 4 s, stand still.
3. Open it. **F8** or DIFF — 1.5 s.
4. If more than one 0→1 remains, click the row. **SAVE RAM**. Extra F8 keeps only bytes that stayed 1 in every diff.

Identified rows search the heap for the packed ObjectID+RegionID+LayerID triple, then nearby, then ObjectID alone, and diff around those hits. A row without an identity is refused — finish SAVE DIFF first (the old 34 MB `.data` fallback returned thousands of unrelated bytes). A heap byte is saved only with a static pointer chain from `darksiders1.exe`. Last capture: `snapshots/last_capture.npz`.

## SAVES — decode / encode / install

- **DECODE TO JSON** — `war sav decode` of one slot → `saves/decoded/`. Slot `-1` is autosave, `0`–`9` the manual list.
- **ENCODE FROM JSON** — `war sav encode` of a Keen JSON back into the **autosave** slot of a `.sav`. Slots 0–9 are preserved; the target is backed up first.

To rewrite the save to your own Steam account (the UserId flow):

1. **ENCODE TO EDITED** — war rewrite of autosave UserId → `saves/edited/`.
2. Quit Darksiders. Steam cloud fights a live copy.
3. **INSTALL TO STEAM** — type `INSTALL`. Copies into `remote\` and `remote\autocloud\save\` as both `svd_fmt_0_0.sav` and `keen_savegame_0_0.sav`. Refused while the game is attached.

Same CLI: `python -m tools save-patch … --out saves\edited\FILE.sav --install`. See [SAVES.md](SAVES.md).

## After you save a row

`targets.json` updates. `runtime.mem` hot-reloads. Rebuild the published table with `python -m tools export-docs` → [memory_map.md](memory_map.md).
