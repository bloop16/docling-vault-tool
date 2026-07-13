"""Streamlit-Dashboard fuer die Docling-Batch-Konvertierung.

Visuelle Kontrolle statt CLI-only: Fortschrittsbalken, ETA, Erfolg-/Fehler-
Zaehler und ein herunterladbares Fehlerprotokoll. Die eigentliche
Konvertierungslogik liegt in ``docling_worker.py`` und wird hier nur
orchestriert.

Start::

    streamlit run app_streamlit.py
"""

from __future__ import annotations

import io
import csv
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import streamlit as st

import docling_worker as dw

st.set_page_config(page_title="Docling Vault Tool", page_icon="📄", layout="wide")

st.title("📄 Docling Vault Tool")
st.caption(
    "Batch-Konvertierung von PDF/DOCX/XLSX/PPTX nach strukturiertem Markdown "
    "fuer einen Obsidian-Vault (Vorstufe zum RAG-Setup)."
)


def _format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _errors_to_csv(results: list) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["datei", "kategorie", "hinweis", "fehler", "pfad", "traceback", "dauer_s"]
    )
    for r in results:
        writer.writerow(
            [
                Path(r.source_path).name,
                r.error_category or "",
                r.error_hint or "",
                r.error or "",
                r.source_path,
                (r.error_detail or "").replace("\r\n", "\n"),
                f"{r.duration_s:.2f}",
            ]
        )
    return buf.getvalue().encode("utf-8")


def _file_uri(path: str) -> str:
    """file://-URI zum direkten Oeffnen/Anspringen im Ursprungsordner."""
    try:
        return Path(path).resolve().as_uri()
    except Exception:  # noqa: BLE001 -- z. B. relativer/ungueltiger Pfad
        return ""


# --- Konfiguration ---------------------------------------------------------
with st.sidebar:
    st.header("Konfiguration")
    input_dir = st.text_input(
        "Quellordner",
        value=st.session_state.get("input_dir", ""),
        help="Ordner mit den PDF/DOCX/XLSX-Dateien (wird rekursiv durchsucht).",
    )
    output_dir = st.text_input(
        "Ziel-Vault-Ordner",
        value=st.session_state.get("output_dir", ""),
        help="Zielordner fuer die Markdown-Dateien (Obsidian-Vault).",
    )
    cpu_count = os.cpu_count() or 2
    max_workers = st.slider(
        "Parallele Prozesse",
        min_value=1,
        max_value=cpu_count,
        value=max(1, cpu_count - 1),
        help="Docling ist CPU- und speicherlastig. Bei knappem RAM reduzieren.",
    )
    do_ocr = st.checkbox(
        "OCR aktivieren",
        value=False,
        help="Nur fuer gescannte PDFs ohne Textlayer. Deutlich langsamer.",
    )
    st.divider()
    st.subheader("Nach erfolgreicher Konvertierung")
    on_success_label = st.radio(
        "Mit Originaldatei:",
        options=["Behalten", "Ins Archiv verschieben", "Löschen"],
        index=0,
        help="Nur erfolgreich konvertierte Originale sind betroffen. "
        "Fehlgeschlagene Dateien bleiben immer unangetastet.",
    )
    on_success = {
        "Behalten": "keep",
        "Ins Archiv verschieben": "archive",
        "Löschen": "delete",
    }[on_success_label]
    archive_dir = ""
    if on_success == "archive":
        archive_dir = st.text_input(
            "Archiv-Ordner",
            value=st.session_state.get("archive_dir", ""),
            help="Struktur des Quellordners wird hier gespiegelt.",
        )
        st.session_state["archive_dir"] = archive_dir
    elif on_success == "delete":
        st.warning("⚠️ Originale werden nach Erfolg unwiderruflich gelöscht.")
    st.divider()
    st.caption(
        "Unterstuetzte Formate: "
        + ", ".join(sorted(e.lstrip(".") for e in dw.SUPPORTED_EXTENSIONS))
    )

# Eingaben fuer den naechsten Rerun merken.
st.session_state["input_dir"] = input_dir
st.session_state["output_dir"] = output_dir

# --- Vorschau / Scan -------------------------------------------------------
col_scan, col_start = st.columns([1, 1])
scan = col_scan.button("🔍 Dateien scannen", use_container_width=True)
start = col_start.button(
    "🚀 Konvertierung starten", type="primary", use_container_width=True
)

if scan:
    if not input_dir or not Path(input_dir).is_dir():
        st.error("Bitte einen gueltigen Quellordner angeben.")
    else:
        files = dw.discover_files(input_dir)
        st.session_state["scanned_files"] = [str(f) for f in files]
        st.success(f"{len(files)} unterstuetzte Datei(en) gefunden.")

if st.session_state.get("scanned_files"):
    st.info(f"Zuletzt gescannt: {len(st.session_state['scanned_files'])} Datei(en).")

