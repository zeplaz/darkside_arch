# Keen saves

Same slot, two files. JSON is a **schema dump**. It is not a memory map.

| File | Role |
|------|------|
| `keen_savegame_0_0.sav` | Install and **Load** in-game |
| `keen_savegame_0_0.json` | Inspect / diff only |

Gitignored under `saves/`. Do not commit them.

## Use / do not use

| Need | Use the save? |
|------|----------------|
| Scan types (`Souls` float, `Health` int, flags `uint8`) | Yes |
| Inventory classnames (`sword/warsword`, …) | Later watch **ids** only — not AP names |
| AP location names / chest keymap | No |
| Module offsets | No — `capture` / `scan` |
| Search RAM for `ObjectID` 88 | No — IDs are per-region; 88 is a map tile **and** a destroyable |

Chests persist as unnamed `World + RegionID + LayerID + ObjectID` plus `Destroyed` / `Triggered` / `Open`. `Open` on this slot is linked doors. `MapTileData.Visited` is fog-of-war. `NumberOfChestsOpened` is a counter.

## This slot (`keen_savegame_0_0`)

| Field | Value |
|-------|--------|
| Spawn | `overworld` / `CI_02` @ `Start_04` |
| Souls | `172.0` (`float`) |
| Health / Wrath / Chaos | `1100` (`int`) / `500.0` / `250.0` (`float`) |
| Chests opened | 5 |
| Artifacts | 20 pawn + 6 general + 1 master |
| Gear | Late loadout (L6 warsword, gauntlets, scythe, Crossblade, …) |

`CI_01` ≈ first city (Crossroads-class). `CI_02` is the next cell. This bag vs 5 chests is **not** a fresh Crossroads start. For unused Crossroads checks, use a new game.

## Install `.sav`

Backup first. Typical Steam path (id varies):

```
%STEAM%\userdata\<id>\462780\remote\
```

Copy `keen_savegame_0_0.sav` next to the other `keen_savegame_*` files → Load that slot.

## Commands

| Command | Options | Meaning |
|---------|---------|---------|
| `python -m tools save-brief PATH.json` | `PATH` | Print spawn, types, inventory, flags |
| `python -m tools save-diff` | `--before` `--after` | Field delta between two **JSON** exports |
| `python -m tools save-diff` | `--include-tiles` | Also print minimap fog |

The game writes `.sav`. `save-diff` needs two JSON exports (Sacha’s exporter). After load: stand at a still-closed check → `capture`.
