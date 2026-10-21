# tools

Mapper-only. Discovers module-relative offsets and writes `targets.json`. Players use [ds_client](../ds_client/README.md).

```powershell
pip install -r requirements-dev.txt
```

## What to run

| Job | UI | CLI |
|-----|----|-----|
| Chest / artifact / flag | Pick → Baseline → After → Save | `python -m tools capture --region Crossroads` |
| HUD souls | — | `python -m tools scan --auto-save` |
| Live catalog + watches | `python -m tools dashboard` | — |
| List AP checks | left pane | `python -m tools locations --region Crossroads --unmapped` |
| Refresh world names | — | `python -m tools sync-world` |
| Push targets → DB | Save / Refresh | `python -m tools sync-map` |
| Lock-in Markdown | **Write docs/memory_map.md** | `python -m tools export-docs` |
| Tag last live delta | — | `python -m tools tag "Exact Location Name"` |
| Raw PE dump / diff | — | `snapshot --name X` / `diff A B` |
| Keen JSON | — | `save-brief` / `save-diff` |

Location **labels** must match Sacha’s `Locations.py` byte-for-byte ([docs/WORLD.md](../docs/WORLD.md)). Pick from the catalog; do not invent names.

## Dashboard vs CLI

Both paths log the same way: dump writable `.data` / `.bss`, keep a single `0→1`, write a `uint8` row into `targets.json`. Do **not** click Save in the UI and also run `capture` for the same chest.

| | Dashboard (UI) | Terminal (manual) |
|--|----------------|-------------------|
| Start | `python -m tools dashboard` | same install; no extra server |
| URL | http://127.0.0.1:8765/ (opens a tab) | — |
| Pick a check | Area dropdown + Open/Mapped + Chests/Artifacts | `--region` / `--location` / `--next` or a number menu |
| Baseline | **Capture baseline** (stand still, check closed) | Enter on `capture` |
| After the action | Open in-game, then **Capture after** | Open in-game, then Enter |
| Write offset | **Save to targets.json** (needs exactly one `0→1`) | auto-save on (or `--no-auto-save`) |
| Watch live values | Right pane **Watches** / **Delta log** | `python -m ds_client` in another terminal |
| Lock-in Markdown | **Write docs/memory_map.md** | `python -m tools export-docs` |
| Souls / HUD number | not in the UI | `python -m tools scan --auto-save` |

Heap-only flags will not show. That is a pointer-path problem, not a HUD scan.

### Run the UI

```powershell
pip install -r requirements-dev.txt
python -m tools dashboard
```

Game must be running for Baseline / After. Leave the dashboard terminal open. `Ctrl+C` stops it.

| Option | Default | Meaning |
|--------|---------|---------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8765` | |
| `--db` | `darksiders_debug.db` | |
| `--no-browser` | off | Print the URL only |

### UI click path (location check)

1. Launch Warmastered, stand at a **still-closed** check.
2. Left: **Area** = map cell (e.g. Crossroads). **Open** + **Chests** (or Artifacts / Other).
3. Click the location row (AP name). The tool cannot see which chest you face.
4. **Capture baseline** — two idle dumps.
5. Open / trigger it in-game.
6. **Capture after** — pane lists changed bytes (`0→1`).
7. **Save to targets.json** if exactly one candidate. Same file the CLI writes.
8. After you trust it: **Write docs/memory_map.md** (or `export-docs`). Do not spam this every probe.

Middle toggle: `targets.json` vs on-disk `docs/memory_map.md`. Right: last verified watches vs `ds_client` delta log.

### CLI path (same job)

```powershell
python -m tools capture --region Crossroads
```

Number picker (or `--location "Down Stairs"` / `--next`). Enter = baseline, do the action, Enter = after. Auto-save is on.

```powershell
python -m tools scan --auto-save
```

Souls only (default `--type float`). There is no dashboard equivalent.

```powershell
python -m tools snapshot --name before
python -m tools snapshot --name after
python -m tools diff before after --zero-to-one
```

Lowest-level dumps if you do not want `capture` or the UI.

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
