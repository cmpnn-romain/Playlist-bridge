# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""Track model, normalization and version-aware fuzzy matching.

Platforms index different editions of the same song ("Song - 2011 Remaster",
"Song (Radio Edit)", "Song [feat. X]", "Artist - Song"...). We therefore:

* normalize aggressively (accents, case, punctuation, feat., remaster/edition noise);
* treat *soft* tags (remaster, deluxe, mono, explicit...) as irrelevant;
* treat *hard* tags (live, remix, acoustic, instrumental, cover...) as a different
  recording: a mismatch is penalised and only accepted in opt-in "approx" mode;
* use duration and album as tie-breakers; skip candidates not playable in the region.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

_FEAT = re.compile(r"\s*[\(\[]?\s*(?<!\w)(feat\.?|ft\.?|featuring)\s[^)\]]*[\)\]]?", re.I)
_SOFT = (
    r"remaster(?:ed)?|deluxe|version|edit|mono|stereo|explicit|clean|official|video|audio|"
    r"lyrics?|single|album|bonus|original mix|anniversary|expanded|re-?recorded"
)
_SOFT_PAREN = re.compile(rf"\s*[\(\[][^)\]]*(?:{_SOFT})[^)\]]*[\)\]]", re.I)
_SOFT_TAIL = re.compile(rf"\s+-\s+[^-]*(?:{_SOFT})[^-]*$", re.I)
_FROM = re.compile(r"\s*[\(\[-]\s*(?:from|taken from)\s+.*$", re.I)

_HARD = re.compile(
    r"(?<!\w)(live|remix|rmx|acoustic|instrumental|karaoke|cover|demo|slowed|sped up|"
    r"reverb|nightcore|8d|a cappella|acapella|unplugged|mashup|bootleg)(?!\w)"
)
_TAG_ALIAS = {"rmx": "remix", "acapella": "a cappella"}
_ARTIST_SPLIT = re.compile(r"\s*[,/;&]\s*|\s+(?:x|and|feat\.?|ft\.?)\s+", re.I)


def _fold(s: str) -> str:
    """NFKC, lowercase, strip accents from Latin letters only (keeps kana/hangul intact)."""
    out = []
    for c in unicodedata.normalize("NFKC", s or ""):
        if ord(c) < 0x250:
            out.extend(ch for ch in unicodedata.normalize("NFKD", c) if not unicodedata.combining(ch))
        else:
            out.append(c)
    return "".join(out).lower()


def norm(s: str) -> str:
    raw = _fold(s)
    t = raw.replace("&", " and ")
    t = _FEAT.sub("", t)
    t = _SOFT_PAREN.sub("", t)
    t = _SOFT_TAIL.sub("", t)
    t = _FROM.sub("", t)
    t = re.sub(r"['’`´]", "", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^the ", "", t)
    return t or re.sub(r"\s+", " ", raw).strip()


def version_tags(title: str) -> frozenset[str]:
    return frozenset(_TAG_ALIAS.get(m, m) for m in _HARD.findall(_fold(title)))


def artist_set(names: list[str]) -> frozenset[str]:
    out = set()
    for n in names:
        for part in _ARTIST_SPLIT.split(_fold(n)):
            p = norm(part)
            if p:
                out.add(p)
        if not out:
            out.add(norm(n))
    return frozenset(out)


@dataclass
class Track:
    service: str  # "ytm" | "tidal"
    id: str
    title: str
    artists: list[str]
    duration: int | None = None  # seconds
    album: str | None = None
    available: bool = True  # playable in the user's region
    extra: dict = field(default_factory=dict, repr=False)

    @property
    def clean_title(self) -> str:
        """Normalized title; drops a leading 'Artist - ' (common on YTM uploads)."""
        t = self.title
        for a in self.artists:
            pre = a.lower() + " - "
            if t.lower().startswith(pre):
                t = t[len(pre) :]
                break
        return norm(t)

    @property
    def tags(self) -> frozenset[str]:
        return version_tags(self.title)

    @property
    def tkey(self) -> str:
        return self.clean_title + "#" + ",".join(sorted(self.tags))

    @property
    def key(self) -> str:
        """Service-independent fingerprint (primary artist + title + version tags)."""
        first = norm(self.artists[0]) if self.artists else ""
        return f"{first}|{self.tkey}"

    @property
    def label(self) -> str:
        return f"{', '.join(self.artists)} - {self.title}"


def _title_sim(a: str, b: str) -> float:
    ratio = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    jac = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    return max(ratio, jac)


def _artist_sim(a: frozenset[str], b: frozenset[str]) -> float:
    if a & b:
        return 1.0
    return max((SequenceMatcher(None, x, y).ratio() for x in a for y in b), default=0.0)


def score(src: Track, cand: Track) -> tuple[float, bool]:
    """(similarity 0..1 ignoring version tags, version_tags_differ)."""
    t = _title_sim(src.clean_title, cand.clean_title)
    a = _artist_sim(artist_set(src.artists), artist_set(cand.artists))
    s = 0.6 * t + 0.4 * a
    if src.album and cand.album and norm(src.album) == norm(cand.album):
        s += 0.04
    if src.duration and cand.duration:
        d = abs(src.duration - cand.duration)
        s += 0.05 if d <= 3 else (-0.15 if d > 10 else 0.0)
        if d > 45:
            s -= 0.15
    return s, src.tags != cand.tags


@dataclass
class Match:
    track: Track
    score: float
    approx: bool  # same song, different recording (live/remix/...)


VERSION_PENALTY = 0.3


def best_match(src: Track, candidates: list[Track], threshold: float = 0.8, allow_approx: bool = False) -> Match | None:
    playable = [c for c in candidates if c.available]  # regional licensing
    scored = []
    for c in playable:
        s, mismatch = score(src, c)
        scored.append((s - (VERSION_PENALTY if mismatch else 0.0), s, mismatch, c))
    scored.sort(key=lambda x: -x[0])
    if scored and scored[0][0] >= threshold:
        return Match(scored[0][3], scored[0][0], False)
    if allow_approx:
        for _, s, mismatch, c in sorted(scored, key=lambda x: -x[1]):
            if mismatch and s >= threshold:
                return Match(c, s, True)
    return None


class Index:
    """Fast 'is this song already in that playlist?' check, tolerant to formatting."""

    def __init__(self, tracks: list[Track]):
        self._by_title: dict[str, list[frozenset[str]]] = {}
        for t in tracks:
            self._by_title.setdefault(t.tkey, []).append(artist_set(t.artists))

    def has(self, t: Track) -> bool:
        mine = artist_set(t.artists)
        return any(mine & other or not mine for other in self._by_title.get(t.tkey, []))
