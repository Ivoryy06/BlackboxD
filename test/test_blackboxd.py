"""
tests/test_blackboxd.py
~~~~~~~~~~~~~~~~~~~~~~~
Integration and unit tests for the blackboxd core.

Run with:  pytest tests/ -v
"""

from __future__ import annotations

import datetime
import tempfile
import time
from pathlib import Path

import pytest

from blackboxd.config.config import (
    CollectorConfig,
    Config,
    StorageConfig,
    TimelineConfig,
    EXAMPLE_CONFIG,
    write_example_config,
)
from blackboxd.collectors.base import Normalizer, WindowInfo
from blackboxd.collectors.mock import MockCollector
from blackboxd.models import Event, EventKind, FocusQuality, RawEvent, Session, TimelineDay
from blackboxd.storage.engine import StorageEngine
from blackboxd.timeline.reconstructor import Reconstructor
from blackboxd.timeline.renderer import TextRenderer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_events.db"


@pytest.fixture
def engine(tmp_db: Path) -> StorageEngine:
    e = StorageEngine(tmp_db)
    e.open()
    yield e
    e.close()


@pytest.fixture
def collector_config() -> CollectorConfig:
    return CollectorConfig(
        backend="mock",
        poll_interval=1.0,
        idle_threshold=60,
    )


@pytest.fixture
def timeline_config() -> TimelineConfig:
    return TimelineConfig(
        session_split_threshold=120,
        min_session_duration=5,
    )


@pytest.fixture
def reconstructor(timeline_config: TimelineConfig) -> Reconstructor:
    return Reconstructor(timeline_config)


@pytest.fixture
def mock_collector(collector_config: CollectorConfig) -> MockCollector:
    return MockCollector(collector_config, frozen=True)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestEventKind:
    def test_string_values(self):
        assert EventKind.WINDOW_FOCUS == "window_focus"
        assert EventKind.IDLE_START   == "idle_start"

    def test_roundtrip(self):
        for kind in EventKind:
            assert EventKind(kind.value) == kind


class TestRawEvent:
    def test_now_factory(self):
        before = time.time()
        raw = RawEvent.now(EventKind.WINDOW_FOCUS, "test", app_name="Firefox")
        after = time.time()
        assert before <= raw.timestamp <= after
        assert raw.payload["app_name"] == "Firefox"

    def test_frozen(self):
        raw = RawEvent(EventKind.DAEMON_START, 1000.0, "test")
        with pytest.raises(Exception):
            raw.timestamp = 2000.0  # type: ignore[misc]


class TestSession:
    def _make_session(self, start: float, end: float) -> Session:
        s = Session(app_name="Firefox", app_class="firefox", start=start, end=end)
        return s

    def test_duration(self):
        s = self._make_session(1000.0, 1060.0)
        assert s.duration == 60.0

    def test_duration_open(self):
        s = Session(app_name="X", app_class="x", start=1000.0)
        assert s.duration == 0.0

    def test_fmt_duration_seconds(self):
        s = self._make_session(1000.0, 1045.0)
        assert s.fmt_duration() == "45s"

    def test_fmt_duration_minutes(self):
        s = self._make_session(0.0, 185.0)
        assert s.fmt_duration() == "3m 05s"

    def test_fmt_duration_hours(self):
        s = self._make_session(0.0, 3661.0)
        assert s.fmt_duration() == "1h 01m"

    def test_focus_quality_deep(self):
        s = self._make_session(0.0, 26 * 60.0)
        assert s.focus_quality == FocusQuality.DEEP

    def test_focus_quality_sustained(self):
        s = self._make_session(0.0, 15 * 60.0)
        assert s.focus_quality == FocusQuality.SUSTAINED

    def test_focus_quality_shallow(self):
        s = self._make_session(0.0, 5 * 60.0)
        assert s.focus_quality == FocusQuality.SHALLOW

    def test_focus_quality_glance(self):
        s = self._make_session(0.0, 90.0)
        assert s.focus_quality == FocusQuality.GLANCE

    def test_primary_title(self):
        s = self._make_session(0.0, 100.0)
        assert s.primary_title is None
        s.titles = ["Title A", "Title B"]
        assert s.primary_title == "Title B"


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_defaults(self):
        cfg = Config.default()
        assert cfg.collector.backend        == "auto"
        assert cfg.collector.poll_interval  == 1.0
        assert cfg.collector.idle_threshold == 120
        assert cfg.storage.retention_days   == 0
        assert cfg.timeline.session_split_threshold == 300

    def test_load_missing_returns_defaults(self, tmp_path: Path):
        cfg = Config.load(tmp_path / "nonexistent.toml")
        assert cfg.collector.backend == "auto"

    def test_load_valid_toml(self, tmp_path: Path):
        toml = tmp_path / "config.toml"
        toml.write_text(
            "[collector]\n"
            "backend = 'hyprland'\n"
            "poll_interval = 2.0\n"
            "idle_threshold = 180\n"
            "ignore_apps = ['1Password']\n"
            "[storage]\n"
            "retention_days = 30\n"
        )
        cfg = Config.load(toml)
        assert cfg.collector.backend        == "hyprland"
        assert cfg.collector.poll_interval  == 2.0
        assert cfg.collector.idle_threshold == 180
        assert cfg.collector.ignore_apps    == ["1Password"]
        assert cfg.storage.retention_days   == 30

    def test_invalid_toml_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.toml"
        bad.write_text("[[[[invalid")
        with pytest.raises(ValueError, match="Invalid TOML"):
            Config.load(bad)

    def test_validation_poll_interval(self, tmp_path: Path):
        toml = tmp_path / "cfg.toml"
        toml.write_text("[collector]\npoll_interval = -1\n")
        with pytest.raises(ValueError, match="poll_interval"):
            Config.load(toml)

    def test_write_example_config(self, tmp_path: Path):
        out = tmp_path / "sub" / "config.toml"
        write_example_config(out)
        assert out.exists()
        assert "[collector]" in out.read_text()


