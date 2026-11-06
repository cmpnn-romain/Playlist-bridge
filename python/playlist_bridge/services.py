# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""Thin adapters over ytmusicapi and tidalapi. Every network call goes through a Guard."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Protocol

try:
    from ytmusicapi.models.content.enums import LikeStatus
except ImportError:  # older ytmusicapi: the rating is the plain string

    class LikeStatus:
        LIKE = "LIKE"


from .guard import EXIT_LOGIN, Guard
from .matching import Track

# Pseudo-playlist id for the user's liked songs (YouTube Music "Liked Music", Tidal favourites): synced like any playlist.
LIKED = "library:liked"
_YTM_SYSTEM_PLAYLISTS = {"LM", "SE"}  # "Your Likes" and "Episodes for later" are not playlists to copy


def need_login(message: str):
    """Exit with code 3: only the user can fix this (`playlist-bridge login`), so a supervisor must not restart us."""
    print(message, file=sys.stderr)
    raise SystemExit(EXIT_LOGIN)


class Service(Protocol):
    name: str

    def playlists(self) -> dict[str, str]: ...  # title -> playlist id
    def tracks(self, playlist_id: str) -> list[Track]: ...
    def search(self, query: str) -> list[Track]: ...
    def create_playlist(self, title: str) -> str: ...
    def add(self, playlist_id: str, track_ids: list[str]) -> None: ...


class YTMusic:
    name = "ytm"

    def __init__(self, auth_file: Path, guard: Guard):
        from ytmusicapi import YTMusic as _YTM

        if not auth_file.exists():
            need_login(f"{auth_file} not found. Run `playlist-bridge login` first.")
        self.api, self.g = _YTM(str(auth_file)), guard

    @staticmethod
    def _conv(t: dict) -> Track:
        alb = t.get("album")
        return Track(
            "ytm",
            t["videoId"],
            t["title"],
            [a["name"] for a in t.get("artists") or []],
            t.get("duration_seconds"),
            alb.get("name") if isinstance(alb, dict) else None,
            t.get("isAvailable", True) is not False,
        )

    def playlists(self) -> dict[str, str]:
        res = self.g.call(self.api.get_library_playlists, limit=None, cost=3)
        return {p["title"]: p["playlistId"] for p in res if p.get("playlistId") not in _YTM_SYSTEM_PLAYLISTS}

    def tracks(self, playlist_id: str) -> list[Track]:
        if playlist_id == LIKED:
            data = self.g.call(self.api.get_liked_songs, limit=None, cost=5)
        else:
            data = self.g.call(self.api.get_playlist, playlist_id, limit=None, cost=5)
        return [self._conv(t) for t in data.get("tracks", []) if t.get("videoId")]

    def search(self, query: str) -> list[Track]:
        res = self.g.call(self.api.search, query, filter="songs", limit=8)
        return [self._conv(r) for r in res if r.get("videoId")]

    def create_playlist(self, title: str) -> str:
        res = self.g.call(self.api.create_playlist, title, "Synced by playlist-bridge")
        if not isinstance(res, str):
            raise RuntimeError(f"YTM refused to create playlist: {res}")
        return res

    def add(self, playlist_id: str, track_ids: list[str]) -> None:
        if playlist_id == LIKED:  # one request per song: there is no bulk like
            for video_id in track_ids:
                self.g.call(self.api.rate_song, video_id, LikeStatus.LIKE)
            return
        self.g.call(self.api.add_playlist_items, playlist_id, track_ids, duplicates=False)


class Tidal:
    name = "tidal"

    def __init__(self, auth_file: Path, guard: Guard):
        import tidalapi

        self.tidalapi, self.g = tidalapi, guard
        self.session = tidalapi.Session()
        if not auth_file.exists():
            need_login(f"{auth_file} not found. Run `playlist-bridge login` first.")
        d = json.loads(auth_file.read_text())
        if not self.session.load_oauth_session(d["token_type"], d["access_token"], d.get("refresh_token")):
            need_login("Tidal session expired. Run `playlist-bridge login`.")
        save_tidal_session(self.session, auth_file)  # persist refreshed token

    @staticmethod
    def _conv(t) -> Track:
        artists = [a.name for a in (t.artists or [])] or ([t.artist.name] if t.artist else [])
        title = getattr(t, "full_name", None) or t.name
        playable = bool(getattr(t, "allow_streaming", True)) and bool(getattr(t, "available", True))
        return Track(
            "tidal",
            str(t.id),
            title,
            artists,
            t.duration,
            t.album.name if getattr(t, "album", None) else None,
            playable,
        )

    def playlists(self) -> dict[str, str]:
        return {p.name: p.id for p in self.g.call(self.session.user.playlists, cost=3)}

    def _all(self, fetch_page) -> list[Track]:
        out, offset = [], 0
        while True:
            page = self.g.call(fetch_page, limit=100, offset=offset)
            out += [self._conv(t) for t in page]
            if len(page) < 100:
                return out
            offset += 100

    def tracks(self, playlist_id: str) -> list[Track]:
        if playlist_id == LIKED:
            return self._all(self.session.user.favorites.tracks)
        return self._all(self.g.call(self.session.playlist, playlist_id).tracks)

    def search(self, query: str) -> list[Track]:
        res = self.g.call(self.session.search, query, models=[self.tidalapi.media.Track], limit=8)
        return [self._conv(t) for t in res["tracks"]]

    def create_playlist(self, title: str) -> str:
        return self.g.call(self.session.user.create_playlist, title, "Synced by playlist-bridge").id

    def add(self, playlist_id: str, track_ids: list[str]) -> None:
        if playlist_id == LIKED:
            self.g.call(self.session.user.favorites.add_track, track_ids)
            return
        pl = self.g.call(self.session.playlist, playlist_id)
        self.g.call(pl.add, track_ids)


def save_tidal_session(session, path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "token_type": session.token_type,
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
            }
        )
    )
    path.chmod(0o600)


def login_tidal(path: Path) -> None:
    import tidalapi

    s = tidalapi.Session()
    s.login_oauth_simple()  # prints a link.tidal.com URL to open in the browser
    if not s.check_login():
        raise SystemExit("Tidal login failed.")
    save_tidal_session(s, path)
    print(f"Saved Tidal credentials to {path}")


def login_ytm(path: Path) -> None:
    import ytmusicapi

    print(
        "Open music.youtube.com (logged in), DevTools > Network, filter '/browse',\n"
        "right-click a POST request > Copy as cURL (or copy request headers), paste below."
    )
    ytmusicapi.setup(filepath=str(path))
    path.chmod(0o600)
    print(f"Saved YouTube Music credentials to {path}")
