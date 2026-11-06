# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""Playlist-bridge: syncs playlists between YouTube Music and Tidal, both ways, additive only."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("playlist-bridge")
except PackageNotFoundError:  # running from a checkout that was never installed
    __version__ = "0.0.0"
