"""Normalization helpers shared by live alerts and history replays."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


OREF_TIMEZONE = ZoneInfo("Asia/Jerusalem")
_SORT_MIN_ALERT_DATE = datetime.min.replace(tzinfo=OREF_TIMEZONE)


@dataclass(frozen=True)
class AlertEvent:
    key: str
    raw: dict
    cat: str
    title: str
    data: tuple[str, ...]
    desc: str
    alert_date: datetime | None = None


def decode_alert_text(content: bytes) -> str:
    # 1. Keep the existing BOM-safe decoding rule in one shared place.
    # 2. Both live alerts and history replays pass through the same text decode path.
    return content.decode("utf-8-sig").strip()


def current_oref_time() -> datetime:
    # 1. Keep all replay and expiry comparisons on the same timezone basis, even
    #    when the consuming machine is not configured for Israel time.
    # 2. The OREF history endpoint timestamps are local Israel wall-clock times,
    #    so `Asia/Jerusalem` is the right reference zone.
    return datetime.now(OREF_TIMEZONE)


def ensure_oref_datetime(value: datetime) -> datetime:
    # 1. Normalize every runtime cutoff onto the same explicit timezone basis.
    # 2. Naive datetimes are interpreted as already being OREF-local times, while
    #    aware datetimes are converted into that zone.
    if value.tzinfo is None:
        return value.replace(tzinfo=OREF_TIMEZONE)
    return value.astimezone(OREF_TIMEZONE)


def parse_live_alert_text(alert_text: str) -> AlertEvent | None:
    # 1. Treat empty or nearly-empty payloads as "no current alert".
    # 2. This preserves the long-standing behavior of the main loop.
    if len(alert_text) <= 3:
        return None
    raw_alert = json.loads(alert_text)
    return normalize_live_alert(raw_alert)


def normalize_live_alert(raw_alert: dict) -> AlertEvent:
    # 1. Live alerts already use the runtime schema, so normalization mostly
    #    ensures the data list and the deduplication key are stable.
    data = _normalize_localities(raw_alert.get("data"))
    alert_id = str(raw_alert.get("id", ""))
    alert_date = parse_alert_datetime(raw_alert.get("alertDate"))
    title = str(raw_alert.get("title", ""))
    cat = str(raw_alert.get("cat", ""))
    desc = str(raw_alert.get("desc", ""))
    raw = {
        "id": alert_id,
        "cat": cat,
        "title": title,
        "data": list(data),
        "desc": desc,
    }
    if alert_date is not None:
        raw["alertDate"] = raw_alert.get("alertDate")
    return AlertEvent(
        key=_build_alert_key(
            alert_id=alert_id,
            alert_date=alert_date,
            cat=cat,
            title=title,
            data=data,
        ),
        raw=raw,
        cat=cat,
        title=title,
        data=data,
        desc=desc,
        alert_date=alert_date,
    )


def normalize_history_payload(raw_items: object) -> list[AlertEvent]:
    # 1. The history endpoint returns a list, but its item shape is not identical
    #    to the live alert schema.
    # 2. Normalize it into the same AlertEvent model used by the rest of the app.
    if not isinstance(raw_items, list):
        return []

    normalized: list[AlertEvent] = []
    seen_keys: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        event = normalize_history_alert(raw_item)
        if event is None or event.key in seen_keys:
            continue
        seen_keys.add(event.key)
        normalized.append(event)
    normalized.sort(key=_history_sort_key)
    return normalized


def normalize_history_alert(raw_item: dict) -> AlertEvent | None:
    # 1. History replays may use `category` instead of `cat`, may expose
    #    `category_desc` instead of `title`, and may encode the locality list
    #    as one comma-separated string.
    # 2. Convert all of that into the live-style shape once here.
    data = _normalize_localities(raw_item.get("data"))
    if not data:
        return None

    alert_date = parse_alert_datetime(raw_item.get("alertDate"))
    cat = str(raw_item.get("category") or raw_item.get("cat") or "")
    title = str(raw_item.get("title") or raw_item.get("category_desc") or raw_item.get("desc") or "")
    desc = str(raw_item.get("desc") or raw_item.get("description") or "")
    alert_id = raw_item.get("id")
    raw = {
        "id": str(alert_id) if alert_id is not None else "",
        "cat": cat,
        "title": title,
        "data": list(data),
        "desc": desc,
    }
    if alert_date is not None:
        raw["alertDate"] = raw_item.get("alertDate")
    return AlertEvent(
        key=_build_alert_key(
            alert_id=str(alert_id) if alert_id is not None else "",
            alert_date=alert_date,
            cat=cat,
            title=title,
            data=data,
        ),
        raw=raw,
        cat=cat,
        title=title,
        data=data,
        desc=desc,
        alert_date=alert_date,
    )


def parse_alert_datetime(value: object) -> datetime | None:
    # 1. Support a few timestamp layouts because the history API is not guaranteed
    #    to stay pinned to one exact string representation.
    # 2. Always return datetimes on the explicit OREF timezone basis so replay
    #    and expiry work correctly on machines outside Israel's local timezone.
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    candidates = (
        text.replace("Z", "+00:00"),
        text.replace(" ", "T"),
        text,
    )
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            pass
        else:
            return ensure_oref_datetime(parsed)

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return ensure_oref_datetime(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return None


def _normalize_localities(value: object) -> tuple[str, ...]:
    # 1. Normalize either a list payload or a comma-separated string payload.
    # 2. Trim whitespace and drop empty fragments so downstream code can assume
    #    clean locality names.
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return tuple()


def _build_alert_key(
    *,
    alert_id: str,
    alert_date: datetime | None,
    cat: str,
    title: str,
    data: tuple[str, ...],
) -> str:
    # 1. Prefer the upstream alert id when it exists because that matches the
    #    current live-alert dedup behavior.
    # 2. Fall back to a stable synthetic key for history rows that do not carry an id.
    if alert_id:
        return f"id:{alert_id}"
    date_text = alert_date.isoformat(sep=" ", timespec="seconds") if alert_date else ""
    locality_text = ",".join(data)
    return f"hist:{date_text}|{cat}|{title}|{locality_text}"


def _history_sort_key(event: AlertEvent) -> tuple[datetime, str]:
    return (event.alert_date or _SORT_MIN_ALERT_DATE, event.key)
