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
import time
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
    # Auch der reduzierte Wiederholungsversuch ist gescheitert -> Hinweis.
    assert all("reduzierten Einstellungen" in r.error_hint for r in results)


# --- Automatischer Wiederholungsversuch mit reduzierten Einstellungen -------
# Simuliert den realen std::bad_alloc-Fall: eine riesige CAD-Zeichnung crasht
# den Worker bei voller Bildskalierung, laesst sich aber mit reduzierten
# Einstellungen (keine Bildextraktion) konvertieren.

def _config_init(config, output_dir, input_root):
    dw._WORKER_CONFIG = config


def _task_crash_unless_reduced(source_path: str) -> dw.ConversionResult:
    if "huge" in source_path and dw._WORKER_CONFIG.generate_picture_images:
        os._exit(137)          # bad_alloc nur bei voller Konfiguration
    return _task_ok(source_path)


def _task_memfail_unless_reduced(source_path: str) -> dw.ConversionResult:
    if "huge" in source_path and dw._WORKER_CONFIG.generate_picture_images:
        return dw.ConversionResult(
            source_path=source_path, success=False,
            error="Stage preprocess failed for run 12, pages [2]: std::bad_alloc",
            error_category="speicher", error_hint="Speicher reicht nicht.",
        )
    return _task_ok(source_path)


def test_reduced_retry_rescues_crashing_file(tmp_path, monkeypatch):
    """Worker-Absturz -> automatischer Erfolg im reduzierten Einzelprozess."""
    monkeypatch.setattr(dw, "init_worker", _config_init)
    monkeypatch.setattr(dw, "convert_file_task", _task_crash_unless_reduced)
    files = _paths(tmp_path, ["ok.pdf", "huge.pdf"])

    seen = []
    results = dw.run_conversion_batch(
        files, dw.ConverterConfig(), tmp_path, tmp_path, max_workers=2,
        progress=lambda d, t, r: seen.append((d, t)),
    )

    by_path = {Path(r.source_path).name: r for r in results}
    assert by_path["ok.pdf"].success and not by_path["ok.pdf"].reduced_mode
    rescued = by_path["huge.pdf"]
    assert rescued.success
    assert rescued.reduced_mode
    assert seen[-1] == (2, 2)


def test_reduced_retry_rescues_memory_failure(tmp_path, monkeypatch):
    """Gemeldeter Speicherfehler (ohne Absturz) wird ebenfalls gerettet."""
    monkeypatch.setattr(dw, "init_worker", _config_init)
    monkeypatch.setattr(dw, "convert_file_task", _task_memfail_unless_reduced)
    files = _paths(tmp_path, ["ok.pdf", "huge.pdf"])

    results = dw.run_conversion_batch(
        files, dw.ConverterConfig(), tmp_path, tmp_path, max_workers=2,
    )

    assert len(results) == 2
    by_path = {Path(r.source_path).name: r for r in results}
    assert by_path["huge.pdf"].success
    assert by_path["huge.pdf"].reduced_mode

# --- Heartbeat & Sofort-Abbruch ---------------------------------------------

def _task_slowish(source_path: str) -> dw.ConversionResult:
    time.sleep(1.5)
    return _task_ok(source_path)


def _task_sleep_forever(source_path: str) -> dw.ConversionResult:
    if "schlaf" in source_path:
        time.sleep(120)
    return _task_ok(source_path)


class _CancelSignal(BaseException):
    """Simuliert Streamlits Skript-Unterbrechung (kein Exception-Abkoemmling)."""


def test_heartbeat_fires_while_workers_busy(tmp_path, monkeypatch):
    monkeypatch.setattr(dw, "init_worker", _noop_init)
    monkeypatch.setattr(dw, "convert_file_task", _task_slowish)
    files = _paths(tmp_path, ["a.pdf"])

    beats = []
    results = dw.run_conversion_batch(
        files, dw.ConverterConfig(), tmp_path, tmp_path, max_workers=1,
        heartbeat=lambda: beats.append(1),
    )
    assert len(results) == 1 and results[0].success
    assert beats, "Heartbeat muss waehrend laufender Worker ticken"


