"""Rendering and persistence helpers for normalized alerts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from alert_model import AlertEvent
from alert_types import AlertTypeInfo, classify_alert
from israel_map import IsraelMap


@dataclass
class AlertDrawResult:
    marker_ids: list[int]
    changed_marker_ids: list[int]
    resolved_points: list[tuple[float, float]]
    alert_type: AlertTypeInfo


class AlertMarkerRegistry:
    def __init__(self) -> None:
        # 1. Keep one visible alert marker per resolved map locality.
        # 2. The registry is keyed by the final coordinates lookup key so alerts
        #    that normalize to the same mapped locality replace each other.
        self._marker_by_locality: dict[str, int] = {}
        self._state_by_locality: dict[str, str] = {}

    def current_state(self, map_view: IsraelMap, *, locality_key: str) -> str | None:
        # 1. Treat missing canvas markers as "no current state" so stale
        #    registry entries left behind by expiry or manual clear do not hide
        #    real state changes from the blink logic.
        # 2. Keep the cleanup here so callers can ask one question without
        #    needing separate stale-entry handling.
        item_id = self._marker_by_locality.get(locality_key)
        if item_id is None:
            return None
        if not map_view.has_marker(item_id):
            self._marker_by_locality.pop(locality_key, None)
            self._state_by_locality.pop(locality_key, None)
            return None
        return self._state_by_locality.get(locality_key)

    def replace_marker(
        self,
        map_view: IsraelMap,
        *,
        locality_key: str,
        item_id: int,
        state_key: str,
    ) -> None:
        # 1. Remove the older marker first so the new alert visibly replaces it
        #    instead of stacking on top of it.
        # 2. Ignore already-missing markers because they may have been cleared by
        #    expiry or by a manual map reset.
        previous_item_id = self._marker_by_locality.get(locality_key)
        if previous_item_id is not None and previous_item_id != item_id:
            map_view.remove_marker(previous_item_id, refresh=False)
        self._marker_by_locality[locality_key] = item_id
        self._state_by_locality[locality_key] = state_key

    def clear(self) -> None:
        # 1. Drop all locality mappings after a manual map clear so the next
        #    live poll can repopulate the map from scratch.
        # 2. Keep this state reset explicit because the canvas and the alert
        #    loop maintain related, but separate, pieces of runtime state.
        self._marker_by_locality.clear()
        self._state_by_locality.clear()


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
    marker_registry: AlertMarkerRegistry,
) -> AlertDrawResult:
    # 1. Resolve the alert color once per alert and reuse it for every locality.
    # 2. Return both all drawn markers and the subset whose locality state
    #    actually changed, so blinking can ignore repeated same-state localities.
    drawn_marker_ids: list[int] = []
    changed_marker_ids: list[int] = []
    resolved_points: list[tuple[float, float]] = []
    alert_type = classify_alert(alert)
    color = alert_type.color
    state_key = alert_type.state_key
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
        resolved_points.append((latitude, longitude))
        previous_state_key = marker_registry.current_state(
            map_view,
            locality_key=coords_key,
        )
        item_id = map_view.draw(
            latitude,
            longitude,
            color,
            alert_type.shape,
            8,
            refresh=False,
            include_in_localized_zoom=alert_type.include_in_localized_zoom,
        )
        marker_registry.replace_marker(
            map_view,
            locality_key=coords_key,
            item_id=item_id,
            state_key=state_key,
        )
        drawn_marker_ids.append(item_id)
        if previous_state_key != state_key:
            changed_marker_ids.append(item_id)
    return AlertDrawResult(
        marker_ids=drawn_marker_ids,
        changed_marker_ids=changed_marker_ids,
        resolved_points=resolved_points,
        alert_type=alert_type,
    )


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
