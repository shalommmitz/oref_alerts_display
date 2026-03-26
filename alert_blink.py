"""Blink new alert markers for a short operator-attention window."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from israel_map import IsraelMap


BLINK_DURATION_SECONDS = 10.0


@dataclass
class _BlinkState:
    started_at: float
    visible: bool


class AlertBlinkManager:
    def __init__(self) -> None:
        self._markers: dict[int, _BlinkState] = {}

    def remember_markers(self, marker_ids: list[int], *, started_at: float | None = None) -> None:
        # 1. Start each new marker in the visible state so the first blink phase
        #    is "on" instead of hiding the alert immediately on arrival.
        # 2. Use one monotonic timestamp for the whole alert batch so all
        #    markers from the same incoming alert blink in sync.
        if not marker_ids:
            return
        anchor = monotonic() if started_at is None else started_at
        for item_id in marker_ids:
            self._markers[item_id] = _BlinkState(started_at=anchor, visible=True)

    def update(self, map_view: IsraelMap, *, now: float | None = None) -> int:
        # 1. Toggle marker visibility from the main loop so blinking stays on
        #    the Tk thread and does not need a separate worker.
        # 2. After 10 seconds, force the marker visible and stop tracking it.
        anchor = monotonic() if now is None else now
        changed_count = 0
        finished_ids: list[int] = []
        for item_id, state in list(self._markers.items()):
            elapsed = anchor - state.started_at
            if elapsed >= BLINK_DURATION_SECONDS:
                if not map_view.set_marker_visible(item_id, True):
                    finished_ids.append(item_id)
                    continue
                if not state.visible:
                    changed_count += 1
                finished_ids.append(item_id)
                continue

            visible = int(elapsed) % 2 == 0
            if visible == state.visible:
                continue
            if not map_view.set_marker_visible(item_id, visible):
                finished_ids.append(item_id)
                continue
            state.visible = visible
            changed_count += 1

        for item_id in finished_ids:
            self._markers.pop(item_id, None)
        return changed_count

    def clear(self, map_view: IsraelMap) -> int:
        # 1. Restore all tracked markers to visible when blinking is disabled so
        #    no alert dot stays hidden after the operator opts out.
        # 2. Drop the tracking state in one place so future alerts can restart
        #    blinking cleanly if the setting is re-enabled later.
        restored_count = 0
        for item_id in list(self._markers):
            if map_view.set_marker_visible(item_id, True):
                restored_count += 1
        self._markers.clear()
        return restored_count
