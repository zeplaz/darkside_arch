# Runtime paths

`darkside_arch` ships two player runtimes. Mapping tools stay shared. Ship **one**.

| | **mem** | **dll** |
|--|--|--|
| Entry | `python -m runtime.mem` | `python -m runtime.dll` + inject `darkside_arch.dll` |
| Location checks | RAM `offsets` on `location_flag` rows | In-process identity scan → `save_object` join |
| Items | `WriteProcessMemory` | Same RPM from the Python host |
| Native | none | Rust `runtime/dll/native` |
| Needs | Per-chest RAM DUMP | `save_object` on the row (SAVE DIFF) |

## Shared contract

[`targets.json`](../targets.json):

- `save_object` — Keen identity; required for DLL joins and mem heap dumps
- `offsets` — required for mem location watches; ignored for dll **locations**; still used for item/stat/goal under both
- AP names — same join to world catalogs

## Layout

```
ap/                 shared AP protocol / state / catalog / client
runtime/mem/        RAM watcher path
runtime/dll/host/   Python host + TCP IPC + item apply
runtime/dll/native/ Rust cdylib (darkside_arch.dll)
tools/              mapping dashboard (feeds targets.json)
ds_client/          shim → runtime.mem
```

## DLL flow

```
game + darkside_arch.dll --TCP--> runtime.dll host --WS--> Archipelago
         open(identity)              LocationChecks
                                     RPM item writes --> game
```

Test without inject:  
`python -m runtime.dll --no-ap --simulate-open "{\"region_id\":2,\"layer_id\":6,\"object_id\":342}"`
