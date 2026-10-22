"""EventBus sink: location_flag 0→1 (and stay-1) → LocationChecks / goal."""

from __future__ import annotations

from typing import Optional, Protocol

from ds_client.ap_catalog import ApCatalog
from ds_client.models import CATEGORY_LOCATION, Event


class LocationCheckSubmitter(Protocol):
    def submit_location_checks(self, location_ids: list[int]) -> None: ...
    def submit_goal(self) -> None: ...


def is_truthy(value_raw: str) -> bool:
    text = (value_raw or "").strip()
    if text in {"", "0", "0.0", "False", "false", "None"}:
        return False
    try:
        return float(text) != 0.0
    except ValueError:
        return True


def is_checked_transition(prev: str, value: str) -> bool:
    """True on 0→1 and on first sample already 1 (stay-1 after reconnect)."""
    if not is_truthy(value):
        return False
    if prev == "":
        return True
    return not is_truthy(prev)


class ApLocationSink:
    def __init__(
        self,
        runtime: Optional[LocationCheckSubmitter],
        catalog: ApCatalog,
    ) -> None:
        self._runtime = runtime
        self._catalog = catalog

    def emit(self, event: Event) -> None:
        if self._runtime is None:
            return
        if event.event_type == "SESSION":
            return
        if not is_checked_transition(event.prev_value, event.value_raw):
            return

        label = event.label or event.notes
        if event.event_type == "GOAL" or self._catalog.is_goal_label(label):
            self._runtime.submit_goal()
            return

        if event.event_type != "LOCATION_CHECK" and event.category != CATEGORY_LOCATION:
            return
        loc_id = self._catalog.location_id(label)
        if loc_id is None:
            print(f"[AP] LOCATION_CHECK label {label!r} is not in the world catalog")
            return
        self._runtime.submit_location_checks([loc_id])

    def flush(self) -> None:
        return
