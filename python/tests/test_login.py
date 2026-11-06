# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
import concurrent.futures
import os
import select
import stat
import threading
import time
from types import SimpleNamespace

import pytest

from playlist_bridge.login import curl_to_headers, headers_complete, login_all, login_tidal, login_ytm, read_pasted, what_is_wrong

FIREFOX = (
    "POST /youtubei/v1/browse HTTP/3\nHost: music.youtube.com\nUser-Agent: Mozilla/5.0\n"
    "cookie: SID=abc; __Secure-3PAPISID=xyz\nx-goog-authuser: 0\nOrigin: https://music.youtube.com\n"
)
CHROME = "cookie:\nSID=abc\nx-goog-authuser:\n0\n"


def test_headers_complete():
    assert headers_complete(FIREFOX) and headers_complete(CHROME)
    assert not headers_complete("cookie: SID=abc\n")
    assert not headers_complete("")


def paste(text, *, ctrl_d=False, close=False, **kw):
    """Feed `text` into read_pasted through a pipe; the writer is kept open (like a terminal) unless close=True."""
    r, w = os.pipe()
    os.write(w, text.encode() + (b"\x04" if ctrl_d else b""))
    if close:
        os.close(w)
    said = []
    t0 = time.time()
    failsafe = threading.Timer(8, lambda: os.write(w, b"\x04"))  # a broken reader must fail the test, not hang CI
    failsafe.start()
    try:
        out = read_pasted(r, say=said.append, idle=0.1, hint_after=0.2, **kw)
    finally:
        failsafe.cancel()
        os.close(r)
        if not close:
            os.close(w)
    return out, said, time.time() - t0


def test_a_complete_paste_ends_by_itself_without_ctrl_d():
    out, said, took = paste(FIREFOX)
    assert out == FIREFOX and said == [] and took < 2


def test_ctrl_d_and_end_of_file_still_end_it():
    assert paste("cookie: a\n", ctrl_d=True)[0] == "cookie: a\n"
    assert paste("cookie: a\n", close=True)[0] == "cookie: a\n"


def test_an_incomplete_paste_gets_a_hint_then_waits_for_ctrl_d():
    r, w = os.pipe()
    os.write(w, b"cookie: a\n")
    said = []
    threading.Timer(0.5, lambda: os.write(w, b"\x04")).start()
    out = read_pasted(r, say=said.append, idle=0.1, hint_after=0.2)
    os.close(r), os.close(w)
    assert out == "cookie: a\n"
    assert any("cookie and x-goog-authuser" in m for m in said) and sum("That is not it" in m for m in said) == 1  # said once


def paste_in_terminal(text: str, *, idle=0.3):
    """Paste `text` into a pseudo-terminal *after* the reader has started (like a person), and return (what was read, what was echoed)."""
    pty = pytest.importorskip("pty")
    master, slave = pty.openpty()
    data = text.encode()

    def typist():
        time.sleep(0.3)  # the reader has switched the terminal to hidden, unlimited-line mode by now
        for i in range(0, len(data), 1024):
            os.write(master, data[i : i + 1024])
            time.sleep(0.005)

    threading.Thread(target=typist).start()
    failsafe = threading.Timer(8, lambda: os.write(master, b"\x04"))  # a broken reader must fail the test, not hang it
    failsafe.start()
    try:
        out = read_pasted(slave, idle=idle, hint_after=30, say=lambda m: None)
    finally:
        failsafe.cancel()
    echoed = b""
    while select.select([master], [], [], 0.2)[0]:
        echoed += os.read(master, 65536)
    os.close(master), os.close(slave)
    return out, echoed


def test_what_is_pasted_in_a_terminal_is_never_echoed():
    out, echoed = paste_in_terminal(FIREFOX.replace("\n", "\r"))
    assert headers_complete(out) and "\r" not in out
    assert b"SID=abc" not in echoed  # the cookies did not appear on screen


def test_long_lines_over_4096_characters_survive_in_a_terminal():
    out, _ = paste_in_terminal("cookie: " + "A" * 9000 + "\rx-goog-authuser: 0\r")
    assert out.count("A") == 9000


# ---------- login_ytm ----------
def reader(*pastes):
    it = iter(pastes)
    return lambda: next(it)


def test_ytm_success_saves_a_private_file_and_checks_it(tmp_path):
    p, said, checked = tmp_path / "ytm.json", [], []
    login_ytm(p, read=reader(FIREFOX), check=checked.append, say=said.append)
    assert checked == [p] and stat.S_IMODE(p.stat().st_mode) == 0o600
    assert any("1." in m and "music.youtube.com" in m for m in said) and any("✓ YouTube Music" in m for m in said)


def test_ytm_bad_paste_is_reported_and_retried(tmp_path):
    p, said = tmp_path / "ytm.json", []
    login_ytm(p, read=reader("", "garbage\n", FIREFOX), check=lambda x: None, say=said.append)
    text = "\n".join(said)
    assert "nothing was pasted" in text and "no cookie and x-goog-authuser" in text and "✓ YouTube Music" in text
    assert p.exists()


def test_ytm_headers_that_do_not_log_in_are_rejected_and_not_kept(tmp_path):
    p, said = tmp_path / "ytm.json", []

    def check(_):
        raise RuntimeError("401 Unauthorized")

    with pytest.raises(SystemExit) as e:
        login_ytm(p, read=reader(FIREFOX, FIREFOX, FIREFOX), check=check, say=said.append)
    assert "playlist-bridge --login" in str(e.value) and not p.exists()
    assert sum("✗" in m for m in said) == 3 and any("401" in m for m in said)


