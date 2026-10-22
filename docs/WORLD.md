# World fork

Names live in Sacha’s world. This repo stores offsets + labels only.

| | |
|--|--|
| Fork | https://github.com/Sachaqc/Archipelago-Darksiders |
| vs AP `main` | https://github.com/ArchipelagoMW/Archipelago/compare/main...Sachaqc:Archipelago-Darksiders:main |
| Local clone | `world/Archipelago-Darksiders/` (gitignored) |

## Pin

Bump this table after every `git pull` of the clone.

| Field | Value |
|-------|--------|
| Branch | `main` |
| Commit | `71ddf44` — *First test without Errors* (2026-10-19) |

```powershell
if (-not (Test-Path world\Archipelago-Darksiders)) {
  New-Item -ItemType Directory -Path world -Force | Out-Null
  git clone https://github.com/Sachaqc/Archipelago-Darksiders.git world\Archipelago-Darksiders
}
git -C world\Archipelago-Darksiders pull --ff-only origin main
python -m tools sync-world
```

`sync-world` writes [world_locations.json](world_locations.json) and [world_items.json](world_items.json).

## Contract

| | |
|--|--|
| Names | `targets.json` `label` = `Locations.py` / `Items.py` byte-for-byte |
| IDs | Stay in the world package + those JSON caches. Never hand-type ids |
| Goal | `Victory` from event `Abaddon The Destroyer defeated` (7 shards + Mask + Ruin + Shadowflight). Boss dict is still commented — do not invent flags |
| Client | AP ≥ **0.6.7**, game name `Darksiders` |

## Mapping queue (Crossroads)

Templates exist in `targets.json`, all `enabled: false` / `offsets: ["0x0"]`.

| Location | |
|----------|--|
| `Crossroads Currency Chest Down Stairs` | Capture first |
| `Crossroads Currency Chest South Crater` | |
| `Crossroads Currency Chest in Subway Station` | |
| `Crossroads Life Chest Behind Gholen West` | |
| `Crossroads Life Chest Behind Gholen North` | |
| `Crossroads Life Chest NE Crater` | |
| `Crossroads Secret Chest Destroy Fire Hydrants` | |
| `Crossroads Soldier Artifact in Subway Station` | |
| `Crossroads Rare Chest Blocked by Ice` | Skip until ice tools |

Capture them with `python -m tools dashboard` ([tools](../tools/README.md)).

Later `0x0` templates: inventory `Beholder Key`, `Heart of the Chosen`, `Progressive Chaoseater`, `Progressive Scythe`, `Progressive Gauntlet`, `Armageddon Blade Shards`, `Armageddon Blade`; stat `Soul_Count`; goal `Abaddon The Destroyer defeated`.
