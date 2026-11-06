# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

from . import __version__
from .daemon import run_forever
from .db import Database
from .files import DB_FILE, TIDAL_FILE, YTM_FILE, run_lock, stop_running
from .guard import EXIT_LOGIN, Guard
from .sync import Options, sync_once

LEGACY = ("login", "sync", "install", "stop", "update", "uninstall")
INTERVAL_HOURS = 6.0
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
        say(f"Skipped {r.skipped_removed} track(s) synced before and removed since.")
    for u in r.approx:
        say(f"Different version of the song: {u}")
    for u in r.missing:
        say(f"No confident match (not in the catalogue, region-locked, or titled differently): {u}")
    for e in r.errors:
        say(f"Error: {e}")
    if r.stopped:
        say(f"Stopped early: {r.stopped}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in LEGACY:  # `playlist-bridge --sync` (old units, old `update`) still works
        argv[0] = "--" + argv[0]
    p = argparse.ArgumentParser(prog="playlist-bridge")
    p.add_argument("--version", action="version", version=f"playlist-bridge {__version__}")
    act = p.add_mutually_exclusive_group()
    for name, text in (
        ("login", "log in to YouTube Music, then to Tidal"),
        ("sync", "keep the two libraries in step, for ever, in the background and at every login (Linux, systemd)"),
        ("stop", "stop the background sync, and do not start it at login"),
        ("update", "install the latest version from GitHub"),
        ("uninstall", "remove everything: the background sync, your logins and data, and the program itself"),
    ):
        act.add_argument(f"--{name}", dest="cmd", action="store_const", const=name, help=text)
    act.add_argument("--install", dest="cmd", action="store_const", const="sync", help=argparse.SUPPRESS)  # the old name of --sync
    p.add_argument(
        "--foreground", action="store_true", help="with --sync: run in this terminal instead of the background (Ctrl+C stops it)"
    )
    args = p.parse_args(argv)
    if not args.cmd:  # no action: show what there is to do
        p.print_help()
        return 0
    HOME.mkdir(parents=True, exist_ok=True)

    if args.cmd == "login":
        from .login import login_all

        login_all(YTM_AUTH, TIDAL_AUTH)
        return 0

    if args.cmd == "update":
        from .update import update

        return update(HOME)
    if args.cmd == "uninstall":
        from .uninstall import uninstall

        return uninstall(HOME)
    if args.cmd == "stop":
        from . import autostart

        autostart.stop()
        return 0

    # systemd sets INVOCATION_ID: the service itself (also an old unit, which runs a bare `--sync`) must never set itself up again
    foreground = args.foreground or "INVOCATION_ID" in os.environ
    if args.cmd == "sync" and not foreground:
        from . import autostart

        if not (YTM_AUTH.exists() and TIDAL_AUTH.exists()):
            print("Log in first: playlist-bridge --login", file=sys.stderr)
            return EXIT_LOGIN
        stop_running(HOME)  # two runs cannot share the lock: a sync left in a terminal would leave the service failing
        try:
            autostart.install(home=os.environ.get("PLAYLIST_BRIDGE_HOME"))
            return 0
        except SystemExit as e:
            print(e.code, file=sys.stderr)
            say("Running in this terminal instead (Ctrl+C stops it).")

    db = Database(DB_PATH)
    from .services import Tidal, YTMusic

    opt = Options()
    g_ytm = Guard("ytm", db, daily_quota=int(os.environ.get("PLAYLIST_BRIDGE_YTM_QUOTA", 2000)))
    g_tidal = Guard("tidal", db, daily_quota=int(os.environ.get("PLAYLIST_BRIDGE_TIDAL_QUOTA", 3000)))

    def cycle():
        # rebuilt each time, so a refreshed login is picked up and a stale session never lingers
        return sync_once(YTMusic(YTM_AUTH, g_ytm), Tidal(TIDAL_AUTH, g_tidal), db, opt)

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    with run_lock(HOME):
        say(f"Playlist-bridge {__version__}: syncing about every {INTERVAL_HOURS:g} h. Ctrl+C stops; progress is saved.")
        try:
            return run_forever(cycle, db, interval_hours=INTERVAL_HOURS, on_report=print_report, log=say)
        except KeyboardInterrupt:
            say("Stopped. Progress is saved; run it again to resume.")
            return 130


if __name__ == "__main__":
    sys.exit(main())
