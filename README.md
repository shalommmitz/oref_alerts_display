# PIKUD-HAOREF Local Alert Display

Local display of PIKUD-HAOREF alerts and related status on a standalone map of Israel.

Current version: `1.1`

The goal of this project is fast local response and reduced dependence on third-party web sites. Alerts are fetched directly, resolved to local coordinates, and rendered on a local map window.

## What It Does

- Polls the PIKUD-HAOREF alert endpoint.
- Decodes BOM-prefixed JSON safely.
- Resolves alert localities to WGS84 latitude/longitude using a local YAML lookup table.
- Draws alerts on a local Israel outline image.
- Optionally auto-zooms to a `2x` localized half-map view when all current zoom-participating alerts fit in one region.
- Supports a non-blocking map API so callers can run their own loop.
- Includes sample alert payloads and a placeholder reference loop for custom integrations.

## Repository Layout

- `show_alerts`: main runtime script. Polls alerts, resolves localities, and draws them.
- `alert_fetcher.py`: background polling thread for the live alert endpoint.
- `watchdog.py`: thread-safe health monitor for UI heartbeat, fetch attempts, update age, and Online/Offline status.
- `alert_audio.py`: asynchronous audio playback for audible alert notifications.
- `alert_blink.py`: short attention-window blinking for newly drawn alert markers.
- `alert_focus_circle.py`: temporary focus-circle overlays for small incoming alerts.
- `alert_expiry.py`: time-based cleanup for alert markers that should disappear automatically.
- `alert_history.py`: history replay client for startup catch-up and outage recovery.
- `alert_model.py`: normalization helpers for live alerts and history rows.
- `alert_types.py`: YAML-backed alert-type classification and policy loader.
- `alert_render.py`: alert persistence and drawing helpers.
- `israel_map.py`: standalone map window and drawing module.
- `utils.py`: shared helpers, including UI-friendly sleep and locality coordinate loading.
- `map_reference_usage.py`: placeholder example for integrating a custom `fetch_coords()` loop.
- `align_map`: interactive helper for collecting true city positions on the outline image for calibration.
- `alert_example_1.yaml`, `alert_example_2.yaml`: sample alert payloads for local testing.
- `demo.yaml`: scripted alert sequence used by `Help -> Demo`.
- `alert_categories.yaml`: single source of truth for alert titles, colors, shapes, legend text, zoom policy, and auto-clear policy.
- `reference_alert_categories.yaml`: local cache of the official OREF alert-category metadata, kept only as a human reference when updating `alert_categories.yaml`.
- `localities.yaml`: authoritative source locality dataset.
- `cities.json`: fallback locality dataset used to fill gaps not present in `localities.yaml`.
- `locality_latitude_longitude.yaml`: generated locality-to-coordinate lookup table used at runtime.
- `align_map_points.yaml`: generated calibration control points captured with `align_map`.
- `convert_localities.py`: regenerates `locality_latitude_longitude.yaml` from `localities.yaml`, backfilling missing names from `cities.json`.
- `create_venv`: recreates the local virtual environment and installs dependencies from `requirements.txt`.
- `israel_outline.png`: map background image used by `IsraelMap`.
- `requirements.txt`: pip-installable Python dependencies.

## Runtime Requirements

- Python 3.8 or newer.
- `requests`
- `PyYAML`
- `Pillow`
- `pygame`
- `python-bidi`
- `tzdata`
- `backports.zoneinfo` on Python 3.8
- `tkinter`

Example install in a normal Python environment:

```bash
python3 -m pip install -r requirements.txt
```

Notes:

- `tkinter` is usually installed through the OS package manager, not `pip`.
- On Debian/Ubuntu, install it with `sudo apt install python3-tk`.
- On Fedora, install it with `sudo dnf install python3-tkinter`.
- On Arch, install it with `sudo pacman -S tk`.
- The map window needs a graphical display. In a headless container or server, you need an X server or equivalent display backend.
- Audible alerts use `pygame` to play `ocean_4s.mp3`. If mp3 playback is unavailable, the app logs the problem and falls back to the window-system bell instead of staying silent.
- `tzdata` is included so `ZoneInfo("Asia/Jerusalem")` works even on machines without system timezone data.
- On Python 3.8, `backports.zoneinfo` is installed automatically so the same timezone logic works on Ubuntu 20.04's default Python.

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
- verifies that the interpreter is Python 3.8 or newer
- verifies that the required Python modules import successfully
- stops with a clear message if `tkinter` is missing from the OS installation

