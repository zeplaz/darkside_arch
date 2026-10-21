# docs

| File | Commit | What it is |
|------|--------|------------|
| [memory_map.md](memory_map.md) | yes | Locked-in offsets. Auto-written by `export-docs` |
| [WORLD.md](WORLD.md) | yes | World-fork pin, sync, name contract |
| [SAVES.md](SAVES.md) | yes | Sacha Keen `.sav` / JSON — types, not offsets |
| [world_locations.json](world_locations.json) | yes | Catalog cache from `Locations.py` |
| `README.md` | yes | This index |

| When | UI | CLI |
|------|----|-----|
| Mapping session | `python -m tools dashboard` → http://127.0.0.1:8765/ | — |
| Chest / flag | Pick row → Baseline → After → Save | `python -m tools capture --region Crossroads` |
| Souls | — | `python -m tools scan --auto-save` |
| After verify | **Write docs/memory_map.md** | `python -m tools export-docs` |
| World clone updated | — | `python -m tools sync-world` then bump [WORLD.md](WORLD.md) |

Do not run `export-docs` on every probe. Labels must match [WORLD.md](WORLD.md) byte-for-byte.
