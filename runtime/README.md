# Runtimes

Two deployable player clients. Ship **one**.

| Path | Entry | Role |
|------|-------|------|
| **mem** | `python -m runtime.mem` | Out-of-process RAM watches + item writes |
| **dll** | `python -m runtime.dll` + inject DLL | In-process identity scan → LocationChecks; host still RPM-writes items |

Shared: [`ap/`](../ap/), [`targets.json`](../targets.json), [`tools/`](../tools/).

`python -m ds_client` still redirects to **mem**.

Details: [docs/runtime.md](../docs/runtime.md) · [dll/README.md](dll/README.md) · [mem/README.md](mem/README.md)
