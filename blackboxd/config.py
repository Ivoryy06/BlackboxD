"""
blackboxd.config
~~~~~~~~~~~~~~~~
Loads and validates configuration from a TOML file. Falls back to sane
defaults when keys are absent — the daemon should always start without
a config file present.

Config file search order:
  1. Path given by --config CLI flag
  2. $XDG_CONFIG_HOME/blackboxd/config.toml
  3. ~/.config/blackboxd/config.toml
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Default constants
# ---------------------------------------------------------------------------

DEFAULT_POLL_INTERVAL    = 1.0    # seconds between collector polls
DEFAULT_IDLE_THRESHOLD   = 120    # seconds of inactivity before IDLE_START
DEFAULT_SESSION_SPLIT    = 300    # idle gap (seconds) that splits sessions
DEFAULT_TITLE_MAX_LEN    = 120    # truncate window titles at this length
DEFAULT_DB_PATH          = "~/.local/share/blackboxd/events.db"
DEFAULT_LOG_PATH         = "~/.local/share/blackboxd/blackboxd.log"


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------

@dataclass
class CollectorConfig:
    """Settings for the collector subsystem."""

    # Which collector backend to use. "auto" = detect from environment.
    backend: str = "auto"

    # Seconds between active-window polls.
    poll_interval: float = DEFAULT_POLL_INTERVAL

    # Seconds of no input before an IDLE_START event fires.
    idle_threshold: int = DEFAULT_IDLE_THRESHOLD

    # Extra app names / classes to completely ignore (privacy filter).
    ignore_apps: list[str] = field(default_factory=list)

    # If True, window titles are never stored (only app names).
    suppress_titles: bool = False

    # If True, titles are hashed (SHA-256 truncated) instead of stored.
    hash_titles: bool = False


@dataclass
class StorageConfig:
    """Settings for the storage engine."""

    db_path: Path = Path(DEFAULT_DB_PATH).expanduser()
    log_path: Path = Path(DEFAULT_LOG_PATH).expanduser()

    # Maximum number of days to retain events (0 = forever).
    retention_days: int = 0

    # Flush WAL to main DB file after this many events.
    wal_checkpoint_interval: int = 500


@dataclass
class TimelineConfig:
    """Settings for timeline reconstruction."""

    # Idle gap (seconds) that starts a new session.
    session_split_threshold: int = DEFAULT_SESSION_SPLIT

    # Minimum session duration (seconds) to include in reports.
    min_session_duration: int = 5

    # Truncate window titles to this length in output.
    title_max_length: int = DEFAULT_TITLE_MAX_LEN


@dataclass
class Config:
    """Top-level configuration object."""

    collector: CollectorConfig = field(default_factory=CollectorConfig)
    storage:   StorageConfig   = field(default_factory=StorageConfig)
    timeline:  TimelineConfig  = field(default_factory=TimelineConfig)

    # Source path (informational only).
    _path: Path | None = field(default=None, repr=False, compare=False)

    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load config from *path*, or search the standard locations.

        Returns a Config with defaults if no file is found.
        """
        resolved = path or _find_config_file()
        if resolved is None:
            return cls()

        raw = _read_toml(resolved)
        return _parse(raw, resolved)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_config_file() -> Path | None:
    xdg = os.environ.get("XDG_CONFIG_HOME", "~/.config")
    candidates = [
        Path(xdg).expanduser() / "blackboxd" / "config.toml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {path}")
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {path}: {exc}") from exc


def _parse(raw: dict[str, Any], path: Path) -> Config:
    col_raw  = raw.get("collector", {})
    stor_raw = raw.get("storage", {})
    tl_raw   = raw.get("timeline", {})

    collector = CollectorConfig(
        backend          = col_raw.get("backend", "auto"),
        poll_interval    = float(col_raw.get("poll_interval", DEFAULT_POLL_INTERVAL)),
        idle_threshold   = int(col_raw.get("idle_threshold", DEFAULT_IDLE_THRESHOLD)),
        ignore_apps      = list(col_raw.get("ignore_apps", [])),
        suppress_titles  = bool(col_raw.get("suppress_titles", False)),
        hash_titles      = bool(col_raw.get("hash_titles", False)),
    )

    storage = StorageConfig(
        db_path                 = Path(stor_raw.get("db_path", DEFAULT_DB_PATH)).expanduser(),
        log_path                = Path(stor_raw.get("log_path", DEFAULT_LOG_PATH)).expanduser(),
        retention_days          = int(stor_raw.get("retention_days", 0)),
        wal_checkpoint_interval = int(stor_raw.get("wal_checkpoint_interval", 500)),
    )

    timeline = TimelineConfig(
        session_split_threshold = int(tl_raw.get("session_split_threshold", DEFAULT_SESSION_SPLIT)),
        min_session_duration    = int(tl_raw.get("min_session_duration", 5)),
        title_max_length        = int(tl_raw.get("title_max_length", DEFAULT_TITLE_MAX_LEN)),
    )

    _validate(collector, storage, timeline)

    cfg = Config(collector=collector, storage=storage, timeline=timeline)
    cfg._path = path
    return cfg


def _validate(
    collector: CollectorConfig,
    storage:   StorageConfig,
    timeline:  TimelineConfig,
) -> None:
    if collector.poll_interval <= 0:
        raise ValueError("collector.poll_interval must be > 0")
    if collector.idle_threshold < 10:
        raise ValueError("collector.idle_threshold must be >= 10 seconds")
    if storage.retention_days < 0:
        raise ValueError("storage.retention_days must be >= 0")
    if timeline.session_split_threshold < collector.idle_threshold:
        raise ValueError(
            "timeline.session_split_threshold must be >= collector.idle_threshold"
        )


# ---------------------------------------------------------------------------
# Example config generator (used by installer / first-run)
# ---------------------------------------------------------------------------

EXAMPLE_CONFIG = """\
# blackboxd configuration
# All values shown are defaults. Uncomment and edit as needed.

[collector]
# backend = "auto"          # auto | hyprland | gnome | x11 | mock
# poll_interval = 1.0       # seconds between window-focus polls
# idle_threshold = 120      # seconds of inactivity before marking idle
# ignore_apps = []          # e.g. ["1Password", "KeePassXC"]
# suppress_titles = false   # true = never store window titles
# hash_titles = false       # true = store SHA-256 of titles instead

[storage]
# db_path = "~/.local/share/blackboxd/events.db"
# log_path = "~/.local/share/blackboxd/blackboxd.log"
# retention_days = 0        # 0 = keep forever
# wal_checkpoint_interval = 500

[timeline]
# session_split_threshold = 300   # idle gap (s) that starts a new session
# min_session_duration = 5        # sessions shorter than this are dropped
# title_max_length = 120
"""


def write_example_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EXAMPLE_CONFIG)
