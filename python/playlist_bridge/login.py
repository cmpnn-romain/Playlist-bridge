# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""`login`: connect YouTube Music, then Tidal, once. Short numbered steps, a hidden paste that ends by itself, and a check at the end."""

from __future__ import annotations

import os
import re
import select
import shlex
import sys
from pathlib import Path

from . import ui

YTM_STEPS = """\
Step 1 of 2: YouTube Music

Follow these steps.

  1. Open https://music.youtube.com in a browser and log in to your account.
  2. Right-click an empty part of the page and choose "Inspect". This opens the developer tools (F12 does the same).
  3. At the top of the developer tools, click the "Network" tab.
  4. In its "Filter" box, type  browse
  5. On the page, click "Library" (on the left). A line named "browse" appears in the list of requests.
  6. Right-click that "browse" line, then choose:
       Chrome or Edge:  Copy > Copy as cURL (bash)
       Firefox:         Copy Value > Copy as cURL
     (Copy request headers works too. "Copy URL" does not: it is only the address.)
  7. Click in this terminal and paste (Ctrl+Shift+V, or right-click). Nothing will show up, on purpose: it holds your cookies.
"""

CTRL_D = b"\x04"


_ANSI_C = re.compile(r"\$'((?:[^'\\]|\\.)*)'")


def _ansi_c(m: re.Match) -> str:
    return shlex.quote(re.sub(r"\\(['\"\\])", r"\1", m.group(1)))  # the escapes Chrome writes: \' \" \\


def curl_to_headers(text: str) -> str:
    """Turn a "Copy as cURL" command into the "Name: value" lines the library reads (cookies are -b). Else: unchanged."""
    t = text.strip()
    if not t.lower().startswith("curl"):
        return text
    t = re.sub(r"\\\r?\n", " ", t)  # line continuations
    t = _ANSI_C.sub(_ansi_c, t)  # bash's $'...' quoting, which Chrome uses for values holding a quote
    try:
        parts = shlex.split(t)
    except ValueError:  # an open quote: the paste is not finished
        return text
    lines, i = [], 0
    while i < len(parts):
        flag = parts[i]
        if flag in ("-H", "--header") and i + 1 < len(parts):
            lines.append(parts[i + 1])
            i += 2
        elif flag in ("-b", "--cookie") and i + 1 < len(parts):
            lines.append("cookie: " + parts[i + 1])
            i += 2
        else:
            i += 1
    return "\n".join(lines) + "\n"


def headers_complete(text: str) -> bool:
    """Both headers YouTube Music needs are there (as a cURL command, headers on lines, or Chrome's key-then-value lines)."""
    low = curl_to_headers(text).lower()
    return "cookie:" in low and "x-goog-authuser:" in low


def only_an_address(text: str) -> bool:
    t = text.strip()
    return t.lower().startswith("http") and "\n" not in t and " " not in t


def what_is_wrong(text: str) -> str:
    if not text.strip():
        return "nothing was pasted"
    if only_an_address(text):
        return 'that is only the request\'s address (its URL). Use "Copy as cURL" or "Copy request headers" instead'
    return "the paste has no cookie and x-goog-authuser: copy the whole request (step 4)"


def read_pasted(fd: int, *, idle: float = 1.0, hint_after: float = 5.0, say=ui.say) -> str:
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
                say(f"  That is not it: {what_is_wrong(buf.decode('utf-8', 'replace'))}.")
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


def login_ytm(path: Path, *, read=None, check=None, say=ui.say, attempts: int = 3) -> None:
    import ytmusicapi

    read = read or (lambda: read_pasted(sys.stdin.fileno(), say=say))
    check = check or _check_ytm
    say(YTM_STEPS)
    for attempt in range(1, attempts + 1):
        say("Waiting for your paste...")
        text = curl_to_headers(read())
        try:
            if not headers_complete(text):
                raise ValueError(what_is_wrong(text))
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
    raise SystemExit("YouTube Music login failed. Run `playlist-bridge --login` to try again.")


def login_tidal(path: Path, *, say=ui.say, session_factory=None, show_qr=ui.qr, waiting=ui.status) -> None:
    import tidalapi

    from .services import save_tidal_session

    session = (session_factory or tidalapi.Session)()
    link, future = session.login_oauth()
    url = link.verification_uri_complete
    if not url.startswith("http"):
        url = "https://" + url
    say(f"Step 2 of 2: Tidal\n\nFollow this link:\n\n    {url}\n\nThe link works for {max(1, int(link.expires_in) // 60)} minutes.")
    show_qr(url)
    try:
        with waiting("Waiting for you to approve it..."):
            future.result()
    except Exception as e:
        raise SystemExit(f"Tidal login failed: {_oneline(e)}") from None
    if not session.check_login():
        raise SystemExit("Tidal login failed.")
    save_tidal_session(session, path)
    say("\n✓ Tidal is connected.\n")


def login_all(ytm_path: Path, tidal_path: Path, say=ui.say, clear=ui.clear) -> None:
    say("Connecting your two accounts. You only do this once.\n")
    login_ytm(ytm_path, say=say)
    login_tidal(tidal_path, say=say)
    clear()  # the steps and the pastes are done with: leave only the result
    say("✓ YouTube Music is connected.")
    say("✓ Tidal is connected.")
    say("\nAll set. Start syncing with:  playlist-bridge --sync")
