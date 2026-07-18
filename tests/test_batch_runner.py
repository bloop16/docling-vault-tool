"""Tests fuer run_conversion_batch: Worker-Abstuerze duerfen den Batch nicht killen.

Hintergrund (realer Windows-Erstlauf): EIN std::bad_alloc in einem Worker riss
den ProcessPoolExecutor und damit 547 wartende Dateien mit. Der Runner muss
den Pool neu starten, die restlichen Dateien verarbeiten und nur die
Absturz-Verursacher als "prozessabsturz" markieren.

Die Tests nutzen den echten ProcessPoolExecutor; unter Linux (fork) erben die
Worker die gepatchten Modul-Funktionen, sodass kein Docling noetig ist.
"""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import pytest

import docling_worker as dw

pytestmark = pytest.mark.skipif(
    multiprocessing.get_start_method() != "fork",
    reason="Patch-Vererbung an Worker benoetigt fork (Linux)",
)


def _noop_init(config, output_dir, input_root):
    pass


def _task_ok(source_path: str) -> dw.ConversionResult:
    return dw.ConversionResult(source_path=source_path, success=True,
                               output_path=source_path + ".md")


def _task_crash_on_boom(source_path: str) -> dw.ConversionResult:
    if "boom" in source_path:
        os._exit(137)          # harter Absturz, wie std::bad_alloc/OOM-Kill
    return _task_ok(source_path)


def _paths(tmp_path: Path, names: list[str]) -> list[str]:
    out = []
    for n in names:
        p = tmp_path / n
        p.write_text("x")
        out.append(str(p))
    return out


def test_batch_without_crashes(tmp_path, monkeypatch):
    monkeypatch.setattr(dw, "init_worker", _noop_init)
    monkeypatch.setattr(dw, "convert_file_task", _task_ok)
    files = _paths(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])

    seen = []
    results = dw.run_conversion_batch(
        files, dw.ConverterConfig(), tmp_path, tmp_path, max_workers=2,
        progress=lambda d, t, r: seen.append((d, t)),
    )
    assert len(results) == 3
    assert all(r.success for r in results)
    assert seen[-1] == (3, 3)


def test_batch_survives_worker_crash(tmp_path, monkeypatch):
    """Eine abstuerzende Datei darf die uebrigen nicht mitreissen."""
    monkeypatch.setattr(dw, "init_worker", _noop_init)
    monkeypatch.setattr(dw, "convert_file_task", _task_crash_on_boom)
    files = _paths(tmp_path, [f"doc{i}.pdf" for i in range(6)] + ["boom.pdf"])

    results = dw.run_conversion_batch(
        files, dw.ConverterConfig(), tmp_path, tmp_path, max_workers=2,
    )

    assert len(results) == 7                      # ALLE Dateien gemeldet
    by_path = {Path(r.source_path).name: r for r in results}
    crashed = by_path["boom.pdf"]
    assert not crashed.success
    assert crashed.error_category == "prozessabsturz"
    assert "reduzieren" in crashed.error_hint

    ok_names = [n for n, r in by_path.items() if r.success]
    # Alle Nicht-Absturz-Dateien wurden (ggf. nach Pool-Neustart) konvertiert.
    assert len(ok_names) == 6


def _task_always_crash(source_path: str) -> dw.ConversionResult:
    os._exit(137)


def test_batch_all_files_crash(tmp_path, monkeypatch):
    """Auch der Extremfall (jede Datei crasht) terminiert mit Ergebnissen."""
    monkeypatch.setattr(dw, "init_worker", _noop_init)
    monkeypatch.setattr(dw, "convert_file_task", _task_always_crash)
    files = _paths(tmp_path, ["boom1.pdf", "boom2.pdf"])

    results = dw.run_conversion_batch(
        files, dw.ConverterConfig(), tmp_path, tmp_path, max_workers=2,
    )
    assert len(results) == 2
    assert all(r.error_category == "prozessabsturz" for r in results)