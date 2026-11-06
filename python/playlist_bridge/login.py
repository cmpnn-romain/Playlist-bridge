# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""`login`: connect YouTube Music, then Tidal, once. Short numbered steps, a hidden paste that ends by itself, and a check at the end."""

from __future__ import annotations

import os
import select
import sys
from pathlib import Path

YTM_STEPS = """\
Step 1 of 2: YouTube Music

  1. In your browser, open https://music.youtube.com and make sure you are logged in.
  2. Press F12 to open the developer tools, then click the "Network" tab.
  3. Type  browse  in the filter box, then click "Library" on the page.
  4. Right-click the first "browse" request that appears, then:
       Chrome or Edge:  Copy > Copy request headers
       Firefox:         Copy Value > Copy Request Headers
  5. Come back here and paste it. Nothing will show up, on purpose: it holds your cookies.
"""

CTRL_D = b"\x04"


def headers_complete(text: str) -> bool:
    """Both headers YouTube Music needs are there (copied in one line or Chrome's key-then-value lines)."""
    low = text.lower()
    return "cookie:" in low and "x-goog-authuser:" in low


def read_pasted(fd: int, *, idle: float = 1.0, hint_after: float = 5.0, say=print) -> str:
    """Read what the user pastes, hidden. It ends by itself once the pasted headers are complete and nothing more arrives
    (no Ctrl-D needed); Ctrl-D still ends it early. In a terminal, echo and the 4096-character line limit are switched off."""
    is_tty = os.isatty(fd)
    saved = None
    if is_tty:
        import termios
        import tty

        saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)
    buf, hinted = b"", False
    try:
        while True:
            complete = headers_complete(buf.decode("utf-8", "replace"))
            wait = idle if complete else (hint_after if buf and not hinted else None)
            ready, _, _ = select.select([fd], [], [], wait)
            if not ready:
                if complete:
                    break
                say("  That is not everything yet: it must include the cookie and x-goog-authuser lines.")
                say("  Paste again, or press Ctrl-D to give up.")
                hinted = True
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            if CTRL_D in chunk:  # in a terminal without line mode, Ctrl-D arrives as a plain byte
                buf += chunk.split(CTRL_D)[0]
                break
            buf += chunk
    finally:
        if saved is not None:
            import termios

            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return buf.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")


def _oneline(e: BaseException) -> str:
    lines = str(e).strip().splitlines()
    return (lines[0] if lines else type(e).__name__)[:200]


def _check_ytm(path: Path) -> None:
    from ytmusicapi import YTMusic

    YTMusic(str(path)).get_library_playlists(limit=1)  # fails if the headers do not really log us in


def login_ytm(path: Path, *, read=None, check=None, say=print, attempts: int = 3) -> None:
    import ytmusicapi

    read = read or (lambda: read_pasted(sys.stdin.fileno(), say=say))
    check = check or _check_ytm
    say(YTM_STEPS)
    for attempt in range(1, attempts + 1):
        say("Waiting for your paste...")
        text = read()
        try:
            if not text.strip():
                raise ValueError("nothing was pasted")
            old = os.umask(0o077)  # the file holds cookies: readable by you only, from the first byte
            try:
                ytmusicapi.setup(filepath=str(path), headers_raw=text)
            finally:
                os.umask(old)
            check(path)
        except Exception as e:
            path.unlink(missing_ok=True)
            say(f"\n✗ That did not work: {_oneline(e)}")
            if attempt < attempts:
                say("  Copy the request again (step 4) and paste it here.\n")
            continue
        say("\n✓ YouTube Music is connected.\n")
        return
    raise SystemExit("YouTube Music login failed. Run `playlist-bridge login` to try again.")


def login_tidal(path: Path, *, say=print, session_factory=None) -> None:
    import tidalapi

    from .services import save_tidal_session

    session = (session_factory or tidalapi.Session)()
    link, future = session.login_oauth()
    url = link.verification_uri_complete
    if not url.startswith("http"):
        url = "https://" + url
    say("Step 2 of 2: Tidal\n")
    say("  Open this link in your browser and approve the login:\n")
    say(f"      {url}\n")
    say(f"Waiting for you to approve it (the link works for {max(1, int(link.expires_in) // 60)} minutes)...")
    try:
        future.result()
    except Exception as e:
        raise SystemExit(f"Tidal login failed: {_oneline(e)}") from None
    if not session.check_login():
        raise SystemExit("Tidal login failed.")
    save_tidal_session(session, path)
    say("\n✓ Tidal is connected.\n")


def login_all(ytm_path: Path, tidal_path: Path, say=print) -> None:
    say("Connecting your two accounts. You only do this once.\n")
    login_ytm(ytm_path, say=say)
    login_tidal(tidal_path, say=say)
    say("All set. Start syncing with:  playlist-bridge sync")
