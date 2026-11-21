# Darkside Arch

Darksiders **Warmastered (Steam x64)** Archipelago client — two deployable player runtimes plus the mapping toolchain.

## Runtimes (ship one)

| Path | Entry | How-to |
|------|-------|--------|
| **mem** | `python -m runtime.mem` | [runtime/mem/README.md](runtime/mem/README.md) |
| **dll** | `python -m runtime.dll` + inject | [runtime/dll/README.md](runtime/dll/README.md) |

Architecture (mem vs dll): [docs/runtime.md](docs/runtime.md) · runtime helper: [runtime/README.md](runtime/README.md).

## Mapping — find RAM offsets

- **Dashboard (start here):** `python -m tools dashboard` → guide [docs/DASHBOARD.md](docs/DASHBOARD.md)
- **Tools CLI** (`scan`, `identify`, `poke`, `capture`, `save-diff`, …): [tools/README.md](tools/README.md)
- **Keen object dumps + provenance** (`Chests.json` / `Artifacts.json` / …): [game_data/README.md](game_data/README.md)

## Save handling

- Keen `.sav` slots, ObjectIDs, `war`, UserId install: [docs/SAVES.md](docs/SAVES.md)
- Sacha's world fork, catalog sync, mapping queue: [docs/WORLD.md](docs/WORLD.md)

## Data & shared code

- [`targets.json`](targets.json) — our Keen identities + RAM offsets (source of truth)
- [`ap/`](ap/) — shared Archipelago client code
- [`ds_client/`](ds_client/) — `python -m ds_client` (mem path entry)
- [`docs/`](docs/README.md) — full docs index
