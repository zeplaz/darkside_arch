# World fork

Names and AP ids live in Sacha’s `worlds/darksiders/data/*.json`. This repo stores Keen object keys + RAM offsets in `targets.json`. Two JSON sources — do not merge RAM into the world package. `targets.json` is ours; Sacha will not recognize it.

| | |
|--|--|
| Fork | https://github.com/Sachaqc/Archipelago-Darksiders |
| vs AP `main` | https://github.com/ArchipelagoMW/Archipelago/compare/main...Sachaqc:Archipelago-Darksiders:main |
| Local clone | `world/Archipelago-Darksiders/` (gitignored) |
| AP catalog | `worlds/darksiders/data/` (per-region JSON + `Items.json`) |

## Pin

Bump this table after every `git pull` of the clone.

| Field | Value |
|-------|--------|
| Branch | `main` |
| Commit | `0a61a1c` — *Update Locations.py* (2026-10-23) |

```powershell
if (-not (Test-Path world\Archipelago-Darksiders)) {
  New-Item -ItemType Directory -Path world -Force | Out-Null
  git clone https://github.com/Sachaqc/Archipelago-Darksiders.git world\Archipelago-Darksiders
}
git -C world\Archipelago-Darksiders pull --ff-only origin main
python -m tools sync-world
```

`sync-world` reads `data/*.json` (not the old `Locations.py` dicts) and writes [world_locations.json](world_locations.json) and [world_items.json](world_items.json). Locations.py still decides which JSON files are in the AP table (`create_location_table_from_json`). Commented files (Black Throne, Eden, Iron Canopy, Leviathan Drift) sync with `"in_ap": false`.

## Contract

| | Who | |
|--|--|--|
| Location **name** + AP **id** | Sacha `data/*.json` | Join key. `targets.json` `label` is byte-for-byte the same |
| `vanilla item` | Sacha JSON | Hint only — several Hollows rows currently say Currency for armor/keys |
| Keen **object** | This repo `save_object` | `world` + RegionID + LayerID + ObjectID + `Triggered`/`Destroyed`/`Open` |
| RAM **offset** | This repo `targets.json` only | Warmastered / ASLR. Never write RVAs into the world |

If Sacha later adds Keen keys on a location object, we ingest them. RAM offsets stay here. `ds_client` only watches RAM.

| | |
|--|--|
| Goal | Event `Abaddon Destroyer defeated` → item `Victory` (still Python events, not JSON) |
| Client | AP ≥ **0.6.7**, game name `Darksiders` |

Ask Sacha: a `Seraphim Hotel.json`; stop `print(location)` in `Locations.py` (fires on import); `Regions.py` `Choking grounds.json` vs file `Choking Grounds.json` (breaks Linux); Hollows `vanilla item` copy-paste.

## Mapping queue

Hotel is a local/proposed patch: [proposed/Seraphim Hotel.json](proposed/Seraphim%20Hotel.json) (AP ids **200 / 201** — 1029/1030 now belong to Hollows). Copy into `worlds/darksiders/data/` and load it from `Locations.py` / `Regions.py`. Send that file to Sacha; do not treat the ids as final until he accepts them.

| Location | |
|----------|--|
| `Seraphim Hotel Life Chest 1` | AP 200. Keen `SB_G_Chest_HealthChest_01` `overworld` r=2 L=6 obj=342 `Triggered` (`/overworld/CI_StartBld`) |
| `Seraphim Hotel Life Chest 2` | AP 201. Keen `CI_SB_Exit_Chest_HealthChest` `overworld` r=260 L=1 obj=16 `Triggered` (`/overworld/CI_SB_Exit`). Different region than chest 1. |
| `Crossroads Currency Chest Down Back Alley Stairs` | was “Down Stairs”, AP 600 |
| `Crossroads Currency Chest in North Building` | new, AP 601 |
| `Crossroads Currency Chest South Crater` | AP 602 |
| `Crossroads Currency Chest in Subway Station` | AP 603 |
| `Crossroads Life Chest East Crater` | AP 604 — old Gholen/NE names retired |
| `Crossroads Life Chest in NE Back Alley` | AP 605 |
| `Crossroads Life Chest West of Library` | AP 606 |
| `Crossroads Rare Chest Blocked by Ice` | AP 607 — skip until ice tools |
| `Crossroads Secret Chest Destroy Fire Hydrants` | AP 608 |
| `Crossroads Soldier Artifact in Subway Station` | AP 609 |

Identify with two in-game save slots → dashboard **DIFF SAVES** ([tools](../tools/README.md)). That is not a RAM watch.

Later `0x0` templates: inventory `Beholder Key` (id 60), `Heart of the Chosen` (id 90), `Progressive Chaoseater` (id 100, cap 4), `Progressive Scythe` (id 110, cap 4), `Progressive Gauntlet` (id 113, cap 4), `Armageddon Blade Shards` (id 103), `Armageddon Blade` (id 102); stat `Soul_Count`; goal `Abaddon Destroyer defeated`.
