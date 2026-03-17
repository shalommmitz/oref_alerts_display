# PIKUD-HAOREF Local Alert Display

Local display of PIKUD-HAOREF alerts and related status on a standalone map of Israel.

The goal of this project is fast local response and reduced dependence on third-party web sites. Alerts are fetched directly, resolved to local coordinates, and rendered on a local map window.

## What It Does

- Polls the PIKUD-HAOREF alert endpoint.
- Decodes BOM-prefixed JSON safely.
- Resolves alert localities to WGS84 latitude/longitude using a local YAML lookup table.
- Draws alerts on a local Israel outline image.
- Supports a non-blocking map API so callers can run their own loop.
- Includes sample alert payloads and a placeholder reference loop for custom integrations.

## Repository Layout

- `show_alerts`: main runtime script. Polls alerts, resolves localities, and draws them.
- `israel_map.py`: standalone map window and drawing module.
- `utils.py`: shared helpers, including UI-friendly sleep and locality coordinate loading.
- `map_reference_usage.py`: placeholder example for integrating a custom `fetch_coords()` loop.
- `align_map`: interactive helper for collecting true city positions on the outline image for calibration.
- `alert_example_1.yaml`, `alert_example_2.yaml`: sample alert payloads for local testing.
- `localities.yaml`: authoritative source locality dataset.
- `cities.json`: fallback locality dataset used to fill gaps not present in `localities.yaml`.
- `locality_latitude_longitude.yaml`: generated locality-to-coordinate lookup table used at runtime.
- `align_map_points.yaml`: generated calibration control points captured with `align_map`.
- `convert_localities.py`: regenerates `locality_latitude_longitude.yaml` from `localities.yaml`, backfilling missing names from `cities.json`.
- `israel_outline.png`: map background image used by `IsraelMap`.
- `requirements.txt`: pip-installable Python dependencies.

## Runtime Requirements

- Python 3.12 or compatible modern Python 3.
- `requests`
- `PyYAML`
- `Pillow`
- `tkinter`

Example install in a normal Python environment:

```bash
python3 -m pip install -r requirements.txt
```

Notes:

- `tkinter` is usually installed through the OS package manager, not `pip`.
- The map window needs a graphical display. In a headless container or server, you need an X server or equivalent display backend.

## Running The Alert Viewer

```bash
./show_alerts
```

What happens:

- The script polls `https://www.oref.org.il/warningMessages/alert/Alerts.json`.
- Empty or nearly-empty responses are treated as "no current alert" and retried after 10 seconds.
- New alerts are stored in `last_alert.yaml`.
- Each alerted locality is matched against the local coordinate table and drawn on the map.

Current alert color mapping:

- `cat == "1"` (missile attack) -> `red`
- `cat == "6"` (KATBAM attack)  -> `orange`
- `cat == "10"`(release)        -> `gray`

Unknown categories currently cause the script to exit.

## Testing With Sample Data

Inside `show_alerts`, set:

```python
TEST = True
```

The script will then load a local sample alert instead of polling the network.

Current sample file used by the script:

- `alert_example_2.yaml`

## Using The Map Module Directly

Basic blocking usage:

```python
from israel_map import IsraelMap

map_view = IsraelMap()
map_view.draw(32.0853, 34.7818, "red", "circle", 10)
map_view.run()
```

Non-blocking usage with your own loop:

```python
import time
from israel_map import IsraelMap

map_view = IsraelMap(auto_refresh=False)

while map_view.is_open():
    map_view.reset(refresh=False)
    map_view.draw(32.0853, 34.7818, "orange", "square", 10, refresh=False)
    map_view.update()
    time.sleep(0.05)
```

Supported draw parameters:

- Colors: `white`, `black`, `blue`, `red`, `green`, `gray`, `orange`, `background`
- Shapes: `circle`, `rect`, `square`
- Size: pixel diameter or width

## Placeholder Integration Example

`map_reference_usage.py` shows how to:

- call a placeholder `fetch_coords()`
- draw returned coordinates
- keep the map responsive while waiting
- run indefinitely until the window closes

## Map Calibration Helper

Use `align_map` to collect control points on the outline image:

```bash
python3 align_map
```

What it does:

- shows one city at a time and displays the current estimated position as a guide
- keeps the map at full scale and makes the helper vertically scrollable
- lets you left-click the true position, or press `Space` if the estimate is already correct
- lets you use `Backspace` to revise the previous city
- after the last city, lets you press `Enter` to save and quit or stay open to fix the last point
- writes the collected points to `align_map_points.yaml`

## Data Generation

If `localities.yaml` or `cities.json` changes, regenerate the runtime lookup table with:

```bash
python3 convert_localities.py
```

This produces:

```text
locality_latitude_longitude.yaml
```

The runtime code expects that generated file to exist in the project directory.

## Important Implementation Notes

- The background image is loaded from `israel_outline.png` by default.
- Coordinate placement uses a calibrated normalized lat/lon transform fitted against control points collected on the current outline asset. Do not assume the current mapping is a pure geographic projection.
- All shapes share the same coordinate transform.
- `localities.yaml` has priority over `cities.json` when generating the runtime locality lookup.
- The alert endpoint may return UTF-8 BOM-prefixed JSON. `show_alerts` handles this explicitly.

## License

MIT. See [LICENSE](LICENSE).
