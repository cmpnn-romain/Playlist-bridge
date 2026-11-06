# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
"""How `login` looks in a terminal: panels, numbered steps, colours, a spinner and a QR code.

The rest of the program only calls `say(text)` with plain text. `say` here recognises a few shapes of that text and draws them
nicely; anything else is printed as it is. Colours and boxes disappear by themselves when the output is not a terminal (a pipe,
a log file) or when NO_COLOR is set.
"""

from __future__ import annotations

import io
import re
from contextlib import nullcontext

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console(highlight=False)

_STEP = re.compile(r"^\s{1,4}(\d+)\.\s+(.*)$")
_CONTINUATION = re.compile(r"^\s{5,}\S")


def _emphasis(t: Text) -> Text:
    t.highlight_regex(r'"[^"]+"', "bold")
    t.highlight_regex(r"https?://\S+", "underline bright_blue")
    t.highlight_regex(r"Copy as cURL( \(bash\))?", "bold green")
    t.highlight_regex(r"\bCtrl[+-]\w+(?:\+\w+)?", "bold yellow")
    return t


def _body(text: str):
    """Plain lines stay plain; "  1. ..." lines become a number column and a text column that wraps under itself."""
    parts, plain, grid = [], [], None

    def flush_plain():
        if plain:
            parts.append(_emphasis(Text("\n".join(plain))))
            plain.clear()

    for line in text.split("\n"):
        m = _STEP.match(line)
        if m:
            flush_plain()
            if grid is None:
                grid = Table.grid(padding=(0, 1))
                grid.add_column(style="bold cyan", no_wrap=True, justify="right")
                grid.add_column(overflow="fold")
                parts.append(grid)
                rows = []
            rows.append([m.group(1) + ".", m.group(2)])
        elif grid is not None and rows and _CONTINUATION.match(line):
            rows[-1][1] += "\n" + line.strip()
        else:
            if grid is not None:
                for n, body in rows:
                    grid.add_row(n, _emphasis(Text(body)))
                grid = None
            plain.append(line)
    if grid is not None:
        for n, body in rows:
            grid.add_row(n, _emphasis(Text(body)))
    flush_plain()
    return Group(*parts)


def say(msg: str = "") -> None:
    text = msg.strip("\n")
    if msg.startswith("\n"):
        console.print()
    first = text.split("\n", 1)[0]
    if first.startswith("Step "):  # "Step 1 of 2: YouTube Music" + a body: a titled box
        title, _, body = text.partition("\n")
        console.print(
            Panel(
                _body(body.strip("\n")),
                title=Text(title.replace(": ", " · ", 1), style="bold cyan"),
                title_align="left",
                border_style="cyan",
                padding=(1, 2),
            )
        )
    elif first.startswith("All set"):
        console.print(Panel(Text(text, style="bold green"), border_style="green", padding=(0, 2)))
    elif first.startswith("✓"):
        console.print(Text(msg.strip("\n"), style="bold green"))
    elif first.startswith("✗"):
        console.print(Text(text, style="bold red"))
    elif first.startswith("Connecting"):
        console.print(Text(text, style="bold"))
        console.print()
    elif first.startswith("Waiting"):
        console.print(Text(text, style="dim italic"))
    elif text.lstrip().startswith("That is not it"):
        console.print(Text(text, style="yellow"))
    elif text.lstrip().startswith(("Paste again", "Copy the request again")):
        console.print(Text(text, style="dim"))
    else:
        console.print(msg, markup=False, highlight=False)
    if msg.endswith("\n\n"):
        console.print()


def qr(url: str) -> None:
    """The link as a QR code, so a phone can scan it from a server's screen. Only in a real terminal, and only if it fits."""
    if not console.is_terminal:
        return
    try:
        import segno

        out = io.StringIO()
        segno.make(url, error="l").terminal(out=out, compact=True, border=2)
        art = out.getvalue()
    except Exception:  # decoration only: never in the way of the login
        return
    lines = art.splitlines()
    if lines and max(len(ln) for ln in lines) <= console.width:
        console.print(Text.from_ansi(art), end="")
        console.print(Text("Or scan it with your phone.", style="dim"))
        console.print()


def status(message: str):
    """A spinner with `message` while the program waits; nothing at all when the output is not a terminal."""
    return console.status(Text(message, style="dim"), spinner="dots") if console.is_terminal else nullcontext()
