"""Tests fuer file_transfer: ZIP-Roundtrip, Zip-Slip-Schutz, Upload-Ablage."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

import file_transfer as ft


def _make_tree(root: Path) -> None:
    (root / "sub").mkdir(parents=True)
    (root / "a.md").write_text("Notiz A", encoding="utf-8")
    (root / "sub" / "b.md").write_text("Notiz B", encoding="utf-8")
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "app.json").write_text("{}")
    (root / ".versteckt.md").write_text("x")


def test_zip_roundtrip(tmp_path):
    src = tmp_path / "vault"
    _make_tree(src)

    archive = ft.zip_folder(src, tmp_path / "out" / "vault.zip")
    assert archive.exists()

    dest = tmp_path / "wieder"
    extracted = ft.safe_extract_zip(archive, dest)
    names = sorted(p.relative_to(dest).as_posix() for p in extracted)
    assert names == ["a.md", "sub/b.md"]           # versteckte Eintraege fehlen
    assert (dest / "sub" / "b.md").read_text(encoding="utf-8") == "Notiz B"


def test_zip_slip_is_rejected(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("harmlos.txt", "ok")
        zf.writestr("../ausbruch.txt", "boese")

    dest = tmp_path / "ziel"
    with pytest.raises(ft.UnsafeZipError):
        ft.safe_extract_zip(evil, dest)
    # Validierung passiert VOR dem Schreiben: auch der harmlose Eintrag
    # darf nicht angelegt worden sein.
    assert not (dest / "harmlos.txt").exists()
    assert not (tmp_path / "ausbruch.txt").exists()


def test_zip_absolute_path_rejected(tmp_path):
    evil = tmp_path / "abs.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        info = zipfile.ZipInfo("/etc/boese.txt")
        zf.writestr(info, "x")

    # Fuehrende Slashes werden entfernt -> landet sicher IM Zielordner.
    dest = tmp_path / "ziel"
    extracted = ft.safe_extract_zip(evil, dest)
    assert [p.relative_to(dest).as_posix() for p in extracted] == ["etc/boese.txt"]


def test_store_uploads_mixed(tmp_path):
    inner = tmp_path / "quelle"
    inner.mkdir()
    (inner / "doc.pdf").write_bytes(b"pdf")
    archive_path = ft.zip_folder(inner, tmp_path / "batch.zip")

    uploads = [
        ("einzeln.docx", io.BytesIO(b"docx-inhalt")),
        ("batch.zip", open(archive_path, "rb")),
        ("C:\\pfad\\getarnt.pdf", io.BytesIO(b"x")),   # Pfadanteile entfernen
    ]
    try:
        stored = ft.store_uploads(uploads, tmp_path / "eingang")
    finally:
        uploads[1][1].close()

    names = sorted(p.name for p in stored)
    assert names == ["doc.pdf", "einzeln.docx", "getarnt.pdf"]
    assert (tmp_path / "eingang" / "einzeln.docx").read_bytes() == b"docx-inhalt"
    assert (tmp_path / "eingang" / "doc.pdf").exists()      # aus dem ZIP
    assert (tmp_path / "eingang" / "getarnt.pdf").exists()  # ohne C:\pfad\


def test_folder_size_and_format(tmp_path):
    src = tmp_path / "vault"
    _make_tree(src)
    size = ft.folder_size(src)
    # Nur a.md (7 Bytes) + sub/b.md (7 Bytes); versteckte Dateien zaehlen nicht.
    assert size == 14
    assert ft.format_size(14) == "14 B"
    assert ft.format_size(3 * 1024 * 1024) == "3.0 MB"


# --- Funde aus dem Code-Review (claude-skills code-reviewer) ----------------

def test_zip_bomb_limits(tmp_path):
    import io
    import zipfile

    # Hohe Kompressionsrate + grosser Eintrag -> abgelehnt.
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("null.bin", b"\x00" * (20 * 1024 * 1024))
    bomb.seek(0)
    with pytest.raises(ft.UnsafeZipError):
        ft.safe_extract_zip(bomb, tmp_path / "out")

    # Normale Archive bleiben erlaubt.
    ok = io.BytesIO()
    with zipfile.ZipFile(ok, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.txt", "Inhalt " * 100)
    ok.seek(0)
    out = ft.safe_extract_zip(ok, tmp_path / "out2")
    assert len(out) == 1


def test_upload_name_collision_is_suffixed(tmp_path):
    import io

    stored = ft.store_uploads(
        [("2024/rechnung.pdf", io.BytesIO(b"alt")),
         ("2025/rechnung.pdf", io.BytesIO(b"neu"))],
        tmp_path,
    )
    assert len(stored) == 2
    assert len({p.name for p in stored}) == 2       # kein Ueberschreiben
    contents = sorted(p.read_bytes() for p in stored)
    assert contents == [b"alt", b"neu"]
