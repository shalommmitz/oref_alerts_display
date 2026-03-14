"""Standalone module for drawing markers on an outline map of Israel."""

from __future__ import annotations

import base64
import io
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class _MapBounds:
    min_lat: float = 29.45
    max_lat: float = 33.281
    min_lon: float = 34.20
    max_lon: float = 35.88


class IsraelMap:
    """Display a background outline image of Israel and draw markers by lat/lon."""

    _ALLOWED_COLORS = {
        "white",
        "black",
        "blue",
        "red",
        "green",
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
        "gray": "#d3d3d3",
        "orange": "#ff9f1c",
    }
    _X_OFFSET = -8.0
    _LATITUDE_X_SHEAR = 4.5
    _LONGITUDE_Y_SHEAR = 18.0
    _Y_OFFSET = 10.0
    _IMAGE_CANDIDATES = (
        "israel_outline.png",
        "Israel_outline.png",
        "israel_outline.jpg",
        "israel_outline.jpeg",
    )

    def __init__(
        self,
        width: int | None = None,
        height: int | None = None,
        title: str = "Israel Map",
        image_path: str | Path | None = None,
        auto_refresh: bool = True,
        padding: int = 20,
    ) -> None:
        self.title = title
        self.auto_refresh = auto_refresh
        self.padding = max(0, padding)
        self.bounds = _MapBounds()
        self._closed = False
        self._drawn_items: list[int] = []

        resolved_image_path = self._resolve_background_path(image_path)
        self._background_image = Image.open(resolved_image_path).convert("RGB")
        if width is not None or height is not None:
            target_width = width if width is not None else self._background_image.width
            target_height = height if height is not None else self._background_image.height
            self._background_image = self._background_image.resize(
                (target_width, target_height),
                Image.Resampling.LANCZOS,
            )
        if self.padding:
            self._background_image = self._pad_image(self._background_image, self.padding)

        self.width = self._background_image.width
        self.height = self._background_image.height
        self.background_color = self._rgb_to_hex(self._background_image.getpixel((0, 0)))
        self._map_bbox = self._detect_map_bbox(self._background_image)

        self.root = tk.Tk()
        self.root.title(self.title)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
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
    ) -> None:
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

        self._drawn_items.append(item_id)
        if refresh is None:
            refresh = self.auto_refresh
        if refresh:
            self.process_events()

    def reset(self, refresh: bool | None = None) -> None:
        """Restore the canvas to the original image-only state."""
        for item_id in self._drawn_items:
            self.canvas.delete(item_id)
        self._drawn_items.clear()
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
        if not self._closed and self.root.winfo_exists():
            self._closed = True
            self.root.destroy()

    def _latlon_to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        left, top, right, bottom = self._map_bbox
        lon_ratio = (lon - self.bounds.min_lon) / (self.bounds.max_lon - self.bounds.min_lon)
        lat_ratio = (self.bounds.max_lat - lat) / (self.bounds.max_lat - self.bounds.min_lat)
        x = left + lon_ratio * (right - left)
        y = top + lat_ratio * (bottom - top)
        x -= self._LATITUDE_X_SHEAR * (lat - self.bounds.min_lat)
        x += self._X_OFFSET
        y += self._LONGITUDE_Y_SHEAR * (lon - self.bounds.min_lon)
        y += self._Y_OFFSET
        return x, y

    def _detect_map_bbox(self, image: Image.Image) -> tuple[int, int, int, int]:
        grayscale = image.convert("L")
        threshold = 245
        dark_pixels = [
            (x, y)
            for y in range(grayscale.height)
            for x in range(grayscale.width)
            if grayscale.getpixel((x, y)) < threshold
        ]
        if not dark_pixels:
            return 0, 0, self.width - 1, self.height - 1

        xs = [x for x, _ in dark_pixels]
        ys = [y for _, y in dark_pixels]
        return min(xs), min(ys), max(xs), max(ys)

    def _create_photo_image(self, image: Image.Image) -> tk.PhotoImage:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return tk.PhotoImage(data=encoded)

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
