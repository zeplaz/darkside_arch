# darkside_arch

Out-of-process memory client for **Darksiders Warmastered** (`darksiders1.exe`, Steam x64). No injection.

| Track | Who | Install | Run |
|-------|-----|---------|-----|
| Runtime client | Players / future AP sink | `pip install -r requirements.txt` | `python -m ds_client` |
| Mapping tools | Contributors | `pip install -r requirements-dev.txt` | `python -m tools …` |

| I want to… | Command |
|------------|---------|
| Watch enabled `targets.json` rows | `python -m ds_client` |
| Map a chest / artifact / flag | `python -m tools capture --region Crossroads` |
| Map HUD souls | `python -m tools scan --auto-save` |
| Live catalog + telemetry | `python -m tools dashboard` |
| Lock offsets into Markdown | `python -m tools export-docs` |

Details: [ds_client/README.md](ds_client/README.md) · [tools/README.md](tools/README.md)

| Doc | What it is |
|-----|------------|
| [docs/README.md](docs/README.md) | Docs index |
| [docs/memory_map.md](docs/memory_map.md) | Locked-in offsets (commit when real) |
| [docs/WORLD.md](docs/WORLD.md) | World-fork pin + name contract |
| [docs/SAVES.md](docs/SAVES.md) | Sacha Keen `.sav` / JSON |

| Commit | Leave local |
|--------|-------------|
| `ds_client/`, `tools/`, `docs/`, `targets.json`, `requirements*.txt` | `darksiders_debug.db`, `snapshots/`, `saves/`, `llm/`, `world/`, `.venv/` |

| Link | |
|------|--|
| This repo | https://github.com/zeplaz/darkside_arch |
| World (Sacha) | https://github.com/Sachaqc/Archipelago-Darksiders |
| Fork vs AP `main` | https://github.com/ArchipelagoMW/Archipelago/compare/main...Sachaqc:Archipelago-Darksiders:main |
