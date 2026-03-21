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

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class _MapBounds:
    min_lat: float = 29.45
    max_lat: float = 33.281
    min_lon: float = 34.20
    max_lon: float = 35.88


@dataclass(frozen=True)
class _ControlButtonSpec:
    label: str
    tooltip: str
    enabled: bool = True
    action: str | None = None


@dataclass(frozen=True)
class _DrawCommand:
    latitude: float
    longitude: float
    color: str
    shape: str
    size: int


class _Tooltip:
    def __init__(
        self,
        widgets: tuple[tk.Widget, ...],
        text: str,
        *,
        background: str,
        foreground: str,
        border: str,
    ) -> None:
        self.widgets = widgets
        self.text = text
        self.background = background
        self.foreground = foreground
        self.border = border
        self._tip_window: tk.Toplevel | None = None
        self._after_id: str | None = None
        self._anchor_widget: tk.Widget | None = None

        for widget in widgets:
            widget.bind("<Enter>", self._on_enter, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")
            widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, event: tk.Event) -> None:
        self._anchor_widget = event.widget
        self._schedule()

    def _on_leave(self, _event: tk.Event) -> None:
        self._cancel()
        self._hide()

    def _schedule(self) -> None:
        self._cancel()
        widget = self._anchor_widget
        if widget is None:
            return
        self._after_id = widget.after(180, self._show)

    def _cancel(self) -> None:
        widget = self._anchor_widget
        if widget is not None and self._after_id is not None:
            widget.after_cancel(self._after_id)
        self._after_id = None

    def _show(self) -> None:
        if self._tip_window is not None:
            return
        widget = self._anchor_widget
        if widget is None or not widget.winfo_exists():
            return

        x = widget.winfo_rootx() + max(8, widget.winfo_width() - 6)
        y = widget.winfo_rooty() + widget.winfo_height() + 8
        self._tip_window = tk.Toplevel(widget)
        self._tip_window.wm_overrideredirect(True)
        self._tip_window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self._tip_window,
            text=self.text,
            bg=self.background,
            fg=self.foreground,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=self.border,
            padx=10,
            pady=5,
            font=("TkDefaultFont", 9),
        )
        label.pack()

    def _hide(self) -> None:
        if self._tip_window is not None:
            self._tip_window.destroy()
            self._tip_window = None


