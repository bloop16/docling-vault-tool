"""Tests fuer job_manager: Inkrement, Retry-Cap, Lock, Historie, Watch."""

from __future__ import annotations

import threading
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


def test_watch_polling_cycles(job_env):
    """Polling-Modus: laeuft die gewuenschte Zahl an Zyklen und konvertiert."""
    src, target, job = job_env
    job.poll_interval = 1
    summaries: list = []
    jm.watch_job(
        job, on_cycle=summaries.append, max_cycles=2,
        use_events=False, convert_batch=_fake_batch_factory([]),
    )
    assert len(summaries) == 2
    assert summaries[0].converted_ok == 2      # Erstlauf
    assert summaries[1].converted_ok == 0      # nichts geaendert


def test_watch_event_mode_wakes_on_change(job_env):
    """Ereignismodus: eine neue Datei weckt den Watch vor dem Rescan-Intervall."""
    pytest.importorskip("watchdog")
    src, target, job = job_env
    job.poll_interval = 120   # ohne Ereignis wuerde Zyklus 2 zwei Minuten warten
    summaries: list = []
    log: list = []

    thread = threading.Thread(
        target=jm.watch_job,
        kwargs=dict(
            job=job, on_cycle=summaries.append, max_cycles=2,
            use_events=True, convert_batch=_fake_batch_factory(log),
        ),
    )
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while len(summaries) < 1 and time.monotonic() < deadline:
            time.sleep(0.1)
        assert summaries, "Erstlauf ist nicht erfolgt"

        (src / "neu.pdf").write_text("x")      # Ereignis ausloesen
        thread.join(timeout=15)
        assert not thread.is_alive(), "Ereignis hat den Watch nicht geweckt"
    finally:
        if thread.is_alive():                   # Aufraeumen bei Fehlschlag
            thread.join(timeout=1)

    assert len(summaries) == 2
    assert summaries[1].converted_ok == 1
    assert Path(log[-1]).name == "neu.pdf"


def _writing_batch_factory():
    """Batch-Ersatz, der echte .md-Dateien ins Ziel schreibt (fuer Build-Tests)."""

    def batch(files, job, max_workers, progress):
        results = []
        target = Path(job.target)
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            out = target / (Path(f).stem + ".md")
            out.write_text(f"# {Path(f).stem}\n\nInhalt aus {Path(f).name}.\n",
                           encoding="utf-8")
            results.append(dw.ConversionResult(
                source_path=f, success=True, output_path=str(out)))
        return results

    return batch


def test_job_build_vault_and_index(jobs_home, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "bericht.pdf").write_text("x")
    target = tmp_path / "vault"

    job = jm.add_job("Pipeline", str(src), str(target), dw.ConverterConfig(),
                     build_vault=True)
    assert jm.get_job(job.id).build_vault is True

    summary = jm.run_job(job, convert_batch=_writing_batch_factory())
    assert summary.converted_ok == 1
    assert summary.build_notes == 1
    assert summary.index_total == 1
    assert summary.build_error is None

    # Fertiger Vault: Notiz in Inbox/, Index + INDEX.md vorhanden.
    assert (target / "Inbox" / "bericht.md").exists()
    assert (target / ".vault-index" / "index.db").exists()
    assert (target / "INDEX.md").exists()

    # Historie enthaelt den Build-Schritt.
    rec = jm.load_history(job.id)[-1]
    assert rec["build"] == {"notes": 1, "images": 0, "index_total": 1}

    # Leerlauf: kein erneuter Build (build_notes bleibt None).
    summary2 = jm.run_job(job, convert_batch=_writing_batch_factory())
    assert summary2.converted_ok == 0
    assert summary2.build_notes is None


