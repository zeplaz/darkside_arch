# docs

| Doc | Owns |
|-----|------|
| [../runtime/dll/README.md](../runtime/dll/README.md) | **DLL how-to** (TEST/LIVE, dashboard + CLI). |
| [runtime.md](runtime.md) | Mem vs DLL architecture overview. |
| [DASHBOARD.md](DASHBOARD.md) | Mapping entry: SAVE DIFF, RAM DUMP, SAVES, DLL LAB pointer. |
| [WORLD.md](WORLD.md) | Sacha fork pin, two-JSON split, hotel / Crossroads queue. |
| [SAVES.md](SAVES.md) | Keen `.sav` slots, ObjectIDs, war, UserId install. |
| [memory_map.md](memory_map.md) | Generated RAM table. Never edit by hand (`python -m tools export-docs`). |
| [world_locations.json](world_locations.json) / [world_items.json](world_items.json) | Catalog from `sync-world`. Do not hand-edit. |
| [proposed/](proposed/) | Our test JSON only (hotel **2000 / 2001**). Not part of Sacha’s world. |

Mapping starts at `python -m tools dashboard`. Command list: [tools/README.md](../tools/README.md). Player runtimes: [runtime/README.md](../runtime/README.md).
