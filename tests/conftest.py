"""Gemeinsame Test-Fixtures.

Docling selbst wird nicht benoetigt: ein Stub ersetzt ``docling_core`` und ein
Fake-Converter schreibt Markdown + ein Testbild, sodass die gesamte Pfad-,
Plan- und Job-Logik ohne die schweren Modelle testbar ist.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# Repo-Wurzel importierbar machen (docling_worker, job_manager).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _install_docling_stub() -> None:
    if "docling_core.types.doc" in sys.modules:
        return
    doc_mod = types.ModuleType("docling_core.types.doc")
    doc_mod.ImageRefMode = type("ImageRefMode", (), {"REFERENCED": "referenced"})
    types_mod = types.ModuleType("docling_core.types")
    types_mod.doc = doc_mod
    root = types.ModuleType("docling_core")
    root.types = types_mod
    sys.modules["docling_core"] = root
    sys.modules["docling_core.types"] = types_mod
    sys.modules["docling_core.types.doc"] = doc_mod


_install_docling_stub()


class FakeDoc:
    """Schreibt eine Markdown-Datei samt einem Bild in den Asset-Ordner --
    inklusive absolutem Bildlink, wie ihn Docling bei zentraler Ablage
    erzeugen kann (die Normalisierung ist Teil des Testumfangs)."""

    def save_as_markdown(self, filename, artifacts_dir=None, image_mode=None):
        artifacts = Path(artifacts_dir)
        artifacts.mkdir(parents=True, exist_ok=True)
        img = artifacts / "img_0.png"
        img.write_bytes(b"\x89PNG\r\n")
        Path(filename).write_text(
            f"# Titel\n\nText mit Bild:\n\n![]({img.absolute().as_posix()})\n",
            encoding="utf-8",
        )


class FakeConverter:
    def convert(self, source):
        return type("Result", (), {"document": FakeDoc()})()


class BoomConverter:
    def convert(self, source):
        raise RuntimeError("kaputt")


@pytest.fixture
def fake_converter():
    return FakeConverter()


@pytest.fixture
def boom_converter():
    return BoomConverter()


@pytest.fixture
def jobs_home(tmp_path, monkeypatch):
    """Isoliertes Konfigverzeichnis fuer job_manager-Tests."""
    home = tmp_path / "config-home"
    monkeypatch.setenv("DOCLING_VAULT_HOME", str(home))
    return home
