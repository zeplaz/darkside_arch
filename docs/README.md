# docs

Mapping reference and world-sync notes for **Darksiders Warmastered (x64)**.

## Files

| File | Commit? | Purpose |
|------|---------|---------|
| [memory_map.md](memory_map.md) | yes | Verified offsets (regenerate with tools; commit when real) |
| [WORLD.md](WORLD.md) | yes | World fork pin, sync commands, early location names |
| `README.md` | yes | This index |

## Produce `memory_map.md`

```bash
pip install -r requirements-dev.txt
python -m tools scan … --auto-save
python -m ds_client
python -m tools tag "…" --region "…" --category location_flag
python -m tools export-docs
```

`export-docs` reads SQLite `memory_map` (and syncs enabled `targets.json` rows). A local dirty `darksiders_debug.db` can add unverified rows — only commit `memory_map.md` after you trust the contents.

## Naming

Exact strings from the world package ([WORLD.md](WORLD.md)):

- https://github.com/Sachaqc/Archipelago-Darksiders/blob/main/worlds/darksiders/Locations.py
- https://github.com/Sachaqc/Archipelago-Darksiders/blob/main/worlds/darksiders/Items.py

Compare: https://github.com/ArchipelagoMW/Archipelago/compare/main...Sachaqc:Archipelago-Darksiders:main