# ---------------------------------------------------------------------------
# Storage tests
# ---------------------------------------------------------------------------

class TestStorageEngine:
    def _event(self, kind: EventKind = EventKind.WINDOW_FOCUS, ts: float = 1000.0) -> Event:
        return Event(kind=kind, timestamp=ts, collector="test",
                     app_name="Firefox", app_class="firefox")

    def test_open_creates_db(self, tmp_db: Path):
        e = StorageEngine(tmp_db)
        e.open()
        assert tmp_db.exists()
        e.close()

    def test_append_returns_id(self, engine: StorageEngine):
        row_id = engine.append(self._event())
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_count(self, engine: StorageEngine):
        assert engine.count() == 0
        engine.append(self._event(ts=1000.0))
        engine.append(self._event(ts=1001.0))
        assert engine.count() == 2

    def test_query_all(self, engine: StorageEngine):
        engine.append(self._event(ts=1000.0))
        engine.append(self._event(ts=2000.0))
        results = engine.query()
        assert len(results) == 2
        assert results[0].timestamp == 1000.0
        assert results[1].timestamp == 2000.0

    def test_query_since(self, engine: StorageEngine):
        engine.append(self._event(ts=1000.0))
        engine.append(self._event(ts=2000.0))
        engine.append(self._event(ts=3000.0))
        results = engine.query(since=1500.0)
        assert len(results) == 2
        assert all(e.timestamp >= 1500.0 for e in results)

    def test_query_until(self, engine: StorageEngine):
        engine.append(self._event(ts=1000.0))
        engine.append(self._event(ts=2000.0))
        results = engine.query(until=1500.0)
        assert len(results) == 1

    def test_query_by_kind(self, engine: StorageEngine):
        engine.append(self._event(kind=EventKind.WINDOW_FOCUS, ts=1000.0))
        engine.append(self._event(kind=EventKind.IDLE_START,   ts=1001.0))
        results = engine.query(kinds=[EventKind.IDLE_START])
        assert len(results) == 1
        assert results[0].kind == EventKind.IDLE_START

    def test_latest(self, engine: StorageEngine):
        for i in range(5):
            engine.append(self._event(ts=float(i * 100)))
        latest = engine.latest(3)
        assert len(latest) == 3
        assert latest[0].timestamp > latest[1].timestamp  # newest first

    def test_date_range(self, engine: StorageEngine):
        assert engine.date_range() is None
        engine.append(self._event(ts=1000.0))
        engine.append(self._event(ts=5000.0))
        lo, hi = engine.date_range()
        assert lo == 1000.0
        assert hi == 5000.0

    def test_append_many(self, engine: StorageEngine):
        events = [self._event(ts=float(i)) for i in range(10)]
        engine.append_many(events)
        assert engine.count() == 10

    def test_purge_before(self, engine: StorageEngine):
        engine.append(self._event(ts=500.0))
        engine.append(self._event(ts=1000.0))
        engine.append(self._event(ts=2000.0))
        deleted = engine.purge_before(1500.0)
        assert deleted == 2
        assert engine.count() == 1

    def test_context_manager(self, tmp_db: Path):
        ev = Event(kind=EventKind.DAEMON_START, timestamp=1.0, collector="test")
        with StorageEngine(tmp_db) as e:
            e.append(ev)
        # Re-open and verify persistence
        with StorageEngine(tmp_db) as e:
            assert e.count() == 1

    def test_roundtrip_event_fields(self, engine: StorageEngine):
        ev = Event(
            kind=EventKind.WINDOW_FOCUS,
            timestamp=12345.678,
            collector="hyprland",
            app_name="Firefox",
            app_class="firefox",
            window_title="GitHub - blackboxd",
            workspace="2",
            idle_seconds=None,
        )
        engine.append(ev)
        results = engine.query()
        r = results[0]
        assert r.kind         == EventKind.WINDOW_FOCUS
        assert r.timestamp    == pytest.approx(12345.678)
        assert r.collector    == "hyprland"
        assert r.app_name     == "Firefox"
        assert r.app_class    == "firefox"
        assert r.window_title == "GitHub - blackboxd"
        assert r.workspace    == "2"
        assert r.idle_seconds is None

    def test_schema_idempotent(self, tmp_db: Path):
        """Opening the same DB twice should not fail."""
        e1 = StorageEngine(tmp_db); e1.open(); e1.close()
        e2 = StorageEngine(tmp_db); e2.open(); e2.close()


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------