def test_job_build_error_does_not_fail_run(jobs_home, tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.pdf").write_text("x")
    job = jm.add_job("Kaputt", str(src), str(tmp_path / "vault"),
                     dw.ConverterConfig(), build_vault=True)

    import vault_builder

    def boom(*args, **kwargs):
        raise RuntimeError("build kaputt")

    monkeypatch.setattr(vault_builder, "build_vault", boom)
    summary = jm.run_job(job, convert_batch=_writing_batch_factory())
    assert summary.converted_ok == 1          # Konvertierung bleibt erfolgreich
    assert "build kaputt" in summary.build_error
    assert "build_error" in jm.load_history(job.id)[-1]


def test_config_dir_migrates_legacy_folder(tmp_path, monkeypatch):
    """Daten der frueheren Installation (docling-vault-tool) werden uebernommen."""
    parent = tmp_path / "confroot"
    legacy = parent / "docling-vault-tool"
    (legacy / "manifests").mkdir(parents=True)
    (legacy / "jobs.json").write_text("[]", encoding="utf-8")

    monkeypatch.delenv("DOC2VAULT_HOME", raising=False)
    monkeypatch.delenv("DOCLING_VAULT_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(parent))
    monkeypatch.setattr(jm.sys, "platform", "linux")

    base = jm.config_dir()
    assert base == parent / "doc2vault"
    assert (base / "jobs.json").exists()      # Daten uebernommen
    assert not legacy.exists()                # alter Ordner umbenannt


def test_config_dir_accepts_legacy_env(tmp_path, monkeypatch):
    monkeypatch.delenv("DOC2VAULT_HOME", raising=False)
    monkeypatch.setenv("DOCLING_VAULT_HOME", str(tmp_path / "alt"))
    assert jm.config_dir() == tmp_path / "alt"


def test_remove_job_cleans_all_state(job_env):
    src, target, job = job_env
    jm.run_job(job, convert_batch=_fake_batch_factory([]))
    assert jm._manifest_file(job.id).exists()
    assert jm._history_file(job.id).exists()

    assert jm.remove_job(job.id)
    assert jm.get_job(job.id) is None
    assert not jm._manifest_file(job.id).exists()
    assert not jm._history_file(job.id).exists()


def test_update_job_keeps_manifest(jobs_home, tmp_path):
    """Engine-Wechsel per update_job/set: Manifest bleibt, nichts wird neu
    konvertiert (realer Fall: Tesseract gewaehlt, aber nicht installiert)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.pdf").write_text("x")
    job = jm.add_job("Wechsel", str(src), str(tmp_path / "vault"),
                     dw.ConverterConfig(do_ocr=True, ocr_engine="tesseract"))

    # Mit fehlendem Tesseract verweigert run_job den Lauf mit klarem Hinweis
    # (statt jede Datei einzeln scheitern zu lassen).
    if dw.shutil.which("tesseract") is None:
        with pytest.raises(RuntimeError, match="Tesseract"):
            jm.run_job(job, convert_batch=_fake_batch_factory([]))

    # Engine wechseln -- der typische Reparaturfall.
    updated = jm.update_job(job.id, config_updates={"ocr_engine": "easyocr"})
    assert updated.converter_config().ocr_engine == "easyocr"
    assert updated.converter_config().do_ocr is True          # unangetastet

    # Jetzt laeuft der Job; das Manifest gehoert weiterhin zum selben Job.
    jm.run_job(jm.get_job(job.id), convert_batch=_fake_batch_factory([]))
    manifest_before = jm.load_manifest(job.id)
    assert manifest_before

    # Weitere Aenderung per CLI: Manifest bleibt unangetastet.
    assert jm._run_cli(["set", job.id, "--ocr-langs", "de,en,fr"]) == 0
    assert jm.get_job(job.id).converter_config().ocr_languages == "de,en,fr"
    assert jm.load_manifest(job.id) == manifest_before        # kein Verlust
    # Unbekannte Felder werden abgewiesen.
    with pytest.raises(ValueError):
        jm.update_job(job.id, config_updates={"gibtsnicht": 1})
    # Unbekannter Job.
    assert jm.update_job("nope", config_updates={"do_ocr": False}) is None


def test_scan_changes_skips_duplicates(jobs_home, tmp_path):
    """skip_duplicates: inhaltsgleiche NEUE Dateien landen in duplicates,
    nicht im todo -- unveraenderte Dateien (Idempotenz) bleiben unberuehrt."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"inhalt eins")
    job = jm.add_job("Dup", str(src), str(tmp_path / "vault"))
    jm.update_job(job.id, skip_duplicates=True)
    job = jm.get_job(job.id)
    assert job.skip_duplicates is True

    # Erster Lauf konvertiert a.pdf (Hash landet im Manifest).
    jm.run_job(job, convert_batch=_fake_batch_factory([]))

    # Kopie mit gleichem Inhalt + echte neue Datei + Kopie der neuen Datei.
    (src / "a_kopie.pdf").write_bytes(b"inhalt eins")
    (src / "b.pdf").write_bytes(b"inhalt zwei")
    (src / "b_kopie.pdf").write_bytes(b"inhalt zwei")

    cs = jm.scan_changes(job)
    assert sorted(Path(p).name for p in cs.duplicates) == [
        "a_kopie.pdf", "b_kopie.pdf"
    ]
    assert [Path(p).name for p in cs.new] == ["b.pdf"]
    assert cs.counts()["duplikate"] == 2
    # Ohne skip_duplicates: alles normal neu.
    jm.update_job(job.id, skip_duplicates=False)
    cs2 = jm.scan_changes(jm.get_job(job.id))
    assert len(cs2.new) == 3 and not cs2.duplicates
