# Keen saves

Same slot, two files. JSON is a schema dump, not a memory map. Gitignored under `saves/`.

| File | Use |
|------|-----|
| `*.sav` | Load in-game |
| `*.json` | `save-brief` / `save-diff` / `save-install` only |

Steam saves: `<Steam>\userdata\<id>\462780\remote\` (`save-install --install` finds the Steam folder from the registry).

## Mapping bag (`keen_savegame_0_0`) — late game

| | |
|--|--|
| Spawn | `overworld` / `CI_02` @ `Start_04` |
| Types | Souls `float`, Health `int` |
| Gear | L6 warsword, Armageddon already in inventory |
| Chests | 5 opened — **not** a fresh Crossroads start |

Use it to scan types. Do **not** use it as an AP skip-intro template. For unused Crossroads checks, start a new game.

Keen chests are `World + RegionID + LayerID + ObjectID`, not AP names. `ObjectID` 88 is per-region — do not scan RAM for it.

```powershell
python -m tools save-brief PATH.json
python -m tools save-diff BEFORE.json AFTER.json
```

## AP skip-intro — not captured yet

Need a **new** slot: new game → Crossroads after Vulgrim (`overworld` / `CI_01`). Export JSON. Then:

```powershell
python -m tools save-install --json PATH.json --sav PATH.sav --userid YOUR_STEAM_ID --install
```

Rewrites `GameInfo.UserId` in the JSON and every matching `u32le` dword in the `.sav`. Every file it overwrites gets a `.bak` copy first. Refuses (unless `--force`, mapping only) a save that is not `overworld` / `CI_01`, carries Armageddon Blade or shards, or has more than 8 chests opened. `--install` needs `--sav`.
