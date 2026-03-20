"""Time-based cleanup for alert markers that should disappear automatically."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from alert_model import AlertEvent
from alert_render import is_event_ended_alert
from israel_map import IsraelMap


EVENT_ENDED_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class _PendingExpiry:
    item_id: int
    expires_at: datetime


class AlertExpiryManager:
    def __init__(self) -> None:
        self._pending: list[_PendingExpiry] = []

    def remember_drawn_alert(
        self,
        alert: AlertEvent,
        marker_ids: list[int],
        *,
        drawn_at: datetime | None = None,
    ) -> None:
        # 1. Only "event ended" alerts should auto-clear.
        # 2. All other alert types stay persistent until the user clears the map.
        if not marker_ids or not is_event_ended_alert(alert):
            return

        # 3. Prefer the alert timestamp when replay history provides one so a
        #    recovered alert still expires based on its original appearance time.
        # 4. Fall back to the local draw time for live alerts that do not carry a
        #    timestamp in the current payload shape.
        appeared_at = alert.alert_date or drawn_at or datetime.now()
        expires_at = appeared_at + EVENT_ENDED_TTL
        for item_id in marker_ids:
            self._pending.append(_PendingExpiry(item_id=item_id, expires_at=expires_at))

    def expire_due_markers(
        self,
        map_view: IsraelMap,
        *,
        now: datetime | None = None,
        log_fn: Callable[[str], None] | None = None,
    ) -> int:
        # 1. Walk the pending list once and keep only markers whose deadline has
        #    not been reached yet.
        # 2. Marker deletion is delegated to `IsraelMap` so the canvas state and
        #    the saved marker list stay in sync.
        anchor = now or datetime.now()
        remaining: list[_PendingExpiry] = []
        cleared_count = 0
        for pending in self._pending:
            if pending.expires_at > anchor:
                remaining.append(pending)
                continue
            if map_view.remove_marker(pending.item_id, refresh=False):
                cleared_count += 1
        self._pending = remaining

        # 3. Log only when real marker removals happened so the main loop output
        #    stays quiet during normal polling.
        if cleared_count and log_fn is not None:
            log_fn(f"Cleared {cleared_count} ended-alert markers after {EVENT_ENDED_TTL}")
        return cleared_count
