# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""`uninstall`: remove everything - the background service, the logins and data, and the program itself."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from . import autostart
from .files import OWN_FILES, run_lock, stop_running

PACKAGE = "playlist-bridge"


def package_command(prefix: str = sys.prefix, python: str = sys.executable, which=shutil.which) -> list[str]:
    """How this copy of the program was installed decides how it is removed."""
    parts = Path(prefix).parts
    if "pipx" in parts and "venvs" in parts and which("pipx"):
        return ["pipx", "uninstall", PACKAGE]
    return [python, "-m", "pip", "uninstall", "-y", PACKAGE]


def uninstall(
    home: Path,
    *,
    yes: bool = False,
    ask=input,
    interactive: bool | None = None,
    run=subprocess.run,
    say=print,
    unit_directory: Path | None = None,
    command: list[str] | None = None,
) -> int:
    if not yes:
        if not (sys.stdin.isatty() if interactive is None else interactive):
            say("Not removing anything without a confirmation: run it in a terminal, or add --yes.")
            return 1
        say(f"This stops the background sync, deletes your logins and the sync history in {home}, and uninstalls Playlist-bridge.")
        say("Your music on YouTube Music and Tidal is not touched.")
        if ask("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            say("Nothing was removed.")
            return 1

    autostart.remove(directory=unit_directory, run=run)

    home.mkdir(parents=True, exist_ok=True)
    stop_running(home, say=say)  # a sync left running in a terminal
    with run_lock(home):  # still refuses if something else is running
        for name in OWN_FILES:  # only our own files: the folder could be anything the user pointed us at
            (home / name).unlink(missing_ok=True)
    try:
        home.rmdir()  # only if nothing else is in it
    except OSError:
        pass
    say("Logins and data deleted.")

    cmd = command or package_command()
    try:
        run(cmd, check=True)
    except (OSError, subprocess.CalledProcessError):
        say(f"Could not remove the program itself. Run this: {' '.join(cmd)}")
        return 1
    say("Playlist-bridge is gone.")
    return 0
