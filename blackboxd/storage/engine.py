"""
blackboxd.storage.engine
~~~~~~~~~~~~~~~~~~~~~~~~
Append-only SQLite event store.

Design decisions:
- WAL mode for safe concurrent reads from the CLI while the daemon writes.
- Single `events` table; no FKs, no joins — fast appends, simple queries.
- Monotonic `id` is the only row identity; no UUID overhead.
- All timestamps stored as REAL (Unix epoch seconds).
- Schema migrations via a simple version table; forwards-only.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Sequence

from blackboxd.models import Event, EventKind

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT    NOT NULL,
    timestamp     REAL    NOT NULL,
    collector     TEXT    NOT NULL,
    app_name      TEXT,
    app_class     TEXT,
    window_title  TEXT,
    workspace     TEXT,
    idle_seconds  REAL
);
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_events_kind      ON events (kind);",
    "CREATE INDEX IF NOT EXISTS idx_events_app_class ON events (app_class);",
]


class StorageEngine:
    """Thread-safe SQLite event store.

    Usage::

        engine = StorageEngine(Path("~/.local/share/blackboxd/events.db"))
        engine.open()
        engine.append(event)
        events = engine.query(since=..., until=...)
        engine.close()

    Or as a context manager::

        with StorageEngine(path) as engine:
            engine.append(event)
    """

    def __init__(
        self,
        db_path: Path,
        wal_checkpoint_interval: int = 500,
    ) -> None:
        self._path = db_path
        self._wal_checkpoint_interval = wal_checkpoint_interval
        self._conn: sqlite3.Connection | None = None
        self._pending_writes: int = 0

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def open(self) -> None:
        """Open the database, run migrations, configure pragmas."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            self._path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row

        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.execute("PRAGMA synchronous = NORMAL;")
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA cache_size = -8000;")

        with self._tx() as cur:
            cur.execute(CREATE_META)
            cur.execute(CREATE_EVENTS)
            for idx in CREATE_INDEXES:
                cur.execute(idx)
            self._migrate(cur)

        log.info("Storage opened: %s", self._path)

    def close(self) -> None:
        if self._conn:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            self._conn.close()
            self._conn = None
            log.info("Storage closed.")

    def __enter__(self) -> "StorageEngine":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Writes                                                               #
    # ------------------------------------------------------------------ #

    def append(self, event: Event) -> int:
        """Insert one event. Returns the assigned row id."""
        conn = self._require_conn()
        cur = conn.execute(
            """
            INSERT INTO events
                (kind, timestamp, collector, app_name, app_class,
                 window_title, workspace, idle_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.kind.value,
                event.timestamp,
                event.collector,
                event.app_name,
                event.app_class,
                event.window_title,
                event.workspace,
                event.idle_seconds,
            ),
        )
        row_id: int = cur.lastrowid  # type: ignore[assignment]

        self._pending_writes += 1
        if self._pending_writes >= self._wal_checkpoint_interval:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            self._pending_writes = 0

        return row_id

    def append_many(self, events: Sequence[Event]) -> None:
        """Bulk-insert events in a single transaction."""
        if not events:
            return
        with self._tx() as cur:
            cur.executemany(
                """
                INSERT INTO events
                    (kind, timestamp, collector, app_name, app_class,
                     window_title, workspace, idle_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        e.kind.value, e.timestamp, e.collector,
                        e.app_name, e.app_class, e.window_title,
                        e.workspace, e.idle_seconds,
                    )
                    for e in events
                ],
            )

    # ------------------------------------------------------------------ #
    # Reads                                                                #
    # ------------------------------------------------------------------ #

    def query(
        self,
        since:  float | None = None,
        until:  float | None = None,
        kinds:  list[EventKind] | None = None,
        limit:  int | None = None,
    ) -> list[Event]:
        """Return events matching the given filters, oldest first."""
        clauses: list[str] = []
        params: list[object] = []

        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)
        if kinds:
            placeholders = ",".join("?" * len(kinds))
            clauses.append(f"kind IN ({placeholders})")
            params.extend(k.value for k in kinds)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        lim   = f"LIMIT {limit}" if limit else ""

        sql = f"SELECT * FROM events {where} ORDER BY timestamp ASC {lim}"
        rows = self._require_conn().execute(sql, params).fetchall()
        return [_row_to_event(r) for r in rows]

    def latest(self, n: int = 50) -> list[Event]:
        """Return the *n* most recent events, newest first."""
        rows = self._require_conn().execute(
            "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (n,)
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    def count(self) -> int:
        row = self._require_conn().execute("SELECT COUNT(*) FROM events").fetchone()
        return int(row[0])

    def date_range(self) -> tuple[float, float] | None:
        """Return (earliest_ts, latest_ts) or None if the store is empty."""
        row = self._require_conn().execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM events"
        ).fetchone()
        if row[0] is None:
            return None
        return float(row[0]), float(row[1])

    # ------------------------------------------------------------------ #
    # Maintenance                                                          #
    # ------------------------------------------------------------------ #

    def purge_before(self, timestamp: float) -> int:
        """Delete all events older than *timestamp*. Returns deleted count."""
        cur = self._require_conn().execute(
            "DELETE FROM events WHERE timestamp < ?", (timestamp,)
        )
        deleted: int = cur.rowcount
        log.info("Purged %d events before ts=%.0f", deleted, timestamp)
        return deleted

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("StorageEngine is not open. Call .open() first.")
        return self._conn

    @contextmanager
    def _tx(self) -> Generator[sqlite3.Cursor, None, None]:
        conn = self._require_conn()
        conn.execute("BEGIN")
        try:
            cur = conn.cursor()
            yield cur
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def _migrate(self, cur: sqlite3.Cursor) -> None:
        row = cur.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        current = int(row["value"]) if row else 0

        if current < 1:
            # Version 1: initial schema (already created above).
            cur.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '1')"
            )
            log.info("Migrated schema to version 1.")


# ---------------------------------------------------------------------------
# Row → Event conversion
# ---------------------------------------------------------------------------

def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id           = row["id"],
        kind         = EventKind(row["kind"]),
        timestamp    = row["timestamp"],
        collector    = row["collector"],
        app_name     = row["app_name"],
        app_class    = row["app_class"],
        window_title = row["window_title"],
        workspace    = row["workspace"],
        idle_seconds = row["idle_seconds"],
    )