def test_abort_terminates_running_workers_quickly(tmp_path, monkeypatch):
    """BaseException aus progress (= Abbrechen-Klick) beendet Worker sofort,
    statt minutenlang auf angefangene Dateien zu warten."""
    monkeypatch.setattr(dw, "init_worker", _noop_init)
    monkeypatch.setattr(dw, "convert_file_task", _task_sleep_forever)
    files = _paths(tmp_path, ["fertig.pdf", "schlaf.pdf"])

    def _progress(done, total, res):
        raise _CancelSignal()

    t0 = time.perf_counter()
    with pytest.raises(_CancelSignal):
        dw.run_conversion_batch(
            files, dw.ConverterConfig(), tmp_path, tmp_path, max_workers=2,
            progress=_progress,
        )
    assert time.perf_counter() - t0 < 20, "Abbruch darf nicht auf den 120s-Schlaefer warten"


def test_watch_parent_exits_when_sentinel_closes():
    """Eltern-Waechter: Worker beendet sich, sobald der Elternprozess endet
    (verhindert Waisen-Prozesse mit geladenen Modellen auf Windows)."""
    import multiprocessing as mp
    import threading

    recv, send = mp.Pipe(duplex=False)
    exited = threading.Event()
    t = threading.Thread(
        target=dw._watch_parent,
        args=(recv, lambda code: exited.set()),
        daemon=True,
    )
    t.start()
    assert not exited.wait(0.2)     # Elternprozess "lebt" noch
    send.close()                     # Elternprozess "stirbt"
    assert exited.wait(5), "Waechter hat das Eltern-Ende nicht bemerkt"
    recv.close()


def _task_memfail_first_try(source_path: str) -> dw.ConversionResult:
    """Scheitert beim ersten Versuch mit Speicherfehler, danach ok --
    simuliert Fehler durch GESAMT-Speicherdruck (nicht durch die Datei)."""
    marker = Path(source_path + ".tried")
    if not marker.exists():
        marker.write_text("1")
        return dw.ConversionResult(
            source_path=source_path, success=False,
            error="std::bad_alloc", error_category="speicher")
    return _task_ok(source_path)


def test_memory_pressure_shrinks_workers_and_retries(tmp_path, monkeypatch, caplog):
    """Mehrere Speicherfehler in einer Runde -> Prozesszahl halbieren und
    die Dateien in VOLLER Qualitaet wiederholen (nicht sofort reduziert)."""
    import logging

    monkeypatch.setattr(dw, "init_worker", _noop_init)
    monkeypatch.setattr(dw, "convert_file_task", _task_memfail_first_try)
    files = _paths(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])

    with caplog.at_level(logging.WARNING, logger="doc2vault.worker"):
        results = dw.run_conversion_batch(
            files, dw.ConverterConfig(), tmp_path / "out", tmp_path,
            max_workers=2,
        )

    assert len(results) == 3
    assert all(r.success for r in results)
    # Kein Umweg ueber die reduzierten Einstellungen noetig.
    assert not any(r.reduced_mode for r in results)
    assert any("Speicherdruck erkannt" in rec.message for rec in caplog.records)


def test_constrained_commit_caps_start_workers(tmp_path, monkeypatch, caplog):
    """Knapper Commit (Auslagerungsdatei fehlt oder fest zu klein) ist das
    harte Budget -- der Lauf startet direkt mit weniger Prozessen."""
    import logging

    monkeypatch.setattr(dw, "init_worker", _noop_init)
    monkeypatch.setattr(dw, "convert_file_task", _task_ok)
    # Realfall: 43,5 GB RAM frei, aber nur 34,1 GB Commit -- fest zu
    # kleine Auslagerungsdatei, pagefile_missing ist dabei False.
    monkeypatch.setattr(dw, "memory_diagnostics", lambda: {
        "python_bits": 64, "ram_total_gb": 63.9, "ram_avail_gb": 43.5,
        "commit_avail_gb": 34.1, "virtual_avail_gb": 131072.0,
        "pagefile_missing": False, "commit_hard": True,
    })
    files = _paths(tmp_path, ["a.pdf", "b.pdf"])

    with caplog.at_level(logging.WARNING, logger="doc2vault.worker"):
        results = dw.run_conversion_batch(
            files, dw.ConverterConfig(), tmp_path / "out", tmp_path,
            max_workers=8,
        )

    assert all(r.success for r in results)
    assert any("Commit-Speicher ist das harte Limit" in rec.message
               for rec in caplog.records)
    # (34,1 - 4) // 12 = 2 Prozesse statt 8.
    assert any("Start mit 2 statt 8" in rec.message
               for rec in caplog.records)
