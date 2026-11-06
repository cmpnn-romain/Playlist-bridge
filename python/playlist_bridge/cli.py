# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

from . import __version__
from .daemon import MIN_INTERVAL_HOURS, run_forever
from .db import Database
from .files import DB_FILE, TIDAL_FILE, YTM_FILE, run_lock
from .guard import EXIT_LOGIN, Guard
from .sync import Options, sync_once

HOME = Path(os.environ.get("PLAYLIST_BRIDGE_HOME", Path.home() / ".config" / "playlist-bridge"))
YTM_AUTH = HOME / YTM_FILE
TIDAL_AUTH = HOME / TIDAL_FILE
DB_PATH = HOME / DB_FILE


def _ts(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "-"


def say(msg: str):
    print(f"[{_ts(time.time())}] {msg}", flush=True)


def print_report(r):
    if r.added:
        for k, n in r.added.items():
            say(f"Added {n} track(s): {k}")
    else:
        say("Everything is in sync.")
    if r.skipped_removed:
        say(f"Skipped {r.skipped_removed} track(s) synced before and removed since (--force with --once adds them back).")
    for u in r.approx:
        say(f"Different version of the song: {u}")
    for u in r.missing:
        say(f"No confident match (not in the catalogue, region-locked, or titled differently): {u}")
    for e in r.errors:
        say(f"Error: {e}")
    if r.stopped:
        say(f"Stopped early: {r.stopped}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="playlist-bridge")
    p.add_argument("--version", action="version", version=f"playlist-bridge {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="log in to YouTube Music, then to Tidal")

    sy = sub.add_parser("sync", help="keep the two libraries in step, for ever (liked songs and playlists, both ways, additive only)")
    sy.add_argument(
        "--interval-hours",
        type=float,
        default=6.0,
        help=f"about this long between syncs (default 6, at least {MIN_INTERVAL_HOURS:g}; randomised)",
    )
    sy.add_argument("--once", action="store_true", help="sync once and exit (for cron)")
    sy.add_argument("--threshold", type=float, default=0.8, help="match score 0-1 (default 0.8)")
    sy.add_argument(
        "--allow-approx", action="store_true", help="accept a different recording (live/remix/...) when the studio one is missing"
    )
    sy.add_argument("--force", action="store_true", help="with --once: ignore the journal and re-add tracks removed on purpose")
    sy.add_argument("--retry-missing-days", type=float, default=14)
    sy.add_argument(
        "--ytm-quota",
        type=int,
        default=int(os.environ.get("PLAYLIST_BRIDGE_YTM_QUOTA", 2000)),
        help="max YouTube Music requests per UTC day (self-imposed, default 2000)",
    )
    sy.add_argument(
        "--tidal-quota",
        type=int,
        default=int(os.environ.get("PLAYLIST_BRIDGE_TIDAL_QUOTA", 3000)),
        help="max Tidal requests per UTC day (self-imposed, default 3000)",
    )
    sy.add_argument("--min-interval", type=float, default=1.2, help="minimum seconds between requests, plus random jitter (default 1.2)")

    sub.add_parser("install", help="run sync in the background, now and at every login (Linux, systemd)")
    sub.add_parser("stop", help="stop the background sync, and do not start it at login")
    un = sub.add_parser("uninstall", help="remove everything: the background sync, your logins and data, and the program itself")
    un.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")

    rc = sub.add_parser("reset-cooldown", help="clear a rate-limit cooldown early")
    rc.add_argument("service", choices=["ytm", "tidal"])

    args = p.parse_args(argv)
    HOME.mkdir(parents=True, exist_ok=True)

    if args.cmd == "login":
        from .login import login_all

        login_all(YTM_AUTH, TIDAL_AUTH)
        return 0

    if args.cmd == "uninstall":
        from .uninstall import uninstall

        return uninstall(HOME, yes=args.yes)
    if args.cmd in ("install", "stop"):
        from . import autostart

        if args.cmd == "stop":
            autostart.stop()
        elif not (YTM_AUTH.exists() and TIDAL_AUTH.exists()):
            print("Log in first: playlist-bridge login", file=sys.stderr)
            return EXIT_LOGIN
        else:
            autostart.install(home=os.environ.get("PLAYLIST_BRIDGE_HOME"))
        return 0

    db = Database(DB_PATH)
    if args.cmd == "reset-cooldown":
        db.clear_cooldown(args.service)
        return 0

    if args.force and not args.once:
        p.error("--force only makes sense with --once (it would re-add removed tracks at every sync)")

    from .services import Tidal, YTMusic

    opt = Options(args.threshold, args.allow_approx, args.retry_missing_days, args.force)
    g_ytm = Guard("ytm", db, daily_quota=args.ytm_quota, min_interval=args.min_interval)
    g_tidal = Guard("tidal", db, daily_quota=args.tidal_quota, min_interval=args.min_interval)

    def cycle():
        # rebuilt each time, so a refreshed login is picked up and a stale session never lingers
        return sync_once(YTMusic(YTM_AUTH, g_ytm), Tidal(TIDAL_AUTH, g_tidal), db, opt)

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    with run_lock(HOME):
        hours = max(args.interval_hours, MIN_INTERVAL_HOURS)
        say(f"Playlist-bridge {__version__}: syncing about every {hours:g} h. Ctrl+C stops; progress is saved.")
        try:
            return run_forever(cycle, db, interval_hours=args.interval_hours, once=args.once, on_report=print_report, log=say)
        except KeyboardInterrupt:
            say("Stopped. Progress is saved; run it again to resume.")
            return 130


if __name__ == "__main__":
    sys.exit(main())
