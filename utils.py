import time
from pathlib import Path
from datetime import datetime
from typing import Callable
import sys

import yaml
from israel_map import IsraelMap

BASE_DIR = Path(__file__).resolve().parent
_LOG_TIME_SINK: Callable[[str], None] | None = None


def set_log_time_sink(sink: Callable[[str], None] | None) -> None:
    global _LOG_TIME_SINK
    _LOG_TIME_SINK = sink

def log(msg):
    now = datetime.now()
    if _LOG_TIME_SINK is not None:
        try:
            _LOG_TIME_SINK(now.strftime("%H:%M.%S"))
        except Exception:
            pass
    now_text = now.strftime("%d%B_%H%M.%S")
    with open("log.txt", "a", encoding="utf-8") as handle:
        handle.write(f"{now_text} {msg}\n")
    sys.stdout.write(f"\r{' ' * 80}\r{now_text} {msg[:80]}")
    sys.stdout.flush()

def sleep_with_ui(map_view: IsraelMap, seconds: float) -> bool:
    """Sleep in small steps so the Tk window stays responsive."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not map_view.update():
            return False
        time.sleep(0.1)
    return True

def to_heb_chars(s):
    s.encode('utf-8').decode('unicode_escape')
    return s


def get_coords():
    with (BASE_DIR / "locality_latitude_longitude.yaml").open() as handle:
        x = yaml.safe_load(handle)
    coords = { }
    for locality in x.keys():
        coords[to_heb_chars(locality)] = x[locality]
    return coords
