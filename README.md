# darkside_arch

Passive process watcher for **Darksiders Warmastered Edition** (`darksiders1.exe`).

Reads game memory via Windows APIs (`OpenProcess` / `ReadProcessMemory`). No injection. No hooks.

Events go to stdout and `darksiders_debug.db` (SQLite, WAL). Watch definitions live in `targets.json`.

## Layout

```
ds_client/
  win32.py      # OpenProcess / RPM / module base
  models.py     # WatchTarget, Event, targets.json loader
  sinks.py      # Terminal + SQLite (+ future AP sink)
  watcher.py    # attach / observe / lifecycle
targets.json    # memory watch definitions (edit without touching engine)
```

## Requirements

- Windows
- Python 3.11+
- `pip install -r requirements.txt`

## Run

```bash
python -m ds_client
```

Polls for `darksiders1.exe`, resolves the module base (ASLR-safe), then observes configured targets on change only. If the game exits, the session ends and the watcher waits to reattach.

## targets.json

```json
{
  "observe_interval_ms": 250,
  "module": "darksiders1.exe",
  "targets": [
    {
      "id": "chest_scalding_01",
      "event_type": "LOCATION_CHECK",
      "offsets": ["0xA8E10"],
      "type": "uint8",
      "bitmask": "0x04",
      "notes": "Chest_ScaldingGallow_01 Opened"
    },
    {
      "id": "example_pointer_chain",
      "event_type": "MEMORY_STATE",
      "offsets": ["0x123456", "0x10", "0x8"],
      "type": "int32",
      "notes": "base+A -> +B -> +C"
    }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `offsets` | Module-relative: one entry = `base+offset`. Multiple = pointer chain ending at the final address. |
| `type` | `bool`, `uint8/16/32/64`, `int8/16/32/64`, `float`, `double` |
| `bitmask` | Optional; compare only masked bits (chest/boss flags). |
| `enabled` | Optional; `false` skips the target without deleting it. |

## Scope

Client-side observer. The Archipelago **world** is separate and not tracked here. Future networking belongs in a sink (e.g. `ap_client.py`), not in the memory loop.
