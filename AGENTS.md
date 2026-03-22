# AGENTS.md

## Purpose

This repository locally displays PIKUD-HAOREF alerts and related status on a map of Israel.

Primary goals:

- fast local response
- minimal dependence on third-party web sites
- simple, inspectable local data flow
- a standalone map module that can also be reused by other scripts

License for this project is MIT.

## Code Scan Summary

Current repo contents relevant to runtime behavior:

- `show_alerts`: main executable script
- `alert_fetcher.py`: background live-alert polling worker
- `watchdog.py`: thread-safe health monitor for UI heartbeat, fetch attempts, update age, and Online/Offline state
- `alert_audio.py`: asynchronous audible alert playback helper
- `alert_expiry.py`: time-based cleanup for auto-cleared markers
- `alert_history.py`: history replay client for startup and recovery
- `alert_model.py`: alert normalization helpers
- `alert_render.py`: alert drawing and persistence helpers
- `israel_map.py`: map rendering module
- `utils.py`: shared helpers
- `map_reference_usage.py`: reference integration loop with placeholder `fetch_coords()`
- `align_map`: interactive calibration helper for collecting control points on the outline image
- `convert_localities.py`: one-shot data conversion script
- `create_venv`: helper script that recreates `venv` and installs repo dependencies
- `localities.yaml`: large source dataset of Israeli localities
- `cities.json`: fallback locality dataset with broader coverage
- `locality_latitude_longitude.yaml`: generated runtime lookup table
- `align_map_points.yaml`: generated calibration control points collected with `align_map`
- `alert_example_1.yaml`, `alert_example_2.yaml`: sample alerts
- `last_alert.yaml`: generated runtime artifact containing the last processed alert
- `israel_outline.png`: background image asset used by the map

There are no automated tests in the repository at this time.

## Runtime Architecture

### `show_alerts`

Main loop responsibilities:

- create `IsraelMap(auto_refresh=False)`
- start a background live-alert fetcher thread
- decode the live response using `utf-8-sig` because the endpoint may include a UTF-8 BOM
- on first successful contact, replay the preceding five minutes of history in old-to-new order
- after a network interruption, replay history rows newer than the last successful live poll
- normalize live alerts and history rows into one shared runtime shape
- compute replay timing on the explicit `Asia/Jerusalem` timezone basis
- update the watchdog overlay with Online/Offline state and heartbeat information
- de-duplicate alerts before drawing
- save the last processed alert to `last_alert.yaml`
- map each alerted locality to coordinates
- choose a drawing color from alert category
- draw a circle marker for each matched locality
- optionally raise the window and play a sound for non-startup alerts, based on persisted settings
- automatically remove "האירוע הסתיים" markers 10 minutes after their appearance time
- pump the Tk event loop once per iteration with `map_view.update()`

Current alert category mapping in `show_alerts`:

- `cat == "1"` -> `red`
- `cat == "2"` or `cat == "6"` -> `purple`
- title `בדקות הקרובות צפויות להתקבל התרעות באזורך` -> `yellow`
- title `האירוע הסתיים` -> `gray`

Current unknown-category behavior:

- print the alert
- exit immediately

Configurable endpoints:

- live endpoint can be overridden with `OREF_ALERTS_URL`
- history endpoint can be overridden with `OREF_ALERTS_HISTORY_URL`

Current replay window:

- startup replay: 300 seconds
- recovery replay: from the last successful live poll forward

### `alert_fetcher.py`

This module owns the blocking live HTTP polling.

Key behaviors:

- runs `requests.get()` on a background thread
- records when each fetch attempt starts
- returns only the newest available result to the UI thread
- uses the same timeout policy as the main runtime
- keeps Tk responsive during network stalls

### `watchdog.py`

This module tracks liveness and progress for the operator-facing status overlay.

Key behaviors:

- uses monotonic time for all ages and thresholds
- tracks UI heartbeat from the main loop
- tracks fetch attempts from the worker thread
- tracks end-to-end update age from the main thread
- marks the UI state as `Online` or `Offline`
- treats fetch failures as `Offline`
- provides a stable reason code and reason text for state-transition logging

### `alert_history.py`

This module fetches and filters the history endpoint for replay.

Key behaviors:

- fetches history on demand with the shared timeout policy
- treats HTTP 200 with an empty response body as "no history rows"
- filters rows newer than a caller-provided cutoff time on the explicit `Asia/Jerusalem` timezone basis
- returns alerts in old-to-new order

### `alert_expiry.py`

This module tracks markers that should disappear automatically.

Key behaviors:

- tracks only the semantic "event ended" alert type
- expires those markers 10 minutes after alert appearance
- uses history timestamps when available so replayed rows expire on their original timeline
- computes expiry deadlines on the explicit `Asia/Jerusalem` timezone basis
- limits marker deletions per pass so large expiry batches do not block the UI thread for long stretches
- removes the exact drawn marker ids instead of painting over map locations

### `alert_model.py`

This module normalizes alert payloads from different sources.

Key behaviors:

