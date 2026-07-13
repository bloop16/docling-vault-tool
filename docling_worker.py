"""Docling-basierte Batch-Konvertierung (PDF/DOCX/XLSX/PPTX -> Markdown).

Kernlogik fuer die Umwandlung eines grossen Dokumentenordners in einen
Obsidian-Vault aus strukturierten Markdown-Dateien:

* ``build_converter``      -- baut einen konfigurierten Docling-Converter
* ``discover_files``       -- findet rekursiv alle unterstuetzten Dateien
* ``convert_single_file``  -- konvertiert eine Datei, schreibt .md + Assets
* ``init_worker`` /
  ``convert_file_task``    -- Prozess-Pool-Helfer (ein Converter pro Prozess)

Docling erhaelt die Dokumentstruktur (Ueberschriften, Tabellen) statt reinem
Textbrei und extrahiert eingebettete Bilder als eigene Dateien. Jede erzeugte
``.md``-Datei bekommt YAML-Frontmatter mit ``source``, ``original_path`` und
``assets_folder`` -- Obsidian liest das nativ als Properties.

Das Modul ist bewusst frei von Streamlit-Abhaengigkeiten, damit es sowohl vom
Dashboard (``app_streamlit.py``) als auch direkt per CLI genutzt werden kann::

    python docling_worker.py --input /pfad/zu/quellen --output /pfad/zum/vault
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

# Von Docling nativ unterstuetzte Eingabeformate, die dieses Tool anfasst.
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".html",
    ".htm",
    ".md",
}


@dataclass
class ConverterConfig:
    """Konfiguration fuer den Docling-Converter.

    OCR ist standardmaessig aus (``do_ocr=False``) -- nur fuer gescannte PDFs
    ohne Textlayer gezielt aktivieren, da deutlich langsamer.

    ``on_success`` steuert, was nach erfolgreicher Konvertierung mit der
    Originaldatei passiert: ``"keep"`` (Default, nichts), ``"archive"``
    (nach ``archive_dir`` verschieben, Struktur bleibt erhalten) oder
    ``"delete"`` (Original loeschen -- unwiderruflich).
    """

    do_ocr: bool = False
    generate_picture_images: bool = True
    images_scale: float = 2.0
    do_table_structure: bool = True
    on_success: str = "keep"
    archive_dir: Optional[str] = None


@dataclass
class ConversionResult:
    """Ergebnis einer einzelnen Konvertierung (picklebar fuer den Pool)."""

    source_path: str
    success: bool
    output_path: Optional[str] = None
    assets_folder: Optional[str] = None
    num_images: int = 0
    duration_s: float = 0.0
    # Fehlerinformationen (nur bei success=False gesetzt):
    error: Optional[str] = None           # knappe Zeile: "Typ: Nachricht"
    error_category: Optional[str] = None  # klassifiziert, z. B. "passwortgeschützt"
    error_hint: Optional[str] = None      # Klartext-Handlungshinweis
    error_detail: Optional[str] = None    # voller Traceback (echte Ursache)
    # Nachbearbeitung des Originals (archive/delete):
    moved_to: Optional[str] = None


def build_converter(config: Optional[ConverterConfig] = None):
    """Erzeugt einen konfigurierten Docling ``DocumentConverter``.

    Der Import von Docling passiert bewusst lazy (erst hier), damit das Modul
    auch ohne installiertes Docling importierbar bleibt -- z. B. fuer
    ``discover_files`` oder die Unit-Tests der Pfadlogik.
    """
    if config is None:
        config = ConverterConfig()

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = config.do_ocr
    pipeline_options.do_table_structure = config.do_table_structure
    pipeline_options.generate_picture_images = config.generate_picture_images
    pipeline_options.images_scale = config.images_scale
    if config.do_table_structure:
        # Zellen-Matching verbessert die Tabellenrekonstruktion.
        pipeline_options.table_structure_options.do_cell_matching = True

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )


def discover_files(
    input_dir: os.PathLike | str,
    extensions: Iterable[str] = SUPPORTED_EXTENSIONS,
) -> list[Path]:
    """Findet rekursiv alle unterstuetzten Dateien unterhalb von ``input_dir``.

    Ergebnis ist stabil sortiert (deterministische Reihenfolge/ETA). Versteckte
    Verzeichnisse (``.git`` etc.) und typische temporaere Office-Sperrdateien
    (``~$...``) werden uebersprungen.
    """
    input_path = Path(input_dir)
    exts = {e.lower() for e in extensions}
    files: list[Path] = []
    for path in input_path.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in exts:
            continue
        if path.name.startswith("~$"):
            continue
        if any(part.startswith(".") for part in path.relative_to(input_path).parts[:-1]):
            continue
        files.append(path)
    return sorted(files)


def _asset_key(rel_path: Path) -> str:
    """Kollisionsfreier Ordnername fuer die Assets einer Quelldatei.

    Aus ``berichte/2024/q1.pdf`` wird ``berichte__2024__q1`` -- so kollidieren
    gleichnamige Dateien aus verschiedenen Unterordnern nicht im ``assets/``-
    Verzeichnis.
    """
    stem_rel = rel_path.with_suffix("")
    return "__".join(stem_rel.parts)


def _yaml_frontmatter(fields: dict[str, object]) -> str:
    """Baut einen YAML-Frontmatter-Block. Strings werden JSON-quoted.

    JSON-Doppelquoting liefert einen gueltigen YAML-Skalar und escaped
    Sonderzeichen (Backslashes in Windows-Pfaden, Doppelpunkte, ...) korrekt.
    """
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


# Klassifizierung der haeufigsten Fehlerursachen -> (Kategorie, Klartext-Hinweis).
# Reihenfolge = Prioritaet; erste passende Regel gewinnt. Gematcht wird gegen
# Exceptionklasse + Nachricht + Traceback (kleingeschrieben).
_ERROR_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (
        ("password", "encrypted", "passwort", "verschlüss", "decrypt", "is protected"),
        "passwortgeschützt",
        "Datei ist passwort-/verschluesselungsgeschuetzt — vor der Konvertierung entsperren.",
    ),
    (
        ("no such file", "does not exist", "filenotfound", "permission denied"),
        "nicht lesbar",
        "Datei nicht gefunden oder keine Leserechte.",
    ),
    (
        ("memoryerror", "cannot allocate", "out of memory", "oom", "killed"),
        "speicher",
        "Zu wenig Arbeitsspeicher — Anzahl paralleler Prozesse reduzieren.",
    ),
    (
        ("timeout", "timed out"),
        "timeout",
        "Zeitueberschreitung bei der Verarbeitung — Datei ggf. sehr gross/komplex.",
    ),
    (
        ("unsupported", "no backend", "not supported", "unknown format"),
        "nicht unterstützt",
        "Format/Variante wird von Docling nicht unterstuetzt.",
    ),
    (
        ("corrupt", "damaged", "eof marker", "not a pdf", "invalid", "broken",
         "cannot read", "failed to parse", "malformed", "bad", "truncated",
         "zip file", "not a zip"),
        "beschädigt",
        "Datei ist vermutlich beschaedigt oder kein gueltiges Dokument.",
    ),
]


def _classify_error(text: str) -> tuple[str, str]:
    """Ordnet einen Fehlertext einer Kategorie + Klartext-Hinweis zu."""
    low = text.lower()
    for keywords, category, hint in _ERROR_RULES:
        if any(k in low for k in keywords):
            return category, hint
    return "fehler", "Unerwarteter Fehler — vollstaendige Ursache siehe Details/Traceback."


def _apply_post_action(
    source: Path,
    config: ConverterConfig,
    input_root: Optional[os.PathLike | str],
) -> Optional[str]:
    """Verschiebt/loescht das Original nach erfolgreicher Konvertierung.

    Gibt das Zielverzeichnis (bei ``archive``) bzw. ``"<geloescht>"`` zurueck,
    oder ``None`` wenn nichts getan wurde.
    """
    if config.on_success == "archive" and config.archive_dir:
        try:
            rel = source.relative_to(input_root) if input_root else Path(source.name)
        except ValueError:
            rel = Path(source.name)
        dest = Path(config.archive_dir) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        return str(dest)
    if config.on_success == "delete":
        source.unlink()
        return "<geloescht>"
    return None


def convert_single_file(
    source_path: os.PathLike | str,
    output_dir: os.PathLike | str,
    input_root: Optional[os.PathLike | str] = None,
    config: Optional[ConverterConfig] = None,
    converter=None,
) -> ConversionResult:
    """Konvertiert eine Datei nach Markdown und extrahiert eingebettete Bilder.

    Die Verzeichnisstruktur relativ zu ``input_root`` wird im ``output_dir``
    (dem Vault) gespiegelt. Bilder landen unter ``output_dir/assets/<key>/``.
    Fehler werden abgefangen, klassifiziert und mit vollem Traceback als
    ``ConversionResult(success=False)`` zurueckgegeben -- ein kaputtes Dokument
    bricht den Batch nicht ab.
    """
    if config is None:
        config = ConverterConfig()
    start = time.perf_counter()
    source = Path(source_path)
    out_root = Path(output_dir)

    try:
        rel = source.relative_to(input_root) if input_root else Path(source.name)
    except ValueError:
        # Quelle liegt nicht unter input_root -> flach ablegen.
        rel = Path(source.name)

    md_path = out_root / rel.with_suffix(".md")
    assets_dir = out_root / "assets" / _asset_key(rel)

    try:
        from docling_core.types.doc import ImageRefMode

        if converter is None:
            converter = build_converter(config)

        result = converter.convert(source)
        doc = result.document

        md_path.parent.mkdir(parents=True, exist_ok=True)

        # save_as_markdown schreibt die .md samt referenzierter Bilder in
        # assets_dir und setzt relative Links von der .md dorthin.
        doc.save_as_markdown(
            md_path,
            artifacts_dir=assets_dir,
            image_mode=ImageRefMode.REFERENCED,
        )

        num_images = 0
        assets_rel: Optional[str] = None
        if assets_dir.exists():
            num_images = sum(1 for p in assets_dir.iterdir() if p.is_file())
            if num_images:
                assets_rel = os.path.relpath(assets_dir, out_root).replace(os.sep, "/")

        frontmatter = _yaml_frontmatter(
            {
                "source": source.name,
                "original_path": str(source.resolve()),
                "assets_folder": assets_rel,
                "converted_at": datetime.now(timezone.utc)
                .isoformat(timespec="seconds"),
                "converter": "docling",
            }
        )

        body = md_path.read_text(encoding="utf-8")
        md_path.write_text(frontmatter + body, encoding="utf-8")

        # Original erst NACH erfolgreichem Schreiben archivieren/loeschen.
        moved_to = _apply_post_action(source, config, input_root)

        return ConversionResult(
            source_path=str(source),
            success=True,
            output_path=str(md_path),
            assets_folder=str(assets_dir) if assets_rel else None,
            num_images=num_images,
            duration_s=time.perf_counter() - start,
            moved_to=moved_to,
        )
    except Exception as exc:  # noqa: BLE001 -- Batch soll robust weiterlaufen
        detail = traceback.format_exc()
        concise = f"{type(exc).__name__}: {exc}".strip()
        category, hint = _classify_error(f"{type(exc).__name__} {exc}\n{detail}")
        return ConversionResult(
            source_path=str(source),
            success=False,
            duration_s=time.perf_counter() - start,
            error=concise,
            error_category=category,
            error_hint=hint,
            error_detail=detail.strip(),
        )


# ---------------------------------------------------------------------------
# Prozess-Pool-Helfer
# ---------------------------------------------------------------------------
# Docling ist CPU-lastig, deshalb ProcessPoolExecutor statt Threads (der GIL
# wuerde bei Threads bremsen). Jeder Worker-Prozess baut EINEN Converter beim
# Start (init_worker) und verwendet ihn fuer alle ihm zugewiesenen Dateien --
# der teure Modell-/Pipeline-Aufbau passiert so nur einmal pro Prozess.

_WORKER_CONVERTER = None
_WORKER_CONFIG: Optional[ConverterConfig] = None
_WORKER_OUTPUT: Optional[Path] = None
_WORKER_ROOT: Optional[Path] = None


def init_worker(config: ConverterConfig, output_dir: str, input_root: str) -> None:
    """Initialisiert einen Worker-Prozess (baut den Converter einmalig)."""
    global _WORKER_CONVERTER, _WORKER_CONFIG, _WORKER_OUTPUT, _WORKER_ROOT
    _WORKER_CONFIG = config
    _WORKER_OUTPUT = Path(output_dir)
    _WORKER_ROOT = Path(input_root)
    _WORKER_CONVERTER = build_converter(config)


def convert_file_task(source_path: str) -> ConversionResult:
    """Pool-Task: konvertiert eine Datei mit dem Prozess-lokalen Converter."""
    return convert_single_file(
        source_path,
        _WORKER_OUTPUT,
        input_root=_WORKER_ROOT,
        config=_WORKER_CONFIG,
        converter=_WORKER_CONVERTER,
    )


# ---------------------------------------------------------------------------
# CLI (nackte Nutzung ohne Streamlit)
# ---------------------------------------------------------------------------

def _run_cli(argv: Optional[list[str]] = None) -> int:
    from concurrent.futures import ProcessPoolExecutor, as_completed

    parser = argparse.ArgumentParser(
        description="Docling-Batch-Konvertierung (PDF/DOCX/XLSX -> Markdown)."
    )
    parser.add_argument("--input", "-i", required=True, help="Quellordner")
    parser.add_argument("--output", "-o", required=True, help="Ziel-Vault-Ordner")
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=max(1, (os.cpu_count() or 2) - 1),
        help="Anzahl paralleler Prozesse (Default: CPUs-1)",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="OCR aktivieren (langsam; nur fuer gescannte PDFs)",
    )
    parser.add_argument(
        "--on-success",
        choices=["keep", "archive", "delete"],
        default="keep",
        help="Was mit erfolgreich konvertierten Originalen passiert "
        "(keep=behalten, archive=verschieben, delete=loeschen)",
    )
    parser.add_argument(
        "--archive-dir",
        default=None,
        help="Zielordner fuer --on-success archive",
    )
    parser.add_argument(
        "--error-log",
        default=None,
        help="Optionaler Pfad fuer ein JSON-Fehlerprotokoll",
    )
    args = parser.parse_args(argv)

    input_root = Path(args.input).resolve()
    output_dir = Path(args.output).resolve()
    if not input_root.is_dir():
        parser.error(f"Quellordner existiert nicht: {input_root}")
    if args.on_success == "archive" and not args.archive_dir:
        parser.error("--on-success archive erfordert --archive-dir")
    output_dir.mkdir(parents=True, exist_ok=True)

    config = ConverterConfig(
        do_ocr=args.ocr,
        on_success=args.on_success,
        archive_dir=str(Path(args.archive_dir).resolve()) if args.archive_dir else None,
    )
    files = discover_files(input_root)
    total = len(files)
    if total == 0:
        print(f"Keine unterstuetzten Dateien in {input_root} gefunden.")
        return 0

    print(f"{total} Dateien gefunden. Starte mit {args.workers} Prozess(en)...")
    ok = 0
    failed: list[ConversionResult] = []
    start = time.perf_counter()

    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=init_worker,
        initargs=(config, str(output_dir), str(input_root)),
    ) as pool:
        futures = {
            pool.submit(convert_file_task, str(f)): f for f in files
        }
        for done, future in enumerate(as_completed(futures), start=1):
            res = future.result()
            if res.success:
                ok += 1
            else:
                failed.append(res)
            elapsed = time.perf_counter() - start
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate if rate else 0
            print(
                f"[{done}/{total}] ok={ok} fehler={len(failed)} "
                f"ETA={eta:6.0f}s  {Path(res.source_path).name}",
                flush=True,
            )

    print(f"\nFertig: {ok} erfolgreich, {len(failed)} fehlgeschlagen.")
    if failed:
        by_cat: dict[str, int] = {}
        for r in failed:
            by_cat[r.error_category or "fehler"] = by_cat.get(r.error_category or "fehler", 0) + 1
        print("Fehler nach Kategorie:")
        for cat, count in sorted(by_cat.items(), key=lambda kv: -kv[1]):
            print(f"  {cat}: {count}")
    if failed and args.error_log:
        Path(args.error_log).write_text(
            json.dumps([asdict(r) for r in failed], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Fehlerprotokoll: {args.error_log}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_cli())
