# tools — developer mapping toolchain

Discover and document Steam x64 offsets. Players do **not** need this package — see [`../ds_client/`](../ds_client/README.md).

## Setup

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements-dev.txt
```

Installs client deps + `PyMemoryEditor[speed]`.

## Commands

| Command | Purpose |
|---------|---------|
| `python -m tools scan … [--auto-save]` | Exact + refine scan; `--auto-save` upserts `targets.json` |
| `python -m tools sync-map` | `targets.json` → SQLite `memory_map` |
| `python -m tools tag LABEL [--region R] [--category C]` | Tag latest delta |
| `python -m tools export-docs [PATH]` | Write `docs/memory_map.md` |

## Soul count (first goal)

1. Game running, free roam, note HUD souls.
2. Scan and save:

```bash
python -m tools scan --type uint32 --id soul_count --label Soul_Count --category stat --auto-save
```

3. Verify:

```bash
python -m ds_client
```

Omit `--auto-save` for a dry-run print only.

## Chest / flag

Use **exact** world names ([docs/WORLD.md](../docs/WORLD.md)):

```bash
python -m tools scan --type uint8 --id chest_crossroads_currency_down_stairs \
  --label "Crossroads Currency Chest Down Stairs" \
  --category location_flag --auto-save
```

Then:

```bash
python -m tools tag "Crossroads Currency Chest Down Stairs" --region Crossroads --category location_flag
python -m tools export-docs
```

## Loop

1. `scan … --auto-save`
2. `python -m ds_client` (baseline → action → delta)
3. optional `tag`
4. `export-docs` → commit `docs/memory_map.md` only when verified

## ASLR + schema

`--auto-save` writes module-relative `offsets` into this repo’s schema (`observe_interval_ms` / `module` / `targets[]`). Absolute VAs are debug-only and never stored. Same `id` updates in place; new `id` appends. Existing `region` / `bitmask` are preserved when the scan omits them.

## Package files

| File | Role |
|------|------|
| `scanner.py` | PME scan + `--auto-save` |
| `export_docs.py` | SQLite → Markdown |
| `cli.py` / `__main__.py` | `python -m tools` |

## Related

- [ds_client/README.md](../ds_client/README.md)
- [docs/README.md](../docs/README.md)
- [docs/WORLD.md](../docs/WORLD.md)