class TestNormalizer:
    def _raw(self, **kwargs) -> RawEvent:
        defaults = dict(
            kind=EventKind.WINDOW_FOCUS,
            timestamp=1000.0,
            source="test",
            payload={"app_name": "Firefox", "app_class": "firefox", "title": "Some Page"},
        )
        defaults.update(kwargs)
        return RawEvent(**defaults)

    def test_basic_normalization(self):
        cfg = CollectorConfig()
        n = Normalizer(cfg)
        event = n.normalize(self._raw())
        assert event.app_name == "Firefox"
        assert event.kind     == EventKind.WINDOW_FOCUS

    def test_suppress_titles(self):
        cfg = CollectorConfig(suppress_titles=True)
        n = Normalizer(cfg)
        event = n.normalize(self._raw())
        assert event.window_title is None

    def test_hash_titles(self):
        cfg = CollectorConfig(hash_titles=True)
        n = Normalizer(cfg)
        event = n.normalize(self._raw())
        assert event.window_title is not None
        assert len(event.window_title) == 16  # SHA-256 truncated
        assert event.window_title != "Some Page"

    def test_hash_is_deterministic(self):
        cfg = CollectorConfig(hash_titles=True)
        n = Normalizer(cfg)
        e1 = n.normalize(self._raw())
        e2 = n.normalize(self._raw())
        assert e1.window_title == e2.window_title

    def test_idle_seconds_preserved(self):
        cfg = CollectorConfig()
        n = Normalizer(cfg)
        raw = self._raw(
            kind=EventKind.IDLE_END,
            payload={"idle_seconds": 130.5},
        )
        event = n.normalize(raw)
        assert event.idle_seconds == pytest.approx(130.5)


# ---------------------------------------------------------------------------
# Mock collector tests
# ---------------------------------------------------------------------------

