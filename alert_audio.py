"""Asynchronous audio playback for alert notifications."""

from __future__ import annotations

import os
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Callable


class AudioAlertPlayer:
    _INITIALIZATION_WAIT_SECONDS = 0.5

    def __init__(self, sound_path: Path, *, log_fn: Callable[[str], None] | None = None) -> None:
        # 1. Keep the configuration tiny: one fixed sound file and one optional
        #    logger are all this app currently needs for audible alerts.
        # 2. Resolve the path early so later playback requests do not depend on
        #    the current working directory.
        self._sound_path = Path(sound_path).expanduser().resolve()
        self._log_fn = log_fn
        self._commands: Queue[str | None] = Queue()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._ready = Event()
        self._available = False
        self._start_failed = False

    def warm_up(self) -> bool:
        # 1. Prime the backend ahead of the first real alert so the operator
        #    does not lose the first sound to lazy initialization delays.
        # 2. Return the current availability so callers can decide whether they
        #    need a fallback notification path.
        if self._start_failed:
            return False
        self._ensure_started(wait=True)
        return self._available

    def play(self) -> bool:
        # 1. Keep the UI thread non-blocking by enqueueing the request and
        #    letting the worker own all audio-library interaction after startup.
        # 2. Return whether an mp3 play request was actually accepted so the
        #    caller can fall back to a simpler notification if needed.
        if self._start_failed:
            return False
        self._ensure_started(wait=True)
        if self._start_failed or not self._available:
            return False
        self._commands.put("play")
        return True

    def close(self) -> None:
        # 1. Let shutdown stay best-effort because the app should still exit
        #    cleanly even if the audio backend is unavailable.
        # 2. Join only briefly so a stuck audio backend cannot block exit.
        thread = self._thread
        if thread is None:
            return
        self._commands.put(None)
        thread.join(timeout=1.0)

    def _ensure_started(self, *, wait: bool) -> None:
        if self._thread is not None or self._start_failed:
            if wait and self._thread is not None:
                self._ready.wait(timeout=self._INITIALIZATION_WAIT_SECONDS)
            return
        with self._lock:
            if self._thread is not None or self._start_failed:
                if wait and self._thread is not None:
                    self._ready.wait(timeout=self._INITIALIZATION_WAIT_SECONDS)
                return
            worker = Thread(target=self._worker, name="alert-audio", daemon=True)
            self._thread = worker
            worker.start()
        if wait:
            self._ready.wait(timeout=self._INITIALIZATION_WAIT_SECONDS)

    def _worker(self) -> None:
        # 1. Hide pygame's startup banner so it does not pollute the operator's
        #    terminal output every time the program starts.
        # 2. Load the mp3 once and replay it on demand so alert notification
        #    stays fast after the first trigger.
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import pygame
        except Exception as exc:
            self._mark_failed(f"Could not import pygame for audio alerts: {exc}")
            return

        try:
            pygame.mixer.init()
            pygame.mixer.music.load(str(self._sound_path))
        except Exception as exc:
            self._mark_failed(f"Could not initialize audio alerts: {exc}")
            try:
                pygame.mixer.quit()
            except Exception:
                pass
            return
        self._available = True
        self._ready.set()

        try:
            while True:
                command = self._commands.get()
                if command is None:
                    break
                self._drain_play_burst()
                try:
                    pygame.mixer.music.stop()
                    pygame.mixer.music.play()
                except Exception as exc:
                    self._log_once(f"Could not play audio alert: {exc}")
        finally:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            try:
                pygame.mixer.quit()
            except Exception:
                pass

    def _drain_play_burst(self) -> None:
        # 1. Coalesce stacked play requests so a burst of alerts produces one
        #    immediate replay instead of a queued-up train of repeated sounds.
        while True:
            try:
                command = self._commands.get_nowait()
            except Empty:
                return
            if command is None:
                self._commands.put(None)
                return

    def _mark_failed(self, message: str) -> None:
        self._start_failed = True
        self._ready.set()
        self._log_once(message)

    def _log_once(self, message: str) -> None:
        if self._log_fn is None:
            return
        self._log_fn(message)
