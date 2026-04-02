"""Background HTTP polling for show_alerts."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, SimpleQueue
from threading import Event, Thread
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from watchdog import WatchdogMonitor


@dataclass(frozen=True)
class FetchResult:
    status_code: int | None = None
    content: bytes | None = None
    error_type: str | None = None
    error_message: str | None = None


class AlertFetcher:
    def __init__(
        self,
        url: str,
        poll_interval: float,
        timeout: tuple[float, float],
        watchdog: WatchdogMonitor | None = None,
    ) -> None:
        self.url = url
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.watchdog = watchdog
        self._stop_event = Event()
        self._pause_event = Event()
        self._results: SimpleQueue[FetchResult] = SimpleQueue()
        self._thread = Thread(
            target=self._run,
            name="alert-fetcher",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=1.0)

    def pause(self) -> None:
        # 1. Pause only future polling work. An already-running request may still
        #    finish, so callers that need a clean pause should also drain results.
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def clear_pending_results(self) -> None:
        # 1. Drop queued fetch results so higher-level modes, such as Demo, can
        #    resume from a clean boundary instead of replaying stale live data.
        while True:
            try:
                self._results.get_nowait()
            except Empty:
                return

    def poll(self) -> FetchResult | None:
        # 1. Drain the queue and keep only the newest result.
        # 2. This prevents the UI thread from replaying stale network states.
        latest: FetchResult | None = None
        while True:
            try:
                latest = self._results.get_nowait()
            except Empty:
                return latest

    def _run(self) -> None:
        # 1. Create the session inside the worker thread because all network I/O
        #    for this helper happens on that thread.
        session = requests.Session()
        try:
            while not self._stop_event.is_set():
                while self._pause_event.is_set() and not self._stop_event.is_set():
                    self._stop_event.wait(0.1)
                if self._stop_event.is_set():
                    break

                # 2. Run the blocking HTTP request away from Tk so network stalls
                #    do not freeze the map window.
                if self.watchdog is not None:
                    self.watchdog.note_fetch_attempt()
                try:
                    response = session.get(self.url, timeout=self.timeout)
                except requests.RequestException as exc:
                    self._results.put(
                        FetchResult(
                            error_type=exc.__class__.__name__,
                            error_message=str(exc),
                        )
                    )
                else:
                    self._results.put(
                        FetchResult(
                            status_code=response.status_code,
                            content=response.content,
                        )
                    )
                    response.close()

                # 3. Wait between polls, but let shutdown or pause interrupt the sleep.
                remaining = self.poll_interval
                while remaining > 0 and not self._stop_event.is_set() and not self._pause_event.is_set():
                    sleep_slice = min(0.1, remaining)
                    if self._stop_event.wait(sleep_slice):
                        break
                    remaining -= sleep_slice
        finally:
            session.close()
