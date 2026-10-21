# World fork

Location and item **names** live in Sacha’s world, not this repo.

| | |
|--|--|
| Fork | https://github.com/Sachaqc/Archipelago-Darksiders |
| vs AP `main` | https://github.com/ArchipelagoMW/Archipelago/compare/main...Sachaqc:Archipelago-Darksiders:main |
| Local clone (gitignored) | `world/Archipelago-Darksiders/` |

## Pin

Update this table after every `git pull` of the clone.

| Field | Value |
|-------|--------|
| Branch | `main` |
| Commit | `71ddf44` — *First test without Errors* (2026-10-19) |
| vs AP `main` | ahead **3** / behind **2** (diverged) |

Ahead: `a73deac` → `4aeefc6` → `71ddf44`. Behind 2 is Sacha not merging AP core — not a `darkside_arch` bug.

```powershell
if (-not (Test-Path world\Archipelago-Darksiders)) {
  New-Item -ItemType Directory -Path world -Force | Out-Null
  git clone https://github.com/Sachaqc/Archipelago-Darksiders.git world\Archipelago-Darksiders
}
git -C world\Archipelago-Darksiders fetch origin
git -C world\Archipelago-Darksiders pull --ff-only origin main
git -C world\Archipelago-Darksiders log -1 --oneline
python -m tools sync-world
```

## What `71ddf44` means here

| World file | Change | What we do |
|------------|--------|------------|
| `Locations.py` | Unique AP ids | `label` must match names exactly |
| `Items.py` | `Deaths Blessing`, `Soul Bridge`, more gauntlets | Gear watches use these names |
| `Rules.py` | Goal: Armageddon Blade Shards ×7 | Map late flags later |
| `Regions.py` | Graph matches rules | `--region` strings |
| `archipelago.json` | AP ≥ **0.6.7**, world **0.0.1** | Future sink ≥ 0.6.7 |
| Boss block | Still commented | Do not invent boss flags |

## Contract

| Rule | |
|------|--|
| Names | `targets.json` `label` = `Locations.py` / `Items.py` byte-for-byte |
| IDs | AP numbers stay in the world package; we store offsets + labels |
| After a world pull | Bump the pin, `sync-world`, re-check names before more captures |

```powershell
python -m tools locations --region Crossroads --unmapped
```

## Start here (Crossroads)

| Location | Note |
|----------|------|
| `Crossroads Currency Chest Down Stairs` | |
| `Crossroads Currency Chest South Crater` | |
| `Crossroads Currency Chest in Subway Station` | |
| `Crossroads Life Chest Behind Gholen West` | |
| `Crossroads Life Chest Behind Gholen North` | |
| `Crossroads Life Chest NE Crater` | |
| `Crossroads Rare Chest Blocked by Ice` | Skip until ice tools |
| `Crossroads Secret Chest Destroy Fire Hydrants` | |
| `Crossroads Soldier Artifact in Subway Station` | |

Full list: `Locations.py` or `python -m tools locations`. Later gear names: `Crossblade`, `Shadowflight`, `Progressive Gauntlet`, `Soul Bridge`, `Mask of Shadows`, `Ruin`, `Armageddon Blade Shards`.
