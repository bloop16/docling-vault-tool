"""Tests fuer docling_worker: Discovery, Ablage, Frontmatter, Fehlerpfad."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import docling_worker as dw


def test_discover_files_filters(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.pdf").write_text("x")
    (tmp_path / "sub" / "b.docx").write_text("x")
    (tmp_path / "sub" / "~$b.docx").write_text("x")   # Office-Lockfile
    (tmp_path / "notiz.txt").write_text("x")           # nicht unterstuetzt
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "c.pdf").write_text("x")   # versteckter Ordner

    names = [f.name for f in dw.discover_files(tmp_path)]
    assert names == ["a.pdf", "b.docx"]


def test_discover_files_excludes_target_inside_source(tmp_path):
    """Liegt der Vault in der Quelle, duerfen erzeugte .md nicht Quelle werden."""
    src = tmp_path
    vault = tmp_path / "vault"
    vault.mkdir()
    (src / "a.pdf").write_text("x")
    (vault / "erzeugt.md").write_text("x")

    found = dw.discover_files(src, exclude_dirs=(vault, None, ""))
    assert [f.name for f in found] == ["a.pdf"]


def test_asset_key_collision_free():
    assert dw._asset_key(Path("berichte/2024/q1.pdf")) == "berichte__2024__q1"
    assert dw._asset_key(Path("q1.pdf")) == "q1"


def test_frontmatter_quoting():
    fm = dw._yaml_frontmatter(
        {"source": "a:b.pdf", "original_path": r"C:\x\a.pdf",
         "leer": None, "n": 3, "b": True}
    )
    assert fm.startswith("---\n") and fm.rstrip().endswith("---")
    assert '"a:b.pdf"' in fm
    assert "C:\\\\x\\\\a.pdf" in fm
    assert "leer" not in fm
    assert "n: 3" in fm and "b: true" in fm


def test_convert_mirrors_structure_and_relativizes_links(tmp_path, fake_converter):
    src_root = tmp_path / "in"
    out = tmp_path / "vault"
    (src_root / "sub").mkdir(parents=True)
    src = src_root / "sub" / "doc.pdf"
    src.write_text("x")

    res = dw.convert_single_file(src, out, input_root=src_root,
                                 converter=fake_converter)
    assert res.success, res.error
    md = out / "sub" / "doc.md"
    assert md.exists()
    body = md.read_text(encoding="utf-8")
    assert body.startswith("---\n")
    # Bildlink muss relativ zur Notiz sein, nicht absolut.
    assert "](../assets/sub__doc/img_0.png)" in body
    assert str(out) not in body.split("---", 2)[2]
    assert (out / "assets" / "sub__doc" / "img_0.png").exists()
    assert res.num_images == 1


def test_convert_plan_variants(tmp_path, fake_converter):
    src_root = tmp_path / "in"
    out = tmp_path / "vault"
    (src_root / "a" / "b").mkdir(parents=True)
    src = src_root / "a" / "b" / "doc.pdf"
    src.write_text("x")

    cfg = dw.ConverterConfig(
        notes_subdir="Import", attachments_mode="adjacent",
        add_frontmatter=False, mirror_structure=False,
    )
    res = dw.convert_single_file(src, out, input_root=src_root,
                                 config=cfg, converter=fake_converter)
    assert res.success
    md = out / "Import" / "doc.md"
    assert md.exists()
    assert not md.read_text(encoding="utf-8").startswith("---")
    assert (out / "Import" / "doc_assets" / "img_0.png").exists()


def test_error_classification():
    cat, hint = dw._classify_error("PdfError: file is encrypted with a password")
    assert cat == "passwortgeschützt" and hint
    assert dw._classify_error("EOF marker not found, corrupt")[0] == "beschädigt"
    assert dw._classify_error("MemoryError: cannot allocate")[0] == "speicher"
    assert dw._classify_error("voellig unerwartet")[0] == "fehler"


def test_error_classification_windows_first_run():
    """Die realen Fehlerbilder aus dem Windows-Erstlauf werden erkannt."""
    # OneDrive-Platzhalter ("Dateien bei Bedarf"): unvollstaendig gelesen.
    cat, hint = dw._classify_error(
        "RuntimeError: unexpected EOF, expected 39926 more bytes. "
        "The file might be corrupted."
    )
    assert cat == "cloud-platzhalter"
    assert "OneDrive" in hint

    # Kaputte RapidOCR-Modelldateien (Download von modelscope.cn blockiert).
    assert dw._classify_error(
        "RuntimeError: storage has wrong byte size: expected 100 got 5"
    )[0] == "ocr-modelle"
    assert dw._classify_error(
        "UnpicklingError: pickle data was truncated"
    )[0] == "ocr-modelle"
    assert dw._classify_error(
        "[RapidOCR] Download failed: https://www.modelscope.cn/..."
    )[0] == "ocr-modelle"

    # Harte Worker-Abstuerze.
    assert dw._classify_error("std::bad_alloc")[0] == "speicher"
    assert dw._classify_error(
        "A process in the process pool was terminated abruptly"
    )[0] == "prozessabsturz"


def test_ocr_engine_config_plumbing():
    """Engine/Sprachen sind konfigurierbar; unbekannte Engine bricht sauber ab."""
    cfg = dw.ConverterConfig()
    assert cfg.ocr_engine == "easyocr"        # Standard: keine modelscope-Modelle
    assert cfg.ocr_languages == "de,en"

    with pytest.raises(ValueError):
        dw._make_ocr_options("quatsch", "de")


def test_unreadable_source_is_classified(tmp_path, fake_converter):
    """Der Hydrations-Read faengt unlesbare Quellen sauber ab."""
    fake_dir_as_file = tmp_path / "kaputt.pdf"
    fake_dir_as_file.mkdir()          # Verzeichnis statt Datei -> Lesefehler
    res = dw.convert_single_file(fake_dir_as_file, tmp_path / "out",
                                 input_root=tmp_path, converter=fake_converter)
    assert not res.success
    assert res.error_category         # klassifiziert, kein Absturz


def test_failure_result_fields(tmp_path, boom_converter):
    (tmp_path / "x.pdf").write_text("inhalt")
    res = dw.convert_single_file(tmp_path / "x.pdf", tmp_path / "out",
                                 input_root=tmp_path, converter=boom_converter)
    assert not res.success
    assert res.error and "kaputt" in res.error
    assert res.error_category
    assert res.error_detail and "RuntimeError" in res.error_detail


def test_post_action_archive_and_delete(tmp_path, fake_converter, boom_converter):
    src_root = tmp_path / "in"
    (src_root / "sub").mkdir(parents=True)
    out = tmp_path / "vault"
    arch = tmp_path / "archiv"

    src = src_root / "sub" / "doc.pdf"
    src.write_text("x")
    cfg = dw.ConverterConfig(on_success="archive", archive_dir=str(arch))
    res = dw.convert_single_file(src, out, input_root=src_root,
                                 config=cfg, converter=fake_converter)
    assert res.success and res.moved_to
    assert not src.exists()
    assert (arch / "sub" / "doc.pdf").exists()

    src2 = src_root / "weg.pdf"
    src2.write_text("x")
    cfg2 = dw.ConverterConfig(on_success="delete")
    res2 = dw.convert_single_file(src2, out, input_root=src_root,
                                  config=cfg2, converter=fake_converter)
    assert res2.success and res2.moved_to == "<geloescht>"
    assert not src2.exists()

    # Fehlgeschlagene Dateien bleiben immer erhalten.
    src3 = src_root / "bleibt.pdf"
    src3.write_text("x")
    res3 = dw.convert_single_file(src3, out, input_root=src_root,
                                  config=cfg2, converter=boom_converter)
    assert not res3.success
    assert src3.exists()


# --- Riesenseiten-Erkennung (std::bad_alloc-Praevention) --------------------

def _write_pdf(path, width, height):
    """Minimal gueltige Einseiten-PDF mit gegebener MediaBox (inkl. xref)."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] >>".encode(),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 4\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n"
            + str(xref_pos).encode() + b"\n%%EOF\n")
    path.write_bytes(bytes(out))


