# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
import time

import pytest

from playlist_bridge.db import Database
from playlist_bridge.guard import AuthExpired, Blocked, Guard, QuotaExceeded
from playlist_bridge.matching import Index, Track, best_match, norm, version_tags
from playlist_bridge.services import LIKED
from playlist_bridge.sync import Options, sync_once


def T(svc, id, title, artists, dur=200, album=None, ok=True):
    return Track(svc, id, title, artists, dur, album, ok)


# ---------- formatting inconsistencies / fuzzy matching ----------
@pytest.mark.parametrize(
    "a,b",
    [
        ("Song (Remastered 2011)", "Song"),
        ("Song - 2011 Remaster", "Song"),
        ("Song [feat. X]", "Song"),
        ("Song (Radio Edit)", "Song"),
        ("Song - Single Version", "Song"),
        ("Beyoncé", "Beyonce"),
        ("Don’t Stop", "Dont Stop"),
        ("The Chain", "Chain"),
        ("Rock & Roll", "Rock and Roll"),
        ("Ｓｏｎｇ", "Song"),  # full-width
        ('Song (From "The Movie")', "Song"),
    ],
)
def test_norm_equivalences(a, b):
    assert norm(a) == norm(b)


def test_norm_keeps_meaningful_words():
    assert norm("With or Without You") == "with or without you"
    assert norm("Left Foot Creep") == "left foot creep"
    assert norm("!!!") == "!!!"  # never normalizes to empty


def test_non_latin_not_mangled():
    assert norm("がんばれ") == "がんばれ"


def test_artist_prefix_in_title_and_multi_artist():
    src = T("ytm", "1", "Radiohead - Creep", ["Radiohead"])
    cand = T("tidal", "9", "Creep", ["Radiohead"])
    assert best_match(src, [cand]).track is cand
    src2 = T("ytm", "1", "Under Pressure", ["Queen", "David Bowie"])
    cand2 = T("tidal", "9", "Under Pressure", ["Queen & David Bowie"])
    assert best_match(src2, [cand2]).track is cand2


def test_picks_best_among_versions_using_duration():
    src = T("ytm", "1", "Creep", ["Radiohead"], 238)
    live = T("tidal", "7", "Creep (Live)", ["Radiohead"], 240)
    good = T("tidal", "9", "Creep - Remastered", ["Radiohead"], 239)
    assert best_match(src, [live, good]).track is good


# ---------- different versions of the same song ----------
def test_version_mismatch_rejected_unless_approx():
    src = T("ytm", "1", "Creep", ["Radiohead"], 238)
    live = T("tidal", "7", "Creep (Live)", ["Radiohead"], 238)
    assert version_tags("Creep (Live)") == {"live"}
    assert best_match(src, [live]) is None
    m = best_match(src, [live], allow_approx=True)
    assert m and m.approx and m.track is live
    # and the reverse: a live source must not silently become the studio cut
    assert best_match(T("ytm", "2", "Creep (Live)", ["Radiohead"]), [T("tidal", "9", "Creep", ["Radiohead"])]) is None


def test_wrong_artist_rejected():
    assert best_match(T("ytm", "1", "Creep", ["Radiohead"]), [T("tidal", "9", "Creep", ["Stone Temple Pilots"])]) is None


# ---------- regional licensing ----------
def test_unavailable_candidates_skipped():
    src = T("ytm", "1", "Creep", ["Radiohead"])
    blocked = T("tidal", "8", "Creep", ["Radiohead"], ok=False)
    ok = T("tidal", "9", "Creep (Remastered)", ["Radiohead"])
    assert best_match(src, [blocked]) is None
    assert best_match(src, [blocked, ok]).track is ok


def test_index_tolerates_formatting():
    idx = Index([T("tidal", "1", "Song - 2011 Remaster", ["A & B"])])
    assert idx.has(T("ytm", "2", "Song", ["A"]))
    assert not idx.has(T("ytm", "3", "Song (Live)", ["A"]))


# ---------- guard: 429, backoff, breaker, quota, auth ----------
class Boom(Exception):
    def __init__(self, status, retry_after=None):
        super().__init__(f"HTTP {status}")
        self.response = type("R", (), {"status_code": status, "headers": {"Retry-After": str(retry_after)} if retry_after else {}})()


