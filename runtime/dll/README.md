# DLL runtime

Rust inject DLL + Python AP host. Location checks join on `save_object`; items still use RPM writes.

## Run

**Easiest POC (no AP):** dashboard → **DLL LAB** tab → START HOST → BUILD → SIMULATE → launch game → INJECT → open hotel chest 1. See [docs/DASHBOARD.md](../../docs/DASHBOARD.md).

```powershell
# CLI equivalent (no AP)
python -m runtime.dll --no-ap
# other terminal: cargo build --release in runtime/dll/native
# launch game, then:
python -m tools dll-inject

# With AP later
python -m runtime.dll --connect HOST:PORT --slot NAME
```

IPC: `tcp://127.0.0.1:27111` (line-delimited JSON).

### What the DLL does

1. Connects to the host and receives every `targets.json` row that has a Keen `save_object`.
2. Scans this process for packed `ObjectID|RegionID|LayerID` (Chests.json order).
3. When a nearby byte flips `0→1`, sends `{"op":"open",...}`.
4. Host maps that identity → AP `LocationChecks`.

### Host extras

| Flag | |
|------|--|
| `--simulate-open '{"region_id":2,"layer_id":6,"object_id":342}'` | Test LocationChecks without the game |
| `--no-apply` | Skip RPM item writes |
| `--no-ap` | IPC / simulate only |

Hotel chests 1–2 already have `save_object` and work for DLL checks without RAM offsets.

## Layout

```
runtime/dll/host/     Python AP + TCP server + RPM apply
runtime/dll/native/   darkside_arch.dll (Rust)
tools/dll_inject.py   LoadLibraryW injector
```
