# PIKUD-HAOREF Local Alert Display

Local display of PIKUD-HAOREF alerts and related status on a standalone map of Israel.

Current version: `1.00`

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
- `alert_fetcher.py`: background polling thread for the live alert endpoint.
- `watchdog.py`: thread-safe health monitor for UI heartbeat, fetch attempts, update age, and Online/Offline status.
- `alert_audio.py`: asynchronous audio playback for audible alert notifications.
- `alert_expiry.py`: time-based cleanup for alert markers that should disappear automatically.
- `alert_history.py`: history replay client for startup catch-up and outage recovery.
- `alert_model.py`: normalization helpers for live alerts and history rows.
- `alert_render.py`: alert persistence and drawing helpers.
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
- `create_venv`: recreates the local virtual environment and installs dependencies from `requirements.txt`.
- `israel_outline.png`: map background image used by `IsraelMap`.
- `requirements.txt`: pip-installable Python dependencies.

## Runtime Requirements

- Python 3.12 or compatible modern Python 3.
- `requests`
- `PyYAML`
- `Pillow`
- `pygame`
- `python-bidi`
- `tkinter`

Example install in a normal Python environment:

```bash
python3 -m pip install -r requirements.txt
```

Notes:

- `tkinter` is usually installed through the OS package manager, not `pip`.
- The map window needs a graphical display. In a headless container or server, you need an X server or equivalent display backend.
- Audible alerts use `pygame` to play `ocean_4s.mp3`. If mp3 playback is unavailable, the app logs the problem and falls back to the window-system bell instead of staying silent.

## Quick Start With `create_venv`

The repository includes a helper script that recreates a local virtual environment and installs the current dependencies:

```bash
./create_venv
. v
./show_alerts
```

What `create_venv` does:

- removes any existing `venv`
- creates a fresh `venv`
- writes a small helper file `v` containing `. venv/bin/activate`
- installs from `requirements.txt`

This is the recommended local setup flow for this repository.

## Running The Alert Viewer

```bash
./show_alerts
```

What happens:

- A background thread polls `https://www.oref.org.il/warningMessages/alert/Alerts.json`.
- The Tk thread stays responsive while waiting for network results.
- On the first successful contact, the script replays the previous five minutes of history from the history endpoint, in old-to-new order.
- After a network interruption, the script fetches history since the last successful live poll and replays any missed alerts.
- Live alerts and replayed alerts are normalized into the same runtime shape.
- Replay and expiry timing are anchored to `Asia/Jerusalem`, so they do not depend on the consuming machine's local timezone.
- New alerts are stored in `last_alert.yaml`.
- Each alerted locality is matched against the local coordinate table and drawn on the map.
- "Event ended" markers are automatically removed 10 minutes after their alert appearance time.
- Expired markers are cleared incrementally so large expiry batches do not monopolize the UI thread.
- The map window exposes a standard top menu inside the canvas: `File`, `Edit`, and `Help`.
- `File` includes `Save`, `Settings`, and `Exit`; `Edit` includes `Clear`; `Help` includes `Color Legend` and `About`.
- `Settings` stores both image-save preferences and alert-notification preferences in `settings.yaml`.
- If `Bring Window to Front` is enabled, non-startup alerts raise the map window above other windows.
- If `Play Audible Alert` is enabled, non-startup alerts play `ocean_4s.mp3`.
- Focus-jump and audible-alert notifications share a 10-second cooldown, so alert bursts do not repeatedly steal focus or replay sound.
- Clicking inside the map image opens a modal showing the nearest settlement name and coordinates, with `Close` and `Copy and Close` actions.
- The settlement-name field is selectable for name-only copy, and uses `python-bidi` for stronger Hebrew RTL rendering when available.
- A compact lower-left watchdog shows a pulsing alive icon and `Online` or `Offline`.

Current alert color mapping:

- `cat == "1"` (missile attack) -> `red`
- `cat == "2"` or `cat == "6"` (UAV / older matrix id 6) -> `purple`
- title `בדקות הקרובות צפויות להתקבל התרעות באזורך` -> `yellow`
- title `האירוע הסתיים` -> `gray`

Unknown categories currently cause the script to exit.

## Testing With Sample Data

Inside `show_alerts`, set:

```python
TEST = True
```

The script will then load a local sample alert instead of polling the network.

Current sample file used by the script:

- `last_alert.yaml`

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

- Colors: `white`, `black`, `blue`, `purple`, `red`, `green`, `gray`, `orange`, `background`
- Shapes: `circle`, `rect`, `square`
- Size: pixel diameter or width
- `draw()` now returns the canvas item id for the created marker, which can be passed to `remove_marker()`.

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
- When `show_controls=True`, `IsraelMap` creates an in-canvas menu strip that overlays the top of the image instead of increasing the window height.
- The Settings dialog includes `Image Save Options` and `Alert Notification`, and persists both sections to `settings.yaml`.
- In interactive mode, clicking the image resolves the nearest locality from `locality_latitude_longitude.yaml` using the current map projection.
- Startup history replay does not trigger focus-jump or audio notifications, but live alerts and recovery replay alerts do.
- Operator notifications use one shared 10-second cooldown across focus-jump and audio playback.
- `IsraelMap.remove_marker()` removes a specific marker without affecting later markers drawn at the same locality.
- `localities.yaml` has priority over `cities.json` when generating the runtime locality lookup.
- The alert endpoint may return UTF-8 BOM-prefixed JSON. `show_alerts` handles this explicitly.
- History replay rows are normalized to the same in-memory schema as live alerts before deduplication and drawing.
- The official history endpoint can return HTTP 200 with an empty body when there are no recent rows; the history client treats that as an empty replay list.
- As observed on March 20, 2026, the official history payload rows had only `alertDate`, `title`, `data`, and `category`, with `data` as a single locality string and yellow pre-alert rows using category `14`.
- As observed on March 20, 2026, the official `https://www.oref.org.il/alerts/alertCategories.json` metadata mapped category `2` to `uav`, category `13` to `update`, and category `14` to `flash`, all of which are relevant to current runtime payloads.
- OREF `alertDate` values are interpreted in `Asia/Jerusalem`; replay and expiry do not rely on the consuming machine's local timezone.
- Marker removal inside `IsraelMap` is O(1), and alert expiry is processed in bounded batches to reduce UI freeze risk.
- The watchdog uses monotonic time, not wall-clock time, so freeze detection is independent of timezone and clock jumps.
- The live and history endpoint URLs can be overridden with `OREF_ALERTS_URL` and `OREF_ALERTS_HISTORY_URL`.

## License

MIT. See [LICENSE](LICENSE).