This is the recommended local setup flow for this repository.

## Running The Alert Viewer

```bash
./show_alerts
```

What happens:

- A background thread polls `https://www.oref.org.il/warningMessages/alert/Alerts.json`.
- The Tk thread stays responsive while waiting for network results.
- On the first successful contact, the script replays the configured startup history window from the history endpoint, in old-to-new order.
- After a network interruption, the script fetches history since the last successful live poll and replays any missed alerts.
- Live alerts and replayed alerts are normalized into the same runtime shape.
- Replay and expiry timing are anchored to `Asia/Jerusalem`, so they do not depend on the consuming machine's local timezone.
- New alerts are stored in `last_alert.yaml`.
- Each alerted locality is matched against the local coordinate table and drawn on the map.
- Alert classification, colors, auto-clear behavior, and localized-zoom participation come from `alert_categories.yaml`.
- Marker shape also comes from `alert_categories.yaml`; the current known alert titles use `circle`, and the `unknown_title` fallback uses `triangle`.
- Newly drawn alerts blink for their configured attention duration with a 1-second on / 1-second off cadence, except for history alerts loaded at startup.
- If a repeated alert keeps a locality in the same alert state, that locality does not restart blinking; only newly added or state-changed localities blink.
- If a new non-startup alert has 6 or fewer localities and `Show Focus Circle for Small Alerts` is enabled, the app draws a pale-blue focus circle around that alert cluster for the same configured attention duration.
- Same-state repeat alerts do not raise the window or draw a new focus circle unless at least one mapped locality actually changed alert state.
- Alert categories that declare auto-clear behavior in `alert_categories.yaml` are automatically removed after their configured duration.
- The lower-right corner shows the original Hebrew title of the most recent alert.
- If the most recent alert is an auto-clearing release/end alert, that lower-right title is removed when the last marker from that alert disappears.
- Expired markers are cleared incrementally so large expiry batches do not monopolize the UI thread.
- The map window exposes a standard top menu inside the canvas: `File`, `Edit`, `Send to Back`, and `Help`.
- `File` includes `Save`, `Settings`, and `Exit`; `Edit` includes `Clear`; `Send to Back` lowers the map window and, on Linux/X11, tries to restore the previously fullscreen window; `Help` includes `Usage`, `Demo`, `Color Legend`, and `About`.
- Selecting a leaf menu action writes `Menu action: ...` to the log, and startup writes `Application launched`.
- `Edit -> Clear` resets both the visible map and the in-memory alert state, so the next live poll can redraw current alerts and reapply localized zoom if needed.
- `Settings` stores image-save, alert-notification, and map-display preferences in `settings.yaml`.
- `Settings` also stores the startup history replay window in minutes; the default is 3 minutes.
- `Blink / Focus Duration` controls both the marker-blink duration and the small-alert focus-circle duration; the default is 6 seconds.
- Clicking the map also uses that same attention duration for a transient green blink at the true mapped locality point.
- If `Bring Window to Front` is enabled, non-startup alerts raise the map window above other windows only when at least one locality changes state on the map.
- If `Play Audible Alert` is enabled, non-startup alerts play `ocean_4s.mp3` only when at least one locality changes state on the map.
- `Blink New Alerts on Appearing` is enabled by default and can be turned off in Settings.
- If `Auto Zoom x2 for Localized Alerts` is enabled, the app precomputes three zoomed half-map views at launch and switches to one of them only when newly arrived zoom-participating alerts all fit in the same region.
- Alert types whose YAML entry opts out of localized zoom do not trigger zoom reassessment, and their later auto-clear removal does not trigger it either.
- `Help -> Demo` pauses live polling, changes the status label to `Demo`, plays the alerts from `demo.yaml` one by one with 18 seconds between them, then clears the map, resumes normal operation, and leaves `Demo done` in the lower-right corner until the next real alert replaces it.
- Clicking inside the map shows the nearest settlement in the upper-left corner and starts a green blink on that locality's exact mapped point; a new click replaces the text but does not cancel older click-highlights that are still blinking.
- Focus-jump and audible-alert notifications share a 10-second cooldown, so alert bursts do not repeatedly steal focus or replay sound.
- Clicking inside the map image shows the nearest settlement name and coordinates in a compact upper-left overlay.
- That overlay auto-hides after one minute, and a new click replaces the displayed locality and restarts the timer.
- The coordinates field is selectable for copy, and the `Copy` button copies the coordinates directly.
- A compact lower-left watchdog shows a pulsing alive icon and `Online` or `Offline`.

