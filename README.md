# darkside_arch

Passive process watcher for **Darksiders Warmastered Edition** (`darksiders1.exe`).

Reads game memory via Windows APIs (`OpenProcess` / `ReadProcessMemory`). No injection. No hooks.

Events are printed to the terminal and stored in `darksiders_debug.db` (SQLite).

## Requirements

- Windows
- Python 3.11+
- `pip install -r requirements.txt`

## Run

```bash
python watcher.py
```

Attach Darksiders Warmastered Edition (Steam/GOG). The watcher polls for `darksiders1.exe` every 1.5s, then observes configured memory targets on change only.

## Scope

This repository is the **client-side** observer/client work. The Archipelago **world** lives separately and is not tracked here.
