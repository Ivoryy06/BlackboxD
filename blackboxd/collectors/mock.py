"""
blackboxd.collectors.mock
~~~~~~~~~~~~~~~~~~~~~~~~~
Deterministic fake collector for unit tests and offline development.

Replays a scripted sequence of window-focus events on a configurable
clock. Because it controls its own clock, tests don't need to sleep.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

from blackboxd.collectors.base import BaseCollector, WindowInfo
from blackboxd.config import CollectorConfig
from blackboxd.models import RawEvent



ScriptEntry = tuple[float, WindowInfo | None, float]


DEFAULT_SCRIPT: list[ScriptEntry] = [
    (0,    WindowInfo("Terminal",   "kitty",       "~/projects/blackboxd",   "1"), 0),
    (30,   WindowInfo("Firefox",    "firefox",     "GitHub — blackboxd",      "1"), 0),
    (90,   WindowInfo("Terminal",   "kitty",       "vim models.py",           "1"), 0),
    (200,  WindowInfo("Slack",      "slack",       "# general",               "1"), 0),
    (260,  WindowInfo("Terminal",   "kitty",       "vim models.py",           "1"), 0),
    (900,  WindowInfo("Terminal",   "kitty",       "vim models.py",           "1"), 180),  
    (1080, WindowInfo("Firefox",    "firefox",     "Hacker News",             "2"), 0),
    (1200, WindowInfo("Obsidian",   "obsidian",    "Daily notes",             "2"), 0),
    (1800, WindowInfo("Terminal",   "kitty",       "pytest -v",               "1"), 0),
    (2100, None,                                                                    600),  
    (2700, WindowInfo("Firefox",    "firefox",     "MDN — Python docs",       "1"), 0),
]


class MockCollector(BaseCollector):
    """Replays a scripted sequence of window events.

    Attributes:
        script:  List of (offset_seconds, WindowInfo | None, idle_secs) tuples.
        speed:   Clock multiplier. 2.0 = events play back at 2× real time.
        frozen:  If True, the clock is paused at a fixed timestamp (for pure
                 unit tests that don't want time to advance).
    """

    NAME = "mock"

    def __init__(
        self,
        config: CollectorConfig,
        script: list[ScriptEntry] | None = None,
        speed:  float = 1.0,
        frozen: bool  = False,
        start_ts: float | None = None,
    ) -> None:
        super().__init__(config)
        self._script     = script or DEFAULT_SCRIPT
        self._speed      = speed
        self._frozen     = frozen
        self._start_real = time.time()
        self._start_ts   = start_ts or self._start_real
        self._script_idx = 0

    def is_available(self) -> bool:
        return True

    
    
    

    @property
    def _elapsed(self) -> float:
        if self._frozen:
            return 0.0
        return (time.time() - self._start_real) * self._speed

    @property
    def _now_ts(self) -> float:
        return self._start_ts + self._elapsed

    
    
    

    def get_active_window(self) -> WindowInfo | None:
        entry = self._current_entry()
        return entry[1] if entry else None

    def get_idle_seconds(self) -> float:
        entry = self._current_entry()
        return entry[2] if entry else 0.0

    
    
    

    def _current_entry(self) -> ScriptEntry | None:
        elapsed = self._elapsed
        
        active: ScriptEntry | None = None
        for entry in self._script:
            if entry[0] <= elapsed:
                active = entry
            else:
                break
        return active

    
    
    

    def replay_all(self, base_ts: float | None = None) -> Iterator[RawEvent]:
        """Yield all scripted events without sleeping, using provided timestamps."""
        ts = base_ts or self._start_ts
        prev_window: WindowInfo | None = None

        for offset, window, idle in self._script:
            event_ts = ts + offset

            if idle > 0:
                yield RawEvent(
                    kind=__import__("blackboxd.models", fromlist=["EventKind"]).EventKind.IDLE_START,
                    timestamp=event_ts,
                    source=self.NAME,
                    payload={"idle_seconds": idle},
                )

            if window is not None and window != prev_window:
                yield RawEvent(
                    kind=__import__("blackboxd.models", fromlist=["EventKind"]).EventKind.WINDOW_FOCUS,
                    timestamp=event_ts + idle,
                    source=self.NAME,
                    payload={
                        "app_name":  window.app_name,
                        "app_class": window.app_class,
                        "title":     window.title,
                        "workspace": window.workspace,
                    },
                )
                prev_window = window