class TestMockCollector:
    def test_is_available(self, collector_config: CollectorConfig):
        mc = MockCollector(collector_config)
        assert mc.is_available()

    def test_replay_all_emits_events(self, collector_config: CollectorConfig):
        mc = MockCollector(collector_config)
        events = list(mc.replay_all(base_ts=0.0))
        # Should have at least WINDOW_FOCUS events for each script entry
        focus_events = [e for e in events if e.kind == EventKind.WINDOW_FOCUS]
        assert len(focus_events) >= 5

    def test_replay_respects_app_classes(self, collector_config: CollectorConfig):
        mc = MockCollector(collector_config)
        events = list(mc.replay_all(base_ts=0.0))
        focus = [e for e in events if e.kind == EventKind.WINDOW_FOCUS]
        classes = [e.payload["app_class"] for e in focus]
        assert "firefox" in classes
        assert "kitty"   in classes

    def test_ignore_filter(self):
        cfg = CollectorConfig(ignore_apps=["Firefox"], idle_threshold=9999)
        mc = MockCollector(cfg, frozen=True)
        mc._last_window = None

        # Simulate poll with Firefox as active window
        mc._last_window = None
        window = WindowInfo("Firefox", "firefox", "Some Title", "1")
        assert mc._is_ignored(window)

        window2 = WindowInfo("Terminal", "kitty", "bash", "1")
        assert not mc._is_ignored(window2)


# ---------------------------------------------------------------------------
# Reconstructor tests
# ---------------------------------------------------------------------------

BASE_TS = datetime.datetime(2025, 6, 15, 9, 0, 0).timestamp()


def _focus(app_class: str, app_name: str, offset: float, title: str = "") -> Event:
    return Event(
        kind=EventKind.WINDOW_FOCUS,
        timestamp=BASE_TS + offset,
        collector="test",
        app_class=app_class,
        app_name=app_name,
        window_title=title or app_name,
    )


def _idle_end(offset: float, idle_secs: float) -> Event:
    return Event(
        kind=EventKind.IDLE_END,
        timestamp=BASE_TS + offset,
        collector="test",
        idle_seconds=idle_secs,
    )


class TestReconstructor:
    def test_single_session(self, reconstructor: Reconstructor):
        events = [
            _focus("firefox", "Firefox", 0),
            _focus("kitty",   "Terminal", 600),  # 10 min later
        ]
        sessions = reconstructor.build_sessions(events)
        assert len(sessions) == 2
        assert sessions[0].app_class == "firefox"
        assert sessions[0].duration  == pytest.approx(600.0)

    def test_session_collects_titles(self, reconstructor: Reconstructor):
        events = [
            _focus("firefox", "Firefox", 0,   "GitHub"),
            _focus("firefox", "Firefox", 30,  "MDN"),
            _focus("kitty",   "Terminal", 600, "bash"),
        ]
        sessions = reconstructor.build_sessions(events)
        ff = sessions[0]
        assert "GitHub" in ff.titles
        assert "MDN"    in ff.titles

    def test_idle_split(self, reconstructor: Reconstructor):
        """An idle gap > session_split_threshold should create a new session."""
        events = [
            _focus("firefox", "Firefox", 0),
            _idle_end(200, 180),              # 3 min idle (> 120s threshold)
            _focus("firefox", "Firefox", 200),
        ]
        sessions = reconstructor.build_sessions(events)
        # The idle gap should split into two sessions
        assert len(sessions) == 2

    def test_short_session_dropped(self, reconstructor: Reconstructor):
        """Sessions under min_session_duration should be discarded."""
        events = [
            _focus("firefox", "Firefox", 0),
            _focus("slack",   "Slack",   3),   # 3s — below 5s threshold
            _focus("kitty",   "Terminal", 600),
        ]
        sessions = reconstructor.build_sessions(events)
        classes = [s.app_class for s in sessions]
        assert "slack" not in classes

    def test_build_day_totals(self, reconstructor: Reconstructor):
        events = [
            _focus("firefox", "Firefox", 0),
            _focus("kitty",   "Terminal", 1200),  # 20 min Firefox
            _focus("slack",   "Slack",    1800),  # 10 min Terminal
        ]
        sessions = reconstructor.build_sessions(events)
        date = datetime.date(2025, 6, 15).isoformat()
        day = reconstructor.build_day(sessions, date)

        assert day.switches >= 2
        assert day.total_active > 0
        assert "Firefox" in day.top_apps
        assert day.top_apps["Firefox"] == pytest.approx(1200.0, abs=1.0)

    def test_build_day_top_apps_sorted(self, reconstructor: Reconstructor):
        events = [
            _focus("slack",   "Slack",   0),
            _focus("firefox", "Firefox", 30),   # 30s Slack
            _focus("kitty",   "Terminal", 1230), # 1200s Firefox
        ]
        sessions = reconstructor.build_sessions(events)
        date = datetime.date(2025, 6, 15).isoformat()
        day = reconstructor.build_day(sessions, date)
        apps = list(day.top_apps.keys())
        # Firefox should be first (most time)
        assert apps[0] == "Firefox"

    def test_build_days_groups_by_date(self, reconstructor: Reconstructor):
        # Events spanning two days
        day1 = datetime.datetime(2025, 6, 15, 10, 0).timestamp()
        day2 = datetime.datetime(2025, 6, 16, 10, 0).timestamp()
        events = [
            Event(kind=EventKind.WINDOW_FOCUS, timestamp=day1,
                  collector="t", app_class="firefox", app_name="Firefox"),
            Event(kind=EventKind.WINDOW_FOCUS, timestamp=day1 + 3600,
                  collector="t", app_class="kitty", app_name="Terminal"),
            Event(kind=EventKind.WINDOW_FOCUS, timestamp=day2,
                  collector="t", app_class="firefox", app_name="Firefox"),
        ]
        days = reconstructor.build_days(events)
        assert len(days) == 2
        dates = [d.date for d in days]
        assert "2025-06-15" in dates
        assert "2025-06-16" in dates

    def test_empty_events(self, reconstructor: Reconstructor):
        sessions = reconstructor.build_sessions([])
        assert sessions == []
        days = reconstructor.build_days([])
        assert days == []


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------

