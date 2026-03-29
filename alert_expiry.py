"""Time-based cleanup for alert markers that should disappear automatically."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from heapq import heappop, heappush
from typing import Callable

from alert_model import AlertEvent, current_oref_time, ensure_oref_datetime
from alert_render import is_event_ended_alert
from israel_map import IsraelMap


EVENT_ENDED_TTL = timedelta(minutes=10)
MAX_EXPIRY_REMOVALS_PER_PASS = 100


@dataclass(order=True, frozen=True)
class _PendingExpiry:
    expires_at: datetime
    item_id: int


class AlertExpiryManager:
    def __init__(self) -> None:
        self._pending: list[_PendingExpiry] = []

    def clear(self) -> None:
        # 1. Manual map clears should also discard pending expiry work so old
        #    marker ids are not carried into the next alert cycle.
        # 2. This keeps the expiry heap aligned with what is actually visible.
        self._pending.clear()

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
        appeared_at = alert.alert_date
        if appeared_at is None and drawn_at is not None:
            appeared_at = ensure_oref_datetime(drawn_at)
        if appeared_at is None:
            appeared_at = current_oref_time()
        expires_at = appeared_at + EVENT_ENDED_TTL
        for item_id in marker_ids:
            heappush(self._pending, _PendingExpiry(expires_at=expires_at, item_id=item_id))

    def expire_due_markers(
        self,
        map_view: IsraelMap,
        *,
        now: datetime | None = None,
        log_fn: Callable[[str], None] | None = None,
        max_removals: int = MAX_EXPIRY_REMOVALS_PER_PASS,
    ) -> int:
        # 1. Walk the pending list once and keep only markers whose deadline has
        #    not been reached yet.
        # 2. Limit the number of Tk canvas deletions per pass so a large expiry
        #    batch cannot monopolize the UI thread.
        anchor = ensure_oref_datetime(now) if now is not None else current_oref_time()
        cleared_count = 0
        removal_budget = max(1, max_removals)
        while self._pending and cleared_count < removal_budget:
            pending = self._pending[0]
            if pending.expires_at > anchor:
                break
            heappop(self._pending)
            if map_view.remove_marker(pending.item_id, refresh=False):
                cleared_count += 1

        # 3. Log only when real marker removals happened so the main loop output
        #    stays quiet during normal polling.
        if cleared_count and log_fn is not None:
            log_fn(f"Cleared {cleared_count} 10-minutes old ended-alert markers")
        return cleared_count
