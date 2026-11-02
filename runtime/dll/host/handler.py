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
    ) -> None:
        self.catalog = catalog
        self.runtime = runtime
        self.identities = identities if identities is not None else load_location_identities()
        self._reported: Set[IdentityKey] = set()

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
            return
        if op == "log":
            print(f"[dll] {msg.get('msg', msg)}")
            return
        if op == "open":
            self._on_open(msg)
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
        if self.runtime is not None:
            self.runtime.submit_location_checks([loc_id])
