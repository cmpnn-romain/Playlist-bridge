import io

import pytest
from rich.console import Console

from playlist_bridge import login, ui


@pytest.fixture
def screen(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(ui, "console", Console(file=buf, width=100, highlight=False))
    return buf


def test_the_ytm_steps_are_a_titled_box_with_numbered_rows(screen):
    ui.say(login.YTM_STEPS)
    out = screen.getvalue()
    assert "Step 1 of 2 · YouTube Music" in out and "╭" in out and "╰" in out
    for n in range(1, 8):
        assert f"{n}. " in out
    assert "\x1b" not in out  # no colour codes when it is not a terminal
    # a long step wraps under its own text, not under the number
    line = next(ln for ln in out.splitlines() if "(F12 does the same)" in ln)
    assert line.index("(F12") == out.splitlines()[[i for i, ln in enumerate(out.splitlines()) if "2. Right-click" in ln][0]].index(
        "Right-click"
    )


def test_results_and_the_final_box(screen):
    ui.say("\n✓ YouTube Music is connected.\n")
    ui.say("\n✗ That did not work: 401")
    ui.say("All set. Start syncing with:  playlist-bridge --sync")
    out = screen.getvalue()
    assert "✓ YouTube Music is connected." in out and "✗ That did not work: 401" in out and "All set" in out and "╭" in out


def test_plain_text_is_printed_as_it_is(screen):
    ui.say("[bold]not markup[/bold] https://x.y/z")
    assert "[bold]not markup[/bold] https://x.y/z" in screen.getvalue()


def test_no_qr_and_no_spinner_outside_a_terminal(screen):
    ui.qr("https://link.tidal.com/AB12C")
    assert screen.getvalue() == ""
    with ui.status("waiting"):
        pass


def test_the_qr_is_drawn_in_a_terminal(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(ui, "console", Console(file=buf, width=100, force_terminal=True, highlight=False))
    ui.qr("https://link.tidal.com/AB12C")
    assert "█" in buf.getvalue() and "scan" in buf.getvalue()
