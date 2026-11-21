"""Map DLL open events → Archipelago LocationChecks."""

from __future__ import annotations

import json
from typing import Any, Optional, Set

from ap.catalog import ApCatalog
from ap.client import ApRuntime

from runtime.dll.host.targets_index import IdentityKey, LocationIdentity, load_location_identities


class OpenHandler:
    def __init__(
        self,
        *,
        catalog: ApCatalog,
        runtime: Optional[ApRuntime],
        identities: Optional[dict[IdentityKey, LocationIdentity]] = None,
        overlay=None,
    ) -> None:
        self.catalog = catalog
        self.runtime = runtime
        self.identities = identities if identities is not None else load_location_identities()
        self.overlay = overlay
        self._reported: Set[IdentityKey] = set()
        self._connected = False
        self._watches = 0
        self._last_check = ""
        self._refresh_overlay()

    def _refresh_overlay(self) -> None:
        if self.overlay is None:
            return
        if not self._connected:
            self.overlay.set_text("DSH — waiting for injected DLL")
            return
        line = "DSH INJECTED ✓"
        if self._watches:
            line += f" · watching {self._watches} identities"
        if self._last_check:
            line += f" · CHECK {self._last_check}"
        self.overlay.set_text(line)

    def reload(self) -> int:
        self.identities = load_location_identities()
        return len(self.identities)

    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line or line.startswith("hello"):
            print(f"[dll/ipc] {line}")
            return
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print(f"[dll/ipc] non-json: {line}")
            return
        op = msg.get("op")
        if op == "hello":
            print(f"[dll/ipc] dll hello {msg}")
            self._connected = True
            self._refresh_overlay()
            return
        if op == "log":
            text = str(msg.get("msg", msg))
            print(f"[dll] {text}")
            if text.startswith("watches="):
                try:
                    self._watches = int(text[len("watches="):].strip())
                    self._refresh_overlay()
                except ValueError:
                    pass
            return
        if op == "open":
            self._on_open(msg)
            return
        if op == "poke_result":
            ok = bool(msg.get("ok"))
            label = str(msg.get("label") or "")
            addr = msg.get("address")
            if ok:
                print(f"[dll/poke] OK {label} @ {addr} ({msg.get('n')} bytes) — the DLL wrote the game")
            else:
                print(f"[dll/poke] FAILED {label}: {msg.get('error')}")
            return
        print(f"[dll/ipc] unknown op: {msg}")

    def _on_open(self, msg: dict[str, Any]) -> None:
        try:
            region_id = int(msg["region_id"])
            layer_id = int(msg["layer_id"])
            object_id = int(msg["object_id"])
        except (KeyError, TypeError, ValueError) as exc:
            print(f"[dll] bad open payload {msg!r}: {exc}")
            return
        value_key = str(msg.get("value_key") or "Triggered")
        key: IdentityKey = (region_id, layer_id, object_id, value_key)
        ident = self.identities.get(key)
        if ident is None:
            # try any value_key for this triple
            for (r, l, o, _k), candidate in self.identities.items():
                if (r, l, o) == (region_id, layer_id, object_id):
                    ident = candidate
                    key = (r, l, o, candidate.value_key)
                    break
        if ident is None:
            print(
                f"[dll] open unmatched r={region_id} L={layer_id} obj={object_id} {value_key}"
            )
            return
        if key in self._reported:
            return
        self._reported.add(key)

        loc_id = self.catalog.location_id(ident.label)
        if loc_id is None:
            print(f"[dll] {ident.label!r} not in world catalog")
            return
        print(f"[dll] CHECK {ident.label} (AP {loc_id}) via {key}")
        self._last_check = ident.label
        self._refresh_overlay()
        if self.runtime is not None:
            self.runtime.submit_location_checks([loc_id])
