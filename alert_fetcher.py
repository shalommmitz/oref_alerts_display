"""Background HTTP polling for show_alerts."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, SimpleQueue
from threading import Event, Thread

import requests


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
    ) -> None:
        self.url = url
        self.poll_interval = poll_interval
        self.timeout = timeout
        self._stop_event = Event()
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
                # 2. Run the blocking HTTP request away from Tk so network stalls
                #    do not freeze the map window.
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

                # 3. Wait between polls, but let shutdown interrupt the sleep.
                if self._stop_event.wait(self.poll_interval):
                    break
        finally:
            session.close()
