"""Lightweight health monitor for the UI loop and alert polling pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class WatchdogSnapshot:
    update_age_seconds: int
    fetch_attempt_age_seconds: int
    level: str
    pulse_on: bool
    text: str


class WatchdogMonitor:
    def __init__(
        self,
        *,
        poll_interval_seconds: float,
        request_timeout: tuple[float, float] | float,
    ) -> None:
        now = time.monotonic()
        self._lock = Lock()
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._request_timeout_seconds = _timeout_budget_seconds(request_timeout)
        self._last_ui_heartbeat = now
        self._last_fetch_attempt = now
        self._last_pipeline_update = now

    def note_ui_heartbeat(self) -> None:
        # 1. This heartbeat is driven only by the Tk/main loop.
        # 2. If the pulse stops changing on screen, the user immediately knows the
        #    UI thread is no longer making progress.
        self._set_timestamp("_last_ui_heartbeat")

    def note_fetch_attempt(self) -> None:
        # 1. The user asked to monitor whether fetch tries keep happening, not
        #    whether those tries succeed.
        # 2. This timestamp is written from the worker thread before each GET.
        self._set_timestamp("_last_fetch_attempt")

    def note_pipeline_update(self) -> None:
        # 1. This tracks end-to-end progress on the main thread after a worker
        #    result is consumed or a TEST-mode cycle completes.
        # 2. It is the best single "last update" signal for the running app.
        self._set_timestamp("_last_pipeline_update")

    def snapshot(self, now: float | None = None) -> WatchdogSnapshot:
        # 1. Read the three heartbeats atomically so the overlay is based on a
        #    coherent view of the system state.
        # 2. Use monotonic time to avoid wall-clock jumps affecting the age display.
        anchor = time.monotonic() if now is None else now
        with self._lock:
            ui_age = anchor - self._last_ui_heartbeat
            fetch_age = anchor - self._last_fetch_attempt
            update_age = anchor - self._last_pipeline_update

        level = self._status_level(ui_age=ui_age, fetch_age=fetch_age, update_age=update_age)
        pulse_on = int(anchor * 2.0) % 2 == 0
        update_age_seconds = max(0, int(update_age))
        fetch_age_seconds = max(0, int(fetch_age))
        return WatchdogSnapshot(
            update_age_seconds=update_age_seconds,
            fetch_attempt_age_seconds=fetch_age_seconds,
            level=level,
            pulse_on=pulse_on,
            text=f"Upd {update_age_seconds}s | Try {fetch_age_seconds}s",
        )

    def _set_timestamp(self, field_name: str) -> None:
        with self._lock:
            setattr(self, field_name, time.monotonic())

    def _status_level(self, *, ui_age: float, fetch_age: float, update_age: float) -> str:
        # 1. The UI heartbeat should stay fresh because the main loop cycles about
        #    every 0.1 seconds while waiting.
        # 2. The fetch/update ages are compared to the expected 10-second poll
        #    cadence plus timeout slack, because a slow but still-running network
        #    attempt is not a software freeze.
        ui_warn_threshold = 1.0
        ui_stale_threshold = 3.0
        fetch_warn_threshold = self._poll_interval_seconds + 3.0
        fetch_stale_threshold = self._poll_interval_seconds + self._request_timeout_seconds + 4.0
        update_warn_threshold = self._poll_interval_seconds + 3.0
        update_stale_threshold = self._poll_interval_seconds + self._request_timeout_seconds + 4.0

        if (
            ui_age > ui_stale_threshold
            or fetch_age > fetch_stale_threshold
            or update_age > update_stale_threshold
        ):
            return "stale"
        if ui_age > ui_warn_threshold or fetch_age > fetch_warn_threshold or update_age > update_warn_threshold:
            return "warn"
        return "ok"


def _timeout_budget_seconds(timeout: tuple[float, float] | float) -> float:
    if isinstance(timeout, tuple):
        return float(sum(timeout))
    return float(timeout)
