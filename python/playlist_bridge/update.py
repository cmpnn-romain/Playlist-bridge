# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""`update`: install the latest version from GitHub over this one, and move the background service onto it."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__, autostart
from .files import COMMIT_FILE

REPO = "https://github.com/cmpnn-romain/Playlist-bridge.git"  # PLAYLIST_BRIDGE_REPO overrides it (e.g. an SSH address)
BRANCH = "main"


def running_from_a_checkout(module_file: str | None = None) -> bool:
    """True for `pipx install --editable`, `pip install -e` and plain source runs: those are updated with `git pull`."""
    f = module_file or __file__
    return "site-packages" not in f and "dist-packages" not in f


def _version_in(pyproject: Path) -> str:
    m = re.search(r'(?m)^version\s*=\s*"([^"]*)"', pyproject.read_text(encoding="utf-8"))
    return m.group(1) if m else "?"


def _reason(e: subprocess.CalledProcessError) -> str:
    """The line of git's or pip's complaint that says what is wrong (the last line is often only advice)."""
    lines = [ln.strip() for ln in (e.stderr or "").splitlines() if ln.strip()]
    for ln in lines:
        m = re.match(r"(?i)(fatal|error):\s*(.+)", ln)
        if m:
            return m.group(2)
    return lines[-1] if lines else f"exit code {e.returncode}"


def update(
    home: Path,
    *,
    repo: str | None = None,
    python: str = sys.executable,
    run=subprocess.run,
    say=print,
    unit_directory: Path | None = None,
    from_checkout: bool | None = None,
    which=None,
) -> int:
    import shutil

    if running_from_a_checkout() if from_checkout is None else from_checkout:
        say("This copy runs straight from a checkout of the code, so it is updated with `git pull` there.")
        return 1
    if not (which or shutil.which)("git"):
        say("git is needed to download the update, and it was not found.")
        return 1
    repo = repo or os.environ.get("PLAYLIST_BRIDGE_REPO", REPO)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # never sit waiting for a password
    done = home / COMMIT_FILE

    with tempfile.TemporaryDirectory(prefix="playlist-bridge-update-") as tmp:
        src = Path(tmp) / "src"
        say("Looking for a newer version...")
        try:
            run(
                ["git", "clone", "--quiet", "--depth", "1", "--branch", BRANCH, repo, str(src)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            commit = run(["git", "-C", str(src), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        except (subprocess.CalledProcessError, OSError) as e:
            why = _reason(e) if isinstance(e, subprocess.CalledProcessError) else str(e)
            say(f"Could not download the latest version: {why}")
            say("If the repository is private, set PLAYLIST_BRIDGE_REPO to its SSH address (git@github.com:...).")
            return 1

        if done.exists() and done.read_text().strip() == commit:
            say(f"Already up to date ({__version__}, {commit[:7]}).")
            return 0

        new = _version_in(src / "python" / "pyproject.toml")
        say(f"Installing {new} ({commit[:7]}); you have {__version__}...")
        pkg = str(src / "python")
        try:
            # the program itself first (no dependencies: it is the same version number again, so pip must be told to redo it),
            # then whatever the new version needs that is missing
            run(
                [python, "-m", "pip", "install", "--quiet", "--no-deps", "--force-reinstall", pkg],
                check=True,
                capture_output=True,
                text=True,
            )
            run([python, "-m", "pip", "install", "--quiet", pkg], check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, OSError) as e:
            why = _reason(e) if isinstance(e, subprocess.CalledProcessError) else str(e)
            say(f"The update failed: {why}")
            say("Your current version was left as it is.")
            return 1

    done.write_text(commit + "\n")
    say(f"Updated to {new} ({commit[:7]}).")
    try:
        if autostart.refresh(python=python, directory=unit_directory, run=run):
            say("The background sync was restarted on the new version.")
        else:
            say("If `playlist-bridge --sync` is running in a terminal, stop it and start it again to use the new version.")
    except (subprocess.CalledProcessError, SystemExit) as e:
        say(f"Updated, but the background sync could not be restarted: {e}. Run `playlist-bridge --install` to fix it.")
        return 1
    return 0