class TestTextRenderer:
    def _day(self) -> TimelineDay:
        sessions = [
            Session(
                app_name="Firefox",
                app_class="firefox",
                start=BASE_TS,
                end=BASE_TS + 1800,
                titles=["GitHub"],
            ),
            Session(
                app_name="Terminal",
                app_class="kitty",
                start=BASE_TS + 1800,
                end=BASE_TS + 3600,
                titles=["vim main.py"],
            ),
        ]
        day = TimelineDay(
            date="2025-06-15",
            sessions=sessions,
            total_active=3600.0,
            total_idle=0.0,
            switches=1,
            top_apps={"Firefox": 1800.0, "Terminal": 1800.0},
        )
        return day

    def test_render_day_contains_date(self):
        r = TextRenderer(color=False)
        out = r.render_day(self._day())
        assert "2025" in out
        assert "June" in out

    def test_render_day_contains_app_names(self):
        r = TextRenderer(color=False)
        out = r.render_day(self._day())
        assert "Firefox"  in out
        assert "Terminal" in out

    def test_render_day_contains_duration(self):
        r = TextRenderer(color=False)
        out = r.render_day(self._day())
        assert "30m" in out  # 1800s = 30m

    def test_render_summary_one_line_per_day(self):
        r = TextRenderer(color=False)
        days = [self._day(), self._day()]
        days[1].date = "2025-06-16"
        out = r.render_summary(days)
        assert "2025-06-15" in out
        assert "2025-06-16" in out

    def test_render_empty_days(self):
        r = TextRenderer(color=False)
        out = r.render_days([])
        assert "no activity" in out.lower()

    def test_no_color_flag(self):
        r_color   = TextRenderer(color=True)
        r_nocolor = TextRenderer(color=False)
        day = self._day()
        assert "\033[" in r_color.render_day(day)
        assert "\033[" not in r_nocolor.render_day(day)


# ---------------------------------------------------------------------------
# End-to-end integration test
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_full_pipeline(self, tmp_db: Path, collector_config: CollectorConfig):
        """Mock collector → normalizer → storage → reconstructor → renderer."""
        mc = MockCollector(collector_config)
        normalizer = Normalizer(collector_config)

        # Replay all scripted events
        raw_events = list(mc.replay_all(base_ts=BASE_TS))
        events = normalizer.normalize_many(raw_events)

        with StorageEngine(tmp_db) as engine:
            engine.append_many(events)
            assert engine.count() > 0

            stored = engine.query()

        cfg = TimelineConfig(session_split_threshold=120, min_session_duration=5)
        reconstructor = Reconstructor(cfg)
        sessions = reconstructor.build_sessions(stored)
        assert len(sessions) > 0

        date = datetime.date.fromtimestamp(BASE_TS).isoformat()
        day = reconstructor.build_day(sessions, date)
        assert day.total_active > 0
        assert len(day.top_apps) > 0

        renderer = TextRenderer(color=False)
        output = renderer.render_day(day)
        assert len(output) > 100
        assert "Firefox" in output or "Terminal" in output or "Obsidian" in output
