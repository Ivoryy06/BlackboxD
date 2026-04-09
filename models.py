"""
blackboxd.models
~~~~~~~~~~~~~~~~
Canonical data types. Everything the daemon records and the timeline
reconstructor consumes is expressed as these types. No external deps.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


# ---------------------------------------------------------------------------
# Event kinds
# ---------------------------------------------------------------------------

class EventKind(str, Enum):
    """All event categories the system can record.

    String-valued so they survive round-trips through SQLite without a
    lookup table.
    """
    WINDOW_FOCUS     = "window_focus"      # active window changed
    WINDOW_CLOSE     = "window_close"      # a window was closed
    WINDOW_OPEN      = "window_open"       # a new window appeared
    IDLE_START       = "idle_start"        # input stopped for threshold
    IDLE_END         = "idle_end"          # input resumed
    WORKSPACE_SWITCH = "workspace_switch"  # moved to a different workspace / virtual desktop
    APP_LAUNCH       = "app_launch"        # application process started
    APP_EXIT         = "app_exit"          # application process exited
    LOCK_START       = "lock_start"        # screen locked
    LOCK_END         = "lock_end"          # screen unlocked
    DAEMON_START     = "daemon_start"      # blackboxd started recording
    DAEMON_STOP      = "daemon_stop"       # blackboxd stopped recording


# ---------------------------------------------------------------------------
# Raw event — what collectors emit
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RawEvent:
    """An event as produced by a collector, before normalization.

    Attributes:
        kind:       What happened.
        timestamp:  Unix epoch seconds (float for sub-second precision).
        source:     Which collector produced this (e.g. "hyprland", "xprop").
        payload:    Arbitrary key-value data; collector-specific.
    """
    kind:      EventKind
    timestamp: float
    source:    str
    payload:   dict[str, Any] = field(default_factory=dict)

    @classmethod
    def now(cls, kind: EventKind, source: str, **payload: Any) -> "RawEvent":
        return cls(kind=kind, timestamp=time.time(), source=source, payload=payload)


# ---------------------------------------------------------------------------
# Normalized event — storage-ready, collector-agnostic
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Event:
    """A normalized, storage-ready event.

    Fields are flat and typed so they map cleanly to SQLite columns.
    Optional fields are None when not applicable.

    Attributes:
        id:             Monotonically increasing integer, assigned by storage.
        kind:           Event category.
        timestamp:      Unix epoch seconds.
        app_name:       Human-readable application name (e.g. "Firefox").
        app_class:      WM_CLASS or equivalent (e.g. "firefox").
        window_title:   Active window title at event time.
        workspace:      Workspace / virtual desktop identifier.
        idle_seconds:   For IDLE_* events, how long the idle period lasted.
        collector:      Which collector produced this.
    """
    kind:         EventKind
    timestamp:    float
    collector:    str
    id:           int | None    = None
    app_name:     str | None    = None
    app_class:    str | None    = None
    window_title: str | None    = None
    workspace:    str | None    = None
    idle_seconds: float | None  = None

    @property
    def datetime(self) -> str:
        """ISO-8601 local datetime string for display."""
        import datetime
        return datetime.datetime.fromtimestamp(self.timestamp).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Session — a contiguous block of activity in one app
# ---------------------------------------------------------------------------

class FocusQuality(str, Enum):
    """Rough classification of a session's focus depth.

    Thresholds are calibrated to typical knowledge-worker patterns.
    """
    DEEP      = "deep"       # >25 min uninterrupted
    SUSTAINED = "sustained"  # 10–25 min
    SHALLOW   = "shallow"    # 3–10 min
    GLANCE    = "glance"     # <3 min


@dataclass
class Session:
    """A contiguous span of time in a single application.

    A new session starts whenever the active window switches to a different
    app, or after an idle gap longer than the configured split threshold.

    Attributes:
        app_name:       Application name.
        app_class:      WM class / identifier.
        start:          Session start (Unix epoch seconds).
        end:            Session end, or None if ongoing.
        titles:         Window titles seen during the session (ordered).
        workspace:      Workspace where the session occurred.
        idle_gap_after: Idle duration following this session, if any.
    """
    app_name:       str
    app_class:      str
    start:          float
    end:            float | None       = None
    titles:         list[str]          = field(default_factory=list)
    workspace:      str | None         = None
    idle_gap_after: float | None       = None

    # ---- derived --------------------------------------------------------

    @property
    def duration(self) -> float:
        """Elapsed seconds. Returns 0 if session is still open."""
        if self.end is None:
            return 0.0
        return self.end - self.start

    @property
    def focus_quality(self) -> FocusQuality:
        d = self.duration / 60  # minutes
        if d >= 25:
            return FocusQuality.DEEP
        if d >= 10:
            return FocusQuality.SUSTAINED
        if d >= 3:
            return FocusQuality.SHALLOW
        return FocusQuality.GLANCE

    @property
    def primary_title(self) -> str | None:
        """Most recently seen window title."""
        return self.titles[-1] if self.titles else None

    def fmt_duration(self) -> str:
        s = int(self.duration)
        if s < 60:
            return f"{s}s"
        m, s = divmod(s, 60)
        if m < 60:
            return f"{m}m {s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h {m:02d}m"


# ---------------------------------------------------------------------------
# Timeline — a reconstructed view of a time range
# ---------------------------------------------------------------------------

@dataclass
class TimelineDay:
    """All reconstructed activity for a single calendar day.

    Attributes:
        date:           ISO date string (YYYY-MM-DD).
        sessions:       Ordered list of sessions, oldest first.
        total_active:   Total seconds across all sessions.
        total_idle:     Total seconds idle.
        switches:       Number of app switches.
        top_apps:       {app_name: seconds} sorted descending by time.
    """
    date:         str
    sessions:     list[Session]        = field(default_factory=list)
    total_active: float                = 0.0
    total_idle:   float                = 0.0
    switches:     int                  = 0
    top_apps:     dict[str, float]     = field(default_factory=dict)

    def summary_line(self) -> str:
        active_h = self.total_active / 3600
        top = list(self.top_apps.items())[:3]
        top_str = ", ".join(f"{a} ({int(s//60)}m)" for a, s in top)
        return (
            f"{self.date} — "
            f"{active_h:.1f}h active, "
            f"{self.switches} switches"
            + (f" — top: {top_str}" if top_str else "")
        )
