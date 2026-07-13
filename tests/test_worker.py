"""Tests fuer docling_worker: Discovery, Ablage, Frontmatter, Fehlerpfad."""

from __future__ import annotations

import time
from pathlib import Path

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


def test_failure_result_fields(tmp_path, boom_converter):
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
