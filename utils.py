import time
from pathlib import Path
from datetime import datetime

import yaml
from israel_map import IsraelMap

BASE_DIR = Path(__file__).resolve().parent

def log(msg):
    now = datetime.now().strftime("%d%B_%H%M.%S")
    open("log.txt", 'a').write(f"{now} {msg}\n")
    print(f"\r{" "*80}", end="")
    print(f"\r{now} {msg[:80]}", end="")

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