- decodes BOM-prefixed response text
- normalizes live alerts into a shared `AlertEvent` shape
- normalizes history rows whose schema differs from live alerts
- parses history timestamps from several expected string formats
- converts OREF timestamps and replay cutoffs onto the explicit `Asia/Jerusalem` timezone basis

Observed history payload details from the official endpoint on March 20, 2026:

- rows carried `alertDate`, `title`, `data`, and `category`
- `data` was a single locality string, not a list
- current observed categories included `1`, `2`, `13`, and `14`

Observed category metadata from the official endpoint on March 20, 2026:

- `https://www.oref.org.il/alerts/alertCategories.json`
- category `2` -> `uav`
- category `13` -> `update`
- category `14` -> `flash`

### `alert_render.py`

This module handles drawing and alert artifact persistence.

Key behaviors:

- persists `last_alert.yaml`
- updates `biggest_alert.yaml`
- resolves localities to coordinates
- chooses marker color from normalized alert fields
- draws one marker per resolved locality

### `israel_map.py`

`IsraelMap` is the main reusable component.

Key behaviors:

- opens a Tk window in `__init__`
- loads the Israel outline background image from disk
- optionally resizes and pads the image
- converts latitude/longitude into image coordinates using a calibrated transform
- draws markers on a `tk.Canvas`
- creates an in-canvas `File/Edit/Help` menu strip when `show_controls=True`
- renders a compact lower-left watchdog overlay without increasing window height
- supports both blocking and non-blocking usage
- persists both image-save and alert-notification settings in `settings.yaml`
- resolves nearest-settlement lookups from clicks in interactive mode

Public methods:

- `draw(latitude, longitude, color, shape, size, refresh=None)`
- `remove_marker(item_id, refresh=None)`
- `reset(refresh=None)`
- `run()`
- `update()`
- `process_events()`
- `is_open()`
- `close()`

Supported colors:

- `white`
- `black`
- `blue`
- `purple`
- `red`
- `green`
- `gray`
- `orange`
- `background`

Supported shapes:

- `circle`
- `rect`
- `square`

Current geographic validation bounds:

- latitude: `29.45` to `33.281`
- longitude: `34.20` to `35.88`

Current transform details:

- shared by all shapes
- uses normalized latitude/longitude inputs
- is fitted from control points collected on the current `israel_outline.png` asset
- scales with image resize and respects the configured padding
- is not a GIS projection

These constants are implementation-critical. If calibration changes, update them in one place inside `_latlon_to_xy()`.

Marker bookkeeping details:

- active markers are stored by canvas item id
- `remove_marker()` is expected to stay O(1)
- image export iterates the remaining markers in insertion order
- watchdog overlay items are raised with the other canvas overlays
- the menu replaces the old canvas button strip and overlays the top of the image

Current menu structure when `show_controls=True`:

- `File` -> `Save`, `Settings`, `Exit`
- `Edit` -> `Clear`
- `Help` -> `Color Legend`, `About`

Current interactive click behavior:

- clicking inside the image opens a modal with the nearest settlement name and coordinates
- the modal provides `Close` and `Copy and Close`
- the settlement-name field is selectable for name-only copy and prefers `python-bidi` for Hebrew RTL display

Current Settings dialog sections:

- `Image Save Options`
- `Alert Notification`

Current persisted settings in `settings.yaml`:

- `include_datetime`
- `base_name`
- `scale_percent`
- `focus_on_alert`
- `audible_alert`

Current alert-notification behavior:

- `focus_on_alert` raises and focuses the map window for non-startup alerts
- `audible_alert` plays `ocean_4s.mp3` for non-startup alerts
- startup history replay does not trigger either notification
- focus-jump and audio playback share one 10-second cooldown window
- if mp3 playback is unavailable, the runtime falls back to the window-system bell

### `align_map`

This is an interactive calibration helper for `IsraelMap`.

It demonstrates:

- full-scale outline display with vertical scrolling
- city-by-city control point capture
- a visible estimated marker for the current city
- keyboard acceptance of the current estimate with `Space`
- undo of the previous point with `Backspace`
- explicit save-and-quit after the last city with `Enter`

Output file:

- `align_map_points.yaml`

### `utils.py`

Current helpers:

- `sleep_with_ui(map_view, seconds)`: sleep while keeping Tk responsive
- `to_heb_chars(s)`: currently returns the original string
- `get_coords()`: loads `locality_latitude_longitude.yaml`

Note:

- `get_coords()` resolves files relative to `utils.py`

### `map_reference_usage.py`

This is a reference integration script, not the main runtime path.

It demonstrates:

- non-blocking `IsraelMap` usage
- an endless loop
- a placeholder `fetch_coords()`
- waiting while still servicing Tk events

### `convert_localities.py`

This script converts `localities.yaml` into the runtime lookup table and then
backfills missing locality names from `cities.json`.

Source priority:

- entries from `localities.yaml` win
- entries from `cities.json` are used only when the Hebrew locality name does not already exist

Current output format:

