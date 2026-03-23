from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
import shutil
import sys
from typing import Callable, Optional

import yaml
from israel_map import IsraelMap

BASE_DIR = Path(__file__).resolve().parent
_LOG_TIME_SINK: Optional[Callable[[str], None]] = None
_TERMINAL_LINE_WIDTH = max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)


def set_log_time_sink(sink: Optional[Callable[[str], None]]) -> None:
    global _LOG_TIME_SINK
    _LOG_TIME_SINK = sink

def log(msg):
    _emit_runtime_line(msg, persist=True)


def show_status(msg):
    _emit_runtime_line(msg, persist=False)


def finish_runtime_line() -> None:
    # 1. End the carriage-return status line with a real newline so the shell
    #    prompt does not continue on the same row after the program exits.
    # 2. Keep this in one helper so every runtime entry point can use the same
    #    terminal cleanup behavior on shutdown.
    sys.stdout.write("\n")
    sys.stdout.flush()


def _emit_runtime_line(msg, *, persist: bool):
    now = datetime.now()
    if _LOG_TIME_SINK is not None:
        try:
            _LOG_TIME_SINK(now.strftime("%H:%M.%S"))
        except Exception:
            pass
    now_text = now.strftime("%d%B_%H%M.%S")
    if persist:
        with open("log.txt", "a", encoding="utf-8") as handle:
            handle.write(f"{now_text} {msg}\n")
    # 1. Detect terminal width once at program launch and keep the runtime output
    #    width stable for the whole session.
    # 2. Trim the visible line to that width so the carriage-return redraw clears
    #    only the current terminal row instead of assuming 80 columns.
    line_text = f"{now_text} {msg}"
    sys.stdout.write(f"\r{' ' * _TERMINAL_LINE_WIDTH}\r{line_text[:_TERMINAL_LINE_WIDTH]}")
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
