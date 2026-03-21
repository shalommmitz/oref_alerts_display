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
    reason_code: str
    reason_text: str


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
        self._fetch_issue_code = "ok"
        self._fetch_issue_text = "fetch attempts and update processing are healthy"

    def note_ui_heartbeat(self) -> None:
        # 1. This heartbeat is driven only by the Tk/main loop.
        # 2. If the pulse stops changing on screen, the user immediately knows the
        #    UI thread is no longer making progress.
        self._set_timestamp("_last_ui_heartbeat")

    def note_fetch_attempt(self) -> None:
        # 1. The user asked to monitor whether fetch tries keep happening.
        # 2. This timestamp is written from the worker thread before each GET.
        self._set_timestamp("_last_fetch_attempt")

    def note_fetch_success(self) -> None:
        # 1. Clear any previous fetch-related problem after a normal response.
        # 2. The next snapshot will then fall back to the age-based health checks.
        with self._lock:
            self._fetch_issue_code = "ok"
            self._fetch_issue_text = "fetch attempts and update processing are healthy"

    def note_fetch_failure(self, reason: str) -> None:
        # 1. A fetch failure should immediately drive the operator state to Offline.
        # 2. Keep the reason text stable enough that state-transition logging is meaningful.
        message = reason.strip() or "fetch failed"
        with self._lock:
            self._fetch_issue_code = "fetch_failure"
            self._fetch_issue_text = f"fetch failed: {message}"

    def note_pipeline_update(self) -> None:
        # 1. This tracks end-to-end progress on the main thread after a worker
        #    result is consumed or a TEST-mode cycle completes.
        # 2. It is the best single "last update" signal for the running app.
        self._set_timestamp("_last_pipeline_update")

    def snapshot(self, now: float | None = None) -> WatchdogSnapshot:
        # 1. Read the heartbeats atomically so the overlay is based on a coherent
        #    view of the system state.
        # 2. Use monotonic time to avoid wall-clock jumps affecting the age display.
        anchor = time.monotonic() if now is None else now
        with self._lock:
            ui_age = anchor - self._last_ui_heartbeat
            fetch_age = anchor - self._last_fetch_attempt
            update_age = anchor - self._last_pipeline_update
            fetch_issue_code = self._fetch_issue_code
            fetch_issue_text = self._fetch_issue_text

        reason_code, reason_text = self._status_reason(
            ui_age=ui_age,
            fetch_age=fetch_age,
            update_age=update_age,
            fetch_issue_code=fetch_issue_code,
            fetch_issue_text=fetch_issue_text,
        )
        level = "online" if reason_code == "ok" else "offline"
        pulse_on = int(anchor * 2.0) % 2 == 0
        update_age_seconds = max(0, int(update_age))
        fetch_age_seconds = max(0, int(fetch_age))
        return WatchdogSnapshot(
            update_age_seconds=update_age_seconds,
            fetch_attempt_age_seconds=fetch_age_seconds,
            level=level,
            pulse_on=pulse_on,
            text="Online" if level == "online" else "Offline",
            reason_code=reason_code,
            reason_text=reason_text,
        )

    def _set_timestamp(self, field_name: str) -> None:
        with self._lock:
            setattr(self, field_name, time.monotonic())

    def _status_reason(
        self,
        *,
        ui_age: float,
        fetch_age: float,
        update_age: float,
        fetch_issue_code: str,
        fetch_issue_text: str,
    ) -> tuple[str, str]:
        # 1. Report a direct fetch failure first because the user explicitly asked
        #    for Offline on network-fetch issues.
        # 2. After that, fall back to age-based checks that detect stalled tries or
        #    stalled main-loop processing even when there is no explicit exception.
        ui_stale_threshold = 3.0
        fetch_stale_threshold = self._poll_interval_seconds + self._request_timeout_seconds + 4.0
        update_stale_threshold = self._poll_interval_seconds + self._request_timeout_seconds + 4.0

        if fetch_issue_code != "ok":
            return fetch_issue_code, fetch_issue_text
        if ui_age > ui_stale_threshold:
            return "ui_stale", f"UI heartbeat stalled for {int(ui_age)}s"
        if fetch_age > fetch_stale_threshold:
            return "fetch_stale", f"no fetch attempt started for {int(fetch_age)}s"
        if update_age > update_stale_threshold:
            return "update_stale", f"no update cycle completed for {int(update_age)}s"
        return "ok", "fetch attempts and update processing are healthy"


def _timeout_budget_seconds(timeout: tuple[float, float] | float) -> float:
    if isinstance(timeout, tuple):
        return float(sum(timeout))
    return float(timeout)
