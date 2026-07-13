"""Tests fuer job_manager: Inkrement, Retry-Cap, Lock, Historie."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import docling_worker as dw
import job_manager as jm


def _fake_batch_factory(log: list):
    """Batch-Ersatz: 'konvertiert' erfolgreich, ohne Docling zu benoetigen."""

    def fake_batch(files, job, max_workers, progress):
        results = []
        for i, f in enumerate(files, 1):
            log.append(f)
            res = dw.ConversionResult(
                source_path=f, success=True,
                output_path=str(Path(job.target) / (Path(f).stem + ".md")),
            )
            if progress:
                progress(i, len(files), res)
            results.append(res)
        return results

    return fake_batch


def _fail_batch(files, job, max_workers, progress):
    return [
        dw.ConversionResult(source_path=f, success=False,
                            error="boom", error_category="fehler")
        for f in files
    ]


@pytest.fixture
def job_env(jobs_home, tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.pdf").write_text("111")
    (src / "sub" / "b.docx").write_text("222")
    target = tmp_path / "vault"
    job = jm.add_job("Test", str(src), str(target), dw.ConverterConfig())
    return src, target, job


def test_incremental_flow(job_env):
    src, target, job = job_env
    log: list = []
    batch = _fake_batch_factory(log)

    # Dry-Run konvertiert nichts.
    summary = jm.run_job(job, dry_run=True, convert_batch=batch)
    assert summary.dry_run and summary.changes["neu"] == 2
    assert log == []

    # Erster Lauf: beide Dateien.
    summary = jm.run_job(job, convert_batch=batch)
    assert summary.converted_ok == 2

    # Zweiter Lauf: nichts zu tun.
    log.clear()
    summary = jm.run_job(job, convert_batch=batch)
    assert summary.converted_ok == 0
    assert summary.changes["unveraendert"] == 2
    assert log == []

    # Aenderung + neue Datei werden erkannt, nur diese laufen erneut.
    time.sleep(0.01)
    (src / "a.pdf").write_text("111-geaendert-und-laenger")
    (src / "c.xlsx").write_text("333")
    summary = jm.run_job(job, convert_batch=batch)
    assert summary.converted_ok == 2
    assert {Path(f).name for f in log} == {"a.pdf", "c.xlsx"}


def test_removed_reported_but_moved_ignored(job_env):
    src, target, job = job_env
    log: list = []
    jm.run_job(job, convert_batch=_fake_batch_factory(log))

    # Quelldatei verschwindet -> als "entfernt" gemeldet.
    (src / "sub" / "b.docx").unlink()
    changes = jm.scan_changes(job)
    assert len(changes.removed) == 1

    # Absichtlich verschobene Originale (on_success) sind kein "entfernt".
    def moved_batch(files, jobarg, mw, prog):
        return [
            dw.ConversionResult(source_path=f, success=True,
                                output_path="x.md", moved_to="/archiv/x")
            for f in files
        ]

    (src / "neu.pdf").write_text("999")
    jm.run_job(job, convert_batch=moved_batch)
    (src / "neu.pdf").unlink()  # "verschoben"
    changes = jm.scan_changes(job)
    removed_names = {Path(p).name for p in changes.removed}
    assert "neu.pdf" not in removed_names


def test_retry_cap_and_rearm(job_env):
    src, target, job = job_env
    ok_batch = _fake_batch_factory([])
    jm.run_job(job, convert_batch=ok_batch)

    (src / "defekt.pdf").write_text("x")
    for _ in range(jm.RETRY_LIMIT + 1):
        jm.run_job(job, convert_batch=_fail_batch)

    changes = jm.scan_changes(job)
    key = str(src / "defekt.pdf")
    assert key not in changes.retry           # Cap greift
    assert key in changes.unchanged

    # Eine echte Aenderung reaktiviert die Datei.
    time.sleep(0.01)
    (src / "defekt.pdf").write_text("x-repariert-und-laenger")
    changes = jm.scan_changes(job)
    assert key in changes.changed


def test_lock_blocks_second_run(job_env):
    src, target, job = job_env
    lock = jm._acquire_lock(job.id)
    try:
        with pytest.raises(jm.JobLockedError):
            jm.run_job(job, convert_batch=_fake_batch_factory([]))
    finally:
        lock.unlink()


def test_scan_excludes_target_inside_source(jobs_home, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.pdf").write_text("x")
    target = src / "vault"          # Ziel liegt IN der Quelle
    target.mkdir()
    (target / "erzeugt.md").write_text("x")

    job = jm.add_job("Nested", str(src), str(target), dw.ConverterConfig())
    changes = jm.scan_changes(job)
    names = {Path(p).name for p in changes.new}
    assert names == {"a.pdf"}


def test_history_recorded_and_capped(job_env):
    src, target, job = job_env

    # Dry-Run und Leerlauf erzeugen keine Historie.
    jm.run_job(job, dry_run=True, convert_batch=_fake_batch_factory([]))
    assert jm.load_history(job.id) == []

    jm.run_job(job, convert_batch=_fake_batch_factory([]), trigger="cli")
    history = jm.load_history(job.id)
    assert len(history) == 1
    rec = history[0]
    assert rec["trigger"] == "cli"
    assert rec["converted_ok"] == 2
    assert rec["changes"]["neu"] == 2
    assert rec["failures"] == []

    # Leerlauf danach: weiterhin nur ein Eintrag.
    jm.run_job(job, convert_batch=_fake_batch_factory([]))
    assert len(jm.load_history(job.id)) == 1

    # Fehler landen mit Datei + Grund in der Historie.
    (src / "defekt.pdf").write_text("x")
    jm.run_job(job, convert_batch=_fail_batch, trigger="watch")
    history = jm.load_history(job.id)
    assert len(history) == 2
    assert history[-1]["trigger"] == "watch"
    assert history[-1]["converted_failed"] == 1
    assert history[-1]["failures"][0]["error"] == "boom"


def test_remove_job_cleans_all_state(job_env):
    src, target, job = job_env
    jm.run_job(job, convert_batch=_fake_batch_factory([]))
    assert jm._manifest_file(job.id).exists()
    assert jm._history_file(job.id).exists()

    assert jm.remove_job(job.id)
    assert jm.get_job(job.id) is None
    assert not jm._manifest_file(job.id).exists()
    assert not jm._history_file(job.id).exists()
