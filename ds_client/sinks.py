"""Event sinks and SQLite persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Protocol, Sequence

from ds_client.models import WatchTarget, Event

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
        delta = (
            f"{event.prev_value} -> {event.value_raw}"
            if event.prev_value
            else event.value_raw
        )
        name = event.label or event.notes or event.target_id or "-"
        print(
            f"[{now()}] [EVENT] {event.event_type} | Address: {event.address_hex} "
            f"| Val: {delta} | {name}"
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
            INSERT INTO event_logs (
                session_id, event_type, address_hex, value_raw, prev_value,
                notes, target_id, label, region, category, tagged
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.session_id,
                event.event_type,
                event.address_hex,
                event.value_raw,
                event.prev_value,
                event.notes,
                event.target_id,
                event.label,
                event.region,
                event.category,
                event.tagged,
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


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db(db_path: Path = DB_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
    # Differential / tagging columns (safe on existing DBs)
    for col, decl in (
        ("prev_value", "TEXT"),
        ("target_id", "TEXT"),
        ("label", "TEXT"),
        ("region", "TEXT"),
        ("category", "TEXT"),
        ("tagged", "INTEGER DEFAULT 0"),
    ):
        _ensure_column(conn, "event_logs", col, decl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_map (
            map_id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id TEXT UNIQUE NOT NULL,
            label TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'misc',
            module TEXT NOT NULL,
            offsets_json TEXT NOT NULL,
            data_type TEXT NOT NULL,
            bitmask TEXT,
            verified_value TEXT,
            region TEXT,
            notes TEXT,
            address_hex TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def start_session(conn: sqlite3.Connection, pid: int) -> int:
    cur = conn.execute("INSERT INTO sessions (pid) VALUES (?)", (pid,))
    conn.commit()
    return int(cur.lastrowid)


def upsert_memory_map_from_target(
    conn: sqlite3.Connection,
    target: WatchTarget,
    *,
    verified_value: Optional[str] = None,
    address_hex: Optional[str] = None,
) -> None:
    """Insert or update a verified mapping row from a WatchTarget."""
    offsets_json = json.dumps([f"0x{o:X}" for o in target.offsets])
    bitmask = target.format_bitmask() if target.bitmask is not None else None
    conn.execute(
        """
        INSERT INTO memory_map (
            target_id, label, category, module, offsets_json, data_type,
            bitmask, verified_value, region, notes, address_hex, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(target_id) DO UPDATE SET
            label=excluded.label,
            category=excluded.category,
            module=excluded.module,
            offsets_json=excluded.offsets_json,
            data_type=excluded.data_type,
            bitmask=excluded.bitmask,
            verified_value=COALESCE(excluded.verified_value, memory_map.verified_value),
            region=excluded.region,
            notes=excluded.notes,
            address_hex=COALESCE(excluded.address_hex, memory_map.address_hex),
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            target.id,
            target.display_name,
            target.category,
            target.module,
            offsets_json,
            target.dtype,
            bitmask,
            verified_value,
            target.region or None,
            target.notes or None,
            address_hex,
        ),
    )
    conn.commit()


def sync_memory_map_from_targets(
    conn: sqlite3.Connection, targets: Sequence[WatchTarget]
) -> int:
    for target in targets:
        upsert_memory_map_from_target(conn, target)
    return len(targets)


def tag_latest_event(
    conn: sqlite3.Connection,
    label: str,
    *,
    region: str = "",
    category: str = "",
) -> Optional[sqlite3.Row]:
    """Tag the most recent non-SESSION delta event; return the updated row."""
    row = conn.execute(
        """
        SELECT log_id FROM event_logs
        WHERE event_type != 'SESSION'
        ORDER BY log_id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None

    log_id = int(row["log_id"])
    conn.execute(
        """
        UPDATE event_logs
        SET label = ?,
            region = CASE WHEN ? != '' THEN ? ELSE region END,
            category = CASE WHEN ? != '' THEN ? ELSE category END,
            tagged = 1,
            notes = ?
        WHERE log_id = ?
        """,
        (label, region, region, category, category, label, log_id),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM event_logs WHERE log_id = ?", (log_id,)
    ).fetchone()


def list_memory_map(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM memory_map
            ORDER BY
                CASE category
                    WHEN 'location_flag' THEN 0
                    WHEN 'inventory' THEN 1
                    WHEN 'stat' THEN 2
                    ELSE 3
                END,
                label COLLATE NOCASE
            """
        )
    )


def list_recent_events(
    conn: sqlite3.Connection, *, limit: int = 40
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT log_id, timestamp, event_type, address_hex, value_raw,
                   prev_value, target_id, label, region, category, notes, tagged
            FROM event_logs
            WHERE event_type != 'SESSION'
            ORDER BY log_id DESC
            LIMIT ?
            """,
            (max(1, limit),),
        )
    )


def telemetry_snapshot(conn: sqlite3.Connection, *, event_limit: int = 40) -> dict:
    """JSON-friendly snapshot for the live dashboard."""
    maps = []
    for row in list_memory_map(conn):
        maps.append({k: row[k] for k in row.keys()})
    events = []
    for row in list_recent_events(conn, limit=event_limit):
        events.append({k: row[k] for k in row.keys()})
    return {"memory_map": maps, "events": events}
