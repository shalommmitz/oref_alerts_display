"""Transient focus circles for small incoming alerts."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from israel_map import IsraelMap


DEFAULT_FOCUS_CIRCLE_COLOR = "#66b2ff"
DEFAULT_FOCUS_CIRCLE_WIDTH = 2
DEFAULT_FOCUS_CIRCLE_PADDING = 12.0
DEFAULT_FOCUS_CIRCLE_MIN_RADIUS = 18.0
DEFAULT_FOCUS_CIRCLE_DURATION_SECONDS = 6.0


@dataclass
class _FocusCircleState:
    started_at: float


class AlertFocusCircleManager:
    def __init__(self) -> None:
        self._circles: dict[int, _FocusCircleState] = {}
        self._duration_seconds = DEFAULT_FOCUS_CIRCLE_DURATION_SECONDS

    def set_duration(self, duration_seconds: float) -> None:
        # 1. Share one operator-attention duration with the blink manager so the
        #    Settings dialog controls both effects together.
        # 2. Clamp to a tiny positive minimum so already-running circles still
        #    expire predictably even if the setting is edited to a bad value.
        self._duration_seconds = max(0.1, float(duration_seconds))

    def remember_points(
        self,
        map_view: IsraelMap,
        points: list[tuple[float, float]],
        *,
        started_at: float | None = None,
    ) -> int | None:
        # 1. Create one non-destructive overlay item so removing it restores the
        #    underlying pixels exactly, without having to mutate the map image.
        # 2. Skip empty point sets because unresolved localities should not
        #    create a bogus focus ring at the top-left corner.
        if not points:
            return None
        item_id = map_view.draw_focus_circle(
            points,
            outline_color=DEFAULT_FOCUS_CIRCLE_COLOR,
            width=DEFAULT_FOCUS_CIRCLE_WIDTH,
            padding=DEFAULT_FOCUS_CIRCLE_PADDING,
            min_radius=DEFAULT_FOCUS_CIRCLE_MIN_RADIUS,
            refresh=False,
        )
        self._circles[item_id] = _FocusCircleState(
            started_at=monotonic() if started_at is None else started_at
        )
        return item_id

    def update(self, map_view: IsraelMap, *, now: float | None = None) -> int:
        # 1. Remove expired circles from the main loop so all Tk canvas work
        #    stays on the Tk-owning thread.
        # 2. Treat already-missing items as finished because the map may have
        #    been cleared or closed while the circle was still tracked.
        anchor = monotonic() if now is None else now
        removed_count = 0
        finished_ids: list[int] = []
        for item_id, state in list(self._circles.items()):
            elapsed = anchor - state.started_at
            if elapsed < self._duration_seconds:
                continue
            if map_view.remove_focus_circle(item_id, refresh=False):
                removed_count += 1
            finished_ids.append(item_id)

        for item_id in finished_ids:
            self._circles.pop(item_id, None)
        return removed_count

    def clear(self, map_view: IsraelMap) -> int:
        # 1. Remove every tracked circle immediately when the operator disables
        #    the feature in Settings.
        # 2. Keep the cleanup centralized so old tracked ids cannot leak into
        #    later alert cycles.
        removed_count = 0
        for item_id in list(self._circles):
            if map_view.remove_focus_circle(item_id, refresh=False):
                removed_count += 1
        self._circles.clear()
        return removed_count
