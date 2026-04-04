"""Best-effort restoration of the previously fullscreen X11 window."""

from __future__ import annotations

import ctypes
import os


_CLIENT_MESSAGE = 33
_SUBSTRUCTURE_NOTIFY_MASK = 1 << 19
_SUBSTRUCTURE_REDIRECT_MASK = 1 << 20
_NET_WM_STATE_ADD = 1
_NET_ACTIVE_WINDOW_SOURCE_PAGER = 2
_ANY_PROPERTY_TYPE = 0
_SUCCESS = 0


class _ClientMessageData(ctypes.Union):
    _fields_ = (
        ("b", ctypes.c_char * 20),
        ("s", ctypes.c_short * 10),
        ("l", ctypes.c_long * 5),
    )


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = (
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", _ClientMessageData),
    )


class _XEvent(ctypes.Union):
    _fields_ = (
        ("xclient", _XClientMessageEvent),
        ("pad", ctypes.c_long * 24),
    )


class X11FullscreenRestorer:
    def __init__(self) -> None:
        self._library = self._load_x11_library()
        self._active_window_atom: int | None = None
        self._wm_state_atom: int | None = None
        self._fullscreen_atom: int | None = None
        self._saved_fullscreen_window_id: int | None = None

    def note_pre_focus_window(self, own_window_id: int) -> None:
        # 1. Record the currently active fullscreen window before the alert map
        #    raises itself, so `Send to Back` can restore that app afterward.
        # 2. If the active window is already this Tk window, preserve the previous
        #    snapshot instead of overwriting it with self-reference.
        if self._library is None:
            return
        display = self._open_display()
        if display is None:
            return
        try:
            if not self._ensure_atoms(display):
                return
            root_window = self._root_window(display)
            if root_window is None:
                return
            active_window_id = self._read_single_window_property(
                display,
                root_window,
                self._active_window_atom,
            )
            if active_window_id is None or active_window_id == own_window_id:
                return
            if self._window_has_fullscreen_state(display, active_window_id):
                self._saved_fullscreen_window_id = active_window_id
            else:
                self._saved_fullscreen_window_id = None
        finally:
            self._library.XCloseDisplay(display)

    def restore_saved_fullscreen_window(self, own_window_id: int) -> None:
        # 1. Re-activate the previously captured fullscreen window after lowering
        #    the alert map so the operator returns to the interrupted application.
        # 2. Re-assert `_NET_WM_STATE_FULLSCREEN` because some window managers may
        #    have dropped or visually disrupted that state when this map was raised.
        target_window_id = self._saved_fullscreen_window_id
        self._saved_fullscreen_window_id = None
        if (
            self._library is None
            or target_window_id is None
            or target_window_id == own_window_id
        ):
            return
        display = self._open_display()
        if display is None:
            return
        try:
            if not self._ensure_atoms(display):
                return
            root_window = self._root_window(display)
            if root_window is None:
                return
            self._send_wm_state_fullscreen_request(
                display,
                root_window,
                target_window_id,
            )
            self._send_activate_window_request(
                display,
                root_window,
                target_window_id,
            )
            self._library.XFlush(display)
        finally:
            self._library.XCloseDisplay(display)

    def _load_x11_library(self):
        # 1. Keep this helper optional: if libX11 cannot be loaded or DISPLAY is
        #    absent, the rest of the application should continue with normal Tk
        #    raise/lower behavior.
        # 2. Configure ctypes signatures once so later property/event calls stay
        #    explicit and do not rely on platform-default argument conversions.
        if not os.environ.get("DISPLAY"):
            return None
        try:
            library = ctypes.CDLL("libX11.so.6")
        except OSError:
            return None

        library.XOpenDisplay.argtypes = [ctypes.c_char_p]
        library.XOpenDisplay.restype = ctypes.c_void_p
        library.XCloseDisplay.argtypes = [ctypes.c_void_p]
        library.XCloseDisplay.restype = ctypes.c_int
        library.XDefaultScreen.argtypes = [ctypes.c_void_p]
        library.XDefaultScreen.restype = ctypes.c_int
        library.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        library.XRootWindow.restype = ctypes.c_ulong
        library.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        library.XInternAtom.restype = ctypes.c_ulong
        library.XGetWindowProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        library.XGetWindowProperty.restype = ctypes.c_int
        library.XFree.argtypes = [ctypes.c_void_p]
        library.XFree.restype = ctypes.c_int
        library.XSendEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_long,
            ctypes.POINTER(_XEvent),
        ]
        library.XSendEvent.restype = ctypes.c_int
        library.XFlush.argtypes = [ctypes.c_void_p]
        library.XFlush.restype = ctypes.c_int
        return library

    def _open_display(self):
        try:
            return self._library.XOpenDisplay(None)
        except Exception:
            return None

    def _root_window(self, display) -> int | None:
        try:
            screen_number = self._library.XDefaultScreen(display)
            return int(self._library.XRootWindow(display, screen_number))
        except Exception:
            return None

    def _ensure_atoms(self, display) -> bool:
        if (
            self._active_window_atom is not None
            and self._wm_state_atom is not None
            and self._fullscreen_atom is not None
        ):
            return True

        self._active_window_atom = self._intern_atom(display, b"_NET_ACTIVE_WINDOW")
        self._wm_state_atom = self._intern_atom(display, b"_NET_WM_STATE")
        self._fullscreen_atom = self._intern_atom(display, b"_NET_WM_STATE_FULLSCREEN")
        return (
            self._active_window_atom is not None
            and self._wm_state_atom is not None
            and self._fullscreen_atom is not None
        )

    def _intern_atom(self, display, atom_name: bytes) -> int | None:
        try:
            atom = int(self._library.XInternAtom(display, atom_name, False))
        except Exception:
            return None
        return atom or None

    def _read_single_window_property(
        self,
        display,
        window_id: int,
        property_atom: int,
    ) -> int | None:
        values = self._read_window_property_values(display, window_id, property_atom)
        if not values:
            return None
        return int(values[0]) or None

    def _window_has_fullscreen_state(self, display, window_id: int) -> bool:
        if self._fullscreen_atom is None:
            return False
        values = self._read_window_property_values(display, window_id, self._wm_state_atom)
        return self._fullscreen_atom in values

    def _read_window_property_values(
        self,
        display,
        window_id: int,
        property_atom: int,
    ) -> tuple[int, ...]:
        actual_type = ctypes.c_ulong()
        actual_format = ctypes.c_int()
        nitems = ctypes.c_ulong()
        bytes_after = ctypes.c_ulong()
        property_data = ctypes.POINTER(ctypes.c_ubyte)()

        try:
            status = self._library.XGetWindowProperty(
                display,
                ctypes.c_ulong(window_id),
                ctypes.c_ulong(property_atom),
                0,
                1024,
                False,
                _ANY_PROPERTY_TYPE,
                ctypes.byref(actual_type),
                ctypes.byref(actual_format),
                ctypes.byref(nitems),
                ctypes.byref(bytes_after),
                ctypes.byref(property_data),
            )
        except Exception:
            return ()
        if status != _SUCCESS or not property_data or nitems.value == 0:
            if property_data:
                self._library.XFree(property_data)
            return ()

        try:
            if actual_format.value != 32:
                return ()
            value_array = ctypes.cast(
                property_data,
                ctypes.POINTER(ctypes.c_ulong),
            )
            return tuple(int(value_array[index]) for index in range(nitems.value))
        finally:
            self._library.XFree(property_data)

    def _send_activate_window_request(
        self,
        display,
        root_window: int,
        target_window_id: int,
    ) -> None:
        if self._active_window_atom is None:
            return
        event = _XEvent()
        event.xclient.type = _CLIENT_MESSAGE
        event.xclient.serial = 0
        event.xclient.send_event = True
        event.xclient.display = display
        event.xclient.window = target_window_id
        event.xclient.message_type = self._active_window_atom
        event.xclient.format = 32
        event.xclient.data.l[0] = _NET_ACTIVE_WINDOW_SOURCE_PAGER
        event.xclient.data.l[1] = 0
        event.xclient.data.l[2] = 0
        event.xclient.data.l[3] = 0
        event.xclient.data.l[4] = 0
        self._send_root_client_message(display, root_window, event)

    def _send_wm_state_fullscreen_request(
        self,
        display,
        root_window: int,
        target_window_id: int,
    ) -> None:
        if self._wm_state_atom is None or self._fullscreen_atom is None:
            return
        event = _XEvent()
        event.xclient.type = _CLIENT_MESSAGE
        event.xclient.serial = 0
        event.xclient.send_event = True
        event.xclient.display = display
        event.xclient.window = target_window_id
        event.xclient.message_type = self._wm_state_atom
        event.xclient.format = 32
        event.xclient.data.l[0] = _NET_WM_STATE_ADD
        event.xclient.data.l[1] = self._fullscreen_atom
        event.xclient.data.l[2] = 0
        event.xclient.data.l[3] = _NET_ACTIVE_WINDOW_SOURCE_PAGER
        event.xclient.data.l[4] = 0
        self._send_root_client_message(display, root_window, event)

    def _send_root_client_message(self, display, root_window: int, event: _XEvent) -> None:
        try:
            self._library.XSendEvent(
                display,
                ctypes.c_ulong(root_window),
                False,
                _SUBSTRUCTURE_REDIRECT_MASK | _SUBSTRUCTURE_NOTIFY_MASK,
                ctypes.byref(event),
            )
        except Exception:
            return
