# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import argparse
import fcntl
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from . import __version__
from .db import Database
from .guard import Guard
from .sync import Options, sync_playlists

HOME = Path(os.environ.get("PLAYLIST_BRIDGE_HOME", Path.home() / ".config" / "playlist-bridge"))
YTM_AUTH = HOME / "ytm_headers.json"
TIDAL_AUTH = HOME / "tidal_session.json"
DB_PATH = HOME / "playlist-bridge.db"


@contextmanager
def run_lock():
    """One run at a time: parallel/overlapping runs look like a bot and double the request rate."""
    f = open(HOME / "lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit("Another playlist-bridge run is in progress.") from None
    try:
        yield
    finally:
        f.close()


def _ts(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "-"


def cmd_status(db: Database, show_missing: bool):
    print("Requests used today:", {s: db.usage(s) for s in ("ytm", "tidal")})
    for s in ("ytm", "tidal"):
        cd = db.cooldown(s)
        if cd:
            print(f"  {s} COOLING DOWN until {_ts(cd[0])}: {cd[1]}")
    print("Matches:", db.match_counts() or "none yet")
    for started, finished, summary in db.last_runs():
        print(f"  run {_ts(started)} -> {_ts(finished)}: {summary}")
    if show_missing:
        print("\nTracks not found on the other service:")
        for dst, label, at in db.missing():
            print(f"  [{dst}] {label}  (checked {_ts(at)})")


def main(argv=None):
    p = argparse.ArgumentParser(prog="playlist-bridge")
    p.add_argument("--version", action="version", version=f"playlist-bridge {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    lg = sub.add_parser("login", help="authenticate a service")
    lg.add_argument("service", choices=["ytm", "tidal"])

    sy = sub.add_parser("sync", help="sync playlists both ways (additive only)")
    sy.add_argument("--playlist", "-p", action="append", help="limit to this name (repeatable)")
    sy.add_argument("--threshold", type=float, default=0.8, help="match score 0-1 (default 0.8)")
    sy.add_argument(
        "--allow-approx", action="store_true", help="accept a different recording (live/remix/...) when the studio one is missing"
    )
    sy.add_argument("--dry-run", "-n", action="store_true", help="search & report, add nothing (still uses quota)")
    sy.add_argument("--force", action="store_true", help="ignore the journal; re-add tracks removed on purpose")
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

    st = sub.add_parser("status", help="request budget, cooldowns, match stats")
    st.add_argument("--missing", action="store_true", help="list tracks with no match")

    rc = sub.add_parser("reset-cooldown", help="clear a rate-limit cooldown early")
    rc.add_argument("service", choices=["ytm", "tidal"])

    args = p.parse_args(argv)
    HOME.mkdir(parents=True, exist_ok=True)

    if args.cmd == "login":
        from .services import login_tidal, login_ytm

        login_ytm(YTM_AUTH) if args.service == "ytm" else login_tidal(TIDAL_AUTH)
        return 0

    db = Database(DB_PATH)
    if args.cmd == "status":
        cmd_status(db, args.missing)
        return 0
    if args.cmd == "reset-cooldown":
        db.clear_cooldown(args.service)
        return 0

    from .services import Tidal, YTMusic

    with run_lock():
        mk = lambda name, q: Guard(name, db, daily_quota=q, min_interval=args.min_interval)  # noqa: E731
        try:
            ytm = YTMusic(YTM_AUTH, mk("ytm", args.ytm_quota))
            tidal = Tidal(TIDAL_AUTH, mk("tidal", args.tidal_quota))
        except Exception as e:
            print(f"Setup failed: {e}", file=sys.stderr)
            return 1
        opt = Options(args.threshold, args.allow_approx, args.retry_missing_days, args.dry_run, args.force, args.playlist)
        try:
            r = sync_playlists(ytm, tidal, db, opt)
        except KeyboardInterrupt:
            print("\nInterrupted. Progress is saved; re-run to resume.")
            return 130

    verb = "Would add" if args.dry_run else "Added"
    print()
    for k, n in r.added.items():
        print(f"{verb} {n} track(s): {k}")
    if not r.added:
        print("Everything already in sync.")
    if r.skipped_removed:
        print(f"Skipped {r.skipped_removed} track(s) previously synced then removed (use --force to re-add).")
    if r.approx:
        print(f"\n{len(r.approx)} added as a different version of the song:")
        print("\n".join(f"  {u}" for u in r.approx))
    if r.missing:
        print(f"\n{len(r.missing)} track(s) with no confident match (not in catalogue, region-locked, or differently titled):")
        print("\n".join(f"  {u}" for u in r.missing))
    if r.errors:
        print("\nErrors:")
        print("\n".join(f"  {e}" for e in r.errors))
    if r.stopped:
        print(f"\nSTOPPED EARLY: {r.stopped}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
