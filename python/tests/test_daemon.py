# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
import random
import re
import time

import pytest

from playlist_bridge.daemon import (
    EXIT_AUTH,
    EXIT_FAILED,
    EXIT_OK,
    EXIT_STOPPED,
    MIN_INTERVAL_HOURS,
    RETRY_MAX_S,
    run_forever,
    seconds_to_next_utc_day,
    wait_after,
)
from playlist_bridge.db import Database
from playlist_bridge.sync import Report

H = 3600


class Stopper(Exception):
    pass


def loop(cycle, db, rounds, **kw):
    """Run run_forever with a fake clock/sleep, stopping after `rounds` waits."""
    naps, logs = [], []

    def sleep(s):
        naps.append(s)
        if len([n for n in naps]) > 10_000:
            raise AssertionError("runaway")

    state = {"waits": 0}

    def log(m):
        logs.append(m)
        state["waits"] += 1
        if state["waits"] >= rounds:
            raise Stopper

    with pytest.raises(Stopper):
        run_forever(cycle, db, log=log, sleep=sleep, rng=random.Random(1), **kw)
    return naps, logs


def test_normal_wait_is_hours_long_and_irregular(tmp_path):
    db = Database(tmp_path / "d.db")
    waits = []
    for seed in range(50):
        w, _ = wait_after(Report(), db, time.time(), 6 * H, random.Random(seed))
        waits.append(w)
    assert all(0.8 * 6 * H <= w <= 1.3 * 6 * H for w in waits)
    assert len({round(w) for w in waits}) > 40  # never the same beat twice


def test_interval_cannot_be_set_below_the_minimum(tmp_path):
    db = Database(tmp_path / "d.db")
    msgs = []

    def sleep(s):
        raise Stopper

    with pytest.raises(Stopper):
        run_forever(lambda: Report(), db, interval_hours=0.001, sleep=sleep, log=msgs.append, rng=random.Random(1))
    m = re.search(r"in (?:(\d+)h )?(\d+)m", msgs[0])
    minutes = int(m.group(1) or 0) * 60 + int(m.group(2))
    assert minutes >= 0.8 * MIN_INTERVAL_HOURS * 60 - 1


def test_quota_stop_waits_for_next_utc_day(tmp_path):
    db = Database(tmp_path / "d.db")
    r = Report(stopped="budget", stop_kind="quota")
    w, why = wait_after(r, db, 5 * H, 6 * H, random.Random(1))
    assert 19 * H + 300 <= w <= 19 * H + 3600 and "budget" in why
    assert seconds_to_next_utc_day(5 * H) == 19 * H


def test_blocked_stop_waits_out_the_cooldown(tmp_path):
    db = Database(tmp_path / "d.db")
    now = 1_000_000.0
    db.clock = lambda: now
    db.set_cooldown("tidal", now + 2 * H, "429")
    w, _ = wait_after(Report(stopped="x", stop_kind="blocked"), db, now, 6 * H, random.Random(1))
    assert 2 * H + 300 <= w <= 2 * H + 1800


def test_a_crashed_pass_is_retried_and_the_loop_recovers(tmp_path):
    db = Database(tmp_path / "d.db")
    calls = {"n": 0}

    def cycle():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ConnectionError("network down")
        return Report()

    naps, logs = loop(cycle, db, 3)
    assert "ConnectionError" in logs[0] and "ConnectionError" in logs[1]
    assert "next sync" in logs[2].lower()
    assert max(naps) <= 60  # always short naps, so Ctrl+C is noticed


def test_retry_delays_grow_then_cap(tmp_path):
    db = Database(tmp_path / "d.db")
    seen = []

    def cycle():
        raise ConnectionError("down")

    def sleep(s):
        seen.append(s)

    state = {"n": 0}

    def log(m):
        state["n"] += 1
        if state["n"] >= 8:
            raise Stopper

    with pytest.raises(Stopper):
        run_forever(cycle, db, log=log, sleep=sleep, rng=random.Random(1))
    # regroup the 60 s naps into one wait per failure
    waits, cur = [], 0.0
    for s in seen:
        cur += s
        if s < 60:
            waits.append(cur)
            cur = 0.0
    assert waits[0] < waits[1] < waits[2]
    assert max(waits) <= RETRY_MAX_S * 1.5 + 60


def test_auth_failure_ends_the_program(tmp_path):
    db = Database(tmp_path / "d.db")
    code = run_forever(lambda: Report(stopped="login", stop_kind="auth"), db, sleep=lambda s: None, log=lambda m: None)
    assert code == EXIT_AUTH


def test_once_exit_codes(tmp_path):
    db = Database(tmp_path / "d.db")
    quiet = dict(once=True, sleep=lambda s: None, log=lambda m: None)
    assert run_forever(lambda: Report(), db, **quiet) == EXIT_OK
    assert run_forever(lambda: Report(stopped="x", stop_kind="quota"), db, **quiet) == EXIT_STOPPED

    def boom():
        raise RuntimeError("x")

    assert run_forever(boom, db, **quiet) == EXIT_FAILED


def test_report_callback_runs_each_pass(tmp_path):
    db = Database(tmp_path / "d.db")
    got = []
    loop(lambda: Report(), db, 3, on_report=got.append)
    assert len(got) == 3


def test_keyboard_interrupt_propagates(tmp_path):
    db = Database(tmp_path / "d.db")

    def cycle():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_forever(cycle, db, sleep=lambda s: None, log=lambda m: None)
