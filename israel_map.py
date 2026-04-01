"""Standalone module for drawing markers on an outline map of Israel."""

from __future__ import annotations

import base64
import ast
import io
import json
import tkinter as tk
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Callable

from PIL import Image, ImageDraw

try:
    from bidi.algorithm import get_display as _get_bidi_display
except Exception:
    _get_bidi_display = None


APP_VERSION = "1.1"


@dataclass(frozen=True)
class _MapBounds:
    min_lat: float = 29.45
    max_lat: float = 33.281
    min_lon: float = 34.20
    max_lon: float = 35.88


@dataclass(frozen=True)
class _DrawCommand:
    latitude: float
    longitude: float
    color: str
    shape: str
    size: int


@dataclass(frozen=True)
class _FocusCircleCommand:
    points: tuple[tuple[float, float], ...]
    outline_color: str
    width: int
    padding: float
    min_radius: float


@dataclass(frozen=True)
class _LocalityPoint:
    name: str
    latitude: float
    longitude: float
    x: float
    y: float


@dataclass
class _ClickHighlightState:
    locality_name: str
    latitude: float
    longitude: float
    color: str
    shape: str
    size: int
    started_at: float
    visible: bool


@dataclass(frozen=True)
class _MapViewSpec:
    key: str
    crop_left: float
    crop_top: float
    crop_right: float
    crop_bottom: float
    scale: float
    image: Image.Image


