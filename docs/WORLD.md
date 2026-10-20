# World fork sync (Sacha’s Archipelago-Darksiders)

This client does **not** vendor the Archipelago world. Location/item IDs and logic live here:

- Fork: https://github.com/Sachaqc/Archipelago-Darksiders
- vs AP core: https://github.com/ArchipelagoMW/Archipelago/compare/main...Sachaqc:Archipelago-Darksiders:main

Local clone path (gitignored): `world/Archipelago-Darksiders/`

## Documented pin

Update this table whenever you `git pull` the world clone.

| Field | Value |
|-------|--------|
| Branch | `main` |
| Commit | `71ddf44` — *First test without Errors* (2026-10-19) |
| vs AP `main` | ahead **3** / behind **2** (diverged) |

Ahead (Darksiders work): `a73deac` → `4aeefc6` → `71ddf44`.  
Behind 2 = Sacha has not merged the latest Archipelago core commits — world-fork maintenance, not a `darkside_arch` fix.

## Sync local clone

Windows (PowerShell):

```powershell
if (-not (Test-Path world\Archipelago-Darksiders)) {
  New-Item -ItemType Directory -Path world -Force | Out-Null
  git clone https://github.com/Sachaqc/Archipelago-Darksiders.git world\Archipelago-Darksiders
}
git -C world\Archipelago-Darksiders fetch origin
git -C world\Archipelago-Darksiders pull --ff-only origin main
git -C world\Archipelago-Darksiders log -1 --oneline
```

Then bump the pin table above.

## What `71ddf44` implies for this client

| Area | Change | Client impact |
|------|--------|----------------|
| `Locations.py` | Unique location ID ranges | `label` / `tools tag` must match names exactly |
| `Items.py` | `Deaths Blessing` id fix; `Soul Bridge`; more Progressive Gauntlets | Gear watches use these **names** |
| `Rules.py` | Goal: `Armageddon Blade Shards` ×7; new entrances | Map late-game flags later |
| `Regions.py` | Graph matches new rules | `--region` strings |
| `archipelago.json` | `minimum_ap_version` **0.6.7**, `world_version` **0.0.1** | Future AP sink ≥ 0.6.7 |
| Boss locations | Still commented out | Do not invent boss flags yet |

## Early mapping names (from current `Locations.py`)

**Crossroads**

- `Crossroads Currency Chest Down Stairs`
- `Crossroads Currency Chest South Crater`
- `Crossroads Currency Chest in Subway Station`
- `Crossroads Life Chest Behind Gholen West`
- `Crossroads Life Chest Behind Gholen North`
- `Crossroads Life Chest NE Crater`
- `Crossroads Rare Chest Blocked by Ice` (skip until ice tools)
- `Crossroads Secret Chest Destroy Fire Hydrants`
- `Crossroads Soldier Artifact in Subway Station`

**Choking Grounds** (next)

- `Choking Grounds Currency Chest North of Cemetery`
- `Choking Grounds Soldier Artifact North of Vulgrim`
- (full list in `Locations.py`)

**Progression items later:** `Crossblade`, `Shadowflight`, `Progressive Gauntlet`, `Soul Bridge`, `Mask of Shadows`, `Ruin`, `Armageddon Blade Shards`

## Contract with `darkside_arch`

1. `targets.json` `label` and `tools tag` strings match the world **byte-for-byte**.
2. AP numeric IDs stay in the world package; this client stores offsets + labels; a future sink maps label → id.
3. After each world pull, refresh this pin and re-check names before more scans.