Alert-type matching is fully driven by `alert_categories.yaml`.

- The top-level YAML structure is a dictionary keyed by the alert `title` values that arrive in the runtime payloads.
- Adding a new alert type normally means adding a new top-level title entry.
- `known_cats` is reference metadata only; the runtime classification key is the alert title.
- `unknown_title` is a special fallback entry used when an alert title is not otherwise listed.

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

- Colors: `white`, `black`, `blue`, `purple`, `red`, `green`, `gray`, `orange`, `background`, or a literal `#RRGGBB`
- Shapes: `circle`, `rect`, `square`, `triangle`
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
- The Settings dialog includes `Alert Notification`, `Map Display`, `History Replay`, and `Image Save Options`, and persists all four sections to `settings.yaml`.
- The alert-notification, map-display, and replay settings persisted in `settings.yaml` now include `focus_on_alert`, `audible_alert`, `blink_on_appearing`, `attention_duration_seconds`, `small_alert_focus_circle`, and `startup_history_minutes`.
- In interactive mode, clicking the image resolves the nearest locality from `locality_latitude_longitude.yaml` using the current map projection and shows it in a timed upper-left overlay.
- Startup history replay does not trigger focus-jump or audio notifications, but live alerts and recovery replay alerts do.
- Operator notifications use one shared 10-second cooldown across focus-jump and audio playback.
- `IsraelMap.remove_marker()` removes a specific marker without affecting later markers drawn at the same locality.
- Manual map clear resets the alert-loop dedup state too, so a still-active live alert can repopulate the map on the next poll.
- `IsraelMap` precomputes full, top-half `2x`, middle-half `2x`, and bottom-half `2x` background views in memory at launch instead of writing derived images into the repository.
- Marker blinking and small-alert focus circles are driven from the main Tk loop, not separate threads, so all transient canvas changes stay on the canvas-owning thread.
- `localities.yaml` has priority over `cities.json` when generating the runtime locality lookup.
- The alert endpoint may return UTF-8 BOM-prefixed JSON. `show_alerts` handles this explicitly.
- History replay rows are normalized to the same in-memory schema as live alerts before deduplication and drawing.
- The official history endpoint can return HTTP 200 with an empty body when there are no recent rows; the history client treats that as an empty replay list.
- As observed on March 20, 2026, the official history payload rows had only `alertDate`, `title`, `data`, and `category`, with `data` as a single locality string and yellow pre-alert rows using category `14`.
- As observed on March 20, 2026, the official `https://www.oref.org.il/alerts/alertCategories.json` metadata mapped category `2` to `uav`, category `13` to `update`, and category `14` to `flash`, all of which are relevant to current runtime payloads.
- The ground-truth category reference comes from `https://www.oref.org.il/alerts/alertCategories.json` and is cached locally in `reference_alert_categories.yaml`.
- `reference_alert_categories.yaml` is not used by the runtime code; it exists only to help manually verify and update the authoritative runtime file, `alert_categories.yaml`.
- In `reference_alert_categories.yaml`, the most relevant fields are `category`, which is the English description, and `matrix_id`, which corresponds to this project's alert `cat` value.
- OREF `alertDate` values are interpreted in `Asia/Jerusalem`; replay and expiry do not rely on the consuming machine's local timezone.
- Marker removal inside `IsraelMap` is O(1), and alert expiry is processed in bounded batches to reduce UI freeze risk.
- The watchdog uses monotonic time, not wall-clock time, so freeze detection is independent of timezone and clock jumps.
- The live and history endpoint URLs can be overridden with `OREF_ALERTS_URL` and `OREF_ALERTS_HISTORY_URL`.

## License

MIT. See [LICENSE](LICENSE).
