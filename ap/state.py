"""Dedicated AP resync state. Not the mapper debug DB."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from ds_client.ap_protocol import NetworkItem

DB_FILE = Path("ap_state.db")


@dataclass(frozen=True)
class ReceivedRow:
    seed_name: str
    team: int
    slot: int
    idx: int
    item_id: int
    location: int
    player: int
    flags: int
    applied: int


class ApState:
    def __init__(self, db_path: Path = DB_FILE) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS slot_state (
                seed_name TEXT NOT NULL,
                team INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                last_ingested_index INTEGER NOT NULL DEFAULT 0,
                last_applied_index INTEGER NOT NULL DEFAULT 0,
                server_host TEXT,
                server_port INTEGER,
                blade_granted INTEGER NOT NULL DEFAULT 0,
                goal_sent INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (seed_name, team, slot)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS received_items (
                seed_name TEXT NOT NULL,
                team INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                idx INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                location INTEGER NOT NULL,
                player INTEGER NOT NULL,
                flags INTEGER NOT NULL DEFAULT 0,
                applied INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (seed_name, team, slot, idx)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checked_locations (
                seed_name TEXT NOT NULL,
                team INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                location_id INTEGER NOT NULL,
                PRIMARY KEY (seed_name, team, slot, location_id)
            )
            """
        )
        self._conn.commit()

    def _ensure_slot(self, seed_name: str, team: int, slot: int) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO slot_state (seed_name, team, slot)
            VALUES (?, ?, ?)
            """,
            (seed_name, team, slot),
        )

    def bind_server(
        self,
        seed_name: str,
        team: int,
        slot: int,
        host: str,
        port: int,
    ) -> None:
        with self._lock:
            self._ensure_slot(seed_name, team, slot)
            self._conn.execute(
                """
                UPDATE slot_state
                SET server_host = ?, server_port = ?
                WHERE seed_name = ? AND team = ? AND slot = ?
                """,
                (host, port, seed_name, team, slot),
            )
            self._conn.commit()

    def last_ingested_index(self, seed_name: str, team: int, slot: int) -> int:
        with self._lock:
            self._ensure_slot(seed_name, team, slot)
            row = self._conn.execute(
                """
                SELECT last_ingested_index FROM slot_state
                WHERE seed_name = ? AND team = ? AND slot = ?
                """,
                (seed_name, team, slot),
            ).fetchone()
            return int(row["last_ingested_index"]) if row else 0

    def ingest_received(
        self,
        seed_name: str,
        team: int,
        slot: int,
        start_index: int,
        items: Sequence[NetworkItem],
    ) -> list[ReceivedRow]:
        """Store ReceivedItems by absolute index. Replay does not clear applied flags.

        Returns rows that still need a RAM apply (new or previously unapplied).
        """
        pending: list[ReceivedRow] = []
        with self._lock:
            self._ensure_slot(seed_name, team, slot)
            max_idx = self._conn.execute(
                """
                SELECT last_ingested_index FROM slot_state
                WHERE seed_name = ? AND team = ? AND slot = ?
                """,
                (seed_name, team, slot),
            ).fetchone()
            ingested = int(max_idx["last_ingested_index"]) if max_idx else 0
            for offset, item in enumerate(items):
                idx = start_index + offset
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO received_items (
                        seed_name, team, slot, idx, item_id, location, player, flags, applied
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        seed_name,
                        team,
                        slot,
                        idx,
                        item.item,
                        item.location,
                        item.player,
                        item.flags,
                    ),
                )
                row = self._conn.execute(
                    """
                    SELECT * FROM received_items
                    WHERE seed_name = ? AND team = ? AND slot = ? AND idx = ?
                    """,
                    (seed_name, team, slot, idx),
                ).fetchone()
                if row is None:
                    continue
                rec = _row_to_received(row)
                if rec.applied == 0:
                    pending.append(rec)
                if idx + 1 > ingested:
                    ingested = idx + 1
            self._conn.execute(
                """
                UPDATE slot_state SET last_ingested_index = ?
                WHERE seed_name = ? AND team = ? AND slot = ?
                """,
                (ingested, seed_name, team, slot),
            )
            self._conn.commit()
        return pending

    def mark_applied(
        self, seed_name: str, team: int, slot: int, idx: int
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE received_items SET applied = 1
                WHERE seed_name = ? AND team = ? AND slot = ? AND idx = ?
                """,
                (seed_name, team, slot, idx),
            )
            self._conn.commit()

    def is_pending(self, seed_name: str, team: int, slot: int, idx: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT applied FROM received_items
                WHERE seed_name = ? AND team = ? AND slot = ? AND idx = ?
                """,
                (seed_name, team, slot, idx),
            ).fetchone()
            return row is not None and not row["applied"]

    def pending_applies(
        self, seed_name: str, team: int, slot: int
    ) -> list[ReceivedRow]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM received_items
                WHERE seed_name = ? AND team = ? AND slot = ? AND applied = 0
                ORDER BY idx
                """,
                (seed_name, team, slot),
            ).fetchall()
            return [_row_to_received(r) for r in rows]

    def item_count(self, seed_name: str, team: int, slot: int, item_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS n FROM received_items
                WHERE seed_name = ? AND team = ? AND slot = ? AND item_id = ?
                """,
                (seed_name, team, slot, item_id),
            ).fetchone()
            return int(row["n"]) if row else 0

    def add_checked_locations(
        self, seed_name: str, team: int, slot: int, location_ids: Iterable[int]
    ) -> list[int]:
        """Insert location ids. Returns ids that were new."""
        new_ids: list[int] = []
        with self._lock:
            self._ensure_slot(seed_name, team, slot)
            for loc in location_ids:
                loc_i = int(loc)
                cur = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO checked_locations (
                        seed_name, team, slot, location_id
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (seed_name, team, slot, loc_i),
                )
                if cur.rowcount:
                    new_ids.append(loc_i)
            self._conn.commit()
        return new_ids

    def checked_locations(
        self, seed_name: str, team: int, slot: int
    ) -> list[int]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT location_id FROM checked_locations
                WHERE seed_name = ? AND team = ? AND slot = ?
                ORDER BY location_id
                """,
                (seed_name, team, slot),
            ).fetchall()
            return [int(r["location_id"]) for r in rows]

    def blade_granted(self, seed_name: str, team: int, slot: int) -> bool:
        with self._lock:
            self._ensure_slot(seed_name, team, slot)
            row = self._conn.execute(
                """
                SELECT blade_granted FROM slot_state
                WHERE seed_name = ? AND team = ? AND slot = ?
                """,
                (seed_name, team, slot),
            ).fetchone()
            return bool(row["blade_granted"]) if row else False

    def set_blade_granted(
        self, seed_name: str, team: int, slot: int, value: bool = True
    ) -> None:
        with self._lock:
            self._ensure_slot(seed_name, team, slot)
            self._conn.execute(
                """
                UPDATE slot_state SET blade_granted = ?
                WHERE seed_name = ? AND team = ? AND slot = ?
                """,
                (1 if value else 0, seed_name, team, slot),
            )
            self._conn.commit()

    def goal_sent(self, seed_name: str, team: int, slot: int) -> bool:
        with self._lock:
            self._ensure_slot(seed_name, team, slot)
            row = self._conn.execute(
                """
                SELECT goal_sent FROM slot_state
                WHERE seed_name = ? AND team = ? AND slot = ?
                """,
                (seed_name, team, slot),
            ).fetchone()
            return bool(row["goal_sent"]) if row else False

    def set_goal_sent(
        self, seed_name: str, team: int, slot: int, value: bool = True
    ) -> None:
        with self._lock:
            self._ensure_slot(seed_name, team, slot)
            self._conn.execute(
                """
                UPDATE slot_state SET goal_sent = ?
                WHERE seed_name = ? AND team = ? AND slot = ?
                """,
                (1 if value else 0, seed_name, team, slot),
            )
            self._conn.commit()


def _row_to_received(row: sqlite3.Row) -> ReceivedRow:
    return ReceivedRow(
        seed_name=str(row["seed_name"]),
        team=int(row["team"]),
        slot=int(row["slot"]),
        idx=int(row["idx"]),
        item_id=int(row["item_id"]),
        location=int(row["location"]),
        player=int(row["player"]),
        flags=int(row["flags"]),
        applied=int(row["applied"]),
    )


def open_state(db_path: Path = DB_FILE) -> ApState:
    return ApState(db_path)
