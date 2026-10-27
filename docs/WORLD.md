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
| Commit | `10d573a` — *All Locations* (2026-10-26) |

```powershell
if (-not (Test-Path world\Archipelago-Darksiders)) {
  New-Item -ItemType Directory -Path world -Force | Out-Null
  git clone https://github.com/Sachaqc/Archipelago-Darksiders.git world\Archipelago-Darksiders
}
git -C world\Archipelago-Darksiders pull --ff-only origin main
python -m tools sync-world
```

`sync-world` reads `data/*.json` (plus `docs/proposed/` for names he has not loaded yet) and writes [world_locations.json](world_locations.json) and [world_items.json](world_items.json). `Locations.py` `create_location_table_from_json` decides `"in_ap"`. Catalog now: **321** names (**319** in AP, hotel **2** deferred). Join key is still the location **name**. Black Throne / Eden / Iron Canopy are live. `Seraphim Hotel.json` is in his `data/` but **not** imported in `Locations.py`. Hotel AP ids **200 / 201** now collide with Black Throne chests — he must remint those if he loads hotel.

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
| Goal | Event `Abaddon the Destroyer defeated` → item `Victory` (`Leviathan Drift.json`, not a location ID) |
| Client | AP ≥ **0.6.7**, game name `Darksiders` |

Ask Sacha: load `Seraphim Hotel.json` from `Locations.py` / `Regions.py` so the two hotel chests are `in_ap`.

## Mapping queue

Hotel JSON is in his `data/Seraphim Hotel.json` (AP ids **200 / 201**) but `Locations.py` still does not import it, so tools mark the two chests deferred. [proposed/Seraphim Hotel.json](proposed/Seraphim%20Hotel.json) is our copy.

| Location | |
|----------|--|
| `Seraphim Hotel Life Chest 1` | AP 200. Keen `SB_G_Chest_HealthChest_01` `overworld` r=2 L=6 obj=342 `Triggered` (`/overworld/CI_StartBld`) |
| `Seraphim Hotel Life Chest 2` | AP 201. Keen `CI_SB_Exit_Chest_HealthChest` `overworld` r=260 L=1 obj=16 `Triggered` (`/overworld/CI_SB_Exit`). Different region than chest 1. |
| `Crossroads South Crater Chest` | AP 600 Currency |
| `Crossroads West of Library Chest` | AP 601 Health |
| `Crossroads Chest Blocked by Ice` | AP 602 Hellfire — skip until ice tools |
| `Crossroads Subway Station Artifact` | AP 603 Soldier Artifact |
| `Crossroads Subway Station Chest` | AP 604 Currency |
| `Crossroads North Building Chest` | AP 605 Currency |
| `Crossroads Back Alley Chest` | AP 606 Health |
| `Crossroads Back Alley Downstairs Chest` | AP 607 Currency |
| `Crossroads East Crater Chest` | AP 608 Health |
| `Crossroads Secret Chest Destroy Fire Hydrants` | AP 609 Currency |

Identify with two in-game save slots → dashboard **DIFF SAVES** ([DASHBOARD.md](DASHBOARD.md)). That is not a RAM watch.

Later `0x0` templates: inventory `Beholder Key` (id 60), `Heart of the Chosen` (id 90), `Progressive Chaoseater` (id 100, cap 4), `Progressive Scythe` (id 110, cap 4), `Progressive Gauntlet` (id 113, cap 4), `Armageddon Blade Shards` (id 103), `Armageddon Blade` (id 102); stat `Soul_Count`; goal `Abaddon the Destroyer defeated`.
