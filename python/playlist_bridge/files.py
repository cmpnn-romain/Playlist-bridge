# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""The names of the files Playlist-bridge keeps in its folder (~/.config/playlist-bridge). Nothing else there is ever touched."""

from __future__ import annotations

import fcntl
import os
import signal
import time
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
    """One run at a time: parallel/overlapping runs look like a bot and double the request rate. The lock file holds the run's pid."""
    f = open(home / LOCK_FILE, "a+")  # not "w": a second run must not wipe the pid of the first
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise SystemExit("Another playlist-bridge run is in progress.") from None
    f.seek(0)
    f.truncate()
    f.write(f"{os.getpid()}\n")
    f.flush()
    try:
        yield
    finally:
        f.close()


def running_pid(home: Path) -> int | None:
    """The pid of the run holding the lock, or None when nothing is running."""
    try:
        f = open(home / LOCK_FILE)
    except OSError:
        return None
    with f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:  # held: a run is going
            try:
                return int(f.read().strip())
            except ValueError:
                return None
        return None  # we got it, so nobody had it


def stop_running(home: Path, *, say=print, kill=os.kill, sleep=time.sleep, wait: float = 15.0) -> bool:
    """Stop a sync running in a terminal (SIGTERM: it saves its progress and exits). True if there was one."""
    pid = running_pid(home)
    if pid is None:
        return False
    try:
        kill(pid, signal.SIGTERM)
    except OSError:
        return False
    for _ in range(int(wait * 4)):
        if running_pid(home) is None:
            break
        sleep(0.25)
    say("Stopped the sync that was running in a terminal. Start it again with `playlist-bridge --sync`.")
    return True