def test_has_huge_pages_detection(tmp_path):
    pytest.importorskip("pypdfium2")
    a0 = tmp_path / "cad_a0.pdf"          # A0 quer: 3370x2384 pt
    _write_pdf(a0, 3370, 2384)
    a4 = tmp_path / "brief_a4.pdf"        # A4 hoch: 595x842 pt
    _write_pdf(a4, 595, 842)

    assert dw.has_huge_pages(a0) is True
    assert dw.has_huge_pages(a4) is False
    # Kaputte/fehlende Dateien duerfen die Erkennung nicht sprengen.
    assert dw.has_huge_pages(tmp_path / "gibtsnicht.pdf") is False


def test_reduced_config_keeps_other_settings():
    cfg = dw.ConverterConfig(do_ocr=True, ocr_engine="tesseract",
                             images_scale=2.0, generate_picture_images=True)
    red = dw._reduced_config(cfg)
    assert red.images_scale == 1.0
    assert red.generate_picture_images is False
    assert red.do_ocr is True and red.ocr_engine == "tesseract"
    assert not dw._is_reduced(cfg)
    assert dw._is_reduced(red)


def test_streamlit_bare_mode_warning_muted():
    """Die 'missing ScriptRunContext'-Logger sind stummgeschaltet (Windows-
    Spawn-Worker wuerden die Warnung sonst pro Prozess ins Log schreiben)."""
    import logging

    dw._mute_streamlit_bare_mode_warning()
    for name in (
        "streamlit.runtime.scriptrunner_utils.script_run_context",
        "streamlit.runtime.scriptrunner.script_run_context",
    ):
        logger = logging.getLogger(name)
        assert not logger.isEnabledFor(logging.WARNING)


