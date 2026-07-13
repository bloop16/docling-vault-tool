"""Tests fuer den XLSX-Sonderfall (Sheet-Limit, Ueberspringen, Trimmen)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import docling_worker as dw

_WORKBOOK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheets>{sheets}</sheets>
</workbook>"""


def _fake_xlsx(path: Path, sheet_names: list[str]) -> Path:
    """Minimales XLSX (nur workbook.xml) -- reicht fuer die Blatt-Zaehlung."""
    sheets = "".join(
        f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
        for i, n in enumerate(sheet_names, start=1)
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", _WORKBOOK_XML.format(sheets=sheets))
    return path


def _real_xlsx(path: Path, sheet_names: list[str]) -> Path:
    """Echte Arbeitsmappe via openpyxl (fuer den Trim-Pfad)."""
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.title = sheet_names[0]
    for name in sheet_names[1:]:
        workbook.create_sheet(name)
    workbook.save(path)
    return path


def test_xlsx_sheet_names(tmp_path):
    f = _fake_xlsx(tmp_path / "mappe.xlsx", ["Umsatz", "Kosten", "Plan"])
    assert dw.xlsx_sheet_names(f) == ["Umsatz", "Kosten", "Plan"]


def test_xlsx_sheet_names_broken_file(tmp_path):
    broken = tmp_path / "kaputt.xlsx"
    broken.write_text("kein zip")
    assert dw.xlsx_sheet_names(broken) == []


def test_xlsx_skip_over_limit(tmp_path, fake_converter):
    src_root = tmp_path / "in"
    src_root.mkdir()
    f = _fake_xlsx(src_root / "gross.xlsx", [f"Blatt{i}" for i in range(5)])

    cfg = dw.ConverterConfig(xlsx_sheet_limit=2, xlsx_on_limit="skip")
    res = dw.convert_single_file(f, tmp_path / "out", input_root=src_root,
                                 config=cfg, converter=fake_converter)
    assert not res.success
    assert res.error_category == "zu viele sheets"
    assert "5 Blätter" in res.error
    assert f.exists()                       # Original bleibt unangetastet
    assert not (tmp_path / "out" / "gross.md").exists()


def test_xlsx_under_limit_converts_normally(tmp_path, fake_converter):
    src_root = tmp_path / "in"
    src_root.mkdir()
    f = _fake_xlsx(src_root / "klein.xlsx", ["A", "B"])

    cfg = dw.ConverterConfig(xlsx_sheet_limit=5, xlsx_on_limit="skip")
    res = dw.convert_single_file(f, tmp_path / "out", input_root=src_root,
                                 config=cfg, converter=fake_converter)
    assert res.success
    body = Path(res.output_path).read_text(encoding="utf-8")
    assert "sheets_total" not in body       # kein Vermerk noetig


def test_xlsx_limit_trims_workbook(tmp_path):
    pytest.importorskip("openpyxl")
    src_root = tmp_path / "in"
    src_root.mkdir()
    f = _real_xlsx(src_root / "mappe.xlsx", ["Q1", "Q2", "Q3", "Q4"])

    seen: dict = {}

    class RecordingConverter:
        """Haelt fest, welche Datei/Blaetter Docling tatsaechlich erhaelt."""

        def convert(self, source):
            seen["input"] = str(source)
            seen["sheets"] = dw.xlsx_sheet_names(source)

            class Doc:
                def save_as_markdown(self, filename, artifacts_dir=None,
                                     image_mode=None):
                    Path(filename).write_text("# Mappe\n", encoding="utf-8")

            return type("Result", (), {"document": Doc()})()

    cfg = dw.ConverterConfig(xlsx_sheet_limit=2, xlsx_on_limit="limit")
    res = dw.convert_single_file(f, tmp_path / "out", input_root=src_root,
                                 config=cfg, converter=RecordingConverter())
    assert res.success, res.error
    assert seen["sheets"] == ["Q1", "Q2"]          # nur die ersten 2 Blaetter
    assert seen["input"] != str(f)                  # getrimmte Kopie, nicht das Original
    assert not Path(seen["input"]).exists()         # Temp-Datei aufgeraeumt
    assert dw.xlsx_sheet_names(f) == ["Q1", "Q2", "Q3", "Q4"]  # Original intakt

    body = Path(res.output_path).read_text(encoding="utf-8")
    assert "sheets_total: 4" in body
    assert "sheets_converted: 2" in body
