"""Smoke-Tests fuer das Dashboard und den Launcher.

Streamlits AppTest fuehrt das komplette Skript headless aus -- das faengt
jeden Import-, Syntax- und Top-Level-Laufzeitfehler (die groesste Datei des
Projekts war zuvor ungetestet). Bewusst NUR Smoke-Niveau: UI-Details sind
zu volatil fuer Vollabdeckung per AppTest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app_streamlit.py"


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Dashboard-Lauf ohne Zugriff auf echte Konfig-/Datenverzeichnisse."""
    monkeypatch.setenv("DOC2VAULT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DOC2VAULT_SOURCE_DIR", raising=False)
    monkeypatch.delenv("DOC2VAULT_TARGET_DIR", raising=False)
    monkeypatch.delenv("DOC2VAULT_ARCHIVE_DIR", raising=False)
    return tmp_path


def test_dashboard_renders_without_exception(isolated_env):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception, f"Dashboard-Skript wirft: {at.exception}"
    # Minimale Strukturpruefung: Kopfzeile und die vier Bereiche existieren.
    page = " ".join(str(getattr(el, "value", "")) for el in at.markdown)
    assert "doc2vault" in page
    tab_labels = " ".join(t.label for t in at.tabs) if at.tabs else page
    for label in ("Konvertierung", "Jobs", "Suche", "Datenaustausch"):
        assert label in tab_labels or label in page


def test_dashboard_launcher_builds_streamlit_argv(monkeypatch):
    import dashboard_launcher

    captured: dict = {}

    def _fake_main():
        import sys

        captured["argv"] = list(sys.argv)
        return 0

    import streamlit.web.cli as stcli

    monkeypatch.setattr(stcli, "main", _fake_main)
    rc = dashboard_launcher.main()
    assert rc == 0
    argv = captured["argv"]
    assert argv[0] == "streamlit" and argv[1] == "run"
    assert argv[2].endswith("app_streamlit.py")
    assert "--browser.gatherUsageStats=false" in argv
