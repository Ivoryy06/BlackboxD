"""
blackboxd.timeline.reconstructor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Reconstructs a human-readable behavioral timeline from raw stored events.

The algorithm is deliberately simple and stateless: given a sorted list
of events, it makes a single left-to-right pass and emits Sessions.

Session boundaries:
  - App switch:  a WINDOW_FOCUS event with a different app_class than the
                 current session's app.
  - Idle split:  an IDLE_END event whose idle_seconds exceeded the configured
                 session_split_threshold. The preceding session is closed
                 at the idle start time; the following session opens at idle end.

Sessions shorter than min_session_duration are discarded (browser
tab flashes, OS notifications, etc.).
"""

from __future__ import annotations

import collections
import datetime
import logging
from typing import Sequence

from blackboxd.config import TimelineConfig
from blackboxd.models import Event, EventKind, FocusQuality, Session, TimelineDay

log = logging.getLogger(__name__)


class Reconstructor:
    """Converts a sequence of Events into Sessions and TimelineDays."""

    def __init__(self, config: TimelineConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def build_sessions(self, events: Sequence[Event]) -> list[Session]:
        """Build an ordered list of Sessions from *events* (must be sorted by timestamp)."""
        sessions: list[Session] = []
        current: Session | None = None

        for event in events:
            if event.kind == EventKind.WINDOW_FOCUS:
                app_class = event.app_class or "unknown"
                app_name  = event.app_name  or app_class

                if current is None:
                    # First focus event — open a session
                    current = _open(event)

                elif app_class != current.app_class:
                    # App switch — close current, open new
                    current.end = event.timestamp
                    _maybe_keep(current, sessions, self.config.min_session_duration)
                    current = _open(event)

                else:
                    # Same app — just record the new title
                    if event.window_title and event.window_title not in current.titles:
                        current.titles.append(event.window_title)

            elif event.kind == EventKind.IDLE_END:
                idle_secs = event.idle_seconds or 0.0
                if idle_secs >= self.config.session_split_threshold and current is not None:
                    # Long idle → close the session that preceded the idle gap
                    idle_start = event.timestamp - idle_secs
                    current.end = idle_start
                    current.idle_gap_after = idle_secs
                    _maybe_keep(current, sessions, self.config.min_session_duration)
                    current = None

            elif event.kind in (EventKind.LOCK_START, EventKind.DAEMON_STOP):
                if current is not None:
                    current.end = event.timestamp
                    _maybe_keep(current, sessions, self.config.min_session_duration)
                    current = None

        # Close any still-open session
        if current is not None:
            import time
            current.end = time.time()
            _maybe_keep(current, sessions, self.config.min_session_duration)

        return sessions

    def build_day(self, sessions: list[Session], date: str) -> TimelineDay:
        """Aggregate *sessions* into a TimelineDay for *date* (YYYY-MM-DD)."""
        day = TimelineDay(date=date)

        # Only include sessions that overlap with this date
        day_start, day_end = _day_bounds(date)
        day_sessions = [
            s for s in sessions
            if (s.end or 0) >= day_start and s.start <= day_end
        ]

        day.sessions = day_sessions
        day.switches = max(0, len(day_sessions) - 1)

        app_seconds: dict[str, float] = collections.defaultdict(float)
        for s in day_sessions:
            dur = s.duration
            day.total_active += dur
            app_seconds[s.app_name] += dur
            day.total_idle += s.idle_gap_after or 0.0

        day.top_apps = dict(
            sorted(app_seconds.items(), key=lambda kv: kv[1], reverse=True)
        )
        return day

    def build_days(
        self,
        events: Sequence[Event],
        since: datetime.date | None = None,
        until: datetime.date | None = None,
    ) -> list[TimelineDay]:
        """Full pipeline: events → sessions → one TimelineDay per calendar day."""
        sessions = self.build_sessions(events)
        if not sessions:
            return []

        # Collect all dates spanned by the sessions
        dates: set[str] = set()
        for s in sessions:
            d = datetime.date.fromtimestamp(s.start).isoformat()
            dates.add(d)
            if s.end:
                d_end = datetime.date.fromtimestamp(s.end).isoformat()
                dates.add(d_end)

        # Filter by requested range
        if since:
            dates = {d for d in dates if d >= since.isoformat()}
        if until:
            dates = {d for d in dates if d <= until.isoformat()}

        return [self.build_day(sessions, d) for d in sorted(dates)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open(event: Event) -> Session:
    s = Session(
        app_name  = event.app_name  or event.app_class or "unknown",
        app_class = event.app_class or "unknown",
        start     = event.timestamp,
        workspace = event.workspace,
    )
    if event.window_title:
        s.titles.append(event.window_title)
    return s


def _maybe_keep(session: Session, out: list[Session], min_dur: int) -> None:
    if session.duration >= min_dur:
        out.append(session)
    else:
        log.debug(
            "Dropped short session: %s (%.1fs)",
            session.app_name,
            session.duration,
        )


def _day_bounds(date_str: str) -> tuple[float, float]:
    """Return (start_timestamp, end_timestamp) for the given ISO date."""
    d = datetime.date.fromisoformat(date_str)
    start = datetime.datetime(d.year, d.month, d.day, 0, 0, 0)
    end   = datetime.datetime(d.year, d.month, d.day, 23, 59, 59)
    return start.timestamp(), end.timestamp()
