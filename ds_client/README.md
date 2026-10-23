# ds_client

Player runtime: RAM watcher + Archipelago 0.6.7 client. Mapping lives in [tools](../tools/README.md). A `save_object` on a row is Keen identity only — this process ignores it until `offsets` is a real watch.

Two independent loops: the AP socket and the `darksiders1.exe` attach. Closing the game does not drop AP; an AP reconnect does not detach RAM. `Ctrl+C` stops both.

```powershell
pip install -r requirements.txt
python -m ds_client --connect archipelago.gg:38281 --slot War
```

| Flag | |
|------|--|
| `--connect HOST[:PORT]` | Also `ws://…` / `wss://…`. Saved to `ap_config.json`; a missing port keeps the saved one |
| `--slot` / `--password` | Saved to `ap_config.json` (plain text, gitignored) |
| `--send-goal` | Send `CLIENT_GOAL` on the next Connect (debug; the Abaddon flag is not mapped yet) |
| `--no-ap` | RAM watcher only |

## `ap_config.json`

Created on first run (from `ap_config.example.json` if present) with a generated `uuid`. Edit it while the client runs — a changed host / port / slot / password reconnects automatically, which covers the room port changing from one day to the next.

| Key | Default | |
|-----|---------|--|
| `host` | `localhost` | `host:port` or `wss://host:port` also accepted |
| `port` | `38281` | |
| `use_wss` | `false` | |
| `slot` / `password` | | Room login; nothing connects while `slot` is empty |
| `game` / `tags` | `Darksiders` | Keep as is |
| `request_goal` | `false` | Set by `--send-goal`, cleared after sending |

## How it behaves

- **Locations:** a `location_flag` row going 0→1 (or already 1 when first read) sends `LocationChecks`. Every check is kept in `ap_state.db` and the full list is resent on each Connect, so nothing is lost to a dropped socket.
- **Items:** `ReceivedItems` are stored by absolute index in `ap_state.db`. RAM is **set to the received total** (counts, progressive levels capped 4 / 4 / 4) or to 1 (flags), never incremented. A replay from index 0, a reconnect, or a fresh PC therefore cannot duplicate items. An index gap sends `Sync`.
- **Unmapped items** stay pending and apply as soon as their offset is saved — they never block other items.
- **7 Armageddon Blade Shards** grant the Armageddon Blade once.
- **Goal:** the GOAL row going 0→1 (or `--send-goal`) sends `CLIENT_GOAL`, remembered and resent on reconnect.

## Checklist

Status against the project requirement list. "Needs offsets" = code is done, but the RAM address is not mapped yet, so it does nothing in game.

| Requirement | Status |
|-------------|--------|
| Secure and plain websocket (`wss://` / `ws://`) | Done |
| Auto reconnect | Done — backoff 1 s → 60 s, reset after a successful Connect |
| Change the port of saved connection info | Done — `--connect host:port` or edit `ap_config.json` live |
| Goal completion (`StatusUpdate` CLIENT_GOAL) | Done, needs the Abaddon GOAL offset (`--send-goal` meanwhile) |
| Send location checked | Done, needs offsets (0 / 132) |
| Item reception / items on demand | Done, needs inventory offsets |
| Extra copies of any item | Done by design (set-to-total, flags are no-ops). **Open:** Beholder Key and Heart of the Chosen share one inventory slot — needs in-game testing |
| Admin / server items (no player or location) | Done — items are keyed by item id only |
| Item index / resync without duplicates | Done (`ap_state.db` + set-to-total) |
| Items sent while offline | Done — replayed on Connect, applied on attach |
| 7 shards → Armageddon Blade | Done, needs the blade offset |
| Progressive weapons | Done (levels 4 / 4 / 4), needs offsets |
| Save file handling (skip tutorial) | Partial — `tools save-install` exists; the Crossroads template save is not captured ([SAVES.md](../docs/SAVES.md)) |
| Skip cutscenes | Not started |
| Entrance randomization | Not started (world side) |
