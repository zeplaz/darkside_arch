# DLL runtime

Rust inject DLL + Python AP host. Location checks join on `save_object`; items still use RPM writes.

## Run

```powershell
# 1) AP host (from repo root)
pip install -r requirements.txt
python -m runtime.dll --connect HOST:PORT --slot NAME

# 2) Build DLL
cd runtime/dll/native
cargo build --release
cd ../../..

# 3) Start the game, then inject
python -m tools dll-inject
# or: python tools/dll_inject.py --dll runtime/dll/native/target/release/darkside_arch.dll
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
