from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent

with (BASE_DIR / "localities.yaml").open() as handle:
    localities = yaml.safe_load(handle)

lookup = {}
for locality in localities:
    lookup[locality["name"]] = {
        "latitude": locality["coordinates"]["wgs84"]["latitude"],
        "longitude": locality["coordinates"]["wgs84"]["longitude"],
    }

with (BASE_DIR / "locality_latitude_longitude.yaml").open("w") as handle:
    yaml.safe_dump(lookup, handle)
