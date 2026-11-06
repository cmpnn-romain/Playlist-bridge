# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
import subprocess
from pathlib import Path

import pytest

from playlist_bridge import autostart, cli
from playlist_bridge import update as upd
from playlist_bridge.files import COMMIT_FILE
from playlist_bridge.update import running_from_a_checkout, update

COMMIT = "abc1234def5678"


class Runner:
    """Stands in for git, pip and systemctl: nothing real runs."""

    def __init__(self, commit=COMMIT, version="0.2.0", clone_fails=False, pip_fails=False, install_fails=False):
        self.calls, self.envs = [], []
        self.commit, self.version = commit, version
        self.clone_fails, self.pip_fails, self.install_fails = clone_fails, pip_fails, install_fails

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        self.envs.append(kw.get("env"))
        if cmd[0] == "git" and "clone" in cmd:
            if self.clone_fails:
                raise subprocess.CalledProcessError(128, cmd, stderr="Cloning...\nfatal: repository not found")
            dest = Path(cmd[-1])
            (dest / "python").mkdir(parents=True)
            (dest / "python" / "pyproject.toml").write_text(f'[project]\nname = "playlist-bridge"\nversion = "{self.version}"\n')
        if cmd[0] == "git" and "rev-parse" in cmd:
            return subprocess.CompletedProcess(cmd, 0, self.commit + "\n", "")
        if "pip" in cmd and self.pip_fails:
            raise subprocess.CalledProcessError(1, cmd, stderr="ERROR: could not build")
        if "playlist_bridge" in cmd and self.install_fails:
            raise subprocess.CalledProcessError(3, cmd, stderr="Log in first")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def kinds(self):
        out = []
        for c in self.calls:
            if c[0] == "git":
                out.append("clone" if "clone" in c else "rev-parse")
            elif "pip" in c:
                out.append("pip-redo" if "--no-deps" in c else "pip-deps")
            elif "playlist_bridge" in c:
                out.append("service-install")
            else:
                out.append("systemctl " + " ".join(c[2:]))
        return out


def go(tmp_path, run=None, **kw):
    said = []
    run = run or Runner()
    kw.setdefault("from_checkout", False)
    kw.setdefault("unit_directory", tmp_path / "units")
    code = update(tmp_path, run=run, say=said.append, python="/venv/bin/python", **kw)
    return code, said, run


def test_updates_installs_over_the_current_one_and_remembers_the_commit(tmp_path):
    code, said, run = go(tmp_path)
    assert code == 0
    assert run.kinds() == ["clone", "rev-parse", "pip-redo", "pip-deps"]
    assert (tmp_path / COMMIT_FILE).read_text().strip() == COMMIT
    assert any("Updated to 0.2.0 (abc1234)" in m for m in said)
    assert any("running in a terminal" in m for m in said)  # no background service: tell how to pick up the new version
    redo = next(c for c in run.calls if "--no-deps" in c)
    assert redo[:3] == ["/venv/bin/python", "-m", "pip"] and "--force-reinstall" in redo  # same version number: must be forced


def test_never_waits_for_a_password(tmp_path):
    _, _, run = go(tmp_path)
    assert run.envs[0]["GIT_TERMINAL_PROMPT"] == "0"


def test_already_up_to_date_changes_nothing(tmp_path):
    (tmp_path / COMMIT_FILE).write_text(COMMIT + "\n")
    code, said, run = go(tmp_path)
    assert code == 0 and run.kinds() == ["clone", "rev-parse"]  # only looked
    assert any("Already up to date" in m for m in said)


def test_running_it_twice_installs_once(tmp_path):
    go(tmp_path)
    _, said, run = go(tmp_path)
    assert "pip-redo" not in run.kinds() and any("Already up to date" in m for m in said)


def test_a_newer_commit_is_installed_again(tmp_path):
    go(tmp_path)
    code, _, run = go(tmp_path, run=Runner(commit="fff9999aaa", version="0.2.1"))
    assert code == 0 and "pip-redo" in run.kinds()
    assert (tmp_path / COMMIT_FILE).read_text().strip() == "fff9999aaa"


