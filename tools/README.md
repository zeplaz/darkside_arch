# tools

Mapper-only. Identifies Keen WorldObjects from two save slots, and later finds module-relative RAM offsets. Writes [targets.json](../targets.json), which [ds_client](../ds_client/README.md) hot-reloads. Labels must be the exact names in Sacha’s `worlds/darksiders/data/*.json` ([WORLD.md](../docs/WORLD.md)) — pick them from the catalog, never type them.

Two JSON sources. Sacha’s `data/` is AP names + AP ids + vanilla item. This repo is Keen `save_object` + RAM offsets (`targets.json` is ours). Do not put RAM RVAs in the world package. Join key is the location name string.

```powershell
pip install -r requirements-dev.txt
python -m tools              # list commands
python -m tools CMD --help   # flags for one command
```

| Command | Use |
|---------|-----|
| `dashboard` | Browser UI. Chests: two save slots → **DIFF SAVES**. **Start here.** |
| `capture` | Same save-diff in the terminal (`--sav` `--slots`), then the RAM capture for the live flag |
| `scan` | HUD numbers (souls, counts), or `--sav` / `--slots` for a chest |
| `locations` | List checks with todo / done |
| `sync-world` | Refresh `docs/world_*.json` from `worlds/darksiders/data/` |
| `export-docs` | Write `docs/memory_map.md` once RAM offsets are trusted |
| `save-brief` / `save-diff` / `save-install` / `save-patch` | Keen saves. See [SAVES.md](../docs/SAVES.md) |

`save_object` does **not** enable the row. RAM capture does. `ds_client` skips `offsets: ["0x0"]`.

## `dashboard`

```powershell
python -m tools dashboard     # http://127.0.0.1:8765/   (--port, --host, --db, --no-browser)
```

Chests: two in-game saves, then **DIFF SAVES**. The game can be closed. Press **?** on the page for the full guide.

1. Pause. **Save** while the chest is still closed (note the slot: `-1` autosave, `0`–`9` the list).
2. Open it. **Save** in a different slot.
3. **BRIEF ALL** if you are not sure which slot is closed vs open (spawn, chests, Triggered count).
4. Pick the AP name. Set the two slot numbers. **DIFF SAVES**.
5. Chests write `Triggered`. Breakables are `Destroyed`. Doors are `Open`. **SAVE IDENTITY**.

**EXPORT … JSON** writes `saves/_scratch/slots/`. **SAVES** tab: ENCODE TO EDITED (`saves/edited/`, autosave only) then INSTALL TO STEAM (type `INSTALL`; refused while the game is attached).

That writes `save_object`. It is not a live AP watch. LIVE VALUES only appear after a real RAM offset.

The live flag comes from the **RAM DUMP** tab (closed → F8, open → F8), after the save identity exists:

- **Identified row → heap.** Chest WorldObjects live on the heap, not in `.data`. The capture looks for the packed ObjectID+RegionID+LayerID dwords (`game_data/Chests.json` order), then the same three within 64 bytes, then ObjectID alone, and diffs ±1 KB around those anchors. Chest `.s` scripts write `Triggered` via `setSaveValue`; they are not RAM offsets.
- **No identity → module `.data`.** 34 MB where opening a chest flips ~1,500 unrelated bytes. Chest flags are not there.
- A candidate must be 0 in every baseline sample (5 over 4 s) and 1 in every after sample (3 over 1.5 s). Stand still for both. Each extra F8 keeps only candidates that survived every diff.
- Saving a heap byte runs a pointer scan (depth 3) for a static chain from `darksiders1.exe`; no chain → not saved, because the heap address changes every launch.
- `snapshots/last_capture.npz` keeps the last capture for offline analysis.

## `capture`

```powershell
python -m tools capture --sav FILE.sav --slots 1 2 --location "Seraphim Hotel Life Chest 1"
python -m tools capture --location "Seraphim Hotel Life Chest 1"   # RAM capture (heap, uses its save_object)
```

`--dry-run` prints without writing. Without `--sav`, capture does the RAM capture: heap around the row's `save_object` if it has one, otherwise `.data`.

## `scan`

```powershell
python -m tools scan                               # souls (Soul_Count, float)
python -m tools scan --item "Progressive Chaoseater"
python -m tools scan --sav FILE.sav --slots 1 2 --item "Seraphim Hotel Life Chest 1"
```

Dashboard **ITEM WRITES** shows the scan command for the selected row (Chaoseater = weapon level 1..4, not a chest). HUD: type the number, change it, repeat. Heap addresses become a pointer chain. Chests: `--sav` / `--slots`, not a HUD value of 0.

## `locations` / `sync-world` / `export-docs`

```powershell
python -m tools locations --region "Seraphim Hotel" --todo
python -m tools save-brief --all FILE.sav
python -m tools sync-world
python -m tools export-docs
```

## `targets.json`

| Field | |
|-------|--|
| `id` | Stable key. Required |
| `label` | Exact world name (join key with Sacha’s `data/*.json`) |
| `offsets` | Module-relative hex. `["0x0"]` = not a RAM watch (ignored at runtime) |
| `save_object` | Keen identity: `world`, `region_id`, `layer_id`, `object_id`, `value_key`. Not a live AP watch |
| `type` | `bool`, `uint8/16/32/64`, `int8/16/32/64`, `float`, `double` |
| `bitmask` | Optional; not on float / double |
| `category` | `location_flag` \| `inventory` \| `stat` \| `misc` |
| `event_type` | `LOCATION_CHECK` \| `MEMORY_STATE` (default) \| `GOAL` |
| `enabled` | `false` keeps the row but skips it. Identify leaves this false |
| `module` | Default `darksiders1.exe` |

Never store absolute addresses — they change every launch (ASLR). To drop a row, delete it; SQLite and `memory_map.md` follow on the next sync.
