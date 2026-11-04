# DLL runtime — how to run

**This is the DLL how-to.** Inject after the game starts. Do **not** replace Steam/`version.dll` in the game folder (that is sideload; we do not use it).

Needs: rows with `save_object` in [`targets.json`](../../targets.json) (hotel chests 1–2 already have them). No per-chest RAM offset for location checks.

IPC: `tcp://127.0.0.1:27111`

---

## Fastest: dashboard DLL LAB

```powershell
pip install -r requirements-dev.txt
python -m tools dashboard
```

Open **DLL LAB**. Pick mode, then follow the checklist on the page.

| Mode | Host | What to do |
|------|------|------------|
| **TEST** | `--no-ap` | START HOST → BUILD → **SIMULATE** → launch game → **INJECT** → optional open chest |
| **LIVE** | `ap_config.json` | set slot → START HOST → BUILD → launch game → **INJECT** → open chest in-game |

Stop the host before switching TEST ↔ LIVE. Mapping tabs still own SAVE DIFF / RAM DUMP; this tab only drives host + inject.

---

## CLI

```powershell
# TEST (no Archipelago)
python -m runtime.dll --no-ap

# other terminal — build once
cd runtime/dll/native
cargo build --release
cd ../../..

# launch Darksiders normally, then:
python -m tools dll-inject

# LIVE (AP)
python -m runtime.dll --connect HOST:PORT --slot NAME
# then same: launch game → dll-inject
```

Dry identity check without inject:

```powershell
python -m runtime.dll --no-ap --simulate-open "{\"region_id\":2,\"layer_id\":6,\"object_id\":342}"
```

→ expect `CHECK Seraphim Hotel Life Chest 1`.

| Flag | |
|------|--|
| `--no-ap` | Host only (TEST) |
| `--no-apply` | Skip RPM item writes |
| `--simulate-open '{...}'` | One fake open, then exit |

---

## What success looks like

1. Host log: TCP up, then after inject `hello` / `watches=N`
2. TEST SIMULATE or in-game open: `CHECK …` / `op=open`
3. LIVE: same, plus LocationChecks on the AP socket

## What the DLL does

1. Connects to the host; receives every `save_object` watch
2. Scans this process for packed `ObjectID|RegionID|LayerID`
3. Nearby byte `0→1` → `{"op":"open",...}`
4. Host joins identity → catalog → LocationChecks (LIVE) or log (TEST)

## Layout

```
runtime/dll/host/     Python host (AP + TCP + item apply)
runtime/dll/native/   darkside_arch.dll (Rust)
tools/dll_inject.py   LoadLibraryW injector
tools/dll_lab.py      Dashboard DLL LAB backend
```

Architecture (mem vs dll): [docs/runtime.md](../../docs/runtime.md). Dashboard overview: [docs/DASHBOARD.md](../../docs/DASHBOARD.md).
