# game_data — Keen object dumps

These JSON files are the **source of placed-object identities** (which AP check
maps to which Keen WorldObject). Each file is a `RegionLayer` dump straight out
of the Keen `.json` schema. The dashboard and `tools/identify` read every
`RegionLayer` JSON here; the **filename is the provenance** recorded on a
`save_object` (`source: "Chests.json"` / `"Artifacts.json"` / …).

| File | What it holds |
|------|---------------|
| `Chests.json` | A region dump containing chest objects (and a few waypoints / statics). |
| `Artifacts.json` | A region dump containing artifact `ItemActor`s. |
| `Sword.json` | A sword-altar region dump — quest objects carry a `SaveDataModule` flag (e.g. `SwordPiece_05`), not a `Values` flag. |
| `*.s` | Chest/rarechest Keen scripts — only read to confirm the persist key (`Triggered`). |
| `Scripts.json`, `scripts (1).json` | Region dumps of vis-script/tutorial objects (also scanned; mostly quest flags). |
| `*.dds` | Minimap tiles. Ignored. |

## Expected `RegionLayer` shape

```jsonc
{
  "classname": "RegionLayer",
  "properties": {
    "Root": {
      "classname": "WorldGroup",
      "properties": {
        "Objects": [
          {
            "classname": "ItemActor",          // or StaticObject, base/waypoint, ...
            "properties": {
              "ItemType": "artifact_pawn/artifact_pawn",   // artifacts only
              "Position": [1.0, 2.0, 3.0],
              "ObjectID": 107,
              "RegionID": 33,
              "Name": "Artifact_Pawn_01"
              // "LayerID" may be absent — treated as 0
            }
          }
        ]
      }
    }
  }
}
```

Only `Objects` are read. For each object, `tools.game_data` extracts:
`name`, `classname`, `item_type`, `class_kind`, `flag_names`, `world`,
`region_id`, `layer_id` (defaults to `0`), `object_id`, and `source` (the filename).

## How kinds are detected

| `class_kind` | Rule |
|--------------|------|
| `artifact` | `ItemType` starts with `artifact_` (e.g. `artifact_pawn`, `artifact_master`, `artifact_general`) |
| `chest` | classname contains `chest` / `casket` |
| `door` | classname contains `door` |
| `quest` | the object holds a `SaveDataModule` `FlagName` (e.g. `SwordPiece_05`) and is none of the above |

Artifacts are `ItemActor` objects, **not** `chest_*` objects — and unlike
chests they write **no** `Triggered`/`Destroyed`/`Open` flag to the save, which
is why they cannot be identified by SAVE DIFF. Their identity comes from here
instead (`GAME DATA…` in the dashboard, or `python -m tools identify`).

Quest objects (sword pieces, tutorials, one-shot scripts) persist by **flag
name** (`FlagInfo.FlagName` under a `SaveDataModule`), e.g. `SwordPiece_05` —
a third mechanism alongside chest `Values.Triggered` and artifact inventory.
Those flag names are surfaced as `flag_names` on the object.

## Adding a region

Drop a new `RegionLayer` JSON in here (e.g. `Crossroads.json`). It is picked up
automatically on the next dashboard / `tools` run — no code change. Keep the
object `Name` values: those are what `--object NAME` and the GAME DATA picker
match on.

Note: `Artifacts.json` currently holds a **test region** (`RegionID 33`,
package `br_mechtest`) with placeholder artifact names. To map a real location,
dump its actual region and add that file.
