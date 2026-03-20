"""History replay support for startup catch-up and outage recovery."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import requests

from alert_model import AlertEvent, decode_alert_text, normalize_history_payload


class AlertHistoryClient:
    def __init__(self, url: str, timeout: tuple[float, float]) -> None:
        self.url = url
        self.timeout = timeout

    def fetch_recent(self, lookback_seconds: int, now: datetime | None = None) -> list[AlertEvent]:
        # 1. Startup replay wants a relative window ending "now".
        # 2. Convert that into the same absolute cutoff used by recovery replay.
        anchor = now or datetime.now()
        return self.fetch_since(anchor - timedelta(seconds=lookback_seconds))

    def fetch_since(self, since: datetime) -> list[AlertEvent]:
        # 1. Fetch the raw history payload from the endpoint.
        # 2. Normalize rows and keep only alerts newer than the requested cutoff.
        events = self._fetch_all()
        return [event for event in events if event.alert_date is not None and event.alert_date > since]

    def _fetch_all(self) -> list[AlertEvent]:
        # 1. History fetches are infrequent, so a one-shot request is enough here.
        # 2. Reuse the same timeout policy as live fetches so failure modes stay predictable.
        response = requests.get(self.url, timeout=self.timeout)
        response.raise_for_status()
        alert_text = decode_alert_text(response.content)
        # 3. The official history endpoint may reply with HTTP 200 and an empty body
        #    when there are no recent alerts to replay.
        # 4. Treat that as an empty history list instead of raising a JSON parse error.
        if not alert_text:
            return []
        raw_items = json.loads(alert_text)
        return normalize_history_payload(raw_items)
