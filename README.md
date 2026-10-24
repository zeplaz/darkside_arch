# darkside_arch

Out-of-process Archipelago client for **Darksiders Warmastered** (`darksiders1.exe`, Steam x64). Reads and writes game RAM from outside; no DLL injection. Run everything from the repo root.

| Track | Who | Install | Run |
|-------|-----|---------|-----|
| Mapping | Contributors | `pip install -r requirements-dev.txt` | `python -m tools dashboard` |
| Runtime / AP | Players | `pip install -r requirements.txt` | `python -m ds_client` |

A seed is **not playable yet**: 0 / 132 location RAM offsets. The client is written; it has nothing to watch. Full checklist: [ds_client/README.md](ds_client/README.md#checklist).

---

## Mapping dashboard

**This is the entry.** Open the browser workspace, identify a check from two save slots, then dump RAM for the live flag. CLI commands under `python -m tools` do the same jobs without the UI.

```powershell
pip install -r requirements-dev.txt
python -m tools dashboard
```

→ `http://127.0.0.1:8765/`

| It does | It does not |
|---------|-------------|
| Write [targets.json](targets.json) (`save_object`, then RAM `offsets`) | Connect to an AP server |
| Decode two Keen slots and name the WorldObject | Inject a DLL or poke memory from the page |
| Find the live 0→1 byte after you open the chest | Enable LocationChecks from identity alone |

`save_object` = Keen id (`world` + RegionID + LayerID + ObjectID + `Triggered`). **Not** a live watch. `ds_client` ignores `offsets: ["0x0"]` until RAM DUMP saves a real offset.

Longer copy + screenshots-in-words: [docs/DASHBOARD.md](docs/DASHBOARD.md). **?** on the page is the same guide.

### Identify a chest (SAVE DIFF)

Game can be closed. Slots: `-1` autosave, `0`–`9` the list.

1. Pause. **Save** while the chest is still closed. Note the slot.
2. Open it. **Save** in a different slot.
3. Pick the AP name on the **left** (catalog — do not type labels).
4. Set CLOSED / OPENED. **DIFF SAVES**.
5. **MATCH** shows chest `Triggered` rows. **DESTROYED** / **OPEN** / **ALL** unhide breakables and doors if you need them.
6. Highlight the chest. **SAVE IDENTITY**.

Hotel chest 1 is already identified (`overworld` r=2 L=6 obj=342). It still needs RAM DUMP.

### Live flag (RAM DUMP)

1. Load a save where that chest is still **closed**. Stand next to it.
2. **RAM DUMP** tab. **F8** (4 s, stand still).
3. Open the chest. **F8** (1.5 s).
4. Pick the 0→1 row if needed. **SAVE RAM**.

Heap around the Keen identity — not `.data`. No identity → do SAVE DIFF first.

### Left list / SAVES tab

Filter by OPEN / IDENTIFIED / MAPPED, kind (chest, artifact, armor, cube), chest loot, sort. **ITEM WRITES** is HUD scans (souls, weapon levels), not chests.

**SAVES** tab: ENCODE TO EDITED (`saves/edited/`), quit the game, INSTALL TO STEAM (type `INSTALL`). [docs/SAVES.md](docs/SAVES.md).

---

## Play

```powershell
pip install -r requirements.txt
python -m ds_client --connect HOST:PORT --slot NAME
```

Until offsets exist this only connects; it cannot report checks or apply items. Config: `ap_config.json` (gitignored). Details: [ds_client/README.md](ds_client/README.md).

---

## Docs

| Doc | Owns |
|-----|------|
| [docs/DASHBOARD.md](docs/DASHBOARD.md) | Dashboard: tabs, SAVE DIFF, RAM DUMP, SAVES |
| [docs/WORLD.md](docs/WORLD.md) | World pin, two-JSON split, hotel / Crossroads queue |
| [docs/SAVES.md](docs/SAVES.md) | Keen `.sav` slots, ObjectIDs, war / UserId |
| [docs/memory_map.md](docs/memory_map.md) | Generated RAM table (`export-docs`) |
| [tools/README.md](tools/README.md) | Every `python -m tools` command |
| [ds_client/README.md](ds_client/README.md) | Player client, flags, checklist |
| [docs/README.md](docs/README.md) | Index of `docs/` |

## Commit vs local

| Commit | Leave local (gitignored) |
|--------|-------------|
| `ds_client/`, `tools/`, `docs/`, `targets.json`, `ap_config.example.json`, `requirements*.txt` | `ap_config.json`, `ap_state.db`, `darksiders_debug.db`, `snapshots/`, `saves/`, `world/`, `.venv/` |

World: https://github.com/Sachaqc/Archipelago-Darksiders
