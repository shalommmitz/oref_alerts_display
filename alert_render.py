"""Rendering and persistence helpers for normalized alerts."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import yaml

from alert_model import AlertEvent
from israel_map import IsraelMap


class AlertMarkerRegistry:
    def __init__(self) -> None:
        # 1. Keep one visible alert marker per resolved map locality.
        # 2. The registry is keyed by the final coordinates lookup key so alerts
        #    that normalize to the same mapped locality replace each other.
        self._marker_by_locality: dict[str, int] = {}

    def replace_marker(
        self,
        map_view: IsraelMap,
        *,
        locality_key: str,
        item_id: int,
    ) -> None:
        # 1. Remove the older marker first so the new alert visibly replaces it
        #    instead of stacking on top of it.
        # 2. Ignore already-missing markers because they may have been cleared by
        #    expiry or by a manual map reset.
        previous_item_id = self._marker_by_locality.get(locality_key)
        if previous_item_id is not None and previous_item_id != item_id:
            map_view.remove_marker(previous_item_id, refresh=False)
        self._marker_by_locality[locality_key] = item_id


def persist_alert_artifacts(
    alert: AlertEvent,
    *,
    base_dir: Path,
    biggest_alert_size: int,
) -> int:
    # 1. Preserve the existing debugging artifacts in one shared place.
    # 2. Return the updated biggest-alert size so the caller can keep its state.
    raw_text = str(alert.raw)
    if len(raw_text) > biggest_alert_size:
        with (base_dir / "biggest_alert.yaml").open("w", encoding="utf-8") as handle:
            yaml.safe_dump(alert.raw, handle)
        biggest_alert_size = len(raw_text)

    with (base_dir / "last_alert.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(alert.raw, handle)
    return biggest_alert_size


def draw_alert(
    map_view: IsraelMap,
    coords: dict[str, dict[str, float]],
    alert: AlertEvent,
    log_fn: Callable[[str], None],
    marker_registry: AlertMarkerRegistry,
) -> list[int]:
    # 1. Resolve the alert color once per alert and reuse it for every locality.
    # 2. Keep the marker-drawing loop focused only on locality lookup, replacement,
    #    and drawing.
    drawn_marker_ids: list[int] = []
    color = _alert_color(alert, log_fn)
    for locality in alert.data:
        coords_key = _find_coords_key(locality, coords)
        if coords_key is None:
            print(locality)
            for candidate in coords.keys():
                if candidate.startswith(locality[:2]):
                    print("   ", candidate)
            continue

        latitude = coords[coords_key]["latitude"]
        longitude = coords[coords_key]["longitude"]
        item_id = map_view.draw(latitude, longitude, color, "circle", 8, refresh=False)
        marker_registry.replace_marker(
            map_view,
            locality_key=coords_key,
            item_id=item_id,
        )
        drawn_marker_ids.append(item_id)
    return drawn_marker_ids


def is_event_ended_alert(alert: AlertEvent) -> bool:
    # 1. Keep the "ended event" semantics in one place so time-based cleanup does
    #    not depend on the current display color.
    # 2. The user-facing behavior is defined by alert meaning, not by whichever
    #    color happens to represent that alert today.
    # 3. The official OREF category id currently arrives as 13 for this title,
    #    while older saved payloads in this project used 10.
    return alert.title == "האירוע הסתיים"


def is_upcoming_area_alert(alert: AlertEvent) -> bool:
    # 1. History currently uses category 14 for the yellow pre-alert rows while
    #    older saved payloads in this project used category 10.
    # 2. Title matching keeps the decision stable across those source differences.
    return alert.title == "בדקות הקרובות צפויות להתקבל התרעות באזורך"


def _find_coords_key(locality: str, coords: dict[str, dict[str, float]]) -> str | None:
    # 1. Preserve the existing exact-match plus prefix heuristic.
    # 2. Use the normalized locality string consistently instead of ignoring it.
    normalized_locality = locality
    if " - " in normalized_locality:
        normalized_locality = normalized_locality.split(" - ")[0]
    normalized_locality = normalized_locality.replace("''", '"')

    if locality in coords:
        return locality
    if normalized_locality in coords:
        return normalized_locality

    for candidate in coords.keys():
        if candidate.startswith(normalized_locality):
            return candidate
    return None


def _alert_color(alert: AlertEvent, log_fn: Callable[[str], None]) -> str:
    # 1. Check the title-based update/flash semantics first because the official
    #    endpoint now emits category ids 13 and 14 for those rows.
    # 2. Keep backward compatibility with older locally saved payloads whose
    #    category field used the older matrix-style values.
    if is_upcoming_area_alert(alert):
        return "yellow"
    if is_event_ended_alert(alert):
        return "gray"

    match alert.cat:
        case "1":
            return "red"
        case "2" | "6":
            # 3. The official category metadata maps current id 2 (`uav`) to the
            #    older matrix id 6 that this project also treats as UAV intrusion.
            return "purple"
        case _:
            raise ValueError(f"Unknown alert code {alert.cat}")
