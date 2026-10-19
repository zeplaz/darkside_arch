"""Event sinks and SQLite persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol, Sequence

from ds_client.models import Event

DB_FILE = Path("darksiders_debug.db")
FLUSH_EVERY_EVENTS = 32


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...
    def flush(self) -> None: ...


class TerminalSink:
    """Stdout sink — prints only what the bus publishes (change/session events)."""

    def emit(self, event: Event) -> None:
        print(
            f"[{now()}] [EVENT] {event.event_type} | Address: {event.address_hex} "
            f"| Val: {event.value_raw} | {event.notes}"
        )

    def flush(self) -> None:
        return


class SqliteSink:
    """Buffered SQLite writer (WAL)."""

    def __init__(
        self, conn: sqlite3.Connection, flush_every: int = FLUSH_EVERY_EVENTS
    ) -> None:
        self._conn = conn
        self._flush_every = flush_every
        self._pending = 0

    def emit(self, event: Event) -> None:
        self._conn.execute(
            """
            INSERT INTO event_logs (session_id, event_type, address_hex, value_raw, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.session_id,
                event.event_type,
                event.address_hex,
                event.value_raw,
                event.notes,
            ),
        )
        self._pending += 1
        if self._pending >= self._flush_every:
            self.flush()

    def flush(self) -> None:
        if self._pending:
            self._conn.commit()
            self._pending = 0


class EventBus:
    def __init__(self, sinks: Sequence[EventSink]) -> None:
        self._sinks = list(sinks)

    def publish(self, event: Event) -> None:
        for sink in self._sinks:
            sink.emit(event)

    def flush(self) -> None:
        for sink in self._sinks:
            sink.flush()


def init_db(db_path: Path = DB_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pid INTEGER,
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS event_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            event_type TEXT,
            address_hex TEXT,
            value_raw TEXT,
            notes TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
        """
    )
    conn.commit()
    return conn


def start_session(conn: sqlite3.Connection, pid: int) -> int:
    cur = conn.execute("INSERT INTO sessions (pid) VALUES (?)", (pid,))
    conn.commit()
    return int(cur.lastrowid)
