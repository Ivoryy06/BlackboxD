"""
blackboxd.collectors.base
~~~~~~~~~~~~~~~~~~~~~~~~~
Abstract base for all collector backends, plus the event normalizer that
converts raw collector payloads into canonical Event objects.

Every new environment (Hyprland, GNOME, X11, Wayland-generic, macOS, …)
is a subclass of BaseCollector. The daemon only talks to BaseCollector;
it never imports a concrete backend directly.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

from blackboxd.config.config import CollectorConfig
from blackboxd.models import Event, EventKind, RawEvent

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Window-info snapshot — what every collector must be able to return
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class WindowInfo:
    """The currently focused window, as seen by the compositor / WM."""
    app_name:  str | None   # human name, e.g. "Firefox"
    app_class: str | None   # WM_CLASS or app-id, e.g. "firefox"
    title:     str | None   # window title
    workspace: str | None   # workspace / desktop identifier


# ---------------------------------------------------------------------------
# Abstract base collector
# ---------------------------------------------------------------------------

class BaseCollector(ABC):
    """Interface every collector backend must implement.

    Lifecycle::

        collector.setup()
        while running:
            events = list(collector.poll())
            ...
        collector.teardown()

    Or use as a context manager (calls setup/teardown automatically).
    """

    NAME: str = "base"  # override in each subclass

    def __init__(self, config: CollectorConfig) -> None:
        self.config = config
        self._last_window: WindowInfo | None = None
        self._idle_start_ts: float | None = None

    # ---- lifecycle -------------------------------------------------------

    def setup(self) -> None:
        """Called once before polling begins. Override to open connections."""

    def teardown(self) -> None:
        """Called once when the daemon shuts down. Override to close connections."""

    def __enter__(self) -> "BaseCollector":
        self.setup()
        return self

    def __exit__(self, *_: object) -> None:
        self.teardown()

    # ---- required API ----------------------------------------------------

    @abstractmethod
    def get_active_window(self) -> WindowInfo | None:
        """Return info about the currently focused window, or None if unknown."""

    @abstractmethod
    def get_idle_seconds(self) -> float:
        """Return seconds since the last user input event (keyboard / mouse)."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this backend can run in the current environment."""

    # ---- polling ---------------------------------------------------------

    def poll(self) -> Iterator[RawEvent]:
        """Produce zero or more RawEvents reflecting changes since last call.

        The daemon calls this on every tick. The base implementation handles
        window-focus change detection and idle start/end detection; subclasses
        should not need to override this method.
        """
        import time

        now_ts = time.time()
        window = self.get_active_window()
        idle   = self.get_idle_seconds()

        # --- idle detection ---
        if idle >= self.config.idle_threshold:
            if self._idle_start_ts is None:
                # Transition: active → idle
                self._idle_start_ts = now_ts - idle  # backdate to actual start
                yield RawEvent(
                    kind=EventKind.IDLE_START,
                    timestamp=self._idle_start_ts,
                    source=self.NAME,
                    payload={"idle_seconds": idle},
                )
        else:
            if self._idle_start_ts is not None:
                # Transition: idle → active
                duration = now_ts - self._idle_start_ts
                self._idle_start_ts = None
                yield RawEvent(
                    kind=EventKind.IDLE_END,
                    timestamp=now_ts,
                    source=self.NAME,
                    payload={"idle_seconds": duration},
                )

        # --- window-focus detection ---
        if self._idle_start_ts is not None:
            # Don't emit focus events while idle
            return

        if window is not None and window != self._last_window:
            self._last_window = window
            if not self._is_ignored(window):
                yield RawEvent(
                    kind=EventKind.WINDOW_FOCUS,
                    timestamp=now_ts,
                    source=self.NAME,
                    payload={
                        "app_name":  window.app_name,
                        "app_class": window.app_class,
                        "title":     window.title,
                        "workspace": window.workspace,
                    },
                )

    def _is_ignored(self, window: WindowInfo) -> bool:
        """Return True if this window should be filtered out per config."""
        ignore = {a.lower() for a in self.config.ignore_apps}
        name  = (window.app_name  or "").lower()
        klass = (window.app_class or "").lower()
        return name in ignore or klass in ignore


# ---------------------------------------------------------------------------
# Normalizer: RawEvent → Event
# ---------------------------------------------------------------------------

class Normalizer:
    """Converts raw collector events into canonical Event objects.

    Applies privacy filters (title suppression, hashing) defined in config.
    """

    def __init__(self, config: CollectorConfig) -> None:
        self.config = config

    def normalize(self, raw: RawEvent) -> Event:
        p = raw.payload

        title = p.get("title")
        if title and self.config.suppress_titles:
            title = None
        elif title and self.config.hash_titles:
            title = _sha256_short(title)
        elif title:
            title = title[: self.config.__dict__.get("title_max_length", 120)]

        return Event(
            kind         = raw.kind,
            timestamp    = raw.timestamp,
            collector    = raw.source,
            app_name     = p.get("app_name"),
            app_class    = p.get("app_class"),
            window_title = title,
            workspace    = p.get("workspace"),
            idle_seconds = p.get("idle_seconds"),
        )

    def normalize_many(self, raws: list[RawEvent]) -> list[Event]:
        return [self.normalize(r) for r in raws]


def _sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]
