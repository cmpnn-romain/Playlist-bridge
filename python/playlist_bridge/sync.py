# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""One bidirectional, additive, idempotent and resumable pass over the library: the liked songs, then every playlist.

Idempotency comes from three layers:
  1. remote truth - a track already present in the destination (fuzzy-compared) is skipped;
  2. `synced` journal - a track we already added once is not re-added (so a track you later
     delete on one side is not resurrected);
  3. `matches` cache - each song is searched at most once; misses are re-tried only after
     `retry_missing_days` (catalogues and regional licences change).
Journal rows are written right after each successful batch, so a crash, quota stop or
rate-limit block loses nothing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .db import Database
from .guard import AuthExpired, Blocked, QuotaExceeded, Stop
from .matching import Index, Track, best_match
from .services import LIKED, Service

BATCH = 50
STOP_KINDS = {QuotaExceeded: "quota", Blocked: "blocked", AuthExpired: "auth"}


@dataclass
class Options:
    threshold: float = 0.8
    allow_approx: bool = False
    retry_missing_days: float = 14
    force: bool = False


@dataclass
class Report:
    added: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)  # songs searched for this pass and not found
    approx: list[str] = field(default_factory=list)
    skipped_removed: int = 0
    errors: list[str] = field(default_factory=list)
    stopped: str | None = None
    stop_kind: str | None = None  # quota | blocked | auth


def queries(t: Track) -> list[str]:
    artist = t.artists[0] if t.artists else ""
    title = " ".join([t.clean_title, *sorted(t.tags)])
    qs = [f"{artist} {title}".strip()]
    if artist:
        qs.append(title)  # second chance: artist credit differs between catalogues
    return qs


def resolve(src: Track, dst: Service, db: Database, opt: Options, report: Report, title: str):
    """-> (dst_track_id, approx) or None. Searches the destination at most once per song."""
    row = db.get_match(dst.name, src.key)
    if row:
        if row.status == "matched":
            return row.dst_id, False
        if row.status == "approx" and opt.allow_approx:
            return row.dst_id, True
        if row.status == "approx":
            return None
        if time.time() - row.checked_at < opt.retry_missing_days * 86400:
            return None  # known missing; don't burn quota re-asking
    cands: list[Track] = []
    m = None
    try:
        for q in queries(src):
            cands += dst.search(q)
            m = best_match(src, cands, opt.threshold, opt.allow_approx)
            if m:
                break
    except Stop:
        raise
    except Exception as e:  # parsing glitch etc. - don't cache as missing
        report.errors.append(f"search {dst.name} '{src.label}': {e}")
        return None
    if m:
        db.put_match(dst.name, src.key, src.label, m.track.id, m.score, "approx" if m.approx else "matched")
        return m.track.id, m.approx
    db.put_match(dst.name, src.key, src.label, None, 0.0, "missing")
    report.missing.append(f"[{title}] not on {dst.name}: {src.label}")
    return None


def _push(src_tracks, existing, dst, dst_pid, title, pkey, db, opt, report) -> str | None:
    idx = Index(existing)
    have_ids = {t.id for t in existing}
    seen, todo = set(), []
    for t in src_tracks:
        if t.key in seen or idx.has(t):
            continue
        seen.add(t.key)
        if not opt.force and dst_pid and db.was_synced(pkey, dst.name, t.key):
            report.skipped_removed += 1  # we added it before; someone removed it. Respect that.
            continue
        r = resolve(t, dst, db, opt, report, title)
        if r is None:
            continue
        did, approx = r
        if did in have_ids:
            continue
        have_ids.add(did)
        if approx:
            report.approx.append(f"[{title}] {t.label} -> different version on {dst.name}")
        todo.append((t, did))
    if not todo:
        return dst_pid
    label = f"{title} -> {dst.name}"
    try:
        if dst_pid is None:
            dst_pid = dst.create_playlist(title)
            db.set_playlist_id(pkey, dst.name, dst_pid)
        for i in range(0, len(todo), BATCH):
            chunk = todo[i : i + BATCH]
            dst.add(dst_pid, [d for _, d in chunk])
            db.mark_synced(pkey, dst.name, [(t.key, d) for t, d in chunk])
            report.added[label] = report.added.get(label, 0) + len(chunk)
    except Stop:
        raise
    except Exception as e:  # e.g. a YTM playlist you don't own
        report.errors.append(f"[{title}] {dst.name}: {e}")
    return dst_pid


def sync_once(a: Service, b: Service, db: Database, opt: Options | None = None, log=lambda *_: None) -> Report:
    """One pass; `a` is YouTube Music, `b` is Tidal. Never raises for a stop: see Report.stopped / stop_kind."""
    opt = opt or Options()
    report = Report()
    try:
        pa, pb = a.playlists(), b.playlists()
        by_a = {k.casefold(): (k, v) for k, v in pa.items()}
        by_b = {k.casefold(): (k, v) for k, v in pb.items()}
        entries = [(LIKED, "Liked songs", LIKED, LIKED)]  # the library first, then the playlists
        for n in sorted(set(by_a) | set(by_b)):
            title = (by_a.get(n) or by_b.get(n))[0]
            entries.append((n, title, by_a.get(n, (None, None))[1], by_b.get(n, (None, None))[1]))
        for key, title, ida, idb in entries:
            log(f"• {title}")
            try:
                if key != LIKED:
                    db.upsert_playlist(key, title, ida, idb)
                ta = a.tracks(ida) if ida else []
                tb = b.tracks(idb) if idb else []
                # both directions use the *pre-sync* lists, so tracks never ping-pong
                idb = _push(ta, tb, b, idb, title, key, db, opt, report)
                ida = _push(tb, ta, a, ida, title, key, db, opt, report)
            except Stop:
                raise
            except Exception as e:  # one broken playlist must not end the pass
                report.errors.append(f"[{title}] {e}")
    except Stop as e:
        report.stopped = str(e)
        report.stop_kind = STOP_KINDS.get(type(e))
    return report
