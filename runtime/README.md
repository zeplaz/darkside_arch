# Runtimes

Two deployable player clients. Ship **one**.

| Path | Entry | How-to |
|------|-------|--------|
| **mem** | `python -m runtime.mem` | [mem/README.md](mem/README.md) |
| **dll** | `python -m runtime.dll` + inject | **[dll/README.md](dll/README.md)** |

Shared: [`ap/`](../ap/), [`targets.json`](../targets.json), [`tools/`](../tools/).  
`python -m ds_client` → mem. Architecture: [docs/runtime.md](../docs/runtime.md).
