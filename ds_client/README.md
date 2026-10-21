# ds_client

Runtime watcher. Attaches to `darksiders1.exe`, reads `targets.json`, logs changes. Not the scanner — that is [tools](../tools/README.md).

| Step | What happens |
|------|----------------|
| 1 | Wait for `darksiders1.exe` |
| 2 | Resolve module base (ASLR) |
| 3 | Poll **enabled** `targets.json` rows (hot-reload each tick) |
| 4 | On change → stdout + `darksiders_debug.db` |
| 5 | Upsert into SQLite `memory_map` (dashboard reads this) |

No CLI flags. `Ctrl+C` detaches. Game exit → wait and reattach.

```powershell
pip install -r requirements.txt
python -m ds_client
```

Runtime needs `psutil` only. Mapping needs `requirements-dev.txt`.

```
[INIT] Loaded N watch target(s) from targets.json
[WAITING] Searching for darksiders1.exe...
[FOUND] Attached to PID …
[EVENT] MEMORY_STATE | Address: 0x… | Val: 50.0 -> 75.0 | Soul_Count
```

## `targets.json`

| Field | Meaning |
|-------|---------|
| `offsets` | Module-relative. One = `base+offset`; many = pointer chain |
| `type` | `bool`, `uint8/16/32/64`, `int8/16/32/64`, `float`, `double` |
| `bitmask` | Optional; not valid on float/double |
| `label` | Docs + AP name. Location labels must match [WORLD.md](../docs/WORLD.md) |
| `region` | Area string |
| `category` | `location_flag` \| `inventory` \| `stat` \| `misc` |
| `enabled` | `false` skips the row |

Offsets come from `tools capture` / `tools scan --auto-save` only. Never store absolute VAs.

| File | Role |
|------|------|
| `win32.py` | OpenProcess / RPM / module base |
| `models.py` | WatchTarget, Event, loader |
| `sinks.py` | Terminal + SQLite |
| `watcher.py` | Attach / poll / hot-reload |
| `__main__.py` | `python -m ds_client` |

Future Archipelago WebSocket sink belongs **here**, not in `tools/`.
