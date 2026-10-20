# darkside_arch

Out-of-process **Darksiders Warmastered Edition** (`darksiders1.exe`) memory client for Archipelago.

No injection. No hooks. Windows x64 Steam build only.

## Two tracks

| Track | Who | Package | Install | Entry |
|-------|-----|---------|---------|-------|
| **Client (runtime)** | Players / final AP client | [`ds_client/`](ds_client/README.md) | `pip install -r requirements.txt` | `python -m ds_client` |
| **Dev tools** | Mappers / contributors | [`tools/`](tools/README.md) | `pip install -r requirements-dev.txt` | `python -m tools …` |

| Doc | Purpose |
|-----|---------|
| [`docs/memory_map.md`](docs/memory_map.md) | Verified x64 offsets (commit when real) |
| [`docs/WORLD.md`](docs/WORLD.md) | Sacha world fork pin, sync, naming checklist |
| [`docs/README.md`](docs/README.md) | Docs index |

## Layout

```
darkside_arch/
  requirements.txt       # client runtime (psutil)
  requirements-dev.txt   # + PyMemoryEditor[speed]
  targets.json           # watch definitions (shared)
  ds_client/             # FINAL CLIENT
  tools/                 # DEV scan / tag / export
  docs/                  # memory map + world sync notes
  llm/                   # gitignored scratch
  world/                 # gitignored local world clone
```

## Quick start

### A) Client (observe memory)

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m ds_client
```

Needs enabled entries in `targets.json`. Details: [ds_client/README.md](ds_client/README.md).

### B) Dev mapping

```bash
pip install -r requirements-dev.txt
python -m tools scan --type uint32 --id soul_count --label Soul_Count --category stat --auto-save
python -m ds_client
python -m tools tag "Crossroads Currency Chest Down Stairs" --region Crossroads --category location_flag
python -m tools export-docs
```

`--auto-save` upserts module-relative offsets into `targets.json` (`enabled: true`). Details: [tools/README.md](tools/README.md).

## Commit vs local-only

| Artifact | Commit? |
|----------|---------|
| `ds_client/`, `tools/`, `docs/`, `targets.json`, `requirements*.txt` | yes |
| `darksiders_debug.db` | no (auto-created SQLite) |
| `llm/`, `world/`, `.venv/` | no |

## Continuity

| Resource | URL |
|----------|-----|
| This client | https://github.com/zeplaz/darkside_arch |
| World (Sacha) | https://github.com/Sachaqc/Archipelago-Darksiders |
| Fork vs AP `main` | https://github.com/ArchipelagoMW/Archipelago/compare/main...Sachaqc:Archipelago-Darksiders:main |
| World sync notes | [docs/WORLD.md](docs/WORLD.md) |
| AP network protocol | https://github.com/ArchipelagoMW/Archipelago/blob/main/docs/network%20protocol.md |
| AP developer docs | https://archipelago.gg/doc/developer |

## Roadmap

- **Now (client):** attach → `targets.json` → deltas → SQLite
- **Now (tools):** scan `--auto-save` → verify → tag → export `docs/memory_map.md`
- **Later (client):** Archipelago WebSocket sink inside `ds_client/` (not `tools/`)
