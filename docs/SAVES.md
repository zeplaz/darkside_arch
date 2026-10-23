# Keen saves

Same slot, two files. JSON is a schema dump, not a memory map. Gitignored under `saves/`. Keep raw and patched apart:

| Folder | |
|--------|--|
| `saves/sacha_raw/` | Untouched files from Sacha. Never patch these in place. |
| `saves/edited/` | Output of `save-patch`. This is what `--install` should copy. |
| `saves/_scratch/` | Old probes. Ignore. |

| File | Use |
|------|-----|
| `*.sav` | Load in-game |
| `*.json` | `save-brief` / `save-diff` / `save-install` only |

Steam saves: `<Steam>\userdata\<id>\462780\remote\autocloud\save\` (`svd_fmt_0_0.sav` and/or `keen_savegame_0_0.sav`). Change UserId with `save-patch` (whatisaphone/war). Do not poke dwords in the `.sav`.

## Mapping bag (`keen_savegame_0_0`) — late game

| | |
|--|--|
| Spawn | `overworld` / `CI_02` @ `Start_04` |
| Types | Souls `float`, Health `int` |
| Gear | L6 warsword, Armageddon already in inventory |
| Chests | 5 opened — **not** a fresh Crossroads start |

Use it to scan types. Do **not** use it as an AP skip-intro template. For unused Crossroads checks, start a new game.

Keen world objects live in `PlayerSaveData.WorldData[].Regions[].Layers[].WorldObjects[]`. A record is written only after the object has state. The `Values` keys are:

| Key | |
|-----|--|
| `Destroyed` | Breakables (the X/Y props already in an early hotel save) |
| `Open` | Doors |
| `Triggered` | Chests / one-shots |

`Seraphim Hotel Life Chest 1` is `overworld` / RegionID `2` / LayerID `6` / ObjectID `342` / `Triggered` (`SB_G_Chest_HealthChest_01`, `/overworld/CI_StartBld`). Slot 1 = closed, slot 2 = open (`NumberOfChestsOpened` 0→1, Health 81→200).

`Seraphim Hotel Life Chest 2` is `overworld` / RegionID `260` / LayerID `1` / ObjectID `16` / `Triggered` (`CI_SB_Exit_Chest_HealthChest`, `/overworld/CI_SB_Exit`). Sacha matched the name to the minimap; not yet save-diff confirmed. Same hotel, different Keen region — do not look for obj 343 on layer 6.

ObjectID is not global — never search RAM for `342` or `16` alone; the RAM capture anchors on ObjectID + RegionID + LayerID together.

`war sav decode` only reads the autosave slot (`-1`). Manual slots 0–9 sit in the same `.sav`; `save-diff --slots` copies a slot onto autosave before decode.

A closed→open slot pair identifies the chest. Dashboard **DIFF SAVES** / `scan --sav` writes `save_object` onto that AP name. The live flag then comes from the **RAM DUMP** tab, which scans the heap around that identity ([tools](../tools/README.md#dashboard)); `.data` does not hold chest flags.

Dashboard is a workspace. Center tabs: **SAVE DIFF** (mapping), **RAM DUMP** (live flag after identity, heap capture; F8 still works while hidden), **SAVES** (inspect, encode UserId to `saves/edited/`, then **INSTALL TO STEAM**). INSTALL refuses while the game is attached, refuses a live Steam source, and requires typing `INSTALL`. Encode dest must stay under `saves/edited/`. war only rewrites autosave. LIVE VALUES stay on the right.

```powershell
python -m tools dashboard
python -m tools save-brief --slot 1 FILE.sav
python -m tools save-brief --all FILE.sav
python -m tools save-brief --slot 1 --export FILE.sav
python -m tools save-diff --slots 1 2 --location "Seraphim Hotel Life Chest 1" FILE.sav
python -m tools scan --sav FILE.sav --slots 1 2 --item "Seraphim Hotel Life Chest 1"
python -m tools save-diff BEFORE.json AFTER.json
```

## AP skip-intro — not captured yet

Need a **new** slot: new game → Crossroads after Vulgrim (`overworld` / `CI_01`). Export JSON. Then:

```powershell
git clone https://github.com/whatisaphone/war.git tools/vendor/war
cargo install --path tools/vendor/war/crates/war-cli
python -m tools save-patch --sav saves\sacha_raw\keen_savegame_0_0.sav --userid YOUR_STEAM_ID --out saves\edited\keen_savegame_0_0.sav --install
```

`save-patch` runs `war sav decode`, sets `SaveGameInfo.UserId`, then `war sav encode`. war only rewrites the **autosave** slot. `--install` copies into `remote\` and `remote\autocloud\save\` as both `svd_fmt_0_0.sav` and `keen_savegame_0_0.sav`. Quit the game and launch from Steam.

`save-install` is JSON-only / late-game gate. It does not rewrite a playable `.sav`.