# ---------- login_tidal ----------
def fake_session(ok=True, fail=None):
    fut = concurrent.futures.Future()
    fut.set_exception(fail) if fail else fut.set_result(None)
    return SimpleNamespace(
        login_oauth=lambda: (SimpleNamespace(verification_uri_complete="link.tidal.com/AB12C", expires_in=300), fut),
        check_login=lambda: ok,
        token_type="Bearer",
        access_token="a",
        refresh_token="r",
    )


def test_tidal_shows_a_clickable_link_and_saves_the_session(tmp_path):
    p, said = tmp_path / "t.json", []
    login_tidal(p, say=said.append, session_factory=lambda: fake_session())
    text = "\n".join(said)
    assert "https://link.tidal.com/AB12C" in text and "5 minutes" in text and "✓ Tidal" in text
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_tidal_failure_is_clear(tmp_path):
    with pytest.raises(SystemExit) as e:
        login_tidal(tmp_path / "t.json", say=lambda m: None, session_factory=lambda: fake_session(fail=TimeoutError("expired")))
    assert "expired" in str(e.value)
    with pytest.raises(SystemExit):
        login_tidal(tmp_path / "t.json", say=lambda m: None, session_factory=lambda: fake_session(ok=False))


def test_login_all_goes_ytm_then_tidal(tmp_path, monkeypatch):
    from playlist_bridge import login

    order = []
    monkeypatch.setattr(login, "login_ytm", lambda p, say: order.append("ytm"))
    monkeypatch.setattr(login, "login_tidal", lambda p, say: order.append("tidal"))
    said = []
    cleared = []
    login_all(tmp_path / "a", tmp_path / "b", say=said.append, clear=lambda: cleared.append(len(said)))
    assert order == ["ytm", "tidal"] and "playlist-bridge --sync" in said[-1]
    assert said[-3:-1] == ["✓ YouTube Music is connected.", "✓ Tidal is connected."]
    assert cleared == [1]  # after the two logins (only the intro was said), before the result is shown


# ---------- "Copy as cURL" and pasting the wrong thing ----------
CHROME_CURL = (
    "curl 'https://music.youtube.com/youtubei/v1/browse?prettyPrint=false' \\\n"
    "  -H 'accept: */*' \\\n"
    "  -H 'content-type: application/json' \\\n"
    "  -H $'x-goog-authuser: 0' \\\n"
    "  -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64)' \\\n"
    "  -b $'SID=abc; __Secure-3PAPISID=xyz; NOTE=it\\'s' \\\n"
    "  --data-raw '{\"context\":{}}'"
)
FIREFOX_CURL = (
    "curl 'https://music.youtube.com/youtubei/v1/browse' -X POST -H 'User-Agent: Mozilla/5.0' "
    "-H 'Cookie: SID=abc; __Secure-3PAPISID=xyz' -H 'X-Goog-AuthUser: 0' --data-raw '{}'"
)


def test_chrome_curl_becomes_header_lines():
    h = curl_to_headers(CHROME_CURL)
    assert "x-goog-authuser: 0" in h and "cookie: SID=abc; __Secure-3PAPISID=xyz; NOTE=it's" in h  # the quote survives
    assert "user-agent: Mozilla/5.0 (X11; Linux x86_64)" in h
    assert "{" not in h and "https://" not in h  # the body and the address are not headers
    assert headers_complete(CHROME_CURL)


def test_firefox_curl_with_a_cookie_header():
    assert headers_complete(FIREFOX_CURL)
    assert "Cookie: SID=abc" in curl_to_headers(FIREFOX_CURL)


def test_an_unfinished_curl_is_not_complete_yet():
    assert not headers_complete(CHROME_CURL[:120])  # open quote: still being pasted


def test_header_lines_are_returned_untouched():
    assert curl_to_headers(FIREFOX) == FIREFOX


def test_a_curl_paste_ends_by_itself_too():
    out, said, took = paste(CHROME_CURL)
    assert out == CHROME_CURL and said == [] and took < 2


def test_ytm_login_accepts_copy_as_curl(tmp_path):
    import json

    p = tmp_path / "ytm.json"
    login_ytm(p, read=reader(CHROME_CURL), check=lambda x: None, say=lambda m: None)
    saved = json.loads(p.read_text())
    assert saved["cookie"].startswith("SID=abc") and saved["x-goog-authuser"] == "0"


def test_pasting_only_the_url_is_explained(tmp_path):
    url = "https://music.youtube.com/youtubei/v1/browse?ctoken=4qmFsgKl&type=next&prettyPrint=false"
    assert "address" in what_is_wrong(url) and "cURL" in what_is_wrong(url)
    said = []
    login_ytm(tmp_path / "y.json", read=reader(url, CHROME_CURL), check=lambda x: None, say=said.append)
    text = "\n".join(said)
    assert "only the request's address" in text and "✓ YouTube Music" in text


def test_a_url_in_the_terminal_gets_the_same_hint():
    r, w = os.pipe()
    os.write(w, b"https://music.youtube.com/youtubei/v1/browse?x=1\n")
    said = []
    threading.Timer(0.5, lambda: os.write(w, b"\x04")).start()
    read_pasted(r, say=said.append, idle=0.1, hint_after=0.2)
    os.close(r), os.close(w)
    assert any("address" in m for m in said)
