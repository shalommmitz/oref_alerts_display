#!/usr/bin/env python3

import time

from israel_map import IsraelMap


def fetch_coords() -> tuple[float, float] | None:
    """Placeholder. Replace with the real coordinate source."""
    return None


def sleep_with_ui(map_view: IsraelMap, seconds: float) -> bool:
    """Sleep in small steps so the Tk window stays responsive."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not map_view.update():
            return False
        time.sleep(0.1)
    return True


def main() -> None:
    map_view = IsraelMap(auto_refresh=False)

    while map_view.is_open():
        coords = fetch_coords()
        if coords is None:
            if not sleep_with_ui(map_view, 10):
                break
            continue

        latitude, longitude = coords
        map_view.draw(latitude, longitude, "red", "circle", 10, refresh=False)
        if not map_view.update():
            break

    map_view.close()


if __name__ == "__main__":
    main()
