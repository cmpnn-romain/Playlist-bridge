# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""SQLite state: match cache, sync journal, request budget, cooldowns, run history.

Everything that makes a run idempotent and resumable lives here. Writes are
committed immediately so a crash / Ctrl-C / quota stop never loses progress.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists(
    key TEXT PRIMARY KEY, title TEXT, ytm_id TEXT, tidal_id TEXT, updated_at REAL);
-- Result of searching `dst` for the track identified by src_key.
-- status: matched | approx (different version) | missing (not in catalogue / region)
CREATE TABLE IF NOT EXISTS matches(
    dst TEXT, src_key TEXT, src_label TEXT, dst_id TEXT, score REAL,
    status TEXT, checked_at REAL, PRIMARY KEY(dst, src_key));
-- Journal of tracks actually added to a destination playlist (after the API call succeeded).
CREATE TABLE IF NOT EXISTS synced(
    playlist_key TEXT, dst TEXT, src_key TEXT, dst_id TEXT, added_at REAL,
    PRIMARY KEY(playlist_key, dst, src_key));
CREATE TABLE IF NOT EXISTS usage(
    service TEXT, day TEXT, count INTEGER, PRIMARY KEY(service, day));
CREATE TABLE IF NOT EXISTS cooldown(
    service TEXT PRIMARY KEY, until REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL, finished REAL, summary TEXT);
"""


@dataclass
class MatchRow:
    dst_id: str | None
    score: float
    status: str
    checked_at: float


class Database:
    def __init__(self, path: Path | str, clock=time.time):
        self.clock = clock
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _day(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self.clock()))

    # -- playlists
    def upsert_playlist(self, key, title, ytm_id, tidal_id):
        with self.conn:
            self.conn.execute(
                "INSERT INTO playlists VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                "title=excluded.title, ytm_id=COALESCE(excluded.ytm_id, ytm_id), "
                "tidal_id=COALESCE(excluded.tidal_id, tidal_id), updated_at=excluded.updated_at",
                (key, title, ytm_id, tidal_id, self.clock()),
            )

    def set_playlist_id(self, key, service, pid):
        col = {"ytm": "ytm_id", "tidal": "tidal_id"}[service]
        with self.conn:
            self.conn.execute(f"UPDATE playlists SET {col}=? WHERE key=?", (pid, key))

    # -- matches
    def get_match(self, dst, src_key) -> MatchRow | None:
        r = self.conn.execute(
            "SELECT dst_id, score, status, checked_at FROM matches WHERE dst=? AND src_key=?",
            (dst, src_key),
        ).fetchone()
        return MatchRow(*r) if r else None

    def put_match(self, dst, src_key, label, dst_id, score, status):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO matches VALUES(?,?,?,?,?,?,?)",
                (dst, src_key, label, dst_id, score, status, self.clock()),
            )

    def match_counts(self) -> dict[str, int]:
        return dict(self.conn.execute("SELECT status, COUNT(*) FROM matches GROUP BY status").fetchall())

    # -- sync journal
    def was_synced(self, playlist_key, dst, src_key) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM synced WHERE playlist_key=? AND dst=? AND src_key=?",
                (playlist_key, dst, src_key),
            ).fetchone()
            is not None
        )

    def mark_synced(self, playlist_key, dst, items: list[tuple[str, str]]):
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO synced VALUES(?,?,?,?,?)",
                [(playlist_key, dst, k, d, self.clock()) for k, d in items],
            )

    # -- request budget / cooldown
    def usage(self, service) -> int:
        r = self.conn.execute("SELECT count FROM usage WHERE service=? AND day=?", (service, self._day())).fetchone()
        return r[0] if r else 0

    def add_usage(self, service, n=1):
        with self.conn:
            self.conn.execute(
                "INSERT INTO usage VALUES(?,?,?) ON CONFLICT(service,day) DO UPDATE SET count=count+?",
                (service, self._day(), n, n),
            )

    def cooldown(self, service) -> tuple[float, str] | None:
        r = self.conn.execute("SELECT until, reason FROM cooldown WHERE service=?", (service,)).fetchone()
        return r if r and r[0] > self.clock() else None

    def set_cooldown(self, service, until, reason):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO cooldown VALUES(?,?,?)", (service, until, reason))

    def clear_cooldown(self, service):
        with self.conn:
            self.conn.execute("DELETE FROM cooldown WHERE service=?", (service,))

    # -- runs
    def start_run(self) -> int:
        with self.conn:
            return self.conn.execute("INSERT INTO runs(started) VALUES(?)", (self.clock(),)).lastrowid

    def finish_run(self, run_id, summary: dict):
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET finished=?, summary=? WHERE id=?",
                (self.clock(), json.dumps(summary), run_id),
            )

    def last_runs(self, n=5):
        return self.conn.execute("SELECT started, finished, summary FROM runs ORDER BY id DESC LIMIT ?", (n,)).fetchall()
