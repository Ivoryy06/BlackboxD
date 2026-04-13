"""
blackboxd.cli
~~~~~~~~~~~~~
`blackboxd-report` — query the event store and render timeline reports.

Usage examples:

    blackboxd-report                  # today's timeline
    blackboxd-report --date 2025-01-15
    blackboxd-report --days 7         # last 7 days, summary
    blackboxd-report --summary        # compact multi-day overview
    blackboxd-report --raw --limit 50 # dump raw events
    blackboxd-report dashboard        # open self-contained dashboard snapshot
    blackboxd-report dashboard --export ~/activity.html
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path


def _export_dashboard(engine, output: Path | None) -> None:
    """Bake all events into dashboard.html and write a self-contained file."""
    import dataclasses

    here = Path(__file__).parent.parent  # repo root
    template = here / "dashboard.html"
    if not template.exists():
        print(f"dashboard.html not found at {template}", file=sys.stderr)
        sys.exit(1)

    events = engine.query()
    dr = engine.date_range()
    stats = {
        "total_events": len(events),
        "earliest": dr[0] if dr else None,
        "latest":   dr[1] if dr else None,
    }

    def _serial(e):
        d = dataclasses.asdict(e)
        d["kind"] = e.kind.value
        return d

    payload = json.dumps({"events": [_serial(e) for e in events], "stats": stats})
    inline = f'const INLINE_DATA = {payload};'

    html = template.read_text()
    html = html.replace(
        "/* BLACKBOXD_INLINE_DATA — replaced by `blackboxd dashboard --export` */\nconst INLINE_DATA = null;",
        inline,
    )

    dest = output or Path("blackboxd-dashboard.html")
    dest.write_text(html)
    print(f"Dashboard written to {dest}")

    # open in browser if not just exporting to a path
    if output is None:
        import webbrowser
        webbrowser.open(dest.resolve().as_uri())


def main() -> None:
    import argparse

    from blackboxd.config import Config
    from blackboxd.storage.engine import StorageEngine
    from blackboxd.timeline.reconstructor import Reconstructor
    from blackboxd.timeline.renderer import TextRenderer

    parser = argparse.ArgumentParser(
        prog="blackboxd-report",
        description="Render a human-readable timeline from blackboxd event data.",
    )
    parser.add_argument("command", nargs="?", default=None,
                        help="Subcommand: 'dashboard' to open a self-contained HTML snapshot.")
    parser.add_argument("--config",  "-c", metavar="PATH", type=Path, default=None)
    parser.add_argument("--date",    "-d", metavar="YYYY-MM-DD", default=None,
                        help="Show a specific date (default: today).")
    parser.add_argument("--days",    "-n", metavar="N", type=int, default=None,
                        help="Show the last N days.")
    parser.add_argument("--summary", "-s", action="store_true",
                        help="Print compact one-line-per-day summary.")
    parser.add_argument("--raw",     "-r", action="store_true",
                        help="Dump raw events instead of reconstructed timeline.")
    parser.add_argument("--limit",   "-l", metavar="N", type=int, default=200,
                        help="Max events for --raw (default: 200).")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI color output.")
    parser.add_argument("--export",  "-e", metavar="PATH", type=Path, default=None,
                        help="(dashboard) Write snapshot to this path instead of a temp file.")
    args = parser.parse_args()

    config = Config.load(args.config)

    with StorageEngine(config.storage.db_path) as engine:
        if args.command == "dashboard":
            _export_dashboard(engine, args.export)
            return

        if engine.count() == 0:
            print("No events recorded yet. Is blackboxd running?", file=sys.stderr)
            sys.exit(0)

        # Determine time range
        today = datetime.date.today()
        if args.date:
            since_date = datetime.date.fromisoformat(args.date)
            until_date = since_date
        elif args.days:
            since_date = today - datetime.timedelta(days=args.days - 1)
            until_date = today
        else:
            since_date = today
            until_date = today

        since_ts = datetime.datetime(since_date.year, since_date.month, since_date.day).timestamp()
        until_ts = datetime.datetime(until_date.year, until_date.month, until_date.day,
                                     23, 59, 59).timestamp()

        if args.raw:
            events = engine.query(since=since_ts, until=until_ts, limit=args.limit)
            for e in events:
                print(
                    f"{e.datetime}  {e.kind.value:<20}  "
                    f"{(e.app_name or ''):<18}  "
                    f"{(e.window_title or '')[:60]}"
                )
            return

        events = engine.query(since=since_ts, until=until_ts)
        reconstructor = Reconstructor(config.timeline)
        days = reconstructor.build_days(events, since=since_date, until=until_date)

        renderer = TextRenderer(color=not args.no_color)
        if args.summary or len(days) > 1:
            print(renderer.render_summary(days))
            if not args.summary:
                for day in days:
                    print(renderer.render_day(day))
        else:
            if days:
                print(renderer.render_day(days[0]))
            else:
                print("No activity recorded for that period.")
