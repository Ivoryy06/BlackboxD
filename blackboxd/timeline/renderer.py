"""
blackboxd.timeline.renderer
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Renders a TimelineDay (or a list of them) as plain-text output.

The renderer is intentionally decoupled from the reconstructor — it takes
already-built model objects and turns them into strings. A UI layer or a
future Markdown / JSON renderer can use the same model objects.
"""

from __future__ import annotations

import datetime
from io import StringIO

from blackboxd.models import FocusQuality, Session, TimelineDay



QUALITY_SYMBOL = {
    FocusQuality.DEEP:      "■■■■",
    FocusQuality.SUSTAINED: "■■■░",
    FocusQuality.SHALLOW:   "■■░░",
    FocusQuality.GLANCE:    "■░░░",
}

QUALITY_LABEL = {
    FocusQuality.DEEP:      "deep",
    FocusQuality.SUSTAINED: "sustained",
    FocusQuality.SHALLOW:   "shallow",
    FocusQuality.GLANCE:    "glance",
}


class TextRenderer:
    """Formats reconstructed timeline data as plain text."""

    def __init__(self, width: int = 80, color: bool = True) -> None:
        self.width = width
        self.color = color

    
    
    

    def render_day(self, day: TimelineDay) -> str:
        buf = StringIO()
        self._day_header(buf, day)
        self._stats_row(buf, day)
        buf.write("\n")
        self._session_list(buf, day.sessions)
        self._top_apps(buf, day)
        return buf.getvalue()

    def render_days(self, days: list[TimelineDay]) -> str:
        if not days:
            return "(no activity recorded)\n"
        return "\n".join(self.render_day(d) for d in days)

    def render_summary(self, days: list[TimelineDay]) -> str:
        """One line per day — a compact multi-day overview."""
        buf = StringIO()
        buf.write(self._bold("BLACKBOXD — Activity Summary") + "\n")
        buf.write("─" * self.width + "\n")
        for day in days:
            buf.write(day.summary_line() + "\n")
        return buf.getvalue()

    
    
    

    def _day_header(self, buf: StringIO, day: TimelineDay) -> None:
        d = datetime.date.fromisoformat(day.date)
        heading = f"  {d.strftime('%A, %B %-d %Y')}  "
        pad = (self.width - len(heading)) // 2
        buf.write("═" * self.width + "\n")
        buf.write(" " * pad + self._bold(heading) + "\n")
        buf.write("═" * self.width + "\n\n")

    def _stats_row(self, buf: StringIO, day: TimelineDay) -> None:
        active_h = day.total_active / 3600
        idle_h   = day.total_idle   / 3600
        deep_count = sum(
            1 for s in day.sessions if s.focus_quality == FocusQuality.DEEP
        )
        buf.write(
            f"  Active {active_h:.1f}h  ·  "
            f"Idle {idle_h:.1f}h  ·  "
            f"{day.switches} switches  ·  "
            f"{deep_count} deep sessions\n"
        )

    def _session_list(self, buf: StringIO, sessions: list[Session]) -> None:
        if not sessions:
            buf.write("  (no sessions)\n\n")
            return

        buf.write(self._dim("  Time         App                  Duration  Focus\n"))
        buf.write("  " + "─" * (self.width - 4) + "\n")

        for s in sessions:
            time_str = datetime.datetime.fromtimestamp(s.start).strftime("%H:%M:%S")
            app_col  = _truncate(s.app_name, 20).ljust(20)
            dur_col  = s.fmt_duration().rjust(8)
            quality  = QUALITY_SYMBOL[s.focus_quality]
            label    = QUALITY_LABEL[s.focus_quality]

            title_str = ""
            if s.primary_title:
                title_str = self._dim(f"\n               └ {_truncate(s.primary_title, 56)}")

            idle_str = ""
            if s.idle_gap_after and s.idle_gap_after >= 60:
                idle_min = int(s.idle_gap_after // 60)
                idle_str = self._dim(f"\n               └ ··· {idle_min}m idle ···")

            buf.write(
                f"  {time_str}  {app_col}  {dur_col}  {quality} {label}"
                f"{title_str}{idle_str}\n"
            )

        buf.write("\n")

    def _top_apps(self, buf: StringIO, day: TimelineDay) -> None:
        if not day.top_apps:
            return
        buf.write(self._dim("  Top applications\n"))
        buf.write("  " + "─" * 32 + "\n")

        total = sum(day.top_apps.values()) or 1
        for app, secs in list(day.top_apps.items())[:8]:
            bar_len = int((secs / total) * 28)
            bar = "█" * bar_len + "░" * (28 - bar_len)
            mins = int(secs // 60)
            buf.write(f"  {_truncate(app, 14).ljust(14)}  {bar}  {mins:4d}m\n")
        buf.write("\n")

    
    
    

    def _bold(self, text: str) -> str:
        return f"\033[1m{text}\033[0m" if self.color else text

    def _dim(self, text: str) -> str:
        return f"\033[2m{text}\033[0m" if self.color else text






def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"
