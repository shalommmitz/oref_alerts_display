"""Load alert-category policy from a single YAML file."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from alert_model import AlertEvent


_ALERT_CATEGORIES_PATH = Path(__file__).resolve().parent / "alert_categories.yaml"


@dataclass(frozen=True)
class AlertTypeInfo:
    title: str
    key: str
    known_cats: tuple[str, ...]
    color: str
    shape: str
    legend_label: str
    legend_description: str
    state_key: str
    include_in_localized_zoom: bool
    reassess_zoom_on_new: bool
    auto_clear_after_seconds: Optional[int]
    show_in_legend: bool


class AlertTypeRegistry:
    def __init__(self, alert_types: tuple[AlertTypeInfo, ...]) -> None:
        self._alert_types = alert_types
        self._by_key = {alert_type.key: alert_type for alert_type in alert_types}
        self._by_title = {
            alert_type.title: alert_type
            for alert_type in alert_types
        }
        self._unknown_title = self._by_title.get("unknown_title")

    def classify(self, alert: AlertEvent) -> AlertTypeInfo:
        title = str(alert.title)
        if title in self._by_title:
            return self._by_title[title]
        if self._unknown_title is not None:
            return self._unknown_title
        raise ValueError(f"Unknown alert title {alert.title!r}")

    def legend_items(self) -> tuple[AlertTypeInfo, ...]:
        return tuple(
            alert_type
            for alert_type in self._alert_types
            if alert_type.show_in_legend
        )

    def auto_clear_note_text(self) -> str:
        note_parts = [
            "A newer alert replaces the older marker at the same locality."
        ]
        seen_auto_clear_notes: set[tuple[str, int]] = set()
        for alert_type in self._alert_types:
            if alert_type.auto_clear_after_seconds is None:
                continue
            note_key = (alert_type.legend_label, alert_type.auto_clear_after_seconds)
            if note_key in seen_auto_clear_notes:
                continue
            seen_auto_clear_notes.add(note_key)
            note_parts.append(
                f"{alert_type.legend_label} markers clear after "
                f"{_format_duration(alert_type.auto_clear_after_seconds)}."
            )
        return " ".join(note_parts)

    def get(self, key: str) -> AlertTypeInfo:
        return self._by_key[key]


def classify_alert(alert: AlertEvent) -> AlertTypeInfo:
    return get_alert_type_registry().classify(alert)


@lru_cache(maxsize=1)
def get_alert_type_registry() -> AlertTypeRegistry:
    with _ALERT_CATEGORIES_PATH.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    if not isinstance(loaded, dict) or not loaded:
        raise ValueError("alert_categories.yaml must contain a non-empty title mapping")

    parsed_alert_types: list[AlertTypeInfo] = []
    seen_keys: set[str] = set()
    for raw_title, raw_entry in loaded.items():
        title = str(raw_title).strip()
        if not title:
            raise ValueError("Each top-level alert title key must be non-empty")
        if not isinstance(raw_entry, dict):
            raise ValueError(f"Alert title {title!r} must map to a dictionary")
        parsed_alert_types.append(
            _parse_alert_type_entry(
                title=title,
                raw_entry=raw_entry,
                seen_keys=seen_keys,
            )
        )

    return AlertTypeRegistry(tuple(parsed_alert_types))


def _parse_alert_type_entry(
    *,
    title: str,
    raw_entry: dict,
    seen_keys: set[str],
) -> AlertTypeInfo:
    key = str(raw_entry.get("key", "")).strip()
    if not key:
        raise ValueError(f"Alert title {title!r} must define a non-empty key")
    if key in seen_keys:
        raise ValueError(f"Duplicate alert type key {key!r}")
    seen_keys.add(key)

    color = str(raw_entry.get("color", "")).strip()
    if not color:
        raise ValueError(f"Alert title {title!r} must define a color")
    shape = str(raw_entry.get("shape", "")).strip() or "circle"

    legend_label = str(raw_entry.get("legend_label", key)).strip()
    legend_description = str(raw_entry.get("legend_description", "")).strip()
    state_key = str(raw_entry.get("state_key", key)).strip() or key
    include_in_localized_zoom = bool(
        raw_entry.get("include_in_localized_zoom", True)
    )
    reassess_zoom_on_new = bool(
        raw_entry.get("reassess_zoom_on_new", include_in_localized_zoom)
    )
    auto_clear_after_seconds = raw_entry.get("auto_clear_after_seconds")
    if auto_clear_after_seconds in (None, ""):
        parsed_auto_clear_after_seconds = None
    else:
        parsed_auto_clear_after_seconds = int(auto_clear_after_seconds)
        if parsed_auto_clear_after_seconds <= 0:
            raise ValueError(
                f"Alert type {key!r} has non-positive auto_clear_after_seconds"
            )

    known_cats = _parse_known_cats(raw_entry.get("known_cats"))
    return AlertTypeInfo(
        title=title,
        key=key,
        known_cats=known_cats,
        color=color,
        shape=shape,
        legend_label=legend_label,
        legend_description=legend_description,
        state_key=state_key,
        include_in_localized_zoom=include_in_localized_zoom,
        reassess_zoom_on_new=reassess_zoom_on_new,
        auto_clear_after_seconds=parsed_auto_clear_after_seconds,
        show_in_legend=bool(raw_entry.get("show_in_legend", True)),
    )


def _parse_known_cats(raw_known_cats: object) -> tuple[str, ...]:
    if raw_known_cats in (None, ""):
        return tuple()
    if isinstance(raw_known_cats, list):
        return tuple(str(item).strip() for item in raw_known_cats if str(item).strip())
    return (str(raw_known_cats).strip(),)


def _format_duration(duration_seconds: int) -> str:
    if duration_seconds % 3600 == 0:
        hours = duration_seconds // 3600
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    if duration_seconds % 60 == 0:
        minutes = duration_seconds // 60
        return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
    return f"{duration_seconds} second" if duration_seconds == 1 else f"{duration_seconds} seconds"