def test_download_failure_explains_and_keeps_everything(tmp_path):
    code, said, run = go(tmp_path, run=Runner(clone_fails=True))
    assert code == 1 and run.kinds() == ["clone"]
    assert any("repository not found" in m for m in said) and any("PLAYLIST_BRIDGE_REPO" in m for m in said)
    assert not (tmp_path / COMMIT_FILE).exists()


def test_install_failure_leaves_the_current_version_and_is_retried_next_time(tmp_path):
    code, said, _ = go(tmp_path, run=Runner(pip_fails=True))
    assert code == 1 and any("left as it is" in m for m in said) and any("could not build" in m for m in said)
    assert not (tmp_path / COMMIT_FILE).exists()  # not recorded, so the next `update` tries again
    assert go(tmp_path)[0] == 0


def test_a_checkout_is_not_overwritten(tmp_path):
    code, said, run = go(tmp_path, from_checkout=True)
    assert code == 1 and run.calls == [] and any("git pull" in m for m in said)


def test_without_git_it_says_so(tmp_path):
    code, said, run = go(tmp_path, which=lambda name: None)
    assert code == 1 and run.calls == [] and any("git is needed" in m for m in said)


def test_repo_can_be_overridden(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYLIST_BRIDGE_REPO", "git@github.com:me/fork.git")
    _, _, run = go(tmp_path)
    assert "git@github.com:me/fork.git" in run.calls[0]
    _, _, run = go(tmp_path, repo="https://example.org/x.git")
    assert "https://example.org/x.git" in run.calls[0]


def test_the_background_service_moves_to_the_new_version(tmp_path):
    units = tmp_path / "units"
    autostart.install(python="/venv/bin/python", directory=units, run=Runner(), say=lambda m: None)
    code, said, run = go(tmp_path)
    assert code == 0
    assert run.kinds()[-2:] == ["service-install", "systemctl restart " + autostart.UNIT]
    install = next(c for c in run.calls if "playlist_bridge" in c)
    assert install == ["/venv/bin/python", "-m", "playlist_bridge", "--install"]  # the NEW code writes the new unit
    assert any("background sync was restarted" in m for m in said)


def test_a_service_that_cannot_restart_is_reported_but_the_update_stays(tmp_path):
    autostart.install(python="/venv/bin/python", directory=tmp_path / "units", run=Runner(), say=lambda m: None)
    code, said, _ = go(tmp_path, run=Runner(install_fails=True))
    assert code == 1 and (tmp_path / COMMIT_FILE).exists()
    assert any("could not be restarted" in m and "playlist-bridge --install" in m for m in said)


def test_checkout_detection():
    assert not running_from_a_checkout(
        "/home/u/.local/share/pipx/venvs/playlist-bridge/lib/python3.12/site-packages/playlist_bridge/update.py"
    )
    assert not running_from_a_checkout("/usr/lib/python3/dist-packages/playlist_bridge/update.py")
    assert running_from_a_checkout("/home/u/Playlist-bridge/python/playlist_bridge/update.py")


def test_cli_has_an_update_command(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "HOME", tmp_path)
    monkeypatch.setattr(upd, "update", lambda home: 7)
    assert cli.main(["--update"]) == 7


def test_uninstall_also_removes_the_remembered_commit(tmp_path):
    from playlist_bridge.files import OWN_FILES

    assert COMMIT_FILE in OWN_FILES


def test_the_reason_is_the_line_that_says_what_is_wrong():
    advice = "Please make sure you have the correct access rights\nand the repository exists.\n"
    git = subprocess.CalledProcessError(128, "git", stderr=f"fatal: unable to access 'https://x/': Could not resolve host: x\n\n{advice}")
    assert upd._reason(git) == "unable to access 'https://x/': Could not resolve host: x"
    assert upd._reason(subprocess.CalledProcessError(1, "pip", stderr="Collecting x\nERROR: No matching distribution found for x\n")) == (
        "No matching distribution found for x"
    )
    assert upd._reason(subprocess.CalledProcessError(2, "x", stderr="")) == "exit code 2"


def test_the_actions_are_flags_and_the_old_words_still_work(monkeypatch):
    from playlist_bridge import cli
    from playlist_bridge import update as upd

    monkeypatch.setattr(upd, "update", lambda home: 5)
    assert cli.main(["--update"]) == 5 and cli.main(["update"]) == 5  # old service files and old `update` pass the bare word
    with pytest.raises(SystemExit):
        cli.main([])
