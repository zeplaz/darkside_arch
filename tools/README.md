# tools

Mapper-only. Finds module-relative RAM offsets and saves them to `targets.json`, which [ds_client](../ds_client/README.md) hot-reloads. Labels must be the exact `Locations.py` / `Items.py` names ([WORLD.md](../docs/WORLD.md)) — always pick them from the catalog, never type them.

```powershell
pip install -r requirements-dev.txt
python -m tools              # list commands
python -m tools CMD --help   # flags for one command
```

| Command | Use |
|---------|-----|
| `dashboard` | Browser UI: pick a location, capture it, watch live values. **Start here.** |
| `capture` | Same chest capture in the terminal |
| `scan` | HUD numbers: souls, item counts |
| `locations` | List checks with todo / done |
| `sync-world` | Refresh `docs/world_*.json` after pulling the world clone |
| `export-docs` | Write `docs/memory_map.md` once offsets are trusted |
| `save-brief` / `save-diff` / `save-install` | Keen save files — see [SAVES.md](../docs/SAVES.md) |

Every save goes through one path: it reuses the existing row for that label (the `0x0` template), enables it, and re-syncs SQLite. Capturing the same location again overwrites it.

## `dashboard`

```powershell
python -m tools dashboard     # http://127.0.0.1:8765/   (--port, --host, --db, --no-browser)
```

The server attaches to the game read-only about a second after launch and reads every mapped row live, so a saved offset can be checked straight away. Press **?** on the page for the full guide.

1. Pick the location you are standing at (left).
2. **BASELINE** (`B`) while it is still closed. Stand still.
3. Open it in-game, then **DIFF** (`D`). **DIFF AGAIN** drops bytes that flicked back.
4. **SAVE** with one candidate, or click the right row first. Watch it flip under LIVE VALUES.

The capture lives on the server, so reloading the page keeps the baseline.

## `capture`

```powershell
python -m tools capture --region Crossroads      # pick from unmapped checks
python -m tools capture --location "Down Stairs" # one check, mapped or not (recapture)
python -m tools capture --next --region Crossroads
```

Baseline (two idle dumps of `.data`/`.bss`) → open it → after. Keeps only bytes that went 0→1 and were steady during the baseline; saves when exactly one remains. Otherwise it says so — use the dashboard to choose between several. `--dry-run` prints without saving. If nothing ever shows, the flag lives on the heap and needs a pointer path.

## `scan`

```powershell
python -m tools scan                               # souls (Soul_Count, float)
python -m tools scan --item "Progressive Chaoseater"
```

Type the HUD value, change it in-game, type the new value, repeat until one address is left. Heap addresses are turned into a pointer chain automatically. `--item` is a `targets.json` label; its `type` is used unless `--type` overrides it. `--dry-run` prints without saving. Not for chests — a value of 0 matches everything.

## `locations` / `sync-world` / `export-docs`

```powershell
python -m tools locations --region Crossroads --todo
python -m tools sync-world
python -m tools export-docs
```

## `targets.json`

| Field | |
|-------|--|
| `id` | Stable key. Required |
| `label` | Exact world name |
| `offsets` | Module-relative hex. One = `base + RVA`; several = pointer chain. `["0x0"]` = not mapped yet (ignored at runtime) |
| `type` | `bool`, `uint8/16/32/64`, `int8/16/32/64`, `float`, `double` |
| `bitmask` | Optional; not on float / double |
| `category` | `location_flag` \| `inventory` \| `stat` \| `misc` |
| `event_type` | `LOCATION_CHECK` \| `MEMORY_STATE` (default) \| `GOAL` |
| `enabled` | `false` keeps the row but skips it |
| `module` | Default `darksiders1.exe` |

Never store absolute addresses — they change every launch (ASLR). To drop a row, delete it; SQLite and `memory_map.md` follow on the next sync.
