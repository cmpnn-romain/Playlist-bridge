# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""The names of the files Playlist-bridge keeps in its folder (~/.config/playlist-bridge). Nothing else there is ever touched."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path

YTM_FILE = "ytm_headers.json"
TIDAL_FILE = "tidal_session.json"
DB_FILE = "playlist-bridge.db"
LOCK_FILE = "lock"
COMMIT_FILE = "installed-commit"  # the commit `update` last installed
# the database may leave SQLite's side files next to it
OWN_FILES = (YTM_FILE, TIDAL_FILE, DB_FILE, f"{DB_FILE}-journal", f"{DB_FILE}-wal", f"{DB_FILE}-shm", LOCK_FILE, COMMIT_FILE)


@contextmanager
def run_lock(home: Path):
    """One run at a time: parallel/overlapping runs look like a bot and double the request rate."""
    f = open(home / LOCK_FILE, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise SystemExit("Another playlist-bridge run is in progress.") from None
    try:
        yield
    finally:
        f.close()