def guard(db, **kw):
    sleeps = []
    kw.setdefault("min_interval", 0)
    kw.setdefault("jitter", 0)
    kw.setdefault("long_pause_every", None)
    g = Guard("ytm", db, sleep=sleeps.append, **kw)
    return g, sleeps


def flaky(*errors):
    errs = list(errors)

    def fn():
        if errs:
            raise errs.pop(0)
        return "ok"

    return fn


def test_retry_after_honoured_then_success(tmp_path):
    db = Database(tmp_path / "d.db")
    g, sleeps = guard(db)
    assert g.call(flaky(Boom(429, retry_after=7))) == "ok"
    assert 7 <= sleeps[0] <= 7 * 1.5
    assert db.usage("ytm") == 2  # retries count against the budget


def test_exponential_backoff_on_5xx(tmp_path):
    g, sleeps = guard(Database(tmp_path / "d.db"))
    assert g.call(flaky(Boom(503), Boom(502))) == "ok"
    assert sleeps[1] > sleeps[0]


def test_breaker_opens_persisted_cooldown(tmp_path):
    db = Database(tmp_path / "d.db")
    g, _ = guard(db, breaker=3)
    with pytest.raises(Blocked):
        g.call(flaky(Boom(429), Boom(429), Boom(429), Boom(429)))
    assert db.cooldown("ytm")
    # a brand-new process/guard must refuse immediately, without touching the network
    g2, _ = guard(db)
    called = []
    with pytest.raises(Blocked):
        g2.call(lambda: called.append(1))
    assert not called


def test_huge_retry_after_blocks_immediately(tmp_path):
    db = Database(tmp_path / "d.db")
    g, _ = guard(db)
    with pytest.raises(Blocked):
        g.call(flaky(Boom(429, retry_after=7200)))
    assert db.cooldown("ytm")[0] > time.time() + 7000


def test_daily_quota(tmp_path):
    db = Database(tmp_path / "d.db")
    g, _ = guard(db, daily_quota=2)
    g.call(lambda: 1)
    g.call(lambda: 1)
    with pytest.raises(QuotaExceeded):
        g.call(lambda: 1)


def test_auth_error_not_retried(tmp_path):
    g, sleeps = guard(Database(tmp_path / "d.db"))
    with pytest.raises(AuthExpired):
        g.call(flaky(Boom(401)))
    assert not sleeps


def test_non_transient_error_propagates(tmp_path):
    g, _ = guard(Database(tmp_path / "d.db"))
    with pytest.raises(ValueError):
        g.call(flaky(ValueError("bad")))


def test_pacing_adds_delay_and_long_pauses(tmp_path):
    sleeps = []
    t = [0.0]
    g = Guard(
        "ytm",
        Database(tmp_path / "d.db"),
        min_interval=1.0,
        jitter=0.5,
        long_pause_every=(3, 3),
        sleep=lambda s: (sleeps.append(s), t.__setitem__(0, t[0] + s)),
        clock=lambda: t[0],
    )
    for _ in range(6):
        g.call(lambda: 1)
    assert all(s >= 0.9 for s in sleeps[1:])
    assert max(sleeps) >= 5  # the periodic long pause


# ---------- sync: fakes ----------
class Fake:
    def __init__(self, name, pls, catalog):
        self.name, self.pls, self.catalog = name, pls, catalog
        self.added, self.searches = [], 0
        self.fail_add = None

    def playlists(self):
        return {k: k for k in self.pls if k != LIKED}

    def tracks(self, pid):
        return list(self.pls.get(pid, []))

    def search(self, q):
        self.searches += 1
        return self.catalog

    def create_playlist(self, title):
        self.pls[title] = []
        return title

    def add(self, pid, ids):
        if self.fail_add:
            raise self.fail_add
        self.added.append((pid, list(ids)))
        for i in ids:
            self.pls.setdefault(pid, []).append(next(c for c in self.catalog if c.id == i))


