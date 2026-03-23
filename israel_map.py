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
from typing import Callable

from PIL import Image, ImageDraw

try:
    from bidi.algorithm import get_display as _get_bidi_display
except Exception:
    _get_bidi_display = None


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
class _LocalityPoint:
    name: str
    latitude: float
    longitude: float
    x: float
    y: float


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
        self._drawn_markers: dict[int, _DrawCommand] = {}
        self._menu_frame: tk.Frame | None = None
        self._menu_window_id: int | None = None
        self._modal_dialog: tk.Toplevel | None = None
        self._modal_kind: str | None = None
        self._nearest_locality_text: str | None = None
        self._locality_points: list[_LocalityPoint] | None = None
        self._settings_dialog_snapshot: tuple[bool, str, str, bool, bool] | None = None
        self._log_time_background_id: int | None = None
        self._log_time_text_id: int | None = None
        self._watchdog_background_id: int | None = None
        self._watchdog_icon_id: int | None = None
        self._watchdog_text_id: int | None = None
        self._save_include_datetime_var: tk.BooleanVar | None = None
        self._save_base_name_var: tk.StringVar | None = None
        self._save_scale_var: tk.StringVar | None = None
        self._focus_on_alert_var: tk.BooleanVar | None = None
        self._audible_alert_var: tk.BooleanVar | None = None

        resolved_image_path = self._resolve_background_path(image_path)
        self._background_image = Image.open(resolved_image_path).convert("RGB")
        if width is not None or height is not None:
            target_width = width if width is not None else self._background_image.width
            target_height = height if height is not None else self._background_image.height
            self._background_image = self._background_image.resize(
                (target_width, target_height),
                Image.Resampling.LANCZOS,
            )
        self._content_width = self._background_image.width
        self._content_height = self._background_image.height
        if self.padding:
            self._background_image = self._pad_image(self._background_image, self.padding)

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
        self.canvas.create_image(0, 0, anchor="nw", image=self._background_photo)
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

        x, y = self._latlon_to_xy(latitude, longitude)
        draw_color = self._resolve_draw_color(color)
        half = size / 2

        if shape == "circle":
            item_id = self.canvas.create_oval(
                x - half,
                y - half,
                x + half,
                y + half,
                fill=draw_color,
                outline=draw_color,
            )
        elif shape == "square":
            item_id = self.canvas.create_rectangle(
                x - half,
                y - half,
                x + half,
                y + half,
                fill=draw_color,
                outline=draw_color,
            )
        else:
            item_id = self.canvas.create_rectangle(
                x - half,
                y - (size * 0.30),
                x + half,
                y + (size * 0.30),
                fill=draw_color,
                outline=draw_color,
            )

        self._drawn_markers[item_id] = _DrawCommand(latitude, longitude, color, shape, size)
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
        self.canvas.delete(item_id)
        if refresh is None:
            refresh = self.auto_refresh
        if refresh:
            self.process_events()
        return True

    def reset(self, refresh: bool | None = None) -> None:
        """Restore the canvas to the original image-only state."""
        for item_id in tuple(self._drawn_markers):
            self.canvas.delete(item_id)
        self._drawn_markers.clear()
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
        x = self.padding + (x_ratio * self._content_width)
        y = self.padding + (y_ratio * self._content_height)
        return x, y

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
        self._open_nearest_locality_dialog(nearest)

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

    def _open_nearest_locality_dialog(self, locality: _LocalityPoint) -> None:
        # 1. Keep the copied text identical to the displayed text so the operator
        #    can trust that "Copy and Close" exports exactly what was shown.
        # 2. Use a modal dialog because the user explicitly asked for that flow
        #    instead of an inline status overlay or tooltip.
        self._nearest_locality_text = (
            f"Settlement: {locality.name}\n"
            f"Latitude: {locality.latitude:.6f}\n"
            f"Longitude: {locality.longitude:.6f}"
        )
        dialog, body = self._open_modal_shell("Nearest Settlement", kind="nearest_locality")

        title = tk.Label(
            body,
            text="Nearest Settlement",
            anchor="w",
            bg="#eef0f2",
            fg="#2f3841",
            font=("TkDefaultFont", 12, "bold"),
        )
        title.pack(fill="x")

        card = tk.Frame(
            body,
            bg="#f7f8f9",
            highlightthickness=1,
            highlightbackground="#c8cdd2",
            padx=14,
            pady=12,
        )
        card.pack(fill="both", expand=True, pady=(12, 0))

        name_label = tk.Label(
            card,
            text="Settlement",
            anchor="w",
            bg="#f7f8f9",
            fg="#5a6168",
            font=("TkDefaultFont", 10, "bold"),
        )
        name_label.pack(fill="x")

        # 1. Tk text-entry widgets do not reliably render logical Hebrew text in
        #    the correct visual order, so prepare an explicit visual display
        #    string for the field.
        # 2. Keep the original logical Hebrew text separately so copy actions
        #    still place the correct locality name on the clipboard.
        display_name = self._to_visual_rtl_text(locality.name)
        name_value_var = tk.StringVar(value=display_name)
        name_value = tk.Entry(
            card,
            textvariable=name_value_var,
            justify="right",
            state="readonly",
            readonlybackground="#ffffff",
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#c8cdd2",
            highlightcolor="#c8cdd2",
            fg="#20262c",
            font=("TkDefaultFont", 13, "bold"),
        )
        name_value.pack(fill="x", pady=(4, 12), ipady=6)
        name_value.bind(
            "<Button-1>",
            lambda _event: self._select_all_entry_text(name_value),
            add="+",
        )
        name_value.bind(
            "<FocusIn>",
            lambda _event: self._select_all_entry_text(name_value),
            add="+",
        )
        name_value.bind(
            "<Control-c>",
            lambda _event: self._copy_text_to_clipboard(locality.name),
            add="+",
        )
        name_value.bind(
            "<Command-c>",
            lambda _event: self._copy_text_to_clipboard(locality.name),
            add="+",
        )
        name_value.bind(
            "<<Copy>>",
            lambda _event: self._copy_text_to_clipboard(locality.name),
            add="+",
        )

        coords_text = (
            f"Latitude: {locality.latitude:.6f}\n"
            f"Longitude: {locality.longitude:.6f}"
        )
        details = tk.Label(
            card,
            text=coords_text,
            anchor="w",
            justify="left",
            bg="#f7f8f9",
            fg="#394047",
            font=("TkDefaultFont", 11),
        )
        details.pack(fill="x")

        button_row = tk.Frame(body, bg="#eef0f2")
        button_row.pack(fill="x", pady=(14, 0))

        close_button = tk.Button(
            button_row,
            text="Close",
            command=self._close_modal_dialog,
            width=11,
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

        copy_button = tk.Button(
            button_row,
            text="Copy and Close",
            command=self._copy_nearest_locality_and_close,
            width=14,
            bd=0,
            relief="flat",
            font=("TkDefaultFont", 10, "bold"),
            bg=self._CONTROL_COLORS["button_bg"],
            fg=self._CONTROL_COLORS["button_fg"],
            activebackground=self._CONTROL_COLORS["button_active_bg"],
            activeforeground=self._CONTROL_COLORS["button_active_fg"],
            highlightthickness=0,
            takefocus=False,
        )
        copy_button.pack(side="right", padx=(0, 8))

        self._finalize_modal_dialog(dialog, focus_widget=copy_button)

    def _copy_nearest_locality_and_close(self) -> None:
        if self._nearest_locality_text is None:
            self._close_modal_dialog()
            return
        self._copy_text_to_clipboard(self._nearest_locality_text)
        self._close_modal_dialog()

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
        )

        colors = self._CONTROL_COLORS
        dialog, body = self._open_modal_shell("Settings", kind="settings")

        form_panel = tk.LabelFrame(
            body,
            text="Image Save Options",
            width=260,
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
        form_panel.pack(fill="x")
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

        notification_panel = tk.LabelFrame(
            body,
            text="Alert Notification",
            width=260,
            height=94,
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
        notification_panel.pack_propagate(False)

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
            "Click inside the map to open the nearest settlement name and coordinates.",
            "Use Copy and Close in that window if you want the settlement details on the clipboard.",
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
            "Version: 1.00",
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
        self._nearest_locality_text = None
        if modal_kind == "settings" and self._settings_dialog_snapshot is not None:
            include_datetime, base_name, scale, focus_on_alert, audible_alert = self._settings_dialog_snapshot
            self._apply_save_settings(
                include_datetime=include_datetime,
                base_name=base_name,
                scale=scale,
                focus_on_alert=focus_on_alert,
                audible_alert=audible_alert,
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
        self._close_modal_dialog()

    def _load_save_settings(self) -> None:
        self._apply_save_settings(
            include_datetime=self._DEFAULT_SAVE_INCLUDE_DATETIME,
            base_name=self._DEFAULT_SAVE_BASE_NAME,
            scale=self._DEFAULT_SAVE_SCALE,
            focus_on_alert=self._DEFAULT_FOCUS_ON_ALERT,
            audible_alert=self._DEFAULT_AUDIBLE_ALERT,
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
        for marker in self._drawn_markers.values():
            x, y = self._latlon_to_xy(marker.latitude, marker.longitude)
            color = self._resolve_draw_color(marker.color)
            half = marker.size / 2
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
        #    are the two fields that can make saving fail later.
        if not self._save_base_name_value().strip():
            raise ValueError("Base Name is empty")
        self._parse_scale_percent(self._save_scale_value())

    def _build_settings_text(self) -> str:
        include_datetime = "true" if self._save_include_datetime_value() else "false"
        focus_on_alert = "true" if self._focus_on_alert_value() else "false"
        audible_alert = "true" if self._audible_alert_value() else "false"
        base_name = json.dumps(self._save_base_name_value(), ensure_ascii=False)
        scale_percent = json.dumps(self._save_scale_value())
        return (
            f"include_datetime: {include_datetime}\n"
            f"focus_on_alert: {focus_on_alert}\n"
            f"audible_alert: {audible_alert}\n"
            f"base_name: {base_name}\n"
            f"scale_percent: {scale_percent}\n"
        )

    def _parse_settings_text(self, text: str) -> dict[str, bool | str]:
        settings: dict[str, bool | str] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition(":")
            if not separator:
                continue

            normalized_key = key.strip()
            raw_value = value.strip()
            if normalized_key in {"include_datetime", "focus_on_alert", "audible_alert"}:
                settings[normalized_key] = raw_value.casefold() in {"true", "yes", "on", "1"}
            elif normalized_key in {"base_name", "scale_percent"}:
                settings[normalized_key] = self._parse_settings_string(raw_value)
        return settings

    def _parse_settings_string(self, raw_value: str) -> str:
        if not raw_value:
            return ""
        if raw_value[:1] in {'"', "'"}:
            return str(json.loads(raw_value)) if raw_value[:1] == '"' else str(ast.literal_eval(raw_value))
        return raw_value

    def _apply_save_settings(
        self,
        *,
        include_datetime: bool,
        base_name: str,
        scale: str,
        focus_on_alert: bool,
        audible_alert: bool,
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
