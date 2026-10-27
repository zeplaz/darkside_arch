# Mapping dashboard

**This is the mapper entry.** Other `python -m tools` commands are CLI backups of the same steps.

```powershell
pip install -r requirements-dev.txt
python -m tools dashboard
```

Opens `http://127.0.0.1:8765/`. Flags: `--host`, `--port` (default `8765`), `--db`, `--no-browser`.

It is a workspace for writing [targets.json](../targets.json). It does **not** attach as an AP client and does **not** poke `darksiders1.exe`. [ds_client](../ds_client/README.md) is the runtime.

| Tab | Does | Writes |
|-----|------|--------|
| **SAVE DIFF** | Two in-game slots → which Keen WorldObject this AP name is | `save_object` only. Row stays disabled. |
| **RAM DUMP** | Closed then open F8 → live 0→1 byte | RAM `offsets`. This is what LocationChecks need. |
| **SAVES** | Decode / encode UserId, copy into Steam | Files under `saves/edited/`, then Steam remote. |

`save_object` is not a live watch. `ds_client` skips `offsets: ["0x0"]` until RAM DUMP saves a real one.

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

Game can be closed. Slots: `-1` autosave, `0`–`9` the list.

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

## RAM DUMP — live flag

Do this after SAVE IDENTITY. Those flags live on the heap, not in `.data`.

1. Load a save where it is still **untouched**. Stand next to it. Unpause.
2. **RAM DUMP** tab. **F8** or BASELINE — 4 s, stand still.
3. Open it. **F8** or DIFF — 1.5 s.
4. If more than one 0→1 remains, click the row. **SAVE RAM**. Extra F8 keeps only bytes that stayed 1 in every diff.

Identified rows search the heap for the packed ObjectID+RegionID+LayerID triple, then nearby, then ObjectID alone, and diff around those hits. No identity diffs 34 MB of `.data` (wrong place). A heap byte is saved only with a static pointer chain from `darksiders1.exe`. Last capture: `snapshots/last_capture.npz`.

## SAVES — UserId / install

1. **ENCODE TO EDITED** — war rewrite of autosave UserId → `saves/edited/`.
2. Quit Darksiders. Steam cloud fights a live copy.
3. **INSTALL TO STEAM** — type `INSTALL`. Copies into `remote\` and `remote\autocloud\save\` as both `svd_fmt_0_0.sav` and `keen_savegame_0_0.sav`. Refused while the game is attached.

Same CLI: `python -m tools save-patch … --out saves\edited\FILE.sav --install`. See [SAVES.md](SAVES.md).

## After you save a row

`targets.json` updates. `ds_client` hot-reloads. Rebuild the published table with `python -m tools export-docs` → [memory_map.md](memory_map.md).
