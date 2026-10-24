# tools

`python -m tools <command>` — map chests and items into [targets.json](../targets.json). [ds_client](../ds_client/README.md) hot-reloads that file.

```powershell
python -m tools                 # print this list
python -m tools dashboard       # start here  →  http://127.0.0.1:8765/
python -m tools <command> --help
```

| Run | Use |
|-----|-----|
| [`dashboard`](#dashboard) | Browser. Identify from two save slots, then RAM DUMP for the live flag. |
| [`capture`](#capture) | Same identify / RAM dump in the terminal. |
| [`scan`](#scan) | HUD numbers (souls, weapon levels). Add `--sav --slots` only for a chest identity. |
| [`locations`](#locations) | List checks: open / identified / mapped. |
| [`sync-world`](#sync-world) | Refresh `docs/world_*.json` from Sacha’s world package. |
| [`export-docs`](#export-docs) | Rebuild `docs/memory_map.md`. |
| [`save-brief`](#save-brief) | Decode a slot and print spawn / chests / flags. |
| [`save-diff`](#save-diff) | Diff two slots (or JSON). `--location` writes the Keen identity. |
| [`save-patch`](#save-patch) | Set `.sav` UserId (war, autosave only). Then optional `--install`. |
| [`save-install`](#save-install) | JSON template UserId only. Not a playable `.sav`. |

Need `pip install -r requirements-dev.txt` once. Slots are `-1` autosave, `0`–`9` the list. Saves: [SAVES.md](../docs/SAVES.md). Names: [WORLD.md](../docs/WORLD.md).

**Rules**

- Pick AP names from the catalog. Never type them.
- Sacha’s `data/` = names, AP ids, vanilla loot. This repo = Keen identity + RAM offsets. No RVAs in the world package.
- `save_object` is the Keen id, not a live watch. RAM capture turns the row on. `["0x0"]` is ignored.

---

## `dashboard`

```powershell
python -m tools dashboard                 # http://127.0.0.1:8765/
python -m tools dashboard --port 8765 --no-browser
```

Flags: `--host` (default `127.0.0.1`), `--port` (`8765`), `--db`, `--no-browser`.

**Left:** region, search, OPEN / IDENTIFIED / MAPPED, kind (chest / artifact / armor / cube / other), chest loot, sort.

**Center tabs:** SAVE DIFF (identity) · RAM DUMP (live flag) · SAVES (encode UserId, then INSTALL). **?** on the page is the full guide. This page never writes process memory and never talks to AP.

### SAVE DIFF — identify a chest

Game can be closed.

1. Pause. **Save** while the object is still closed (note the slot).
2. Open it. **Save** in a different slot.
3. **BRIEF ALL** if you are not sure which slot is closed vs open.
4. Pick the AP name on the left. Set CLOSED / OPENED. **DIFF SAVES**.
5. **MATCH** keeps the persist type for that row (chest → `Triggered` chests). **ALL** or **DESTROYED** / **OPEN** / **ACTIVATED** unhides the rest. Breakables are `Destroyed`. Doors are `Open`.
6. Highlight the row. **SAVE IDENTITY**.

That writes `save_object` (`world` + RegionID + LayerID + ObjectID + key). LocationChecks still need a RAM offset.

**EXPORT … JSON** writes `saves/_scratch/slots/`. **SAVES** tab: ENCODE TO EDITED (`saves/edited/`, autosave only) then INSTALL TO STEAM (type `INSTALL`; refused while the game is attached).

### RAM DUMP — live flag (after identity)

1. Load a save where the chest is still closed. Stand next to it.
2. **RAM DUMP** tab. **F8** (or BASELINE) — 4 s, stand still.
3. Open the chest. **F8** (or DIFF) — 1.5 s.
4. Pick the 0→1 row if more than one remains. **SAVE RAM**.

Identified rows scan the heap for the packed ObjectID+RegionID+LayerID triple, then nearby, then ObjectID alone, and diff around those anchors. No identity diffs 34 MB of `.data`, where chest flags are not. A heap byte is saved only if a static pointer chain from `darksiders1.exe` exists. Extra F8 keeps only candidates that survived every diff. Last capture: `snapshots/last_capture.npz`.

---

## `capture`

Terminal version of dashboard SAVE DIFF / RAM DUMP.

```powershell
python -m tools capture --sav FILE.sav --slots 1 2 --location "Seraphim Hotel Life Chest 1"
python -m tools capture --location "Seraphim Hotel Life Chest 1"   # RAM; uses save_object if present
python -m tools capture --region "Crossroads" --next
python -m tools capture --sav FILE.sav --slots 1 2 --location "…" --dry-run
```

| Flag | |
|------|--|
| `--location NAME` | Exact catalog name or unique substring. Also recaptures a mapped row. |
| `--sav` `--slots BEFORE AFTER` | Closed then open. Writes `save_object`. |
| `--region` | Filter the picker. |
| `--next` | First unmapped check in `--region`, no menu. |
| `--dry-run` | Print; do not write `targets.json`. |

Without `--sav`, this is the RAM capture (heap around `save_object`, else `.data`).

---

## `scan`

HUD counts for item writes. Not a chest 0→1 unless you pass `--sav`.

```powershell
python -m tools scan                                          # souls (Soul_Count, float)
python -m tools scan --item "Progressive Chaoseater"          # weapon level 1..4
python -m tools scan --sav FILE.sav --slots 1 2 --item "Seraphim Hotel Life Chest 1"
python -m tools scan --item "Progressive Chaoseater" --type uint32 --dry-run
```

| Flag | |
|------|--|
| `--item NAME` | `targets.json` / catalog label. Default is souls. |
| `--type` | Override the row type (`float`, `uint8`, …). |
| `--sav` `--slots` | Chest identity (same as `save-diff --location`). Not a HUD scan. |
| `--dry-run` | Print; do not write. |

Dashboard **ITEM WRITES** shows the command for the selected row. Type the HUD number, change it in-game, type again. Heap hits become a pointer chain.

---

## `locations`

```powershell
python -m tools locations
python -m tools locations --region "Seraphim Hotel"
python -m tools locations --region "Crossroads" --todo
```

`--todo` = no RAM offset yet (identified-only rows still count as todo).

---

## `sync-world`

```powershell
python -m tools sync-world
```

Reads `worlds/darksiders/data/` and rewrites `docs/world_locations.json` + `docs/world_items.json`. Needs the Archipelago-Darksiders clone (see [WORLD.md](../docs/WORLD.md)). No flags.

---

## `export-docs`

```powershell
python -m tools export-docs
```

Rebuilds `docs/memory_map.md` from `targets.json`. Run after you trust a RAM offset. No flags.

---

## `save-brief`

Decode and summarize. Does not write identity or RAM.

```powershell
python -m tools save-brief --slot 1 FILE.sav
python -m tools save-brief --all FILE.sav
python -m tools save-brief --slot 1 --export FILE.sav          # JSON → saves/_scratch/slots/
python -m tools save-brief dump.json
```

| Flag | |
|------|--|
| `path` | `.sav` or Keen JSON. |
| `--slot N` | `-1` autosave, `0`–`9` list. Required for a `.sav` unless `--all`. |
| `--all` | Every occupied slot in a `.sav`. |
| `--export [JSON]` | Write decoded JSON (default under `saves/_scratch/slots/`). |

Prints spawn, chests opened, HP, and Triggered / Destroyed / Open counts.

---

## `save-diff`

```powershell
python -m tools save-diff --slots 1 2 FILE.sav
python -m tools save-diff --slots 1 2 --location "Seraphim Hotel Life Chest 1" FILE.sav
python -m tools save-diff BEFORE.json AFTER.json
python -m tools save-diff --include-tiles --slots 1 2 FILE.sav
```

| Flag | |
|------|--|
| `before` `[after]` | One `.sav` with `--slots`, or two JSON / `.sav` paths. |
| `--slots BEFORE AFTER` | Closed then open. Required for a single `.sav`. |
| `--location NAME` | Write the matching flag onto that catalog row (`save_object`). Chests stay on `Triggered`; breakables are filtered unless they are the only hit. |
| `--include-tiles` | Also print MapTileData (fog), not chests. |

`--location` is the CLI equivalent of dashboard SAVE IDENTITY.

---

## `save-patch`

Change `SaveGameInfo.UserId` with whatisaphone/war. Autosave slot only. Prefer this over poking dwords.

```powershell
python -m tools save-patch --sav FILE.sav --userid YOUR_STEAM_ID --out saves\edited\FILE.sav
python -m tools save-patch --sav saves\edited\FILE.sav --userid YOUR_STEAM_ID --install
```

| Flag | |
|------|--|
| `--sav` | Source `.sav` (not JSON). Required. |
| `--userid` | Steam `userdata` folder name. Required. |
| `--out` | Dest `.sav`. Default overwrites `--sav`. Put output in `saves/edited/`. |
| `--install` | Copy into Steam `remote\` and `remote\autocloud\save\` as both `svd_fmt_0_0.sav` and `keen_savegame_0_0.sav`. Quit the game first. |
| `--dest` | Extra copy folder. |
| `--war` | Path to `war` / `war-cli` if it is not on PATH. |

Dashboard SAVES tab is the same encode → INSTALL flow.

---

## `save-install`

JSON-side UserId rewrite for a Crossroads-after-Vulgrim AP template. Refuses a late-game bag unless `--force`. It does not encode a playable `.sav` — use `save-patch` for that.

```powershell
python -m tools save-install --json TEMPLATE.json --userid YOUR_STEAM_ID --out-json patched.json
python -m tools save-install --json TEMPLATE.json --sav TEMPLATE.sav --userid YOUR_STEAM_ID --install
```

| Flag | |
|------|--|
| `--json` / `--sav` | Template files (at least one). |
| `--userid` | Required. |
| `--old-userid` | Template author id (default: read from `--json`). |
| `--out-json` `--out-sav` | Dest paths. |
| `--install` / `--dest` | Copy patched `.sav` into Steam remote. |
| `--force` | Allow the late-game mapping bag. |

---

## `targets.json`

| Field | |
|-------|--|
| `id` | Stable key. Required. |
| `label` | Exact world name (join key with Sacha’s `data/*.json`). |
| `offsets` | Module-relative hex. `["0x0"]` = not a RAM watch. |
| `save_object` | Keen identity: `world`, `region_id`, `layer_id`, `object_id`, `value_key`. Not a live AP watch. |
| `type` | `bool`, `uint8/16/32/64`, `int8/16/32/64`, `float`, `double`. |
| `bitmask` | Optional; not on float / double. |
| `category` | `location_flag` \| `inventory` \| `stat` \| `misc`. |
| `event_type` | `LOCATION_CHECK` \| `MEMORY_STATE` (default) \| `GOAL`. |
| `enabled` | `false` keeps the row but skips it. Identify leaves this false. |
| `module` | Default `darksiders1.exe`. |

Never store absolute addresses (ASLR). To drop a row, delete it; SQLite and `memory_map.md` follow on the next sync.