class IsraelMap:
    """Display a background outline image of Israel and draw markers by lat/lon."""

    _ALLOWED_COLORS = {
        "white",
        "black",
        "blue",
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
        "red": "#d81e1e",
        "green": "#1f8b4c",
        "yellow": "#d9b11f",
        "gray": "#d3d3d3",
        "orange": "#ff9f1c",
    }
    _IMAGE_CANDIDATES = (
        "israel_outline.png",
    )
    _CONTROL_BUTTONS = (
        _ControlButtonSpec("Clear", "Clear Map", True, "clear_map"),
        _ControlButtonSpec("Save", "Save Map Image", True, "save_map_dialog"),
        _ControlButtonSpec("Exit", "Close", True, "close_app"),
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
    _STATUS_EDGE_MARGIN = 8
    _STATUS_STACK_GAP = 6
    _STATUS_PANEL_Y_OFFSET = 14
    _LOG_TEXT_Y_OFFSET = 6
    _STATUS_AND_BUTTON_FONT = ("TkDefaultFont", 11, "bold")

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
        self._control_window_id: int | None = None
        self._tooltips: list[_Tooltip] = []
        self._modal_dialog: tk.Toplevel | None = None
        self._log_time_background_id: int | None = None
        self._log_time_text_id: int | None = None
        self._watchdog_background_id: int | None = None
        self._watchdog_icon_id: int | None = None
        self._watchdog_text_id: int | None = None
        self._save_include_datetime_var: tk.BooleanVar | None = None
        self._save_base_name_var: tk.StringVar | None = None
        self._save_scale_var: tk.StringVar | None = None

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
            self._create_controls_overlay()
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

    def _finalize_close(self) -> None:
        if not self.root.winfo_exists():
            return
        try:
            self.root.destroy()
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

    def _create_controls_overlay(self) -> None:
        colors = self._CONTROL_COLORS
        control_bar = tk.Frame(
            self.canvas,
            bg=colors["panel_bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=colors["panel_border"],
            padx=6,
            pady=6,
        )

        last_index = len(self._CONTROL_BUTTONS) - 1
        for index, spec in enumerate(self._CONTROL_BUTTONS):
            slot = tk.Frame(control_bar, bg=colors["panel_bg"])
            slot.pack(side="left", padx=(0, 8 if index < last_index else 0))
            button = tk.Button(
                slot,
                text=spec.label,
                command=self._resolve_control_command(spec.action),
                state=tk.NORMAL if spec.enabled else tk.DISABLED,
                width=6,
                padx=8,
                pady=3,
                bd=0,
                relief="flat",
                font=self._STATUS_AND_BUTTON_FONT,
                bg=colors["button_bg"] if spec.enabled else colors["button_disabled_bg"],
                fg=colors["button_fg"],
                activebackground=colors["button_active_bg"],
                activeforeground=colors["button_active_fg"],
                disabledforeground=colors["button_disabled_fg"],
                highlightthickness=0,
                cursor="hand2" if spec.enabled else "arrow",
                takefocus=False,
            )
            button.pack()
            self._tooltips.append(
                _Tooltip(
                    (slot, button),
                    spec.tooltip,
                    background=colors["tooltip_bg"],
                    foreground=colors["tooltip_fg"],
                    border=colors["tooltip_border"],
                )
            )

        self._control_window_id = self.canvas.create_window(
            8,
            8,
            anchor="nw",
            window=control_bar,
        )
        self._raise_controls()

    def _raise_controls(self) -> None:
        self._raise_overlays()

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
        if self._control_window_id is not None:
            self.canvas.tag_raise(self._control_window_id)

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
        #    the window height and stays separated from the control buttons.
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

    def _resolve_control_command(self, action: str | None) -> callable:
        if action == "clear_map":
            return self._clear_map_control
        if action == "save_map_dialog":
            return self._open_save_dialog_control
        if action == "close_app":
            return self._close_app_control
        return self._noop_control

    def _clear_map_control(self) -> None:
        self.reset(refresh=True)

    def _open_save_dialog_control(self) -> None:
        if self._modal_dialog is not None and self._modal_dialog.winfo_exists():
            self._modal_dialog.lift()
            self._modal_dialog.focus_force()
            return

        self._load_save_settings()
        colors = self._CONTROL_COLORS
        dialog = tk.Toplevel(self.root)
        dialog.title("Save Map Image")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg="#eef0f2")
        dialog.protocol("WM_DELETE_WINDOW", self._close_modal_dialog)

        body = tk.Frame(dialog, bg="#eef0f2", padx=18, pady=16)
        body.pack(fill="both", expand=True)

        form_panel = tk.Frame(
            body,
            width=260,
            height=150,
            bg="#f7f8f9",
            highlightthickness=1,
            highlightbackground="#c8cdd2",
            padx=14,
            pady=14,
        )
        form_panel.pack(fill="both", expand=True)
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
            text="Include Data/Time",
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
            text="Ok",
            command=self._handle_save_dialog_ok,
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

        self._modal_dialog = dialog
        dialog.grab_set()
        base_name_entry.focus_force()
        base_name_entry.icursor("end")

    def _close_modal_dialog(self) -> None:
        if self._modal_dialog is None:
            return
        dialog = self._modal_dialog
        self._modal_dialog = None
        if dialog.winfo_exists():
            dialog.grab_release()
            dialog.destroy()

    def _close_app_control(self) -> None:
        self.close()

    def _handle_save_dialog_ok(self) -> None:
        self._save_settings_to_disk()
        self._save_map_image_to_disk()
        self._close_modal_dialog()

    def _load_save_settings(self) -> None:
        self._apply_save_settings(
            include_datetime=self._DEFAULT_SAVE_INCLUDE_DATETIME,
            base_name=self._DEFAULT_SAVE_BASE_NAME,
            scale=self._DEFAULT_SAVE_SCALE,
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

    def _build_settings_text(self) -> str:
        include_datetime = "true" if self._save_include_datetime_value() else "false"
        base_name = json.dumps(self._save_base_name_value(), ensure_ascii=False)
        scale_percent = json.dumps(self._save_scale_value())
        return (
            f"include_datetime: {include_datetime}\n"
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
            if normalized_key == "include_datetime":
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

    def _apply_save_settings(self, *, include_datetime: bool, base_name: str, scale: str) -> None:
        if self._save_include_datetime_var is not None:
            self._save_include_datetime_var.set(bool(include_datetime))
        if self._save_base_name_var is not None:
            self._save_base_name_var.set(base_name)
        if self._save_scale_var is not None:
            self._save_scale_var.set(scale)

    def _save_include_datetime_value(self) -> bool:
        return bool(self._save_include_datetime_var.get()) if self._save_include_datetime_var is not None else False

    def _save_base_name_value(self) -> str:
        return self._save_base_name_var.get() if self._save_base_name_var is not None else self._DEFAULT_SAVE_BASE_NAME

    def _save_scale_value(self) -> str:
        return self._save_scale_var.get() if self._save_scale_var is not None else self._DEFAULT_SAVE_SCALE

    def _log_failure(self, message: str, exc: Exception) -> None:
        try:
            from utils import log

            log(f"{message}: {exc}")
        except Exception:
            pass

    def _noop_control(self) -> None:
        return None

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
