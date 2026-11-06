# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""Request guard: pacing, daily budget, 429/5xx backoff, circuit breaker.

Every call to a streaming service goes through `Guard.call`. Goals:
  * look like a person, not a script: strictly sequential, jittered delays,
    occasional longer pauses;
  * never exceed a self-imposed daily request budget (persisted, so it
    survives restarts) - the run stops cleanly and resumes next time;
  * honour Retry-After, back off exponentially, and after repeated
    throttling open a persisted cooldown instead of hammering a blocked IP.
"""

from __future__ import annotations

import random
import re
import time

from .db import Database

EXIT_LOGIN = 3  # the exit code that means "log in again"


class Stop(Exception):
    """Run must stop now; progress is already saved. Resume later."""


class QuotaExceeded(Stop):
    pass


class Blocked(Stop):
    pass


class AuthExpired(Stop):
    pass


def http_status(exc: BaseException) -> int | None:
    r = getattr(exc, "response", None)
    code = getattr(r, "status_code", None)
    if isinstance(code, int):
        return code
    if type(exc).__name__ == "TooManyRequests":  # tidalapi
        return 429
    m = re.search(r"HTTP\s*(?:error\s*)?(\d{3})", str(exc), re.I)  # ytmusicapi
    return int(m.group(1)) if m else None


def retry_after(exc: BaseException) -> float | None:
    ra = getattr(exc, "retry_after", None)  # tidalapi.TooManyRequests
    if not ra:
        h = getattr(getattr(exc, "response", None), "headers", None) or {}
        ra = h.get("Retry-After")
    try:
        v = float(ra)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def is_network_error(exc: BaseException) -> bool:
    import requests

    return isinstance(
        exc,
        (ConnectionError, TimeoutError, requests.ConnectionError, requests.Timeout),
    )


class Guard:
    def __init__(
        self,
        service: str,
        db: Database,
        *,
        daily_quota: int = 2000,
        min_interval: float = 1.2,
        jitter: float = 0.8,
        long_pause_every: tuple[int, int] | None = (20, 40),
        max_retries: int = 4,
        backoff_base: float = 5.0,
        breaker: int = 3,
        cooldown_s: float = 3600,
        sleep=time.sleep,
        clock=time.time,
        rng: random.Random | None = None,
    ):
        self.service, self.db = service, db
        self.daily_quota, self.min_interval, self.jitter = daily_quota, min_interval, jitter
        self.max_retries, self.backoff_base = max_retries, backoff_base
        self.breaker, self.cooldown_s = breaker, cooldown_s
        self.sleep, self.clock = sleep, clock
        self.rng = rng or random.Random()
        self.long_pause_every = long_pause_every
        self._pause_in = self.rng.randint(*long_pause_every) if long_pause_every else None
        self._last = float("-inf")
        self._throttles = 0

    def _pace(self):
        wait = self.min_interval + self.rng.random() * self.jitter - (self.clock() - self._last)
        if self._pause_in is not None:
            self._pause_in -= 1
            if self._pause_in <= 0:  # human-ish "got distracted" pause
                wait += self.rng.uniform(5, 15)
                self._pause_in = self.rng.randint(*self.long_pause_every)
        if wait > 0:
            self.sleep(wait)
        self._last = self.clock()

    def _open_breaker(self, seconds: float, why: str):
        self.db.set_cooldown(self.service, self.clock() + seconds, why)
        raise Blocked(
            f"{self.service}: {why}. Pausing for {int(seconds // 60)} min. If it keeps happening, try again from a different network."
        )

    def call(self, fn, *args, cost: int = 1, **kwargs):
        cd = self.db.cooldown(self.service)
        if cd:
            raise Blocked(f"{self.service} is cooling down for {int((cd[0] - self.clock()) // 60)} more min ({cd[1]})")
        if self.db.usage(self.service) + cost > self.daily_quota:
            raise QuotaExceeded(
                f"{self.service}: daily budget of {self.daily_quota} requests used. "
                "Progress is saved; run again tomorrow (or raise the quota)."
            )
        attempt = 0
        while True:
            self._pace()
            self.db.add_usage(self.service, cost)
            try:
                res = fn(*args, **kwargs)
            except Exception as e:
                st = http_status(e)
                if st == 401:
                    raise AuthExpired(f"{self.service}: credentials rejected. Run `playlist-bridge --login`.") from e
                throttled = st in (429, 403)
                transient = throttled or (st is not None and st >= 500) or is_network_error(e)
                if not transient:
                    raise
                ra = retry_after(e)
                if throttled:
                    self._throttles += 1
                    if self._throttles >= self.breaker:
                        self._open_breaker(self.cooldown_s, f"repeated HTTP {st} (rate-limited or blocked)")
                    if ra and ra > 900:
                        self._open_breaker(ra, f"server asked to wait {int(ra)}s")
                attempt += 1
                if attempt > self.max_retries:
                    raise
                delay = ra or min(600.0, self.backoff_base * 2**attempt)
                self.sleep(delay * (1 + self.rng.random() * 0.5))
                continue
            self._throttles = 0
            return res
