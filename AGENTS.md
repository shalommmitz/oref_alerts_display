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
- `israel_map.py`: map rendering module
- `utils.py`: shared helpers
- `map_reference_usage.py`: reference integration loop with placeholder `fetch_coords()`
- `align_map`: interactive calibration helper for collecting control points on the outline image
- `convert_localities.py`: one-shot data conversion script
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
- poll the PIKUD-HAOREF JSON alert endpoint
- decode the response using `utf-8-sig` because the endpoint may include a UTF-8 BOM
- ignore empty or trivial responses and sleep for 10 seconds
- de-duplicate alerts by `id`
- save the last processed alert to `last_alert.yaml`
- map each alerted locality to coordinates
- choose a drawing color from alert category
- draw a circle marker for each matched locality
- pump the Tk event loop once per iteration with `map_view.update()`

Current alert category mapping in `show_alerts`:

- `cat == "1"` -> `red`
- `cat == "6"` -> `orange`
- `cat == "10"` -> `gray`

Current unknown-category behavior:

- print the alert
- exit immediately

### `israel_map.py`

`IsraelMap` is the main reusable component.

Key behaviors:

- opens a Tk window in `__init__`
- loads the Israel outline background image from disk
- optionally resizes and pads the image
- converts latitude/longitude into image coordinates using a calibrated transform
- draws markers on a `tk.Canvas`
- supports both blocking and non-blocking usage

Public methods:

- `draw(latitude, longitude, color, shape, size, refresh=None)`
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
- `tkinter`

Environment note from current scan:

- in the current shell, `tkinter` and `Pillow` import successfully
- `requests` and `yaml` do not import in the active Python environment

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
- `show_alerts` depends on the current working directory for local file discovery.
- Locality matching is based on exact match plus prefix heuristics; ambiguous or renamed localities may fail to resolve.
- Unknown alert categories are fatal.

## Recommended Verification After Changes

Run these at minimum after editing code:

```bash
python3 -m py_compile israel_map.py utils.py show_alerts map_reference_usage.py
```

If dependencies are available, also verify:

- `import israel_map`
- `import requests`
- `import yaml`
- `python3 align_map --help`
- `show_alerts` with `TEST = True`
- one manual visual check of known reference localities on the map

## Suggested Improvement Areas

These are not implemented yet, but they are natural future work:

- make file loading path-safe by resolving relative to the module directory
- refit the map transform from a larger, more geographically diverse control-point set
- add automated tests for coordinate validation and alert parsing
- package runtime dependencies in a reproducible environment file
- handle unknown alert categories without exiting
