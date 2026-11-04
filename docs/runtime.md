# Runtime paths

Two player runtimes. Ship **one**. Mapping tools stay shared.

| | **mem** | **dll** |
|--|--|--|
| Entry | `python -m runtime.mem` | `python -m runtime.dll` + inject `darkside_arch.dll` |
| Location checks | RAM `offsets` | Identity scan → `save_object` |
| Items | `WriteProcessMemory` | Same RPM from the Python host |
| How to run | [runtime/mem/README.md](../runtime/mem/README.md) | **[runtime/dll/README.md](../runtime/dll/README.md)** ← DLL instructions |

## Shared contract

[`targets.json`](../targets.json):

- `save_object` — Keen identity (SAVE DIFF); required for DLL joins and mem heap dumps
- `offsets` — required for mem location watches; ignored for dll **locations**; still used for item/stat/goal under both
- AP names — join to world catalogs

## DLL flow

```
game + darkside_arch.dll --TCP--> runtime.dll host --WS--> Archipelago (LIVE only)
         open(identity)              LocationChecks
                                     RPM item writes --> game
```

Dashboard **DLL LAB** can drive TEST (`--no-ap`) or LIVE (`ap_config.json`). Not sideload.
