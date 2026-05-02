"""
blackboxd.daemon
~~~~~~~~~~~~~~~~
The main background process.

Responsibilities:
  - Load config
  - Open the storage engine
  - Instantiate the right collector backend
  - Run the poll loop: collect → normalize → store → sleep
  - Handle signals (SIGTERM / SIGINT) for graceful shutdown
  - Apply optional retention purge on startup

The daemon is intentionally simple: no threads, no asyncio.
A single tight loop with a configurable sleep interval is sufficient
for 1-second resolution activity tracking.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path
from types import FrameType

from blackboxd.collectors.base import Normalizer
from blackboxd.collectors.registry import get_collector
from blackboxd.config import Config
from blackboxd.models import Event, EventKind, RawEvent
from blackboxd.storage.engine import StorageEngine

log = logging.getLogger(__name__)


class Daemon:
    """The blackboxd background service."""

    def __init__(self, config: Config) -> None:
        self.config  = config
        self._running = False
        self._engine: StorageEngine | None = None

    
    
    

    def start(self) -> None:
        """Open storage, register signal handlers, run the poll loop."""
        _configure_logging(self.config.storage.log_path)

        log.info("blackboxd starting (pid=%d)", _getpid())

        self._engine = StorageEngine(
            db_path=self.config.storage.db_path,
            wal_checkpoint_interval=self.config.storage.wal_checkpoint_interval,
        )
        self._engine.open()
        self._apply_retention()

        collector = get_collector(self.config.collector)
        normalizer = Normalizer(self.config.collector)

        collector.setup()
        log.info("Collector backend: %s", collector.NAME)

        self._store(Event(
            kind=EventKind.DAEMON_START,
            timestamp=time.time(),
            collector=collector.NAME,
        ))

        self._running = True
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT,  self._handle_signal)

        try:
            self._loop(collector, normalizer)
        finally:
            self._store(Event(
                kind=EventKind.DAEMON_STOP,
                timestamp=time.time(),
                collector=collector.NAME,
            ))
            collector.teardown()
            self._engine.close()
            log.info("blackboxd stopped.")

    
    
    

    def _loop(self, collector: object, normalizer: Normalizer) -> None:
        from blackboxd.collectors.base import BaseCollector
        assert isinstance(collector, BaseCollector)

        interval = self.config.collector.poll_interval
        log.info("Poll interval: %.1fs", interval)

        while self._running:
            tick_start = time.monotonic()

            try:
                raw_events = list(collector.poll())
                for raw in raw_events:
                    event = normalizer.normalize(raw)
                    row_id = self._store(event)
                    log.debug(
                        "[%d] %s  %s",
                        row_id,
                        event.kind.value,
                        event.app_name or "",
                    )
            except Exception as exc:
                log.warning("Collector error: %s", exc, exc_info=True)

            
            elapsed = time.monotonic() - tick_start
            sleep_for = max(0.0, interval - elapsed)
            time.sleep(sleep_for)

    
    
    

    def _store(self, event: Event) -> int:
        assert self._engine is not None
        return self._engine.append(event)

    def _apply_retention(self) -> None:
        days = self.config.storage.retention_days
        if days <= 0:
            return
        cutoff = time.time() - days * 86400
        assert self._engine is not None
        deleted = self._engine.purge_before(cutoff)
        if deleted:
            log.info("Retention purge: removed %d events older than %d days.", deleted, days)

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        log.info("Received signal %d — shutting down.", signum)
        self._running = False






def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="blackboxd",
        description="Privacy-first activity recorder.",
    )
    parser.add_argument(
        "--config", "-c",
        metavar="PATH",
        type=Path,
        default=None,
        help="Path to config.toml (default: XDG_CONFIG_HOME/blackboxd/config.toml)",
    )
    parser.add_argument(
        "--backend",
        metavar="NAME",
        default=None,
        help="Override collector backend (mock | hyprland | gnome)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    args = parser.parse_args()

    config = Config.load(args.config)

    if args.backend:
        config.collector.backend = args.backend
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    Daemon(config).start()






def _configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(log_path),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=handlers,
    )


def _getpid() -> int:
    import os
    return os.getpid()

import os

def _write_pid():
    pid_dir = Path(f"/run/user/{os.getuid()}")
    pid_file = pid_dir / "blackboxd.pid"
    pid_file.write_text(str(os.getpid()))
    return pid_file

def _clear_pid(pid_file):
    pid_file.unlink(missing_ok=True)