def world():
    a = Fake(
        "ytm",
        {"Mix": [T("ytm", "a1", "One", ["X"]), T("ytm", "a3", "Three", ["Z"])], "OnlyA": [T("ytm", "a2", "Two", ["Y"])]},
        [T("ytm", "a3", "Three", ["Z"])],
    )
    b = Fake(
        "tidal", {"Mix": [T("tidal", "b3", "Three (Remastered)", ["Z"])]}, [T("tidal", "b1", "One", ["X"]), T("tidal", "b2", "Two", ["Y"])]
    )
    return a, b


def run(a, b, db, **kw):
    return sync_once(a, b, db, Options(**kw))


def test_bidirectional_create_and_fuzzy_dedupe(tmp_path):
    a, b = world()
    r = run(a, b, Database(tmp_path / "d.db"))
    assert ("Mix", ["b1"]) in b.added
    assert ("OnlyA", ["b2"]) in b.added  # missing playlist created
    assert a.added == []  # "Three (Remastered)" == "Three": not re-added
    assert not r.missing and not r.errors


# ---------- idempotency ----------
def test_second_run_is_noop_and_makes_no_requests(tmp_path):
    a, b = world()
    db = Database(tmp_path / "d.db")
    run(a, b, db)
    n_added, searches = len(b.added), (a.searches, b.searches)
    r = run(a, b, db)
    assert r.added == {} and len(b.added) == n_added
    assert (a.searches, b.searches) == searches


def test_idempotent_even_if_remote_listing_lags(tmp_path):
    """Remote hasn't reflected our writes yet (eventual consistency): journal prevents double-add."""
    a, b = world()
    db = Database(tmp_path / "d.db")
    run(a, b, db)
    b.pls["Mix"] = [T("tidal", "b3", "Three", ["Z"])]  # pretend the new tracks aren't visible
    b.added.clear()
    run(a, b, db)
    assert b.added == []


def test_user_removed_track_not_resurrected_unless_force(tmp_path):
    a, b = world()
    db = Database(tmp_path / "d.db")
    run(a, b, db)
    b.pls["Mix"] = [t for t in b.pls["Mix"] if t.id != "b1"]
    b.added.clear()
    r = run(a, b, db)
    assert b.added == [] and r.skipped_removed == 1
    run(a, b, db, force=True)
    assert ("Mix", ["b1"]) in b.added


# ---------- missing content / regional ----------
def test_missing_cached_then_retried_after_window(tmp_path):
    a = Fake("ytm", {"P": [T("ytm", "a1", "Ghost Song", ["Nobody"])]}, [])
    b = Fake("tidal", {"P": []}, [T("tidal", "b9", "Other", ["Else"])])
    db = Database(tmp_path / "d.db")
    r = run(a, b, db)
    assert len(r.missing) == 1 and b.searches == 2  # both query variants tried once
    run(a, b, db)
    assert b.searches == 2  # cached miss: no new requests
    run(a, b, db, retry_missing_days=0)
    assert b.searches == 4  # window elapsed -> asked again
    assert db.get_match("tidal", T("ytm", "a1", "Ghost Song", ["Nobody"]).key).status == "missing"


def test_region_blocked_counts_as_missing(tmp_path):
    a = Fake("ytm", {"P": [T("ytm", "a1", "Creep", ["Radiohead"])]}, [])
    b = Fake("tidal", {"P": []}, [T("tidal", "b1", "Creep", ["Radiohead"], ok=False)])
    r = run(a, b, Database(tmp_path / "d.db"))
    assert len(r.missing) == 1 and b.added == []


def test_approx_only_when_opted_in(tmp_path):
    def mk():
        a = Fake("ytm", {"P": [T("ytm", "a1", "Creep", ["Radiohead"], 238)]}, [])
        b = Fake("tidal", {"P": []}, [T("tidal", "b1", "Creep (Live)", ["Radiohead"], 238)])
        return a, b

    a, b = mk()
    assert run(a, b, Database(tmp_path / "1.db")).added == {}
    a, b = mk()
    r = run(a, b, Database(tmp_path / "2.db"), allow_approx=True)
    assert r.added and len(r.approx) == 1


