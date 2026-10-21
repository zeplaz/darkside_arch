# tools

Mapper-only. Discovers module-relative offsets and writes `targets.json`. Players use [ds_client](../ds_client/README.md).

```powershell
pip install -r requirements-dev.txt
```

## What to run

| Job | Command | Writes |
|-----|---------|--------|
| Chest / artifact / flag | `python -m tools capture --region Crossroads` | `targets.json` if one `0→1` |
| HUD souls | `python -m tools scan --auto-save` | `targets.json` (opt-in) |
| Live page | `python -m tools dashboard` | nothing (reads SQLite) |
| List AP checks | `python -m tools locations --region Crossroads --unmapped` | stdout |
| Refresh names from world clone | `python -m tools sync-world` | `docs/world_locations.json` |
| Push `targets.json` → DB | `python -m tools sync-map` | `darksiders_debug.db` |
| Lock-in Markdown | `python -m tools export-docs` | `docs/memory_map.md` |
| Tag last live delta | `python -m tools tag "Exact Location Name"` | SQLite |
| One PE dump | `python -m tools snapshot --name NAME` | `snapshots/NAME/` |
| Diff two dumps | `python -m tools diff A B` | stdout |
| Keen JSON summary | `python -m tools save-brief PATH.json` | stdout |
| Keen JSON delta | `python -m tools save-diff --before A.json --after B.json` | stdout |

Location **labels** must match Sacha’s `Locations.py` byte-for-byte ([docs/WORLD.md](../docs/WORLD.md)). Pick from the catalog; do not invent names.

## Mapping loop

1. Game running, stand at a still-closed check.
2. `python -m tools dashboard` (leave open).
3. `python -m tools capture --region Crossroads` → pick row → Enter → open → Enter.
4. Souls only: `python -m tools scan --auto-save`.
5. When verified: `python -m tools export-docs`.

| Live | Locked-in |
|------|-----------|
| `dashboard` + SQLite | `export-docs` → `docs/memory_map.md` |
| Every probe | Only after verify |

Heap-only flags will not show in capture. That is a pointer-path problem, not a HUD scan.

## `capture` — location checks

Stand still → Enter (idle pair) → open/trigger → Enter. Default type is `uint8`. Auto-save is **on**.

| Option | Default | Meaning |
|--------|---------|---------|
| `--region` | (all) | Filter picker, e.g. `Crossroads` |
| `--location` | | Exact name or unique substring |
| `--next` | off | First unmapped in `--region` (no menu) |
| `--no-auto-save` | | Print only; do not write `targets.json` |
| `--all-deltas` | | Show every changed byte, not only `0→1` |
| `--process` | `darksiders1.exe` | |

```powershell
python -m tools capture --region Crossroads
python -m tools capture --location "Down Stairs"
python -m tools capture --next --region Crossroads
```

## `scan` — known HUD numbers

Type the HUD value, change it in-game, refine. **Not** for chests. Default is souls as `float`.

| Option | Default | Meaning |
|--------|---------|---------|
| `--type` | `float` | `float` souls; `int32` health; `uint8`/`bool` flags (prefer `capture`) |
| `--id` | `soul_count` | `targets.json` id |
| `--label` | `Soul_Count` | Display / docs name |
| `--category` | `stat` | `stat` \| `inventory` \| `location_flag` \| `misc` |
| `--auto-save` | off | Write `targets.json` + sync SQLite |
| `--writeable-only` | off | Faster; may miss read-only |
| `--no-pointer-scan` | off | Skip heap pointer recovery |
| `--process` | `darksiders1.exe` | |
| `--targets` | `targets.json` | |

```powershell
python -m tools scan --auto-save
```

## `dashboard`

http://127.0.0.1:8765/ — real catalog and snapshot buttons, not a mock. You still pick the row.

| Option | Default | Meaning |
|--------|---------|---------|
| `--host` | `127.0.0.1` | |
| `--port` | `8765` | |
| `--db` | `darksiders_debug.db` | |
| `--no-browser` | off | Do not open a tab |

## `locations` / `sync-world` / `sync-map` / `export-docs` / `tag`

| Command | Option | Default | Meaning |
|---------|--------|---------|---------|
| `locations` | `--region` | | Filter by region or name |
| `locations` | `--unmapped` | off | Hide rows that already have a real offset |
| `export-docs` | `[PATH]` | `docs/memory_map.md` | Output file |
| `tag` | `LABEL` | required | Exact world name |
| `tag` | `--region` | | |
| `tag` | `--category` | | `location_flag` \| `inventory` \| `stat` \| `misc` |

`sync-world` and `sync-map` take no options.

## `snapshot` / `diff`

Manual capture equivalent. Dumps writable `.data` / `.bss`.

| Command | Option | Meaning |
|---------|--------|---------|
| `snapshot` | `--name` | Folder under `snapshots/` (required) |
| `snapshot` | `--process` | Default `darksiders1.exe` |
| `diff` | `BEFORE AFTER` | Snapshot names |
| `diff` | `--stable S` | Earlier idle dump; drops ticking bytes |
| `diff` | `--zero-to-one` | Keep only `0→1` |

## `save-brief` / `save-diff`

Keen **JSON** exports only. Not a chest keymap. See [docs/SAVES.md](../docs/SAVES.md).

| Command | Option | Meaning |
|---------|--------|---------|
| `save-brief` | `PATH.json` | Summarize one export |
| `save-diff` | `--before` / `--after` | Field-level delta |
| `save-diff` | `--include-tiles` | Also print minimap fog (`MapTileData`) |

## `targets.json`

`--auto-save` writes module-relative `offsets`. Same `id` updates; new `id` appends. Absolute VAs are never stored.

| Field | Meaning |
|-------|---------|
| `offsets` | One = `base+RVA`; many = pointer chain |
| `type` | See `ds_client` types |
| `label` | Must match `Locations.py` for checks |
| `category` | `location_flag` \| `inventory` \| `stat` \| `misc` |
| `enabled` | `false` skips without deleting |
