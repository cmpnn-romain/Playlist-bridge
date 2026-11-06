# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
import fcntl
import subprocess

import pytest

from playlist_bridge import autostart
from playlist_bridge.files import OWN_FILES
from playlist_bridge.uninstall import package_command, uninstall


class Runner:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if self.fail and cmd[0] == "pipx":
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "pb"
    h.mkdir()
    for n in OWN_FILES:
        (h / n).write_text("x")
    return h


def go(home, tmp_path, **kw):
    said = []
    kw.setdefault("run", Runner())
    code = uninstall(home, say=said.append, unit_directory=tmp_path / "units", command=["pipx", "uninstall", "playlist-bridge"], **kw)
    return code, said, kw["run"]


def test_package_command_follows_how_it_was_installed():
    pipx = "/home/u/.local/share/pipx/venvs/playlist-bridge"
    assert package_command(pipx, "/py", which=lambda n: "/usr/bin/pipx") == ["pipx", "uninstall", "playlist-bridge"]
    assert package_command(pipx, "/py", which=lambda n: None)[:3] == ["/py", "-m", "pip"]  # pipx itself is gone
    assert package_command("/usr", "/usr/bin/python3") == ["/usr/bin/python3", "-m", "pip", "uninstall", "-y", "playlist-bridge"]


def test_removes_everything_when_confirmed(home, tmp_path):
    units = tmp_path / "units"
    autostart.install(python="/py", directory=units, run=Runner(), say=lambda m: None)
    code, said, run = go(home, tmp_path, ask=lambda q: "y", interactive=True)
    assert code == 0
    assert not home.exists()  # empty folder removed too
    assert not (units / autostart.UNIT).exists()
    assert run.calls[-1] == ["pipx", "uninstall", "playlist-bridge"]  # the program itself goes last
    assert "gone" in said[-1]


def test_only_its_own_files_are_deleted(home, tmp_path):
    (home / "notes.txt").write_text("mine")
    code, _, _ = go(home, tmp_path, yes=True)
    assert code == 0
    assert [p.name for p in home.iterdir()] == ["notes.txt"]  # the folder and the stranger's file survive


@pytest.mark.parametrize("answer", ["", "n", "no", "maybe"])
def test_anything_but_yes_removes_nothing(home, tmp_path, answer):
    code, said, run = go(home, tmp_path, ask=lambda q: answer, interactive=True)
    assert code == 1 and run.calls == []
    assert all((home / n).exists() for n in OWN_FILES)
    assert "Nothing was removed." in said


def test_without_a_terminal_it_needs_yes(home, tmp_path):
    code, said, run = go(home, tmp_path, interactive=False)
    assert code == 1 and run.calls == [] and (home / OWN_FILES[0]).exists()
    assert any("--yes" in m for m in said)


def test_refuses_while_a_sync_is_running(home, tmp_path):
    with open(home / "lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit) as e:
            go(home, tmp_path, yes=True)
    assert "in progress" in str(e.value)
    assert (home / OWN_FILES[0]).exists()  # nothing was deleted


def test_if_the_program_cannot_be_removed_it_says_the_command(home, tmp_path):
    code, said, _ = go(home, tmp_path, yes=True, run=Runner(fail=True))
    assert code == 1 and "pipx uninstall playlist-bridge" in said[-1]