- key: locality name in Hebrew
- value: `latitude`, `longitude`

Output file:

- `locality_latitude_longitude.yaml`

## Data Files

### `localities.yaml`

Source dataset used for coordinate generation.

Observed structure:

- list of localities
- each locality includes metadata and `coordinates.wgs84`

Note:

- authoritative, but not complete

### `cities.json`

Fallback dataset used to fill locality names missing from `localities.yaml`.

Observed structure:

- top-level object containing `cities`
- each city entry includes Hebrew name plus `lat` and `lng`

Note:

- broader coverage than `localities.yaml`, but treated as lower-priority fallback

### `locality_latitude_longitude.yaml`

Generated runtime lookup table used by `show_alerts`.

Observed structure:

- YAML mapping
- keys are Hebrew locality names
- values contain `latitude` and `longitude`

### `align_map_points.yaml`

Generated calibration file used as the source of map control points.

Observed structure:

- image metadata: `image`, `padding`, `width`, `height`
- `points` mapping keyed by Hebrew city name
- each point contains `latitude`, `longitude`, `x`, `y`

### Sample alert files

- `alert_example_1.yaml`
- `alert_example_2.yaml`
- `last_alert.yaml` is also used by `show_alerts` when `TEST = True`

Observed structure:

- `id`
- `cat`
- `title`
- `data` as a list of localities
- `desc`

## Dependencies

Code-level dependencies:

- `requests`
- `PyYAML`
- `Pillow`
- `pygame`
- `python-bidi`
- `tkinter`

Environment note from current scan:

- in the current shell, `tkinter` and `Pillow` import successfully
- `requests` and `yaml` do not import in the active Python environment
- `pygame` availability was not verified in the active Python environment

Implication:

- syntax checks can pass while runtime still fails if dependencies are missing
- when documenting or packaging this project, list `requests` and `PyYAML` explicitly

## File Naming

Canonical names in this repository:

- `cities.json`
- `align_map_points.yaml`
- `israel_outline.png`
- `locality_latitude_longitude.yaml`
- `alert_example_1.yaml`
- `alert_example_2.yaml`

## Editing Rules For Future Changes

- Keep all marker placement logic centralized in `IsraelMap._latlon_to_xy()`.
- Do not add shape-specific coordinate math unless there is a deliberate, repo-wide calibration decision.
- All shapes must use the same location rules.
- Preserve BOM-safe alert decoding in `show_alerts`.
- Keep the live-fetch thread separate from Tk work; do not move blocking HTTP calls back onto the UI thread.
- Reuse `utils.sleep_with_ui()` rather than adding new busy-wait loops.
- If alert categories change, update both the code and documentation together.
- If locality matching logic changes, keep `show_alerts` readable and deterministic.
- If the coordinate source changes, regenerate `locality_latitude_longitude.yaml` rather than hand-editing it.
- Preserve the non-blocking API on `IsraelMap`; external loops rely on it.
- Avoid introducing a hard dependency on `PIL.ImageTk`; the current implementation intentionally uses `tk.PhotoImage` data instead.

## Known Constraints

- The viewer requires a graphical display to actually show the Tk window.
- Headless environments need an X server or equivalent display backend.
- Coordinate placement is empirically calibrated to the current image asset, not geodetically accurate.
- The current transform is fitted from a small calibration sample; adding more interior control points should improve overall placement.
- History replay accuracy depends on the upstream history endpoint including usable timestamps.
- `show_alerts` depends on the current working directory for local file discovery.
- Locality matching is based on exact match plus prefix heuristics; ambiguous or renamed localities may fail to resolve.
- Unknown alert categories are fatal.
- The official history endpoint has been observed to return HTTP 200 with an empty body when there are no recent alerts.
- Only the semantic "האירוע הסתיים" alert type auto-clears after 10 minutes; other markers remain until manually cleared.
- Replay timing correctness depends on interpreting OREF timestamps in `Asia/Jerusalem`, not in the consuming machine's local timezone.
- Large batches of expired markers should be processed incrementally; avoid reintroducing unbounded O(n^2) marker removal on the Tk thread.
- The watchdog reports Online/Offline state, treats fetch failure as Offline, and logs state transitions with reasons.

## Recommended Verification After Changes

Run these at minimum after editing code:

```bash
python3 -m py_compile alert_fetcher.py alert_history.py alert_model.py alert_render.py israel_map.py utils.py show_alerts map_reference_usage.py
```

If dependencies are available, also verify:

- `import israel_map`
- `import requests`
- `import yaml`
- `python3 align_map --help`
- `show_alerts` with `TEST = True`
- one startup run that replays the previous five minutes of history
- one manual network interruption and recovery check
- one manual visual check of known reference localities on the map

## Suggested Improvement Areas

These are not implemented yet, but they are natural future work:

- make file loading path-safe by resolving relative to the module directory
- refit the map transform from a larger, more geographically diverse control-point set
- add automated tests for coordinate validation and alert parsing
- package runtime dependencies in a reproducible environment file
- handle unknown alert categories without exiting