class IsraelMap:
    """Display a background outline image of Israel and draw markers by lat/lon."""

    _ALLOWED_COLORS = {
        "white",
        "black",
        "blue",
        "purple",
        "red",
        "green",
        "yellow",
        "gray",
        "orange",
        "background",
    }
    _ALLOWED_SHAPES = {"circle", "rect", "square"}
    _COLOR_MAP = {
        "white": "#ffffff",
        "black": "#000000",
        "blue": "#0057d9",
        "purple": "#7b4bc4",
        "red": "#d81e1e",
        "green": "#1f8b4c",
        "yellow": "#d9b11f",
        "gray": "#d3d3d3",
        "orange": "#ff9f1c",
    }
    _IMAGE_CANDIDATES = (
        "israel_outline.png",
    )
    _CONTROL_COLORS = {
        "panel_bg": "#d8dbde",
        "panel_border": "#a7adb2",
        "button_bg": "#eceeef",
        "button_fg": "#394047",
        "button_active_bg": "#f6f7f8",
        "button_active_fg": "#20262c",
        "button_disabled_bg": "#c9cdd0",
        "button_disabled_fg": "#7b8288",
        "tooltip_bg": "#454b51",
        "tooltip_fg": "#f5f6f7",
        "tooltip_border": "#5a6168",
    }
    _WATCHDOG_COLORS = {
        "online": {
            "panel_bg": "#f0f3f2",
            "panel_border": "#b8c1bc",
            "text": "#31463a",
            "icon_on": "#5d9b76",
            "icon_off": "#79ab8d",
        },
        "offline": {
            "panel_bg": "#f4efef",
            "panel_border": "#c8b7b7",
            "text": "#6d3030",
            "icon_on": "#bf6f6f",
            "icon_off": "#cc8b8b",
        },
    }
    _SETTINGS_FILENAME = "settings.yaml"
    _DEFAULT_SAVE_INCLUDE_DATETIME = True
    _DEFAULT_SAVE_BASE_NAME = "alerts_map"
    _DEFAULT_SAVE_SCALE = "100"
    _DEFAULT_FOCUS_ON_ALERT = False
    _DEFAULT_AUDIBLE_ALERT = False
    _DEFAULT_BLINK_ON_APPEARING = True
    _DEFAULT_ATTENTION_DURATION_SECONDS = "6"
    _DEFAULT_LOCALIZED_AUTO_ZOOM = False
    _DEFAULT_SMALL_ALERT_FOCUS_CIRCLE = True
    _DEFAULT_STARTUP_HISTORY_MINUTES = "3"
    _CLICK_HIGHLIGHT_COLOR = "green"
    _CLICK_HIGHLIGHT_SHAPE = "circle"
    _CLICK_HIGHLIGHT_SIZE = 8
    _CLICK_HIGHLIGHT_TICK_MS = 250
    _LOCALITY_INFO_HIDE_MS = 60_000
    _LOCALITY_INFO_EDGE_MARGIN = 8
    _LOCALITY_INFO_COPY_BUTTON_WIDTH = 5
    _STATUS_EDGE_MARGIN = 8
    _STATUS_STACK_GAP = 6
    _STATUS_PANEL_Y_OFFSET = 14
    _LOG_TEXT_Y_OFFSET = 6
    _STATUS_AND_BUTTON_FONT = ("TkDefaultFont", 11, "bold")
    _LEGEND_ITEMS = (
        ("red", "Missile / Rocket Attack", "Immediate alert for an active incoming attack."),
        ("purple", "UAV Intrusion", "Hostile aircraft or drone intrusion alert."),
        ("yellow", "Area Pre-Alert", "Alerts are expected in the area in the next few minutes."),
        ("gray", "Event Ended", "The local alert event has ended and the marker will clear later."),
    )

    def __init__(
        self,
        width: int | None = None,
        height: int | None = None,
        title: str = "Home Front Command Alerts",
        image_path: str | Path | None = None,
        auto_refresh: bool = True,
        padding: int = 20,
        show_controls: bool = False,
    ) -> None:
        self.title = title
        self.auto_refresh = auto_refresh
        self.padding = max(0, padding)
        self.bounds = _MapBounds()
        self._closed = False
        self._reset_generation = 0
        self._drawn_markers: dict[int, _DrawCommand] = {}
        self._focus_circle_items: dict[int, _FocusCircleCommand] = {}
        self._click_highlight_items: dict[int, _ClickHighlightState] = {}
        self._hidden_marker_ids: set[int] = set()
        self._background_image_id: int | None = None
        self._menu_frame: tk.Frame | None = None
        self._menu_window_id: int | None = None
        self._modal_dialog: tk.Toplevel | None = None
        self._modal_kind: str | None = None
        self._nearest_locality_text: str | None = None
        self._nearest_locality_overlay_window_id: int | None = None
        self._nearest_locality_overlay_frame: tk.Frame | None = None
        self._nearest_locality_overlay_name_var: tk.StringVar | None = None
        self._nearest_locality_overlay_coords_var: tk.StringVar | None = None
        self._nearest_locality_overlay_value_entry: tk.Entry | None = None
        self._nearest_locality_overlay_hide_after_id: str | None = None
        self._click_highlight_after_id: str | None = None
        self._locality_points: list[_LocalityPoint] | None = None
        self._settings_dialog_snapshot: tuple[bool, str, str, bool, bool, bool, str, bool, bool, str] | None = None
        self._log_time_background_id: int | None = None
        self._log_time_text_id: int | None = None
        self._watchdog_background_id: int | None = None
        self._watchdog_icon_id: int | None = None
        self._watchdog_text_id: int | None = None
        self._watchdog_level = "offline"
        self._watchdog_pulse_on = False
        self._save_include_datetime_var: tk.BooleanVar | None = None
        self._save_base_name_var: tk.StringVar | None = None
        self._save_scale_var: tk.StringVar | None = None
        self._focus_on_alert_var: tk.BooleanVar | None = None
        self._audible_alert_var: tk.BooleanVar | None = None
        self._blink_on_appearing_var: tk.BooleanVar | None = None
        self._attention_duration_seconds_var: tk.StringVar | None = None
        self._localized_auto_zoom_var: tk.BooleanVar | None = None
        self._small_alert_focus_circle_var: tk.BooleanVar | None = None
        self._startup_history_minutes_var: tk.StringVar | None = None

        resolved_image_path = self._resolve_background_path(image_path)
        self._base_content_image = Image.open(resolved_image_path).convert("RGB")
        if width is not None or height is not None:
            target_width = width if width is not None else self._base_content_image.width
            target_height = height if height is not None else self._base_content_image.height
            self._base_content_image = self._base_content_image.resize(
                (target_width, target_height),
                Image.Resampling.LANCZOS,
            )
        self._content_width = self._base_content_image.width
        self._content_height = self._base_content_image.height
        self._view_specs = self._build_view_specs(self._base_content_image)
        self._current_view_key = "full"
        self._background_image = self._view_specs[self._current_view_key].image

        self.width = self._background_image.width
        self.height = self._background_image.height
        self.background_color = self._rgb_to_hex(self._background_image.getpixel((0, 0)))

        self.root = tk.Tk()
        self.root.title(self.title)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._save_include_datetime_var = tk.BooleanVar(master=self.root, value=True)
        self._save_base_name_var = tk.StringVar(master=self.root, value="alerts_map")
        self._save_scale_var = tk.StringVar(master=self.root, value="100")
        self._focus_on_alert_var = tk.BooleanVar(master=self.root, value=False)
        self._audible_alert_var = tk.BooleanVar(master=self.root, value=False)
        self._blink_on_appearing_var = tk.BooleanVar(master=self.root, value=True)
        self._attention_duration_seconds_var = tk.StringVar(master=self.root, value=self._DEFAULT_ATTENTION_DURATION_SECONDS)
        self._localized_auto_zoom_var = tk.BooleanVar(master=self.root, value=False)
        self._small_alert_focus_circle_var = tk.BooleanVar(master=self.root, value=True)
        self._startup_history_minutes_var = tk.StringVar(master=self.root, value=self._DEFAULT_STARTUP_HISTORY_MINUTES)
        self._nearest_locality_overlay_name_var = tk.StringVar(master=self.root, value="")
        self._nearest_locality_overlay_coords_var = tk.StringVar(master=self.root, value="")
        self._load_save_settings()
        self.canvas = tk.Canvas(
            self.root,
            width=self.width,
            height=self.height,
            bg=self.background_color,
            highlightthickness=0,
        )
        self.canvas.pack()

        self._background_photo = self._create_photo_image(self._background_image)
        self._background_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self._background_photo)
        if show_controls:
            self._create_menu_bar()
            self._enable_canvas_lookup()
        if self.auto_refresh:
            self.process_events()

    def draw(
        self,
        latitude: float,
        longitude: float,
        color: str,
        shape: str,
        size: int,
        refresh: bool | None = None,
    ) -> int:
        """Draw a marker on the map by geographic coordinate."""
        self._validate_draw_params(latitude, longitude, color, shape, size)

        draw_color = self._resolve_draw_color(color)
        item_id = self._create_marker_item(shape, draw_color)

        self._drawn_markers[item_id] = _DrawCommand(latitude, longitude, color, shape, size)
        self._position_marker_item(item_id, self._drawn_markers[item_id])
        self._raise_overlays()
        if refresh is None:
            refresh = self.auto_refresh
        if refresh:
            self.process_events()
        return item_id

    def draw_focus_circle(
        self,
        points: list[tuple[float, float]],
        *,
        outline_color: str,
        width: int,
        padding: float,
        min_radius: float,
        refresh: bool | None = None,
    ) -> int:
        # 1. Use a dedicated canvas item instead of painting into the bitmap so
        #    removing the circle restores the exact underlying image and markers.
        # 2. Store the source point set so zoom changes can reposition the same
        #    transient circle without needing to recreate it.
        if not points:
            raise ValueError("Focus circle needs at least one point")
        item_id = self.canvas.create_oval(
            0,
            0,
            0,
            0,
            outline=outline_color,
            width=width,
            fill="",
        )
        self._focus_circle_items[item_id] = _FocusCircleCommand(
            points=tuple((float(latitude), float(longitude)) for latitude, longitude in points),
            outline_color=str(outline_color),
            width=max(1, int(width)),
            padding=max(0.0, float(padding)),
            min_radius=max(1.0, float(min_radius)),
        )
        self._position_focus_circle_item(item_id, self._focus_circle_items[item_id])
        if self._background_image_id is not None:
            self.canvas.tag_raise(item_id, self._background_image_id)
        self._raise_overlays()
        if refresh is None:
            refresh = self.auto_refresh
        if refresh:
            self.process_events()
        return item_id

    def remove_marker(self, item_id: int, refresh: bool | None = None) -> bool:
        """Remove one previously drawn marker by canvas item id."""
        # 1. Ignore unknown ids so callers can safely expire markers that were
        #    already removed by a manual map clear or window shutdown.
        # 2. Keep marker removal O(1) so expiring many markers does not turn into
        #    repeated linear scans on the Tk thread.
        if item_id not in self._drawn_markers:
            return False

        self._drawn_markers.pop(item_id, None)
        self._hidden_marker_ids.discard(item_id)
        self.canvas.delete(item_id)
        if refresh is None:
            refresh = self.auto_refresh
        if refresh:
            self.process_events()
        return True

    def remove_focus_circle(self, item_id: int, refresh: bool | None = None) -> bool:
        # 1. Keep transient focus-circle removal separate from marker removal so
        #    marker bookkeeping stays simple and type-specific.
        # 2. Deleting the canvas item is enough to restore the underlying map
        #    pixels because the circle is a separate non-destructive overlay.
        if item_id not in self._focus_circle_items:
            return False

        self._focus_circle_items.pop(item_id, None)
        self.canvas.delete(item_id)
        if refresh is None:
            refresh = self.auto_refresh
        if refresh:
            self.process_events()
        return True

    def has_marker(self, item_id: int) -> bool:
        # 1. Expose marker existence checks so higher-level helpers can detect
        #    when their locality bookkeeping has gone stale after expiry or reset.
        # 2. This keeps the authoritative marker lifetime inside IsraelMap
        #    instead of duplicating canvas-state guesses elsewhere.
        return item_id in self._drawn_markers

    def set_marker_visible(self, item_id: int, visible: bool, refresh: bool | None = None) -> bool:
        # 1. Keep marker visibility changes centralized so blinking, saving, and
        #    future marker-state features share one authoritative path.
        # 2. Track hidden ids explicitly because the export path needs to know
        #    whether a marker is currently visible on screen.
        if item_id not in self._drawn_markers:
            return False

        if visible:
            self._hidden_marker_ids.discard(item_id)
        else:
            self._hidden_marker_ids.add(item_id)
        self.canvas.itemconfigure(item_id, state="normal" if visible else "hidden")
        if refresh is None:
            refresh = self.auto_refresh
        if refresh:
            self.process_events()
        return True

    def _start_click_highlight(self, locality: _LocalityPoint) -> None:
        # 1. Replace any older highlight for the same locality so clicking the
        #    same place again cleanly restarts that locality's attention timer.
        # 2. Keep highlights independent per locality so clicking a second
        #    place while the first is still blinking leaves both active.
        self._remove_click_highlights_for_locality(locality.name)
        item_id = self._create_marker_item(
            self._CLICK_HIGHLIGHT_SHAPE,
            self._resolve_draw_color(self._CLICK_HIGHLIGHT_COLOR),
        )
        highlight = _ClickHighlightState(
            locality_name=locality.name,
            latitude=locality.latitude,
            longitude=locality.longitude,
            color=self._CLICK_HIGHLIGHT_COLOR,
            shape=self._CLICK_HIGHLIGHT_SHAPE,
            size=self._CLICK_HIGHLIGHT_SIZE,
            started_at=monotonic(),
            visible=True,
        )
        self._click_highlight_items[item_id] = highlight
        self._position_click_highlight_item(item_id, highlight)
        self.canvas.itemconfigure(item_id, state="normal")
        self._raise_overlays()
        self._ensure_click_highlight_timer()

    def _remove_click_highlights_for_locality(self, locality_name: str) -> None:
        highlight_ids = [
            item_id
            for item_id, highlight in self._click_highlight_items.items()
            if highlight.locality_name == locality_name
        ]
        for item_id in highlight_ids:
            self._remove_click_highlight(item_id)

    def _remove_click_highlight(self, item_id: int) -> bool:
        if item_id not in self._click_highlight_items:
            return False
        self._click_highlight_items.pop(item_id, None)
        self.canvas.delete(item_id)
        return True

    def _ensure_click_highlight_timer(self) -> None:
        if self._click_highlight_after_id is not None or self._closed or not self.root.winfo_exists():
            return
        try:
            self._click_highlight_after_id = self.root.after(
                self._CLICK_HIGHLIGHT_TICK_MS,
                self._update_click_highlights,
            )
        except tk.TclError:
            self._click_highlight_after_id = None

    def _cancel_click_highlight_timer(self) -> None:
        if self._click_highlight_after_id is None:
            return
        try:
            self.root.after_cancel(self._click_highlight_after_id)
        except tk.TclError:
            pass
        self._click_highlight_after_id = None

    def _update_click_highlights(self) -> None:
        # 1. Keep this fully asynchronous on Tk's timer queue so click-driven
        #    locality highlighting works even while the rest of the app is idle.
        # 2. Removing the transient green overlay restores the exact prior view
        #    because the underlying alert marker, if any, was never modified.
        self._click_highlight_after_id = None
        if self._closed or not self.root.winfo_exists():
            return

        attention_duration_seconds = self.attention_duration_seconds()
        anchor = monotonic()
        finished_ids: list[int] = []
        for item_id, highlight in list(self._click_highlight_items.items()):
            elapsed = anchor - highlight.started_at
            if elapsed >= attention_duration_seconds:
                finished_ids.append(item_id)
                continue

            visible = int(elapsed) % 2 == 0
            if visible == highlight.visible:
                continue
            highlight.visible = visible
            self.canvas.itemconfigure(item_id, state="normal" if visible else "hidden")

        for item_id in finished_ids:
            self._remove_click_highlight(item_id)

        if self._click_highlight_items:
            self._ensure_click_highlight_timer()

    def reset(self, refresh: bool | None = None) -> None:
        """Restore the canvas to the original image-only state."""
        for item_id in tuple(self._drawn_markers):
            self.canvas.delete(item_id)
        for item_id in tuple(self._focus_circle_items):
            self.canvas.delete(item_id)
        for item_id in tuple(self._click_highlight_items):
            self.canvas.delete(item_id)
        self._drawn_markers.clear()
        self._focus_circle_items.clear()
        self._click_highlight_items.clear()
        self._hidden_marker_ids.clear()
        self._cancel_click_highlight_timer()
        self._reset_generation += 1
        self._locality_points = None
        self._apply_view("full")
        if refresh is None:
            refresh = self.auto_refresh
        if refresh:
            self.process_events()

    def run(self) -> None:
        """Start the Tk event loop."""
        self.root.mainloop()

    def process_events(self) -> bool:
        """Process pending Tk events once without blocking."""
        if not self.is_open():
            return False

        try:
            self.root.update_idletasks()
            self.root.update()
        except tk.TclError:
            self._closed = True
            return False
        return True

    def update(self) -> bool:
        """Process pending events once; convenient for external loops."""
        return self.process_events()

    def is_open(self) -> bool:
        """Return whether the map window still exists."""
        return (not self._closed) and bool(self.root.winfo_exists())

    def close(self) -> None:
        """Close the window."""
        if self._closed:
            return

        self._closed = True
        if self._modal_dialog is not None and self._modal_dialog.winfo_exists():
            self._close_modal_dialog()
        if not self.root.winfo_exists():
            return

        try:
            self.root.withdraw()
            self._cancel_nearest_locality_overlay_timer()
            self._cancel_click_highlight_timer()
            self.root.after_idle(self._finalize_close)
        except tk.TclError:
            self._finalize_close()

    def present_window(self, *, trigger_description: str) -> None:
        # 1. Try the standard "raise and focus" sequence first because it works
        #    across the mainstream desktop platforms supported by Tk.
        # 2. Briefly toggling topmost helps some window managers actually move
        #    the map above other windows instead of only giving it keyboard focus.
        if self._closed or not self.root.winfo_exists():
            return
        try:
            self.root.deiconify()
            self.root.lift()
            try:
                self.root.attributes("-topmost", True)
                self.root.after(250, self._clear_topmost_flag)
            except tk.TclError:
                pass
            self.root.focus_force()
            self._log_focus_change(f"Main window raised to front ({trigger_description})")
        except tk.TclError:
            return

    def send_window_to_back(self) -> None:
        # 1. Clear any temporary topmost flag first so a previous "bring to
        #    front" action does not fight the request to push the window back.
        # 2. `lower()` is the standard Tk mechanism for sending a toplevel
        #    behind other windows on the current desktop.
        if self._closed or not self.root.winfo_exists():
            return
        try:
            try:
                self.root.attributes("-topmost", False)
            except tk.TclError:
                pass
            self.root.lower()
        except tk.TclError:
            return

    def focus_on_alert_enabled(self) -> bool:
        return self._focus_on_alert_value()

    def audible_alert_enabled(self) -> bool:
        return self._audible_alert_value()

    def blink_on_appearing_enabled(self) -> bool:
        return self._blink_on_appearing_value()

    def attention_duration_seconds(self) -> float:
        # 1. Keep the shared attention-window conversion in one place so both
        #    blinking and focus circles stay synchronized.
        # 2. The UI stores whole seconds because that is easier to understand
        #    than fractional values for short operator-attention effects.
        try:
            return float(self._parse_attention_duration_seconds(self._attention_duration_seconds_value()))
        except Exception:
            return float(self._parse_attention_duration_seconds(self._DEFAULT_ATTENTION_DURATION_SECONDS))

    def localized_auto_zoom_enabled(self) -> bool:
        return self._localized_auto_zoom_value()

    def small_alert_focus_circle_enabled(self) -> bool:
        return self._small_alert_focus_circle_value()

    def reset_generation(self) -> int:
        # 1. Expose a monotonically increasing reset counter so the main loop
        #    can detect manual clears and discard its own stale alert state.
        # 2. A counter is simpler than callbacks here because `IsraelMap` is
        #    reused outside `show_alerts` and should stay loosely coupled.
        return self._reset_generation

    def startup_history_replay_seconds(self) -> int:
        # 1. Keep the startup replay window conversion in one place so callers
        #    do not duplicate minutes-to-seconds math.
        # 2. The settings dialog stores minutes because that is friendlier for
        #    operators, while the runtime cutoff code works in seconds.
        try:
            return self._parse_startup_history_minutes(self._startup_history_minutes_value()) * 60
        except Exception:
            return self._parse_startup_history_minutes(self._DEFAULT_STARTUP_HISTORY_MINUTES) * 60

    def refresh_localized_zoom(self) -> None:
        # 1. Recompute the preferred map view from the currently visible alert
        #    markers only when the caller explicitly requests it.
        # 2. This lets show_alerts trigger zoom changes only for new alerts,
        #    while expiry and gray-marker cleanup can leave the current view alone.
        desired_view_key = self._pick_localized_view_key()
        self._apply_view(desired_view_key)

    def ring_bell(self) -> None:
        if self._closed or not self.root.winfo_exists():
            return
        try:
            self.root.bell()
        except tk.TclError:
            pass

    def _finalize_close(self) -> None:
        if not self.root.winfo_exists():
            return
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _clear_topmost_flag(self) -> None:
        if self._closed or not self.root.winfo_exists():
            return
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

    def _latlon_to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        base_x, base_y = self._latlon_to_base_xy(lat, lon)
        return self._base_xy_to_view_xy(base_x, base_y)

    def _latlon_to_base_xy(self, lat: float, lon: float) -> tuple[float, float]:
        # Calibration is fitted against control cities collected with align_map on
        # the 413x1015 outline asset. The normalized geographic basis keeps the
        # transform stable and lets it scale cleanly when the image is resized.
        lat_center = 31.3655
        lat_scale = 1.9155
        lon_center = 35.04
        lon_scale = 0.84
        x_coeffs = (
            0.513547718710026,
            0.002805123908288,
            0.42945404405493,
            0.031587125912652,
        )
        y_coeffs = (
            0.517929081179612,
            -0.485313586248668,
            -0.013948572704905,
            0.014398953018679,
        )

        lat_norm = (lat - lat_center) / lat_scale
        lon_norm = (lon - lon_center) / lon_scale
        features = (
            1.0,
            lat_norm,
            lon_norm,
            lat_norm * lon_norm,
        )
        x_ratio = sum(coeff * feature for coeff, feature in zip(x_coeffs, features))
        y_ratio = sum(coeff * feature for coeff, feature in zip(y_coeffs, features))
        x = x_ratio * self._content_width
        y = y_ratio * self._content_height
        return x, y

    def _base_xy_to_view_xy(self, base_x: float, base_y: float) -> tuple[float, float]:
        view = self._view_specs[self._current_view_key]
        x = self.padding + ((base_x - view.crop_left) * view.scale)
        y = self.padding + ((base_y - view.crop_top) * view.scale)
        return x, y

    def _create_marker_item(self, shape: str, draw_color: str) -> int:
        if shape == "circle":
            return self.canvas.create_oval(0, 0, 0, 0, fill=draw_color, outline=draw_color)
        return self.canvas.create_rectangle(0, 0, 0, 0, fill=draw_color, outline=draw_color)

    def _position_marker_item(self, item_id: int, marker: _DrawCommand) -> None:
        x, y = self._latlon_to_xy(marker.latitude, marker.longitude)
        half = marker.size / 2
        if marker.shape == "circle":
            self.canvas.coords(item_id, x - half, y - half, x + half, y + half)
        elif marker.shape == "square":
            self.canvas.coords(item_id, x - half, y - half, x + half, y + half)
        else:
            self.canvas.coords(
                item_id,
                x - half,
                y - (marker.size * 0.30),
                x + half,
                y + (marker.size * 0.30),
            )

    def _position_focus_circle_item(self, item_id: int, focus_circle: _FocusCircleCommand) -> None:
        view_points = [
            self._latlon_to_xy(latitude, longitude)
            for latitude, longitude in focus_circle.points
        ]
        if not view_points:
            return
        center_x = sum(point[0] for point in view_points) / len(view_points)
        center_y = sum(point[1] for point in view_points) / len(view_points)
        max_distance = 0.0
        for point_x, point_y in view_points:
            dx = point_x - center_x
            dy = point_y - center_y
            max_distance = max(max_distance, (dx * dx + dy * dy) ** 0.5)
        radius = max(focus_circle.min_radius, max_distance + focus_circle.padding)
        self.canvas.coords(
            item_id,
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        )
        self.canvas.itemconfigure(
            item_id,
            outline=focus_circle.outline_color,
            width=focus_circle.width,
        )

    def _reposition_drawn_markers(self) -> None:
        for item_id, marker in self._drawn_markers.items():
            self._position_marker_item(item_id, marker)

    def _reposition_focus_circles(self) -> None:
        for item_id, focus_circle in self._focus_circle_items.items():
            self._position_focus_circle_item(item_id, focus_circle)
            if self._background_image_id is not None:
                self.canvas.tag_raise(item_id, self._background_image_id)

    def _position_click_highlight_item(self, item_id: int, highlight: _ClickHighlightState) -> None:
        # 1. Reuse the normal marker positioning path so the click highlight
        #    stays exactly on the calibrated locality point in every zoom view.
        # 2. The click highlight is intentionally drawn as the same shape and
        #    size as a normal alert marker so the user sees the true point.
        self._position_marker_item(
            item_id,
            _DrawCommand(
                latitude=highlight.latitude,
                longitude=highlight.longitude,
                color=highlight.color,
                shape=highlight.shape,
                size=highlight.size,
            ),
        )

    def _reposition_click_highlights(self) -> None:
        for item_id, highlight in self._click_highlight_items.items():
            self._position_click_highlight_item(item_id, highlight)
            if self._background_image_id is not None:
                self.canvas.tag_raise(item_id, self._background_image_id)

    def _build_view_specs(self, base_image: Image.Image) -> dict[str, _MapViewSpec]:
        content_width = base_image.width
        content_height = base_image.height
        top_half_bottom = int(round(content_height * 0.5))
        bottom_half_top = content_height - top_half_bottom
        middle_top = int(round(content_height * 0.25))
        middle_bottom = content_height - middle_top

        return {
            "full": self._create_view_spec(
                key="full",
                image=base_image,
                crop_box=(0, 0, content_width, content_height),
                scale=1.0,
            ),
            "top_half_x2": self._create_view_spec(
                key="top_half_x2",
                image=base_image,
                crop_box=(0, 0, content_width, top_half_bottom),
                scale=2.0,
            ),
            "middle_half_x2": self._create_view_spec(
                key="middle_half_x2",
                image=base_image,
                crop_box=(0, middle_top, content_width, middle_bottom),
                scale=2.0,
            ),
            "bottom_half_x2": self._create_view_spec(
                key="bottom_half_x2",
                image=base_image,
                crop_box=(0, bottom_half_top, content_width, content_height),
                scale=2.0,
            ),
        }

    def _create_view_spec(
        self,
        *,
        key: str,
        image: Image.Image,
        crop_box: tuple[int, int, int, int],
        scale: float,
    ) -> _MapViewSpec:
        cropped_image = image.crop(crop_box)
        if scale != 1.0:
            cropped_image = cropped_image.resize(
                (
                    max(1, int(round(cropped_image.width * scale))),
                    max(1, int(round(cropped_image.height * scale))),
                ),
                Image.Resampling.LANCZOS,
            )
        if self.padding:
            cropped_image = self._pad_image(cropped_image, self.padding)
        return _MapViewSpec(
            key=key,
            crop_left=float(crop_box[0]),
            crop_top=float(crop_box[1]),
            crop_right=float(crop_box[2]),
            crop_bottom=float(crop_box[3]),
            scale=float(scale),
            image=cropped_image,
        )

    def _pick_localized_view_key(self) -> str:
        if not self._localized_auto_zoom_value():
            return "full"

        relevant_points: list[tuple[float, float]] = []
        for marker in self._drawn_markers.values():
            if marker.color == "gray":
                continue
            relevant_points.append(self._latlon_to_base_xy(marker.latitude, marker.longitude))

        if not relevant_points:
            return "full"

        center_y = sum(point[1] for point in relevant_points) / len(relevant_points)
        matching_views = []
        for view_key in ("top_half_x2", "middle_half_x2", "bottom_half_x2"):
            view = self._view_specs[view_key]
            if all(
                view.crop_left <= x <= view.crop_right
                and view.crop_top <= y <= view.crop_bottom
                for x, y in relevant_points
            ):
                crop_center_y = (view.crop_top + view.crop_bottom) / 2.0
                matching_views.append((abs(center_y - crop_center_y), view_key))

        if not matching_views:
            return "full"

        matching_views.sort(key=lambda item: item[0])
        return matching_views[0][1]

    def _apply_view(self, view_key: str) -> None:
        if view_key not in self._view_specs:
            raise ValueError(f"Unknown map view {view_key}")
        if self._current_view_key == view_key:
            return

        self._current_view_key = view_key
        self._background_image = self._view_specs[view_key].image
        self.width = self._background_image.width
        self.height = self._background_image.height
        self.background_color = self._rgb_to_hex(self._background_image.getpixel((0, 0)))
        self._background_photo = self._create_photo_image(self._background_image)
        self._locality_points = None

        self.canvas.configure(
            width=self.width,
            height=self.height,
            bg=self.background_color,
            scrollregion=(0, 0, self.width, self.height),
        )
        if self._background_image_id is not None:
            self.canvas.itemconfigure(self._background_image_id, image=self._background_photo)
            self.canvas.coords(self._background_image_id, 0, 0)
        if self._menu_window_id is not None:
            self.canvas.itemconfigure(self._menu_window_id, width=self.width)

        self._reposition_drawn_markers()
        self._reposition_focus_circles()
        self._reposition_click_highlights()
        self.root.update_idletasks()
        if self._watchdog_text_id is not None:
            self._layout_watchdog_panel(
                self._WATCHDOG_COLORS.get(self._watchdog_level, self._WATCHDOG_COLORS["offline"]),
                pulse_on=self._watchdog_pulse_on,
            )
        if self._log_time_text_id is not None:
            self._layout_log_timestamp_panel()
        self._raise_overlays()

    def _create_photo_image(self, image: Image.Image) -> tk.PhotoImage:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return tk.PhotoImage(data=encoded)

    def _create_menu_bar(self) -> None:
        # 1. Draw the menu inside the canvas so it overlays the image instead of
        #    increasing the outer window height.
        # 2. Keep real drop-down menus for the actions, but host them on
        #    menubuttons inside a slim in-canvas strip.
        colors = self._CONTROL_COLORS
        self.root.configure(menu="")

        menu_frame = tk.Frame(
            self.canvas,
            bg=colors["panel_bg"],
            highlightthickness=1,
            highlightbackground=colors["panel_border"],
            bd=0,
            padx=4,
            pady=0,
        )

        def add_menu_button(
            label: str,
            entries: tuple[tuple[str, Callable[[], None] | None], ...],
        ) -> None:
            button = tk.Menubutton(
                menu_frame,
                text=label,
                indicatoron=False,
                relief="flat",
                bd=0,
                padx=10,
                pady=1,
                bg=colors["panel_bg"],
                fg=colors["button_fg"],
                activebackground=colors["button_active_bg"],
                activeforeground=colors["button_active_fg"],
                highlightthickness=0,
                font=self._STATUS_AND_BUTTON_FONT,
                takefocus=False,
            )
            menu = tk.Menu(button, tearoff=False)
            for entry_label, command in entries:
                if command is None:
                    menu.add_separator()
                else:
                    menu.add_command(label=entry_label, command=command)
            button.configure(menu=menu)
            button.pack(side="left", padx=(0, 4))

        def add_menu_action(label: str, command: Callable[[], None]) -> None:
            button = tk.Button(
                menu_frame,
                text=label,
                command=command,
                relief="flat",
                bd=0,
                padx=10,
                pady=1,
                bg=colors["panel_bg"],
                fg=colors["button_fg"],
                activebackground=colors["button_active_bg"],
                activeforeground=colors["button_active_fg"],
                highlightthickness=0,
                font=self._STATUS_AND_BUTTON_FONT,
                takefocus=False,
            )
            button.pack(side="left", padx=(0, 4))

        add_menu_button(
            "File",
            (
                ("Save", self._save_map_control),
                ("Settings", self._open_settings_dialog_control),
                ("", None),
                ("Exit", self._close_app_control),
            ),
        )
        add_menu_button(
            "Edit",
            (
                ("Clear", self._clear_map_control),
            ),
        )
        add_menu_action("Send to Back", self.send_window_to_back)
        add_menu_button(
            "Help",
            (
                ("Usage", self._open_usage_dialog_control),
                ("Color Legend", self._open_color_legend_dialog_control),
                ("About", self._open_about_dialog_control),
            ),
        )

        self._menu_frame = menu_frame
        self._menu_window_id = self.canvas.create_window(
            0,
            0,
            anchor="nw",
            width=self.width,
            window=menu_frame,
        )
        self._raise_overlays()

    def _enable_canvas_lookup(self) -> None:
        # 1. Bind settlement lookup only for the interactive operator-facing
        #    map mode so reusable non-interactive scripts keep their old behavior.
        # 2. Use `add="+"` so this feature does not replace any future canvas
        #    bindings that other map features may install.
        self.canvas.bind("<Button-1>", self._handle_canvas_lookup_click, add="+")

    def _handle_canvas_lookup_click(self, event: tk.Event) -> None:
        # 1. Ignore clicks outside the drawable image area because the request
        #    is specifically about points inside the map image.
        # 2. Keep the nearest-settlement query in canvas coordinates so it uses
        #    exactly the same projection the operator sees on screen.
        if self._closed or not self.root.winfo_exists():
            return
        if not (0 <= event.x <= self.width and 0 <= event.y <= self.height):
            return

        nearest = self._find_nearest_locality(event.x, event.y)
        if nearest is None:
            return
        self._show_nearest_locality_overlay(nearest)
        self._start_click_highlight(nearest)

    def _find_nearest_locality(self, x: float, y: float) -> _LocalityPoint | None:
        # 1. Build the projected locality cache lazily so startup stays light
        #    for callers that never use the click-to-lookup feature.
        # 2. Compare squared distance because it gives the same nearest result
        #    without paying for repeated square-root calls.
        locality_points = self._ensure_locality_points()
        if not locality_points:
            return None

        return min(
            locality_points,
            key=lambda point: ((point.x - x) ** 2) + ((point.y - y) ** 2),
        )

    def _ensure_locality_points(self) -> list[_LocalityPoint]:
        if self._locality_points is not None:
            return self._locality_points

        # 1. Import here to avoid a module-level circular dependency, because
        #    `utils.py` also imports `IsraelMap` for its sleep helper typing.
        # 2. Cache the projected coordinates once because the locality dataset is
        #    static during runtime and does not need to be recomputed per click.
        from utils import get_coords

        locality_points: list[_LocalityPoint] = []
        for name, point in get_coords().items():
            latitude = float(point["latitude"])
            longitude = float(point["longitude"])
            x, y = self._latlon_to_xy(latitude, longitude)
            locality_points.append(
                _LocalityPoint(
                    name=name,
                    latitude=latitude,
                    longitude=longitude,
                    x=x,
                    y=y,
                )
            )
        self._locality_points = locality_points
        return locality_points

    def _show_nearest_locality_overlay(self, locality: _LocalityPoint) -> None:
        # 1. Replace the previous click result in place so the operator can scan
        #    several localities quickly without dismissing modal windows.
        # 2. Keep the full copied text stable and explicit even though the
        #    visual overlay itself is intentionally compact.
        self._nearest_locality_text = (
            f"Settlement: {locality.name}\n"
            f"Latitude: {locality.latitude:.6f}\n"
            f"Longitude: {locality.longitude:.6f}"
        )
        if self._nearest_locality_overlay_name_var is not None:
            self._nearest_locality_overlay_name_var.set(self._to_visual_rtl_text(locality.name))
        if self._nearest_locality_overlay_coords_var is not None:
            self._nearest_locality_overlay_coords_var.set(
                f"{locality.latitude:.6f}, {locality.longitude:.6f}"
            )
        self._ensure_nearest_locality_overlay()
        self._layout_nearest_locality_overlay()
        if self._nearest_locality_overlay_window_id is not None:
            self.canvas.itemconfigure(self._nearest_locality_overlay_window_id, state="normal")
        self._raise_overlays()
        self._cancel_nearest_locality_overlay_timer()
        self._nearest_locality_overlay_hide_after_id = self.root.after(
            self._LOCALITY_INFO_HIDE_MS,
            self._hide_nearest_locality_overlay,
        )

    def _ensure_nearest_locality_overlay(self) -> None:
        if self._nearest_locality_overlay_frame is not None and self._nearest_locality_overlay_window_id is not None:
            return

        panel = tk.Frame(
            self.canvas,
            bg="#f7f8f9",
            highlightthickness=1,
            highlightbackground="#c8cdd2",
            bd=0,
            padx=8,
            pady=6,
        )

        name_label = tk.Label(
            panel,
            textvariable=self._nearest_locality_overlay_name_var,
            anchor="e",
            justify="right",
            bg="#f7f8f9",
            fg="#20262c",
            font=("TkDefaultFont", 11, "bold"),
        )
        name_label.pack(fill="x")

        coords_entry = tk.Entry(
            panel,
            textvariable=self._nearest_locality_overlay_coords_var,
            justify="left",
            state="readonly",
            width=22,
            readonlybackground="#ffffff",
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#d4d9de",
            highlightcolor="#d4d9de",
            fg="#4b545c",
            font=("TkDefaultFont", 9),
        )
        coords_entry.pack(fill="x", pady=(4, 0), ipady=2)
        coords_entry.bind(
            "<Button-1>",
            lambda _event: self._select_all_entry_text(coords_entry),
            add="+",
        )
        coords_entry.bind(
            "<FocusIn>",
            lambda _event: self._select_all_entry_text(coords_entry),
            add="+",
        )
        coords_entry.bind(
            "<Control-c>",
            lambda _event: self._copy_nearest_locality_coords_only(),
            add="+",
        )
        coords_entry.bind(
            "<Command-c>",
            lambda _event: self._copy_nearest_locality_coords_only(),
            add="+",
        )
        coords_entry.bind(
            "<<Copy>>",
            lambda _event: self._copy_nearest_locality_coords_only(),
            add="+",
        )

        copy_button = tk.Button(
            panel,
            text="Copy",
            command=self._copy_nearest_locality_coords_only,
            width=self._LOCALITY_INFO_COPY_BUTTON_WIDTH,
            bd=0,
            relief="flat",
            font=("TkDefaultFont", 9, "bold"),
            bg=self._CONTROL_COLORS["button_bg"],
            fg=self._CONTROL_COLORS["button_fg"],
            activebackground=self._CONTROL_COLORS["button_active_bg"],
            activeforeground=self._CONTROL_COLORS["button_active_fg"],
            highlightthickness=0,
            takefocus=False,
        )
        copy_button.pack(anchor="w", pady=(4, 0))

        self._nearest_locality_overlay_frame = panel
        self._nearest_locality_overlay_value_entry = coords_entry
        self._nearest_locality_overlay_window_id = self.canvas.create_window(
            0,
            0,
            anchor="nw",
            window=panel,
            state="hidden",
        )

    def _layout_nearest_locality_overlay(self) -> None:
        if self._nearest_locality_overlay_window_id is None:
            return
        panel_left = self._LOCALITY_INFO_EDGE_MARGIN
        panel_top = self._LOCALITY_INFO_EDGE_MARGIN
        if self._menu_window_id is not None:
            menu_bbox = self.canvas.bbox(self._menu_window_id)
            if menu_bbox is not None:
                panel_top = menu_bbox[3] + self._LOCALITY_INFO_EDGE_MARGIN + 2
        self.canvas.coords(
            self._nearest_locality_overlay_window_id,
            panel_left,
            panel_top,
        )

    def _hide_nearest_locality_overlay(self) -> None:
        self._nearest_locality_overlay_hide_after_id = None
        if self._nearest_locality_overlay_window_id is not None:
            self.canvas.itemconfigure(self._nearest_locality_overlay_window_id, state="hidden")

    def _cancel_nearest_locality_overlay_timer(self) -> None:
        if self._nearest_locality_overlay_hide_after_id is None:
            return
        try:
            self.root.after_cancel(self._nearest_locality_overlay_hide_after_id)
        except tk.TclError:
            pass
        self._nearest_locality_overlay_hide_after_id = None

    def _copy_nearest_locality_text(self) -> str:
        if self._nearest_locality_text is None:
            return "break"
        return self._copy_text_to_clipboard(self._nearest_locality_text)

    def _copy_nearest_locality_coords_only(self) -> str:
        if self._nearest_locality_text is None:
            return "break"
        lines = self._nearest_locality_text.splitlines()
        if len(lines) < 3:
            return "break"
        latitude_text = lines[1].partition(": ")[2]
        longitude_text = lines[2].partition(": ")[2]
        if not latitude_text or not longitude_text:
            return "break"
        return self._copy_text_to_clipboard(f"{latitude_text}, {longitude_text}")

    def _copy_text_to_clipboard(self, text: str) -> str:
        # 1. Keep clipboard writes centralized so the nearest-settlement dialog
        #    can reuse the same reliable path for both full details and name-only copy.
        # 2. Return `"break"` so Tk stops its default copy handling when this is
        #    called from a key binding on the locality name field.
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update_idletasks()
        except tk.TclError:
            pass
        return "break"

    def _select_all_entry_text(self, entry: tk.Entry) -> str:
        try:
            entry.selection_range(0, "end")
            entry.icursor("end")
        except tk.TclError:
            pass
        return "break"

    def _to_visual_rtl_text(self, text: str) -> str:
        # 1. Prefer python-bidi when available because it handles mixed Hebrew,
        #    punctuation, and quoted names more accurately than plain reversal.
        # 2. Fall back to a simple reversal so the dialog still improves visibly
        #    even before the dependency is installed in a new environment.
        if _get_bidi_display is not None:
            try:
                return _get_bidi_display(text)
            except Exception:
                pass
        return text[::-1]

    def _raise_overlays(self) -> None:
        for item_id in self._click_highlight_items:
            self.canvas.tag_raise(item_id)
        if self._nearest_locality_overlay_window_id is not None:
            self._layout_nearest_locality_overlay()
            self.canvas.tag_raise(self._nearest_locality_overlay_window_id)
        if self._log_time_background_id is not None:
            self.canvas.tag_raise(self._log_time_background_id)
        if self._log_time_text_id is not None:
            self.canvas.tag_raise(self._log_time_text_id)
        if self._watchdog_background_id is not None:
            self.canvas.tag_raise(self._watchdog_background_id)
        if self._watchdog_icon_id is not None:
            self.canvas.tag_raise(self._watchdog_icon_id)
        if self._watchdog_text_id is not None:
            self.canvas.tag_raise(self._watchdog_text_id)
        if self._menu_window_id is not None:
            self.canvas.tag_raise(self._menu_window_id)

    def set_log_timestamp(self, timestamp: str) -> None:
        if self._closed or not self.root.winfo_exists():
            return

        if self._log_time_background_id is None:
            self._log_time_background_id = self.canvas.create_rectangle(
                0,
                0,
                0,
                0,
                fill="",
                outline="",
                width=0,
            )
        if self._log_time_text_id is None:
            self._log_time_text_id = self.canvas.create_text(
                0,
                0,
                text=timestamp,
                anchor="sw",
                fill="#394047",
                font=("TkDefaultFont", 12, "bold"),
            )
        else:
            self.canvas.itemconfigure(self._log_time_text_id, text=timestamp)
        self._layout_log_timestamp_panel()
        self._raise_overlays()

    def set_watchdog_status(self, text: str, *, level: str, pulse_on: bool) -> None:
        if self._closed or not self.root.winfo_exists():
            return

        # 1. Keep the watchdog in the lower-left corner so it does not increase
        #    the window height and stays separated from the top menu.
        # 2. A pulsing icon makes it obvious when the UI loop itself has stopped
        #    progressing, because the pulse will freeze in place.
        self._watchdog_level = level
        self._watchdog_pulse_on = pulse_on
        colors = self._WATCHDOG_COLORS.get(level, self._WATCHDOG_COLORS["offline"])
        if self._watchdog_text_id is None:
            self._watchdog_text_id = self.canvas.create_text(
                0,
                0,
                text=text,
                anchor="sw",
                fill=colors["text"],
                font=self._STATUS_AND_BUTTON_FONT,
            )
        else:
            self.canvas.itemconfigure(self._watchdog_text_id, text=text, fill=colors["text"])
        self._layout_watchdog_panel(colors, pulse_on)
        self._layout_log_timestamp_panel()
        self._raise_overlays()

    def _layout_log_timestamp_panel(self) -> None:
        if self._log_time_text_id is None or self._log_time_background_id is None:
            return

        panel_left = self._STATUS_EDGE_MARGIN
        panel_bottom = self.height - self._STATUS_EDGE_MARGIN - self._STATUS_PANEL_Y_OFFSET
        if self._watchdog_background_id is not None:
            watchdog_bbox = self.canvas.bbox(self._watchdog_background_id)
            if watchdog_bbox is not None:
                panel_bottom = watchdog_bbox[1] - self._STATUS_STACK_GAP

        text_x = panel_left + 4
        text_y = panel_bottom - 4 + self._LOG_TEXT_Y_OFFSET
        self.canvas.coords(self._log_time_text_id, text_x, text_y)
        bbox = self.canvas.bbox(self._log_time_text_id)
        if bbox is None:
            return
        self.canvas.coords(
            self._log_time_background_id,
            bbox[0] - 6,
            bbox[1] - 4,
            bbox[2] + 6,
            bbox[3] + 4,
        )
        self.canvas.itemconfigure(
            self._log_time_background_id,
            fill="",
            outline="",
            width=0,
        )

    def _layout_watchdog_panel(self, colors: dict[str, str], pulse_on: bool) -> None:
        if self._watchdog_text_id is None:
            return

        panel_left = self._STATUS_EDGE_MARGIN
        panel_bottom = self.height - self._STATUS_EDGE_MARGIN - self._STATUS_PANEL_Y_OFFSET
        text_x = panel_left + 21
        text_y = panel_bottom - 4
        self.canvas.coords(self._watchdog_text_id, text_x, text_y)
        text_bbox = self.canvas.bbox(self._watchdog_text_id)
        if text_bbox is None:
            return

        icon_radius = 4
        icon_gap = 9
        icon_cx = panel_left + 12
        icon_cy = (text_bbox[1] + text_bbox[3]) / 2
        icon_fill = colors["icon_on"] if pulse_on else colors["icon_off"]
        if self._watchdog_icon_id is None:
            self._watchdog_icon_id = self.canvas.create_oval(
                icon_cx - icon_radius,
                icon_cy - icon_radius,
                icon_cx + icon_radius,
                icon_cy + icon_radius,
                fill=icon_fill,
                outline=colors["panel_border"],
                width=1,
            )
        else:
            self.canvas.coords(
                self._watchdog_icon_id,
                icon_cx - icon_radius,
                icon_cy - icon_radius,
                icon_cx + icon_radius,
                icon_cy + icon_radius,
            )
            self.canvas.itemconfigure(
                self._watchdog_icon_id,
                fill=icon_fill,
                outline=colors["panel_border"],
            )

        panel_top = text_bbox[1] - 4
        panel_right = text_bbox[2] + 8
        if self._watchdog_background_id is None:
            self._watchdog_background_id = self.canvas.create_rectangle(
                panel_left,
                panel_top,
                panel_right,
                panel_bottom,
                fill=colors["panel_bg"],
                outline=colors["panel_border"],
                width=1,
            )
        else:
            self.canvas.coords(
                self._watchdog_background_id,
                panel_left,
                panel_top,
                panel_right,
                panel_bottom,
            )
            self.canvas.itemconfigure(
                self._watchdog_background_id,
                fill=colors["panel_bg"],
                outline=colors["panel_border"],
            )

    def _clear_map_control(self) -> None:
        self.reset(refresh=True)

    def _save_map_control(self) -> None:
        # 1. File > Save should act immediately with the current persisted
        #    settings instead of opening another confirmation panel.
        # 2. Keeping save direct makes the new File menu behave like a standard
        #    desktop application.
        self._save_map_image_to_disk()

    def _open_settings_dialog_control(self) -> None:
        # 1. Snapshot the current settings so Cancel can truly discard dialog
        #    edits instead of leaving partial changes behind in memory.
        # 2. Reuse the existing save-related settings rather than inventing a
        #    second configuration model for the same output options.
        self._settings_dialog_snapshot = (
            self._save_include_datetime_value(),
            self._save_base_name_value(),
            self._save_scale_value(),
            self._focus_on_alert_value(),
            self._audible_alert_value(),
            self._blink_on_appearing_value(),
            self._attention_duration_seconds_value(),
            self._localized_auto_zoom_value(),
            self._small_alert_focus_circle_value(),
            self._startup_history_minutes_value(),
        )

        colors = self._CONTROL_COLORS
        settings_panel_width = 320
        dialog, body = self._open_modal_shell("Settings", kind="settings")

        notification_panel = tk.LabelFrame(
            body,
            text="Alert Notification",
            width=settings_panel_width,
            bg="#f7f8f9",
            fg="#5a6168",
            bd=1,
            relief="solid",
            padx=14,
            pady=12,
            font=("TkDefaultFont", 10, "bold"),
            labelanchor="nw",
        )
        notification_panel.pack(fill="x", pady=(12, 0))

        focus_checkbox = tk.Checkbutton(
            notification_panel,
            text="Bring Window to Front",
            variable=self._focus_on_alert_var,
            anchor="w",
            bg="#f7f8f9",
            fg=colors["button_fg"],
            activebackground="#f7f8f9",
            activeforeground=colors["button_active_fg"],
            selectcolor="#f1f3f5",
            highlightthickness=0,
            bd=0,
            padx=0,
            pady=0,
            font=("TkDefaultFont", 10),
        )
        focus_checkbox.pack(fill="x")

        audible_checkbox = tk.Checkbutton(
            notification_panel,
            text="Play Audible Alert",
            variable=self._audible_alert_var,
            anchor="w",
            bg="#f7f8f9",
            fg=colors["button_fg"],
            activebackground="#f7f8f9",
            activeforeground=colors["button_active_fg"],
            selectcolor="#f1f3f5",
            highlightthickness=0,
            bd=0,
            padx=0,
            pady=0,
            font=("TkDefaultFont", 10),
        )
        audible_checkbox.pack(fill="x", pady=(10, 0))

        blink_checkbox = tk.Checkbutton(
            notification_panel,
            text="Blink New Alerts on Appearing",
            variable=self._blink_on_appearing_var,
            anchor="w",
            bg="#f7f8f9",
            fg=colors["button_fg"],
            activebackground="#f7f8f9",
            activeforeground=colors["button_active_fg"],
            selectcolor="#f1f3f5",
            highlightthickness=0,
            bd=0,
            padx=0,
            pady=0,
            font=("TkDefaultFont", 10),
        )
        blink_checkbox.pack(fill="x", pady=(10, 0))

        attention_duration_row = tk.Frame(notification_panel, bg="#f7f8f9")
        attention_duration_row.pack(fill="x", pady=(10, 0))

        attention_duration_label = tk.Label(
            attention_duration_row,
            text="Blink / Focus Duration",
            anchor="w",
            bg="#f7f8f9",
            fg="#5a6168",
            font=("TkDefaultFont", 9, "bold"),
        )
        attention_duration_label.pack(side="left")

        attention_duration_entry = tk.Entry(
            attention_duration_row,
            textvariable=self._attention_duration_seconds_var,
            width=6,
            justify="right",
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#c8cdd2",
            highlightcolor="#9fa6ad",
            bg="#ffffff",
            fg=colors["button_active_fg"],
            insertbackground=colors["button_active_fg"],
            font=("TkDefaultFont", 10),
        )
        attention_duration_entry.pack(side="left", padx=(12, 0))

        attention_duration_suffix = tk.Label(
            attention_duration_row,
            text="seconds",
            anchor="w",
            bg="#f7f8f9",
            fg="#5a6168",
            font=("TkDefaultFont", 10),
        )
        attention_duration_suffix.pack(side="left", padx=(8, 0))

        map_display_panel = tk.LabelFrame(
            body,
            text="Map Display",
            width=settings_panel_width,
            bg="#f7f8f9",
            fg="#5a6168",
            bd=1,
            relief="solid",
            padx=14,
            pady=12,
            font=("TkDefaultFont", 10, "bold"),
            labelanchor="nw",
        )
        map_display_panel.pack(fill="x", pady=(12, 0))

        auto_zoom_checkbox = tk.Checkbutton(
            map_display_panel,
            text="Auto Zoom x2 for Localized Alerts",
            variable=self._localized_auto_zoom_var,
            anchor="w",
            bg="#f7f8f9",
            fg=colors["button_fg"],
            activebackground="#f7f8f9",
            activeforeground=colors["button_active_fg"],
            selectcolor="#f1f3f5",
            highlightthickness=0,
            bd=0,
            padx=0,
            pady=0,
            font=("TkDefaultFont", 10),
        )
        auto_zoom_checkbox.pack(fill="x")

        small_alert_circle_checkbox = tk.Checkbutton(
            map_display_panel,
            text="Show Focus Circle for Small Alerts",
            variable=self._small_alert_focus_circle_var,
            anchor="w",
            bg="#f7f8f9",
            fg=colors["button_fg"],
            activebackground="#f7f8f9",
            activeforeground=colors["button_active_fg"],
            selectcolor="#f1f3f5",
            highlightthickness=0,
            bd=0,
            padx=0,
            pady=0,
            font=("TkDefaultFont", 10),
        )
        small_alert_circle_checkbox.pack(fill="x", pady=(10, 0))

        history_replay_panel = tk.LabelFrame(
            body,
            text="History Replay",
            width=settings_panel_width,
            bg="#f7f8f9",
            fg="#5a6168",
            bd=1,
            relief="solid",
            padx=14,
            pady=12,
            font=("TkDefaultFont", 10, "bold"),
            labelanchor="nw",
        )
        history_replay_panel.pack(fill="x", pady=(12, 0))
        # 1. Let this section size to its content so the minutes entry does not
        #    get clipped on platforms with slightly taller Tk font metrics.
        # 2. Keep the fixed width so the Settings dialog still aligns visually
        #    with the other sections.
        history_replay_panel.configure(width=settings_panel_width)

        replay_minutes_label = tk.Label(
            history_replay_panel,
            text="Import alerts from the last",
            anchor="w",
            bg="#f7f8f9",
            fg="#5a6168",
            font=("TkDefaultFont", 9, "bold"),
        )
        replay_minutes_label.pack(fill="x")

        replay_minutes_row = tk.Frame(history_replay_panel, bg="#f7f8f9")
        replay_minutes_row.pack(fill="x", pady=(8, 0))

        replay_minutes_entry = tk.Entry(
            replay_minutes_row,
            textvariable=self._startup_history_minutes_var,
            width=6,
            justify="right",
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#c8cdd2",
            highlightcolor="#9fa6ad",
            bg="#ffffff",
            fg=colors["button_active_fg"],
            insertbackground=colors["button_active_fg"],
            font=("TkDefaultFont", 10),
        )
        replay_minutes_entry.pack(side="left")

        replay_minutes_suffix = tk.Label(
            replay_minutes_row,
            text="minutes on launch",
            anchor="w",
            bg="#f7f8f9",
            fg="#5a6168",
            font=("TkDefaultFont", 10),
        )
        replay_minutes_suffix.pack(side="left", padx=(8, 0))

        form_panel = tk.LabelFrame(
            body,
            text="Image Save Options",
            width=settings_panel_width,
            height=176,
            bg="#f7f8f9",
            fg="#5a6168",
            bd=1,
            relief="solid",
            padx=14,
            pady=14,
            font=("TkDefaultFont", 10, "bold"),
            labelanchor="nw",
        )
        form_panel.pack(fill="x", pady=(12, 0))
        form_panel.pack_propagate(False)

        base_name_label = tk.Label(
            form_panel,
            text="Base Name",
            anchor="w",
            bg="#f7f8f9",
            fg="#5a6168",
            pady=0,
            font=("TkDefaultFont", 9, "bold"),
        )
        base_name_label.pack(fill="x", pady=(0, 4))

        base_name_entry = tk.Entry(
            form_panel,
            textvariable=self._save_base_name_var,
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#c8cdd2",
            highlightcolor="#9fa6ad",
            bg="#ffffff",
            fg=colors["button_active_fg"],
            insertbackground=colors["button_active_fg"],
            font=("TkDefaultFont", 10),
        )
        base_name_entry.pack(fill="x")

        include_checkbox = tk.Checkbutton(
            form_panel,
            text="Include Date/Time",
            variable=self._save_include_datetime_var,
            anchor="w",
            bg="#f7f8f9",
            fg=colors["button_fg"],
            activebackground="#f7f8f9",
            activeforeground=colors["button_active_fg"],
            selectcolor="#f1f3f5",
            highlightthickness=0,
            bd=0,
            padx=0,
            pady=0,
            font=("TkDefaultFont", 10),
        )
        include_checkbox.pack(fill="x", pady=(14, 0))

        scale_row = tk.Frame(form_panel, bg="#f7f8f9")
        scale_row.pack(fill="x", pady=(14, 0))

        scale_label = tk.Label(
            scale_row,
            text="Scale",
            anchor="w",
            bg="#f7f8f9",
            fg="#5a6168",
            font=("TkDefaultFont", 9, "bold"),
        )
        scale_label.pack(side="left")

        scale_entry = tk.Entry(
            scale_row,
            textvariable=self._save_scale_var,
            width=6,
            justify="right",
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#c8cdd2",
            highlightcolor="#9fa6ad",
            bg="#ffffff",
            fg=colors["button_active_fg"],
            insertbackground=colors["button_active_fg"],
            font=("TkDefaultFont", 10),
        )
        scale_entry.pack(side="left", padx=(12, 6))

        scale_suffix = tk.Label(
            scale_row,
            text="%",
            anchor="w",
            bg="#f7f8f9",
            fg=colors["button_fg"],
            font=("TkDefaultFont", 10),
        )
        scale_suffix.pack(side="left")

        button_row = tk.Frame(body, bg="#eef0f2")
        button_row.pack(fill="x", pady=(14, 0))

        cancel_button = tk.Button(
            button_row,
            text="Cancel",
            command=self._close_modal_dialog,
            width=9,
            bd=0,
            relief="flat",
            font=("TkDefaultFont", 10, "bold"),
            bg="#d6dade",
            fg=colors["button_fg"],
            activebackground="#e0e4e7",
            activeforeground=colors["button_active_fg"],
            highlightthickness=0,
            takefocus=False,
        )
        cancel_button.pack(side="right")

        ok_button = tk.Button(
            button_row,
            text="OK",
            command=self._handle_settings_dialog_ok,
            width=9,
            bd=0,
            relief="flat",
            font=("TkDefaultFont", 10, "bold"),
            bg=colors["button_bg"],
            fg=colors["button_fg"],
            activebackground=colors["button_active_bg"],
            activeforeground=colors["button_active_fg"],
            highlightthickness=0,
            takefocus=False,
        )
        ok_button.pack(side="right", padx=(0, 8))

        self._finalize_modal_dialog(dialog, focus_widget=base_name_entry)

    def _open_color_legend_dialog_control(self) -> None:
        # 1. Keep the legend as a real window so operators can reopen it on
        #    demand without leaving the main map view.
        # 2. Describe only the alert colors used by the runtime, not every color
        #    the generic drawing API happens to support.
        dialog, body = self._open_modal_shell("Color Legend", kind="legend")

        title = tk.Label(
            body,
            text="Color Legend",
            anchor="w",
            bg="#eef0f2",
            fg="#2f3841",
            font=("TkDefaultFont", 12, "bold"),
        )
        title.pack(fill="x")

        subtitle = tk.Label(
            body,
            text="These are the alert marker colors currently used on the map.",
            anchor="w",
            justify="left",
            wraplength=360,
            bg="#eef0f2",
            fg="#5a6168",
            pady=2,
            font=("TkDefaultFont", 10),
        )
        subtitle.pack(fill="x", pady=(4, 12))

        card = tk.Frame(
            body,
            bg="#f7f8f9",
            highlightthickness=1,
            highlightbackground="#c8cdd2",
            padx=14,
            pady=12,
        )
        card.pack(fill="both", expand=True)

        for index, (color_name, label, description) in enumerate(self._LEGEND_ITEMS):
            self._add_legend_row(card, color_name=color_name, label=label, description=description)
            if index < len(self._LEGEND_ITEMS) - 1:
                divider = tk.Frame(card, bg="#d7dce0", height=1)
                divider.pack(fill="x", pady=8)

        note = tk.Label(
            body,
            text="A newer alert replaces the older marker at the same locality. Event Ended markers clear after 10 minutes.",
            anchor="w",
            justify="left",
            wraplength=360,
            bg="#eef0f2",
            fg="#5a6168",
            pady=0,
            font=("TkDefaultFont", 9),
        )
        note.pack(fill="x", pady=(12, 0))

        button_row = tk.Frame(body, bg="#eef0f2")
        button_row.pack(fill="x", pady=(14, 0))

        close_button = tk.Button(
            button_row,
            text="Close",
            command=self._close_modal_dialog,
            width=9,
            bd=0,
            relief="flat",
            font=("TkDefaultFont", 10, "bold"),
            bg="#d6dade",
            fg="#394047",
            activebackground="#e0e4e7",
            activeforeground="#20262c",
            highlightthickness=0,
            takefocus=False,
        )
        close_button.pack(side="right")

        self._finalize_modal_dialog(dialog, focus_widget=close_button)

    def _open_usage_dialog_control(self) -> None:
        # 1. Keep usage guidance in the same modal style as the other Help
        #    screens so the operator gets one consistent interaction pattern.
        # 2. Document the interactive click feature explicitly because it is not
        #    otherwise visible from the menu labels alone.
        dialog, body = self._open_modal_shell("Usage", kind="usage")

        title = tk.Label(
            body,
            text="Usage",
            anchor="w",
            bg="#eef0f2",
            fg="#2f3841",
            font=("TkDefaultFont", 12, "bold"),
        )
        title.pack(fill="x")

        usage_lines = (
            "Click inside the map to show the nearest settlement name and coordinates in the upper-left corner.",
            "The true mapped point of that settlement blinks green for the configured attention duration.",
            "That click info auto-hides after one minute, and a new click replaces it and restarts the timer.",
            "Earlier clicked points keep blinking until their own timers end, even after you click another locality.",
            "The coordinates field is selectable for copy, and the Copy button copies the coordinates directly.",
        )
        for line in usage_lines:
            label = tk.Label(
                body,
                text=line,
                anchor="w",
                justify="left",
                wraplength=360,
                bg="#eef0f2",
                fg="#4b545c",
                pady=0,
                font=("TkDefaultFont", 10),
            )
            label.pack(fill="x", pady=(10, 0))

        button_row = tk.Frame(body, bg="#eef0f2")
        button_row.pack(fill="x", pady=(16, 0))

        close_button = tk.Button(
            button_row,
            text="Close",
            command=self._close_modal_dialog,
            width=9,
            bd=0,
            relief="flat",
            font=("TkDefaultFont", 10, "bold"),
            bg="#d6dade",
            fg="#394047",
            activebackground="#e0e4e7",
            activeforeground="#20262c",
            highlightthickness=0,
            takefocus=False,
        )
        close_button.pack(side="right")

        self._finalize_modal_dialog(dialog, focus_widget=close_button)

    def _open_about_dialog_control(self) -> None:
        # 1. Keep the About text explicit about authorship so both the project
        #    owner and the coding assistant are credited in the UI itself.
        # 2. Use plain factual wording because this is an operational tool, not
        #    a marketing splash screen.
        dialog, body = self._open_modal_shell("About", kind="about")

        title = tk.Label(
            body,
            text="PIKUD-HAOREF Local Alert Display",
            anchor="w",
            bg="#eef0f2",
            fg="#2f3841",
            font=("TkDefaultFont", 12, "bold"),
        )
        title.pack(fill="x")

        about_lines = (
            "Local map viewer for Home Front Command alerts and recent alert history.",
            f"Version: {APP_VERSION}",
            "Project concept, requirements, and operational direction by Shalom Mitz.",
            "Implementation assistance by Codex, based on GPT-5, from OpenAI.",
            "License: MIT.",
        )
        for line in about_lines:
            label = tk.Label(
                body,
                text=line,
                anchor="w",
                justify="left",
                wraplength=360,
                bg="#eef0f2",
                fg="#4b545c",
                pady=0,
                font=("TkDefaultFont", 10),
            )
            label.pack(fill="x", pady=(8 if line == about_lines[0] else 6, 0))

        button_row = tk.Frame(body, bg="#eef0f2")
        button_row.pack(fill="x", pady=(16, 0))

        close_button = tk.Button(
            button_row,
            text="Close",
            command=self._close_modal_dialog,
            width=9,
            bd=0,
            relief="flat",
            font=("TkDefaultFont", 10, "bold"),
            bg="#d6dade",
            fg="#394047",
            activebackground="#e0e4e7",
            activeforeground="#20262c",
            highlightthickness=0,
            takefocus=False,
        )
        close_button.pack(side="right")

        self._finalize_modal_dialog(dialog, focus_widget=close_button)

    def _open_modal_shell(self, title: str, *, kind: str) -> tuple[tk.Toplevel, tk.Frame]:
        # 1. Keep only one modal dialog active at a time so keyboard focus and
        #    grab ownership remain predictable.
        # 2. Store the modal kind because Settings needs special Cancel behavior.
        if self._modal_dialog is not None and self._modal_dialog.winfo_exists():
            self._close_modal_dialog()

        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg="#eef0f2")
        dialog.protocol("WM_DELETE_WINDOW", self._close_modal_dialog)

        body = tk.Frame(dialog, bg="#eef0f2", padx=18, pady=16)
        body.pack(fill="both", expand=True)

        self._modal_dialog = dialog
        self._modal_kind = kind
        return dialog, body

    def _finalize_modal_dialog(
        self,
        dialog: tk.Toplevel,
        *,
        focus_widget: tk.Widget | None = None,
    ) -> None:
        # 1. Center every dialog over the map window so secondary screens feel
        #    attached to the main tool instead of randomly placed.
        # 2. Grab input after layout is stable so the dialog behaves modally on
        #    all supported desktop environments.
        dialog.update_idletasks()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_width = self.root.winfo_width()
        root_height = self.root.winfo_height()
        dialog_width = dialog.winfo_width()
        dialog_height = dialog.winfo_height()
        x = root_x + max(0, (root_width - dialog_width) // 2)
        y = root_y + max(0, (root_height - dialog_height) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        dialog.lift()
        self._log_focus_change(f"Modal dialog opened ({dialog.title()})")
        if focus_widget is not None and focus_widget.winfo_exists():
            focus_widget.focus_force()
            if hasattr(focus_widget, "icursor"):
                try:
                    focus_widget.icursor("end")
                except tk.TclError:
                    pass

    def _add_legend_row(self, parent: tk.Widget, *, color_name: str, label: str, description: str) -> None:
        # 1. Use the same drawn-circle visual language as the map itself so the
        #    legend is immediately recognizable.
        # 2. Keep the text split into a short label and a sentence because the
        #    operator may scan this quickly during an event.
        row = tk.Frame(parent, bg="#f7f8f9")
        row.pack(fill="x")

        swatch = tk.Canvas(
            row,
            width=26,
            height=26,
            bg="#f7f8f9",
            highlightthickness=0,
            bd=0,
        )
        swatch.pack(side="left", padx=(0, 12))
        color = self._resolve_draw_color(color_name)
        swatch.create_oval(5, 5, 21, 21, fill=color, outline=color)

        text_column = tk.Frame(row, bg="#f7f8f9")
        text_column.pack(side="left", fill="x", expand=True)

        title = tk.Label(
            text_column,
            text=label,
            anchor="w",
            bg="#f7f8f9",
            fg="#2f3841",
            font=("TkDefaultFont", 10, "bold"),
        )
        title.pack(fill="x")

        detail = tk.Label(
            text_column,
            text=description,
            anchor="w",
            justify="left",
            wraplength=300,
            bg="#f7f8f9",
            fg="#5a6168",
            font=("TkDefaultFont", 9),
        )
        detail.pack(fill="x", pady=(2, 0))

    def _close_modal_dialog(self) -> None:
        if self._modal_dialog is None:
            return
        dialog = self._modal_dialog
        self._modal_dialog = None
        modal_kind = self._modal_kind
        self._modal_kind = None
        if modal_kind == "settings" and self._settings_dialog_snapshot is not None:
            (
                include_datetime,
                base_name,
                scale,
                focus_on_alert,
                audible_alert,
                blink_on_appearing,
                attention_duration_seconds,
                localized_auto_zoom,
                small_alert_focus_circle,
                startup_history_minutes,
            ) = self._settings_dialog_snapshot
            self._apply_save_settings(
                include_datetime=include_datetime,
                base_name=base_name,
                scale=scale,
                focus_on_alert=focus_on_alert,
                audible_alert=audible_alert,
                blink_on_appearing=blink_on_appearing,
                attention_duration_seconds=attention_duration_seconds,
                localized_auto_zoom=localized_auto_zoom,
                small_alert_focus_circle=small_alert_focus_circle,
                startup_history_minutes=startup_history_minutes,
            )
        self._settings_dialog_snapshot = None
        if dialog.winfo_exists():
            dialog.grab_release()
            dialog.destroy()

    def _close_app_control(self) -> None:
        self.close()

    def _handle_settings_dialog_ok(self) -> None:
        # 1. Validate the editable settings before writing them to disk so a bad
        #    scale or empty base name does not become the new default.
        # 2. Clear the snapshot before closing so OK commits instead of restoring
        #    the previous values like Cancel does.
        try:
            self._validate_save_settings()
        except Exception as exc:
            self._log_failure("Could not save settings", exc)
            return
        self._settings_dialog_snapshot = None
        self._save_settings_to_disk()
        self.refresh_localized_zoom()
        self._close_modal_dialog()

    def _load_save_settings(self) -> None:
        self._apply_save_settings(
            include_datetime=self._DEFAULT_SAVE_INCLUDE_DATETIME,
            base_name=self._DEFAULT_SAVE_BASE_NAME,
            scale=self._DEFAULT_SAVE_SCALE,
            focus_on_alert=self._DEFAULT_FOCUS_ON_ALERT,
            audible_alert=self._DEFAULT_AUDIBLE_ALERT,
            blink_on_appearing=self._DEFAULT_BLINK_ON_APPEARING,
            attention_duration_seconds=self._DEFAULT_ATTENTION_DURATION_SECONDS,
            localized_auto_zoom=self._DEFAULT_LOCALIZED_AUTO_ZOOM,
            small_alert_focus_circle=self._DEFAULT_SMALL_ALERT_FOCUS_CIRCLE,
            startup_history_minutes=self._DEFAULT_STARTUP_HISTORY_MINUTES,
        )

        path = Path.cwd() / self._SETTINGS_FILENAME
        if not path.exists():
            return

        try:
            loaded = self._parse_settings_text(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log_failure(f"Could not load settings from {path}", exc)
            return

        self._apply_save_settings(
            include_datetime=loaded.get("include_datetime", self._DEFAULT_SAVE_INCLUDE_DATETIME),
            base_name=loaded.get("base_name", self._DEFAULT_SAVE_BASE_NAME),
            scale=loaded.get("scale_percent", self._DEFAULT_SAVE_SCALE),
            focus_on_alert=loaded.get("focus_on_alert", self._DEFAULT_FOCUS_ON_ALERT),
            audible_alert=loaded.get("audible_alert", self._DEFAULT_AUDIBLE_ALERT),
            blink_on_appearing=loaded.get("blink_on_appearing", self._DEFAULT_BLINK_ON_APPEARING),
            attention_duration_seconds=str(loaded.get("attention_duration_seconds", self._DEFAULT_ATTENTION_DURATION_SECONDS)),
            localized_auto_zoom=loaded.get("localized_auto_zoom", self._DEFAULT_LOCALIZED_AUTO_ZOOM),
            small_alert_focus_circle=loaded.get("small_alert_focus_circle", self._DEFAULT_SMALL_ALERT_FOCUS_CIRCLE),
            startup_history_minutes=str(loaded.get("startup_history_minutes", self._DEFAULT_STARTUP_HISTORY_MINUTES)),
        )

    def _save_settings_to_disk(self) -> None:
        path = Path.cwd() / self._SETTINGS_FILENAME
        settings_text = self._build_settings_text()
        try:
            path.write_text(settings_text, encoding="utf-8")
        except Exception as exc:
            self._log_failure(f"Could not save settings to {path}", exc)

    def _save_map_image_to_disk(self) -> None:
        try:
            image = self._render_current_map_image()
            scale_percent = self._parse_scale_percent(self._save_scale_value())
            if scale_percent != 100.0:
                scaled_width = max(1, int(round(image.width * scale_percent / 100.0)))
                scaled_height = max(1, int(round(image.height * scale_percent / 100.0)))
                image = image.resize((scaled_width, scaled_height), Image.Resampling.LANCZOS)

            output_path = Path.cwd() / self._build_output_filename()
            image.save(output_path, format="PNG")
        except Exception as exc:
            self._log_failure("Could not save map image", exc)

    def _render_current_map_image(self) -> Image.Image:
        image = self._background_image.copy()
        draw = ImageDraw.Draw(image)
        for focus_circle in self._focus_circle_items.values():
            view_points = [
                self._latlon_to_xy(latitude, longitude)
                for latitude, longitude in focus_circle.points
            ]
            if not view_points:
                continue
            center_x = sum(point[0] for point in view_points) / len(view_points)
            center_y = sum(point[1] for point in view_points) / len(view_points)
            max_distance = 0.0
            for point_x, point_y in view_points:
                dx = point_x - center_x
                dy = point_y - center_y
                max_distance = max(max_distance, (dx * dx + dy * dy) ** 0.5)
            radius = max(focus_circle.min_radius, max_distance + focus_circle.padding)
            draw.ellipse(
                (
                    center_x - radius,
                    center_y - radius,
                    center_x + radius,
                    center_y + radius,
                ),
                outline=focus_circle.outline_color,
                width=focus_circle.width,
            )
        for item_id, marker in self._drawn_markers.items():
            x, y = self._latlon_to_xy(marker.latitude, marker.longitude)
            color = self._resolve_draw_color(marker.color)
            half = marker.size / 2
            if item_id in self._hidden_marker_ids:
                continue
            if marker.shape == "circle":
                draw.ellipse(
                    (x - half, y - half, x + half, y + half),
                    fill=color,
                    outline=color,
                )
            elif marker.shape == "square":
                draw.rectangle(
                    (x - half, y - half, x + half, y + half),
                    fill=color,
                    outline=color,
                )
            else:
                draw.rectangle(
                    (x - half, y - (marker.size * 0.30), x + half, y + (marker.size * 0.30)),
                    fill=color,
                    outline=color,
                )
        return image

    def _build_output_filename(self) -> str:
        base_name = self._save_base_name_value().strip()
        if not base_name:
            raise ValueError("Base Name is empty")

        if base_name.lower().endswith(".png"):
            base_name = base_name[:-4]

        if self._save_include_datetime_value():
            timestamp = datetime.now().strftime("%d%b%Y_%H_%M")
            return f"{base_name}_{timestamp}.png"
        return f"{base_name}.png"

    def _parse_scale_percent(self, scale_text: str) -> float:
        scale_percent = float(scale_text.strip())
        if scale_percent <= 0:
            raise ValueError("Scale must be greater than zero")
        return scale_percent

    def _validate_save_settings(self) -> None:
        # 1. Use the same validation rules for Settings and Save so the stored
        #    preferences cannot drift away from what the save path accepts.
        # 2. Validate both the filename base and the numeric scale because those
        #    are the two save-related fields that can make saving fail later.
        # 3. Validate the shared attention duration and startup replay window so
        #    settings persistence rejects invalid values before they become defaults.
        if not self._save_base_name_value().strip():
            raise ValueError("Base Name is empty")
        self._parse_scale_percent(self._save_scale_value())
        self._parse_attention_duration_seconds(self._attention_duration_seconds_value())
        self._parse_startup_history_minutes(self._startup_history_minutes_value())

    def _build_settings_text(self) -> str:
        include_datetime = "true" if self._save_include_datetime_value() else "false"
        focus_on_alert = "true" if self._focus_on_alert_value() else "false"
        audible_alert = "true" if self._audible_alert_value() else "false"
        blink_on_appearing = "true" if self._blink_on_appearing_value() else "false"
        attention_duration_seconds = self._parse_attention_duration_seconds(self._attention_duration_seconds_value())
        localized_auto_zoom = "true" if self._localized_auto_zoom_value() else "false"
        small_alert_focus_circle = "true" if self._small_alert_focus_circle_value() else "false"
        startup_history_minutes = self._parse_startup_history_minutes(self._startup_history_minutes_value())
        base_name = json.dumps(self._save_base_name_value(), ensure_ascii=False)
        scale_percent = json.dumps(self._save_scale_value())
        return (
            f"include_datetime: {include_datetime}\n"
            f"focus_on_alert: {focus_on_alert}\n"
            f"audible_alert: {audible_alert}\n"
            f"blink_on_appearing: {blink_on_appearing}\n"
            f"attention_duration_seconds: {attention_duration_seconds}\n"
            f"localized_auto_zoom: {localized_auto_zoom}\n"
            f"small_alert_focus_circle: {small_alert_focus_circle}\n"
            f"startup_history_minutes: {startup_history_minutes}\n"
            f"base_name: {base_name}\n"
            f"scale_percent: {scale_percent}\n"
        )

    def _parse_settings_text(self, text: str) -> dict[str, bool | str | int]:
        settings: dict[str, bool | str | int] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition(":")
            if not separator:
                continue

            normalized_key = key.strip()
            raw_value = value.strip()
            if normalized_key in {
                "include_datetime",
                "focus_on_alert",
                "audible_alert",
                "blink_on_appearing",
                "localized_auto_zoom",
                "small_alert_focus_circle",
            }:
                settings[normalized_key] = raw_value.casefold() in {"true", "yes", "on", "1"}
            elif normalized_key in {"base_name", "scale_percent"}:
                settings[normalized_key] = self._parse_settings_string(raw_value)
            elif normalized_key in {"attention_duration_seconds", "startup_history_minutes"}:
                settings[normalized_key] = self._parse_settings_int(raw_value)
        return settings

    def _parse_settings_string(self, raw_value: str) -> str:
        if not raw_value:
            return ""
        if raw_value[:1] in {'"', "'"}:
            return str(json.loads(raw_value)) if raw_value[:1] == '"' else str(ast.literal_eval(raw_value))
        return raw_value

    def _parse_settings_int(self, raw_value: str) -> int:
        return int(self._parse_settings_string(raw_value))

    def _apply_save_settings(
        self,
        *,
        include_datetime: bool,
        base_name: str,
        scale: str,
        focus_on_alert: bool,
        audible_alert: bool,
        blink_on_appearing: bool,
        attention_duration_seconds: str,
        localized_auto_zoom: bool,
        small_alert_focus_circle: bool,
        startup_history_minutes: str,
    ) -> None:
        if self._save_include_datetime_var is not None:
            self._save_include_datetime_var.set(bool(include_datetime))
        if self._save_base_name_var is not None:
            self._save_base_name_var.set(base_name)
        if self._save_scale_var is not None:
            self._save_scale_var.set(scale)
        if self._focus_on_alert_var is not None:
            self._focus_on_alert_var.set(bool(focus_on_alert))
        if self._audible_alert_var is not None:
            self._audible_alert_var.set(bool(audible_alert))
        if self._blink_on_appearing_var is not None:
            self._blink_on_appearing_var.set(bool(blink_on_appearing))
        if self._attention_duration_seconds_var is not None:
            self._attention_duration_seconds_var.set(str(attention_duration_seconds))
        if self._localized_auto_zoom_var is not None:
            self._localized_auto_zoom_var.set(bool(localized_auto_zoom))
        if self._small_alert_focus_circle_var is not None:
            self._small_alert_focus_circle_var.set(bool(small_alert_focus_circle))
        if self._startup_history_minutes_var is not None:
            self._startup_history_minutes_var.set(str(startup_history_minutes))

    def _save_include_datetime_value(self) -> bool:
        return bool(self._save_include_datetime_var.get()) if self._save_include_datetime_var is not None else False

    def _save_base_name_value(self) -> str:
        return self._save_base_name_var.get() if self._save_base_name_var is not None else self._DEFAULT_SAVE_BASE_NAME

    def _save_scale_value(self) -> str:
        return self._save_scale_var.get() if self._save_scale_var is not None else self._DEFAULT_SAVE_SCALE

    def _focus_on_alert_value(self) -> bool:
        return bool(self._focus_on_alert_var.get()) if self._focus_on_alert_var is not None else self._DEFAULT_FOCUS_ON_ALERT

    def _audible_alert_value(self) -> bool:
        return bool(self._audible_alert_var.get()) if self._audible_alert_var is not None else self._DEFAULT_AUDIBLE_ALERT

    def _blink_on_appearing_value(self) -> bool:
        return bool(self._blink_on_appearing_var.get()) if self._blink_on_appearing_var is not None else self._DEFAULT_BLINK_ON_APPEARING

    def _attention_duration_seconds_value(self) -> str:
        return (
            self._attention_duration_seconds_var.get()
            if self._attention_duration_seconds_var is not None
            else self._DEFAULT_ATTENTION_DURATION_SECONDS
        )

    def _parse_attention_duration_seconds(self, seconds_text: str) -> int:
        # 1. Require a positive whole number because the current UI exposes the
        #    duration in seconds, not fractions of a second.
        # 2. One shared parser keeps blinking and focus-circle timing rules identical.
        attention_duration_seconds = int(seconds_text.strip())
        if attention_duration_seconds <= 0:
            raise ValueError("Blink / focus duration must be greater than zero")
        return attention_duration_seconds

    def _localized_auto_zoom_value(self) -> bool:
        return bool(self._localized_auto_zoom_var.get()) if self._localized_auto_zoom_var is not None else self._DEFAULT_LOCALIZED_AUTO_ZOOM

    def _small_alert_focus_circle_value(self) -> bool:
        return (
            bool(self._small_alert_focus_circle_var.get())
            if self._small_alert_focus_circle_var is not None
            else self._DEFAULT_SMALL_ALERT_FOCUS_CIRCLE
        )

    def _startup_history_minutes_value(self) -> str:
        return (
            self._startup_history_minutes_var.get()
            if self._startup_history_minutes_var is not None
            else self._DEFAULT_STARTUP_HISTORY_MINUTES
        )

    def _parse_startup_history_minutes(self, minutes_text: str) -> int:
        # 1. Accept zero to let operators disable startup replay without adding
        #    another checkbox or special-case state.
        # 2. Require a whole number of minutes because fractional minutes would
        #    be harder to read in the Settings dialog and provide little value.
        startup_history_minutes = int(minutes_text.strip())
        if startup_history_minutes < 0:
            raise ValueError("Startup history replay minutes cannot be negative")
        return startup_history_minutes

    def _log_failure(self, message: str, exc: Exception) -> None:
        try:
            from utils import log

            log(f"{message}: {exc}")
        except Exception:
            pass

    def _log_focus_change(self, trigger_description: str) -> None:
        # 1. Keep focus-change logging centralized so all raise/focus paths use
        #    the same wording and can be audited from one place.
        # 2. Import lazily to avoid creating a module-level cycle with utils.
        try:
            from utils import log

            log(f"Focus change: {trigger_description}")
        except Exception:
            pass

    def _resolve_draw_color(self, color: str) -> str:
        if color == "background":
            return self.background_color
        return self._COLOR_MAP[color]

    def _pad_image(self, image: Image.Image, padding: int) -> Image.Image:
        padded = Image.new(
            "RGB",
            (image.width + (2 * padding), image.height + (2 * padding)),
            image.getpixel((0, 0)),
        )
        padded.paste(image, (padding, padding))
        return padded

    def _resolve_background_path(self, image_path: str | Path | None) -> Path:
        if image_path is not None:
            resolved = Path(image_path).expanduser().resolve()
            if resolved.exists():
                return resolved
            raise FileNotFoundError(f"Background image not found: {resolved}")

        base_dir = Path(__file__).resolve().parent
        for candidate in self._IMAGE_CANDIDATES:
            candidate_path = base_dir / candidate
            if candidate_path.exists():
                return candidate_path

        searched = ", ".join(self._IMAGE_CANDIDATES)
        raise FileNotFoundError(f"No background image found. Tried: {searched}")

    def _validate_draw_params(
        self,
        lat: float,
        lon: float,
        color: str,
        shape: str,
        size: int,
    ) -> None:
        if color not in self._ALLOWED_COLORS:
            allowed = ", ".join(sorted(self._ALLOWED_COLORS))
            raise ValueError(f"Invalid color '{color}'. Allowed values: {allowed}")
        if shape not in self._ALLOWED_SHAPES:
            allowed = ", ".join(sorted(self._ALLOWED_SHAPES))
            raise ValueError(f"Invalid shape '{shape}'. Allowed values: {allowed}")
        if size <= 0:
            raise ValueError("size must be a positive integer")
        if not (self.bounds.min_lat <= lat <= self.bounds.max_lat):
            raise ValueError(f"latitude must be in [{self.bounds.min_lat}, {self.bounds.max_lat}]")
        if not (self.bounds.min_lon <= lon <= self.bounds.max_lon):
            raise ValueError(f"longitude must be in [{self.bounds.min_lon}, {self.bounds.max_lon}]")

    @staticmethod
    def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
        return "#{:02x}{:02x}{:02x}".format(*rgb)


if __name__ == "__main__":
    app = IsraelMap()
    app.run()