# --- OCR-Engine-Vorabpruefung & Fehlerklassifizierung (Realtest-Lauf 2) -----

def test_check_ocr_engine(monkeypatch):
    cfg = dw.ConverterConfig(do_ocr=True, ocr_engine="tesseract")
    monkeypatch.setattr(dw.shutil, "which", lambda name: None)
    warning = dw.check_ocr_engine(cfg)
    assert warning and "Tesseract" in warning
    monkeypatch.setattr(dw.shutil, "which", lambda name: r"C:\tesseract.exe")
    assert dw.check_ocr_engine(cfg) is None
    # Ohne OCR bzw. mit EasyOCR gibt es nichts vorab zu pruefen.
    assert dw.check_ocr_engine(dw.ConverterConfig(
        do_ocr=False, ocr_engine="tesseract")) is None
    assert dw.check_ocr_engine(dw.ConverterConfig(
        do_ocr=True, ocr_engine="easyocr")) is None


def test_error_classification_second_real_run():
    """Fehlerbilder aus dem zweiten Windows-Reallauf (3030er-CSV)."""
    cat, hint = dw._classify_error(
        "RuntimeError: Tesseract is not available, aborting: [WinError 2] "
        "Das System kann die angegebene Datei nicht finden Install tesseract"
    )
    assert cat == "ocr-engine"
    assert "EasyOCR" in hint

    cat, hint = dw._classify_error(
        "ConversionError: Conversion failed for: C:\\pfad\\datei.pdf"
    )
    assert cat == "pdf-parser"
    assert "pypdfium" in hint

    cat, _ = dw._classify_error("Inconsistent number of pages: 16!=-1")
    assert cat == "pdf-parser"


def test_pdfium_fallback_rescues_refused_pdf(tmp_path, monkeypatch, fake_converter):
    """docling-parse lehnt ab -> automatischer zweiter Versuch mit pypdfium."""
    src_root = tmp_path / "in"
    src_root.mkdir()
    out = tmp_path / "vault"
    src = src_root / "abgelehnt.pdf"
    src.write_text("x")

    class _RefusingConverter:
        def convert(self, source):
            raise RuntimeError(f"Conversion failed for: {source}")

    def _fake_build(config=None, pdf_backend=None):
        return fake_converter if pdf_backend == "pypdfium" else _RefusingConverter()

    monkeypatch.setattr(dw, "build_converter", _fake_build)
    dw.init_worker(dw.ConverterConfig(), str(out), str(src_root))

    res = dw.convert_file_task(str(src))
    assert res.success
    assert res.pdf_backend == "pypdfium"

    # Nicht-Parser-Fehler loesen KEINEN pypdfium-Versuch aus.
    class _OtherErrorConverter:
        def convert(self, source):
            raise RuntimeError("kaputt")

    def _fake_build_other(config=None, pdf_backend=None):
        assert pdf_backend is None, "unerwarteter pypdfium-Fallback"
        return _OtherErrorConverter()

    monkeypatch.setattr(dw, "build_converter", _fake_build_other)
    dw.init_worker(dw.ConverterConfig(), str(out), str(src_root))
    res2 = dw.convert_file_task(str(src))
    assert not res2.success
    assert res2.pdf_backend is None


def test_check_paths_overlap(tmp_path):
    """Quelle==Ziel bzw. Quelle im Ziel muss als klarer Fehler erscheinen
    (real passiert: '0 unterstuetzte Dateien' ohne Erklaerung)."""
    src = tmp_path / "daten"
    src.mkdir()
    # Identisch: haerteste Falle (Ziel wird beim Scan ausgeschlossen -> 0).
    msg = dw.check_paths(src, src)
    assert msg and "identisch" in msg
    # Quelle innerhalb des Ziels: ebenfalls alles ausgeschlossen.
    msg = dw.check_paths(src, tmp_path)
    assert msg and "innerhalb" in msg
    # Ziel als Unterordner der Quelle: erlaubt (nur Teilbereich ausgeschlossen).
    assert dw.check_paths(src, src / "vault") is None
    # Getrennte Ordner: erlaubt.
    assert dw.check_paths(src, tmp_path / "woanders") is None
    # Leere Angaben: keine Aussage.
    assert dw.check_paths(None, src) is None
    assert dw.check_paths(src, "") is None
