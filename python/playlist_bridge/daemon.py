# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""The always-on loop: one sync pass, then a long, irregular wait, forever.

What keeps the IP out of trouble:
  * the wait between passes is hours long and random (never a fixed beat that looks like a script);
  * after a pass stopped by the daily budget, the next pass waits for the next UTC day, plus a random delay;
  * after a pass stopped because a service asked us to slow down, it waits until the stored cooldown is over, plus a random delay;
  * a pass that crashes (network down...) is retried with a growing, jittered delay, never in a tight loop;
  * expired credentials end the program: nothing can fix them but the user (`playlist-bridge login`).
"""

from __future__ import annotations

import random
import time

from .db import Database

SERVICES = ("ytm", "tidal")
MIN_INTERVAL_HOURS = 1.0
INTERVAL_JITTER = (0.8, 1.3)  # x the interval
RETRY_BASE_S = 900  # first retry after a crashed pass: 15 min, then 30, 60... up to RETRY_MAX_S
RETRY_MAX_S = 4 * 3600
EXIT_OK, EXIT_FAILED, EXIT_STOPPED, EXIT_AUTH = 0, 1, 2, 3


def seconds_to_next_utc_day(now: float) -> float:
    t = time.gmtime(now)
    return 86400 - (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)


def wait_after(report, db: Database, now: float, interval_s: float, rng: random.Random) -> tuple[float, str]:
    if report.stop_kind == "quota":
        return seconds_to_next_utc_day(now) + rng.uniform(300, 3600), "the daily request budget is used"
    if report.stop_kind == "blocked":
        ends = [cd[0] for s in SERVICES if (cd := db.cooldown(s))]
        base = max(ends) - now if ends else interval_s
        return max(base, 0) + rng.uniform(300, 1800), "a service asked us to slow down"
    return interval_s * rng.uniform(*INTERVAL_JITTER), "next sync"


def human(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def run_forever(
    cycle,
    db: Database,
    *,
    interval_hours: float = 6.0,
    once: bool = False,
    on_report=lambda r: None,
    log=print,
    rng: random.Random | None = None,
    sleep=time.sleep,
    clock=time.time,
) -> int:
    """Run `cycle() -> Report` until interrupted (KeyboardInterrupt propagates). Returns an exit code."""
    interval_s = max(interval_hours, MIN_INTERVAL_HOURS) * 3600
    rng = rng or random.Random()
    failures = 0
    while True:
        try:
            report = cycle()
        except Exception as e:  # network down, service outage...: retry later, never in a tight loop
            failures += 1
            wait = min(RETRY_MAX_S, RETRY_BASE_S * 2 ** (failures - 1)) * rng.uniform(1.0, 1.5)
            why = f"the last sync failed ({type(e).__name__}: {e})"
            code = EXIT_FAILED
        else:
            failures = 0
            on_report(report)
            if report.stop_kind == "auth":
                return EXIT_AUTH
            wait, why = wait_after(report, db, clock(), interval_s, rng)
            code = EXIT_STOPPED if report.stopped else EXIT_OK
        if once:
            return code
        log(f"Next sync in {human(wait)}: {why}.")
        remaining = wait
        while remaining > 0:  # short naps, so Ctrl+C / SIGTERM is never far from being noticed
            step = min(remaining, 60.0)
            sleep(step)
            remaining -= step
