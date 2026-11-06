# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""The version comes from the repo-root VERSION file and from nowhere else (docs/VERSIONING.md)."""

import re
from pathlib import Path

from setuptools import setup

version = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").splitlines()[0].strip()
if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
    raise SystemExit(f"VERSION must be strict MAJOR.MINOR.PATCH, got {version!r}")

setup(version=version)
