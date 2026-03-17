from __future__ import annotations

import json
from pathlib import Path

import yaml


BASE_DIR = Path(__file__).resolve().parent
LOCALITIES_PATH = BASE_DIR / "localities.yaml"
CITIES_PATH = BASE_DIR / "cities.json"
OUTPUT_PATH = BASE_DIR / "locality_latitude_longitude.yaml"


def load_authoritative_lookup(path: Path) -> dict[str, dict[str, float]]:
    with path.open(encoding="utf-8") as handle:
        localities = yaml.safe_load(handle)

    lookup: dict[str, dict[str, float]] = {}
    for locality in localities:
        name = locality["name"]
        wgs84 = locality["coordinates"]["wgs84"]
        lookup[name] = {
            "latitude": wgs84["latitude"],
            "longitude": wgs84["longitude"],
        }
    return lookup


def merge_missing_cities(lookup: dict[str, dict[str, float]], path: Path) -> None:
    with path.open(encoding="utf-8") as handle:
        cities = json.load(handle)["cities"]

    for fallback_name, city in cities.items():
        name = city.get("he") or fallback_name
        if name in lookup:
            continue
        if "lat" not in city or "lng" not in city:
            continue
        lookup[name] = {
            "latitude": city["lat"],
            "longitude": city["lng"],
        }


def main() -> None:
    lookup = load_authoritative_lookup(LOCALITIES_PATH)
    merge_missing_cities(lookup, CITIES_PATH)

    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(lookup, handle)


if __name__ == "__main__":
    main()
