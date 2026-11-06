# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
import subprocess

import pytest

from playlist_bridge import autostart, cli
from playlist_bridge.guard import EXIT_LOGIN


class Recorder:
    def __init__(self, fail_with=None):
        self.calls, self.fail_with = [], fail_with

    def __call__(self, cmd, **kw):
        self.calls.append(cmd[2:])
        if self.fail_with:
            raise self.fail_with
        return subprocess.CompletedProcess(cmd, 0, "", "")


def test_unit_runs_this_python_and_never_restarts_on_login_errors():
    u = autostart.unit_text("/opt/pb venv/bin/python", "/data/pb")
    assert 'ExecStart="/opt/pb venv/bin/python" -m playlist_bridge --sync --foreground' in u
    assert f"RestartPreventExitStatus={EXIT_LOGIN}" in u
    assert 'Environment="PLAYLIST_BRIDGE_HOME=/data/pb"' in u
    assert "StartLimitBurst" in u  # a crash can't turn into a restart storm
    assert "Environment" not in autostart.unit_text("/usr/bin/python3")


def test_install_writes_unit_and_enables_it(tmp_path):
    run, said = Recorder(), []
    autostart.install(python="/py", directory=tmp_path, run=run, say=said.append)
    assert (tmp_path / autostart.UNIT).read_text().startswith("[Unit]")
    assert run.calls == [["daemon-reload"], ["enable", "--now", autostart.UNIT]]
    assert any("enable-linger" in m for m in said)


def test_install_twice_is_harmless(tmp_path):
    run = Recorder()
    for _ in range(2):
        autostart.install(python="/py", directory=tmp_path, run=run, say=lambda m: None)
    assert len(list(tmp_path.iterdir())) == 1


def test_stop_disables_but_keeps_the_unit_so_sync_can_turn_it_on_again(tmp_path):
    run, said = Recorder(), []
    autostart.install(python="/py", directory=tmp_path, run=run, say=lambda m: None)
    run.calls.clear()
    autostart.stop(directory=tmp_path, run=run, say=said.append)
    assert run.calls == [["disable", "--now", autostart.UNIT]]
    assert (tmp_path / autostart.UNIT).exists()
    assert "--sync" in said[0]


def test_stop_when_never_installed_does_nothing(tmp_path):
    run, said = Recorder(), []
    autostart.stop(directory=tmp_path, run=run, say=said.append)
    assert run.calls == [] and "not set up" in said[0]


def test_remove_deletes_the_unit_and_is_harmless_when_absent(tmp_path):
    run = Recorder()
    autostart.install(python="/py", directory=tmp_path, run=run, say=lambda m: None)
    run.calls.clear()
    autostart.remove(directory=tmp_path, run=run)
    assert not (tmp_path / autostart.UNIT).exists()
    assert run.calls == [["disable", "--now", autostart.UNIT], ["daemon-reload"]]
    run.calls.clear()
    autostart.remove(directory=tmp_path, run=run)  # nothing to remove
    assert run.calls == []


def test_no_systemd_gives_a_clear_message(tmp_path):
    with pytest.raises(SystemExit) as e:
        autostart.install(python="/py", directory=tmp_path, run=Recorder(FileNotFoundError()), say=lambda m: None)
    assert "systemd" in str(e.value)


def test_systemctl_failure_is_reported(tmp_path):
    err = subprocess.CalledProcessError(1, "systemctl", stderr="Failed to connect to bus")
    with pytest.raises(SystemExit) as e:
        autostart.install(python="/py", directory=tmp_path, run=Recorder(err), say=lambda m: None)
    assert "Failed to connect to bus" in str(e.value)


def test_cli_install_needs_both_logins_first(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "HOME", tmp_path)
    monkeypatch.setattr(cli, "YTM_AUTH", tmp_path / "ytm.json")
    monkeypatch.setattr(cli, "TIDAL_AUTH", tmp_path / "tidal.json")
    assert cli.main(["--install"]) == EXIT_LOGIN
    assert "playlist-bridge --login" in capsys.readouterr().err


def test_status_command_is_gone():
    with pytest.raises(SystemExit):
        cli.main(["status"])