# --- Konvertierung ---------------------------------------------------------
if start:
    if not input_dir or not Path(input_dir).is_dir():
        st.error("Bitte einen gueltigen Quellordner angeben.")
        st.stop()
    if not output_dir:
        st.error("Bitte einen Ziel-Vault-Ordner angeben.")
        st.stop()
    if on_success == "archive" and not archive_dir:
        st.error("Für 'Ins Archiv verschieben' bitte einen Archiv-Ordner angeben.")
        st.stop()

    input_root = Path(input_dir).resolve()
    out_root = Path(output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    files = dw.discover_files(input_root)
    total = len(files)
    if total == 0:
        st.warning("Keine unterstuetzten Dateien gefunden.")
        st.stop()

    config = dw.ConverterConfig(
        do_ocr=do_ocr,
        on_success=on_success,
        archive_dir=str(Path(archive_dir).resolve()) if archive_dir else None,
    )

    st.subheader("Fortschritt")
    progress = st.progress(0.0)
    m1, m2, m3, m4 = st.columns(4)
    ph_done = m1.empty()
    ph_ok = m2.empty()
    ph_fail = m3.empty()
    ph_eta = m4.empty()
    ph_current = st.empty()

    ok = 0
    moved = 0
    failures: list = []
    start_time = time.perf_counter()

    with ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=dw.init_worker,
        initargs=(config, str(out_root), str(input_root)),
    ) as pool:
        futures = {pool.submit(dw.convert_file_task, str(f)): f for f in files}
        for done, future in enumerate(as_completed(futures), start=1):
            try:
                res = future.result()
            except Exception as exc:  # noqa: BLE001
                res = dw.ConversionResult(
                    source_path="<unbekannt>",
                    success=False,
                    error=f"Pool-Fehler: {exc}",
                )
            if res.success:
                ok += 1
                if res.moved_to:
                    moved += 1
            else:
                failures.append(res)

            elapsed = time.perf_counter() - start_time
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate if rate else 0

            progress.progress(done / total)
            ph_done.metric("Verarbeitet", f"{done}/{total}")
            ph_ok.metric("Erfolgreich", ok)
            ph_fail.metric("Fehler", len(failures))
            ph_eta.metric("ETA", _format_duration(eta))
            ph_current.caption(f"Zuletzt: {Path(res.source_path).name}")

    total_time = time.perf_counter() - start_time
    st.success(
        f"Fertig in {_format_duration(total_time)}: "
        f"{ok} erfolgreich, {len(failures)} fehlgeschlagen."
    )
    if moved:
        verb = "gelöscht" if on_success == "delete" else "ins Archiv verschoben"
        st.info(f"{moved} Originaldatei(en) {verb}.")

    if failures:
        st.subheader("⚠️ Fehlerprotokoll")

        # Kurzueberblick: Anzahl je Fehlerkategorie.
        cat_counts: dict[str, int] = {}
        for r in failures:
            cat = r.error_category or "fehler"
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        st.caption(
            "Kategorien: "
            + " · ".join(
                f"{cat} ({n})"
                for cat, n in sorted(cat_counts.items(), key=lambda kv: -kv[1])
            )
        )

        # Tabelle mit klickbarem Quellenlink (Datei + Ordner im Original).
        rows = []
        for r in failures:
            p = Path(r.source_path)
            rows.append(
                {
                    "Datei": p.name,
                    "Kategorie": r.error_category or "fehler",
                    "Hinweis": r.error_hint or "",
                    "Fehler": r.error or "",
                    "Datei öffnen": _file_uri(str(p)),
                    "Ordner öffnen": _file_uri(str(p.parent)),
                    "Pfad": str(p),
                }
            )
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Datei öffnen": st.column_config.LinkColumn(
                    "Datei öffnen", display_text="📄 öffnen"
                ),
                "Ordner öffnen": st.column_config.LinkColumn(
                    "Ordner öffnen", display_text="📂 Ordner"
                ),
            },
        )
        st.caption(
            "Hinweis: Manche Browser blockieren `file://`-Links aus Sicherheits"
            "gründen. Dann den Pfad aus der Spalte *Pfad* kopieren."
        )

        # Echte Ursache pro Datei: voller Traceback zum Aufklappen.
        st.markdown("**Was ist wirklich passiert? (Details je Datei)**")
        for r in failures:
            p = Path(r.source_path)
            with st.expander(f"{p.name} — {r.error or 'Fehler'}"):
                st.write(f"**Kategorie:** {r.error_category or 'fehler'}")
                if r.error_hint:
                    st.write(f"**Hinweis:** {r.error_hint}")
                st.write(f"**Original:** `{p}`")
                uri = _file_uri(str(p))
                if uri:
                    st.markdown(f"[📄 Datei öffnen]({uri}) · [📂 Ordner öffnen]({_file_uri(str(p.parent))})")
                st.code(r.error_detail or r.error or "", language="text")

        st.download_button(
            "⬇️ Fehlerprotokoll (CSV) herunterladen",
            data=_errors_to_csv(failures),
            file_name="docling_fehler.csv",
            mime="text/csv",
        )