# ---------- quota / blocking mid-run: stop cleanly, resume later ----------
def test_quota_stop_saves_progress_and_resumes(tmp_path):
    tracks = [T("ytm", f"a{i}", f"Song {i}", ["Art"]) for i in range(6)]
    cat = [T("tidal", f"b{i}", f"Song {i}", ["Art"]) for i in range(6)]
    a = Fake("ytm", {"P": tracks}, [])
    b = Fake("tidal", {"P": []}, cat)
    db = Database(tmp_path / "d.db")

    real = b.search
    budget = {"n": 3}

    def limited(q):
        if budget["n"] <= 0:
            raise QuotaExceeded("daily budget used")
        budget["n"] -= 1
        # return only the song being searched for, like a real search would
        return [c for c in real(q) if c.title.lower() in q.lower()]

    b.search = limited
    r = run(a, b, db)
    assert r.stopped and "budget" in r.stopped and r.stop_kind == "quota"
    assert db.conn.execute("SELECT COUNT(*) FROM matches WHERE status='matched'").fetchone()[0] == 3  # progress persisted

    budget["n"] = 100
    r = run(a, b, db)
    assert not r.stopped
    assert sorted(i for _, ids in b.added for i in ids) == sorted(c.id for c in cat)  # nothing lost, nothing duplicated


def test_blocked_mid_add_keeps_journal_of_completed_batches(tmp_path, monkeypatch):
    import playlist_bridge.sync as s

    monkeypatch.setattr(s, "BATCH", 2)
    tracks = [T("ytm", f"a{i}", f"Song {i}", ["Art"]) for i in range(5)]
    cat = [T("tidal", f"b{i}", f"Song {i}", ["Art"]) for i in range(5)]
    a, b = Fake("ytm", {"P": tracks}, []), Fake("tidal", {"P": []}, cat)
    b.search = lambda q: [c for c in cat if c.title.lower() in q.lower()]
    orig = b.add
    calls = {"n": 0}

    def add(pid, ids):
        calls["n"] += 1
        if calls["n"] == 2:
            raise Blocked("blocked")
        orig(pid, ids)

    b.add = add
    db = Database(tmp_path / "d.db")
    r = run(a, b, db)
    assert r.stopped and r.stop_kind == "blocked" and len(b.added) == 1  # first batch done
    b.add = orig
    b.pls["P"] = b.pls["P"][:2]
    run(a, b, db)
    assert sorted(i for _, ids in b.added for i in ids) == sorted(c.id for c in cat)


def test_add_failure_reported_not_fatal(tmp_path):
    a, b = world()
    b.fail_add = RuntimeError("not your playlist")
    r = run(a, b, Database(tmp_path / "d.db"))
    assert r.errors and not r.stopped


# ---------- the library: liked songs ----------
def test_liked_songs_sync_both_ways_and_are_idempotent(tmp_path):
    a = Fake("ytm", {}, [T("ytm", "a9", "Beta", ["Y"])])
    b = Fake("tidal", {}, [T("tidal", "b8", "Alpha", ["X"])])
    a.pls[LIKED] = [T("ytm", "a1", "Alpha", ["X"])]
    b.pls[LIKED] = [T("tidal", "b2", "Beta", ["Y"])]
    db = Database(tmp_path / "d.db")
    r = run(a, b, db)
    assert (LIKED, ["b8"]) in b.added and (LIKED, ["a9"]) in a.added
    assert "Liked songs -> tidal" in r.added and "Liked songs -> ytm" in r.added
    again = run(a, b, db)
    assert again.added == {}


def test_a_broken_playlist_does_not_end_the_pass(tmp_path):
    a, b = world()
    real = a.tracks
    a.tracks = lambda pid: (_ for _ in ()).throw(RuntimeError("boom")) if pid == "Mix" else real(pid)
    r = run(a, b, Database(tmp_path / "d.db"))
    assert any("boom" in e for e in r.errors)
    assert ("OnlyA", ["b2"]) in b.added  # the next playlist was still synced


def test_missing_is_reported_once_not_every_pass(tmp_path):
    a = Fake("ytm", {"P": [T("ytm", "a1", "Ghost", ["Nobody"])]}, [])
    b = Fake("tidal", {"P": []}, [])
    db = Database(tmp_path / "d.db")
    assert len(run(a, b, db).missing) == 1
    assert run(a, b, db).missing == []  # cached: a daemon must not repeat the same line forever
