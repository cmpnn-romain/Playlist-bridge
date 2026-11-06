# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""`install` / `uninstall`: run `sync` in the background as a systemd user service, now and at every login."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .guard import EXIT_LOGIN

UNIT = "playlist-bridge.service"


def unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def unit_text(python: str, home: str | None = None) -> str:
    env = f'Environment="PLAYLIST_BRIDGE_HOME={home}"\n' if home else ""
    return f"""[Unit]
Description=Playlist-bridge: keeps YouTube Music and Tidal in step
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=3600
StartLimitBurst=3

[Service]
ExecStart="{python}" -m playlist_bridge sync
{env}Restart=on-failure
RestartSec=900
RestartPreventExitStatus={EXIT_LOGIN}

[Install]
WantedBy=default.target
"""


def _systemctl(run, *args: str):
    try:
        run(["systemctl", "--user", *args], check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit(
            "systemctl not found: `install` needs Linux with systemd (on WSL, enable it in /etc/wsl.conf). "
            "Run `playlist-bridge sync` in a terminal instead."
        ) from None
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"systemctl --user {' '.join(args)} failed: {(e.stderr or '').strip()}") from None


def install(*, python: str = sys.executable, home: str | None = None, directory: Path | None = None, run=subprocess.run, say=print):
    d = directory or unit_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / UNIT).write_text(unit_text(python, home), encoding="utf-8")
    _systemctl(run, "daemon-reload")
    _systemctl(run, "enable", "--now", UNIT)
    say("Playlist-bridge now syncs in the background, and starts again at every login.")
    say("To keep it running while you are logged out too: loginctl enable-linger $USER")


def stop(*, directory: Path | None = None, run=subprocess.run, say=print):
    """Stop the background sync now and do not start it at the next login. `install` turns it on again."""
    if (directory or unit_dir()).joinpath(UNIT).exists():
        _systemctl(run, "disable", "--now", UNIT)
        say("Playlist-bridge stopped, and will not start at login. Run `playlist-bridge install` to turn it on again.")
    else:
        say("Playlist-bridge is not set up to run in the background.")


def remove(*, directory: Path | None = None, run=subprocess.run):
    """Stop the background sync and delete its service file. Quiet, and harmless when there is nothing to remove."""
    path = (directory or unit_dir()) / UNIT
    if path.exists():
        _systemctl(run, "disable", "--now", UNIT)
        path.unlink()
        _systemctl(run, "daemon-reload")
