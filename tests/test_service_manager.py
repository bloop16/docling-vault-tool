"""Tests fuer doc2vault-service (Dienste ohne echtes systemd/schtasks)."""

from __future__ import annotations

import pytest

import service_manager as sm


@pytest.fixture
def captured(monkeypatch, tmp_path):
    """Faengt alle Systemaufrufe ab und isoliert das Unit-Verzeichnis."""
    calls: list[list[str]] = []

    class _OK:
        returncode = 0

    monkeypatch.setattr(sm.subprocess, "run",
                        lambda cmd, check=False: calls.append(cmd) or _OK())
    monkeypatch.setattr(sm, "systemd_unit_dir",
                        lambda: tmp_path / "systemd-user")
    monkeypatch.setattr(sm, "_find_command",
                        lambda name: f"/opt/venv/bin/{name}")
    return calls


def test_linux_install_ui_writes_unit_and_enables(captured, tmp_path):
    rc = sm.install("ui", None, port=8600, platform="linux")
    assert rc == 0
    unit = tmp_path / "systemd-user" / "doc2vault-ui.service"
    text = unit.read_text(encoding="utf-8")
    assert "ExecStart=/opt/venv/bin/doc2vault-ui --server.port 8600" in text
    assert "Restart=on-failure" in text
    assert "WantedBy=default.target" in text
    assert ["systemctl", "--user", "enable", "--now",
            "doc2vault-ui.service"] in captured


def test_linux_watch_and_uninstall(captured, tmp_path):
    assert sm.install("watch", "berichte", port=8501, platform="linux") == 0
    unit = tmp_path / "systemd-user" / "doc2vault-watch-berichte.service"
    assert "doc2vault-jobs watch berichte" in unit.read_text(encoding="utf-8")

    assert sm.uninstall("watch", "berichte", platform="linux") == 0
    assert not unit.exists()
    assert ["systemctl", "--user", "disable", "--now",
            "doc2vault-watch-berichte.service"] in captured


def test_windows_install_uses_schtasks(captured):
    rc = sm.install("ui", None, port=8501, platform="win32")
    assert rc == 0
    create = next(c for c in captured if "/Create" in c)
    assert create[:4] == ["schtasks", "/Create", "/TN", "Doc2VaultUI"]
    assert "/SC" in create and "ONLOGON" in create
    assert any("/Run" in c for c in captured)

    captured.clear()
    assert sm.uninstall("ui", None, platform="win32") == 0
    assert any("/Delete" in c for c in captured)


def test_watch_requires_job_id(captured):
    assert sm.install("watch", None, port=8501, platform="linux") == 2
    assert sm.uninstall("watch", None, platform="win32") == 2


def test_unsupported_platform(captured):
    assert sm.install("ui", None, port=8501, platform="darwin") == 2


def test_cli_parses(monkeypatch, captured):
    monkeypatch.setattr(sm.sys, "platform", "linux")
    assert sm._run_cli(["install", "ui", "--port", "8700"]) == 0
    assert sm._run_cli(["status"]) == 0


def test_find_command_prefers_interpreter_dir(tmp_path, monkeypatch):
    exe_dir = tmp_path / "venv" / "bin"
    exe_dir.mkdir(parents=True)
    (exe_dir / "doc2vault-ui").write_text("#!/bin/sh\n")
    monkeypatch.setattr(sm.sys, "executable", str(exe_dir / "python"))
    assert sm._find_command("doc2vault-ui") == str(exe_dir / "doc2vault-ui")
    with pytest.raises(FileNotFoundError):
        monkeypatch.setattr(sm.shutil, "which", lambda n: None)
        sm._find_command("gibtsnicht")
