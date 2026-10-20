# ds_client — runtime client (watcher)

Final client path: attach to `darksiders1.exe`, read `targets.json`, emit change events.

Not the address scanner — that is [`../tools/`](../tools/README.md).

## Behavior

1. Wait for `darksiders1.exe`
2. Resolve module base (ASLR-safe)
3. Poll enabled watches from repo-root `targets.json`
4. On change → stdout + `darksiders_debug.db` (auto-created, gitignored)
5. Upsert verified deltas into SQLite `memory_map`

Future Archipelago WebSocket sink belongs **here**, not under `tools/`.

## Setup

- Windows 10/11, Python 3.11+, Steam x64 Warmastered
- Enabled rows in `targets.json`

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m ds_client
```

No `requirements-dev.txt` / PyMemoryEditor needed for runtime.

## Run notes

- No CLI flags (`python -m tools` for scan/tag/export)
- Ctrl+C detaches; game exit → wait and reattach

```
[INIT] Loaded N watch target(s) from targets.json
[WAITING] Searching for darksiders1.exe...
[FOUND] Attached to PID …
[EVENT] MEMORY_STATE | Address: 0x… | Val: 50 -> 75 | Soul_Count
```

## `targets.json` schema

| Field | Meaning |
|-------|---------|
| `offsets` | Module-relative; one = `base+offset`; many = pointer chain |
| `type` | `bool`, `uint8/16/32/64`, `int8/16/32/64`, `float`, `double` |
| `bitmask` | Optional masked bits |
| `label` / `region` / `category` | Docs + tagging (`location_flag` \| `inventory` \| `stat` \| `misc`) |
| `enabled` | `false` skips without deleting |

Offsets from `python -m tools scan … --auto-save` only. Never store absolute VAs. Location `label`s must match [docs/WORLD.md](../docs/WORLD.md).

## Package files

| File | Role |
|------|------|
| `win32.py` | OpenProcess / RPM / module base |
| `models.py` | WatchTarget, Event, loader |
| `sinks.py` | Terminal + SQLite |
| `watcher.py` | Lifecycle |
| `__main__.py` | `python -m ds_client` |
