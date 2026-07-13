"""Streamlit-Dashboard fuer die Docling-Batch-Konvertierung.

Modernes, technisches "Vault"-Frontend: visuelle Kontrolle statt CLI-only,
mit Fortschritt, ETA, Erfolg-/Fehler-Zaehler, Quellenlinks und einem
herunterladbaren Fehlerprotokoll. Die eigentliche Konvertierungslogik liegt in
``docling_worker.py`` und wird hier nur orchestriert.

Start::

    streamlit run app_streamlit.py
"""

from __future__ import annotations

import io
import csv
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import streamlit as st

import docling_worker as dw

st.set_page_config(
    page_title="Docling Vault Tool",
    page_icon="🗄️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Optik / Theme
# ---------------------------------------------------------------------------
# Das Design soll auf den ersten Blick zeigen, was das Tool besser kann:
# Struktur statt Textbrei, Bildextraktion, Obsidian-native Properties inkl.
# Rueckverweis zum Original, echte Parallelisierung und transparente Fehler.

ACCENT_1 = "#22d3ee"  # Teal  -> "Struktur"
ACCENT_2 = "#7c8cff"  # Violet -> "Wissen/Vault"

_CSS = """
<style>
:root {
  --v-bg: #0b0f17;
  --v-panel: #121a28;
  --v-panel-2: #0f1622;
  --v-border: rgba(148, 163, 184, 0.16);
  --v-border-strong: rgba(148, 163, 184, 0.28);
  --v-text: #e6edf3;
  --v-muted: #8b98a9;
  --v-accent-1: #22d3ee;
  --v-accent-2: #7c8cff;
  --v-grad: linear-gradient(135deg, #22d3ee 0%, #7c8cff 100%);
}

/* Hintergrund mit dezentem Glow (Wissensgraph-Anmutung) */
.stApp {
  background:
    radial-gradient(900px 420px at 12% -8%, rgba(34, 211, 238, 0.10), transparent 60%),
    radial-gradient(900px 520px at 100% 0%, rgba(124, 140, 255, 0.12), transparent 55%),
    var(--v-bg);
}
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; max-width: 1180px; }

/* ---------------- Hero ---------------- */
.vault-hero {
  position: relative;
  border: 1px solid var(--v-border);
  border-radius: 18px;
  padding: 28px 30px;
  background:
    linear-gradient(180deg, rgba(124,140,255,0.08), rgba(18,26,40,0.4)),
    var(--v-panel);
  overflow: hidden;
}
.vault-hero::after {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(148,163,184,0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148,163,184,0.05) 1px, transparent 1px);
  background-size: 26px 26px;
  mask-image: radial-gradient(600px 200px at 80% 0%, black, transparent 75%);
  pointer-events: none;
}
.vault-badge {
  display: inline-flex; align-items: center; gap: 8px;
  font: 600 11px/1 ui-monospace, "SFMono-Regular", Menlo, monospace;
  letter-spacing: 0.14em; text-transform: uppercase;
  color: #cbd5e1;
  padding: 6px 11px; border-radius: 999px;
  border: 1px solid var(--v-border-strong);
  background: rgba(15, 22, 34, 0.6);
}
.vault-badge .dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--v-grad); box-shadow: 0 0 10px 1px rgba(34,211,238,0.7);
}
.vault-hero h1 {
  margin: 16px 0 6px; font-size: 2.35rem; font-weight: 800; letter-spacing: -0.02em;
  background: linear-gradient(90deg, #e6edf3 0%, #b8c4ff 60%, #7de8ff 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.vault-hero p { margin: 0; color: var(--v-muted); font-size: 1.02rem; max-width: 720px; }
.vault-hero .kicker { color: #d5def0; }

/* ---------------- Feature-Karten ---------------- */
.feature-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px; margin: 16px 0 6px;
}
.feature-card {
  border: 1px solid var(--v-border);
  border-radius: 14px; padding: 15px 16px;
  background: linear-gradient(180deg, rgba(255,255,255,0.02), transparent), var(--v-panel-2);
  transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease;
}
.feature-card:hover {
  transform: translateY(-2px);
  border-color: var(--v-border-strong);
  box-shadow: 0 10px 30px -12px rgba(34,211,238,0.25);
}
.feature-card .ic { font-size: 1.35rem; }
.feature-card .ttl { margin-top: 8px; font-weight: 700; font-size: 0.98rem; color: var(--v-text); }
.feature-card .sub { margin-top: 4px; font-size: 0.82rem; color: var(--v-muted); line-height: 1.35; }

/* ---------------- Pipeline-Visual ---------------- */
.pipeline {
  display: flex; align-items: stretch; gap: 10px; flex-wrap: wrap;
  margin: 10px 0 4px;
}
.pnode {
  flex: 1 1 200px; min-width: 190px;
  border: 1px solid var(--v-border); border-radius: 14px; padding: 14px 16px;
  background: var(--v-panel);
}
.pnode.mid { border-color: rgba(124,140,255,0.45); box-shadow: inset 0 0 0 1px rgba(124,140,255,0.12); }
.pnode .lbl { font: 600 10px/1 ui-monospace, monospace; letter-spacing: .12em; text-transform: uppercase; color: var(--v-muted); }
.pnode .main { margin-top: 8px; font-weight: 700; color: var(--v-text); font-size: 1.02rem; }
.pnode .meta { margin-top: 3px; font-size: 0.8rem; color: var(--v-muted); font-family: ui-monospace, monospace; }
.parrow { display: flex; align-items: center; color: var(--v-accent-1); font-size: 1.3rem; font-weight: 700; }

/* ---------------- Streamlit-Widgets aufhuebschen ---------------- */
section[data-testid="stSidebar"] {
  border-right: 1px solid var(--v-border);
  background: linear-gradient(180deg, #0f1724, #0c121d);
}
div[data-testid="stMetric"] {
  border: 1px solid var(--v-border); border-radius: 14px;
  padding: 14px 16px; background: var(--v-panel);
}
div[data-testid="stMetric"] label p { color: var(--v-muted) !important; font-size: 0.78rem !important; letter-spacing: .04em; }
div[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }

.stButton > button {
  border-radius: 11px; font-weight: 650; border: 1px solid var(--v-border-strong);
  transition: transform .1s ease, box-shadow .15s ease;
}
.stButton > button:hover { transform: translateY(-1px); }
.stButton > button[kind="primary"] {
  background: var(--v-grad); border: none; color: #0a0f1a;
  box-shadow: 0 8px 24px -10px rgba(124,140,255,0.7);
}
div[data-testid="stExpander"] {
  border: 1px solid var(--v-border); border-radius: 12px; background: var(--v-panel-2);
}
.stProgress > div > div > div > div { background: var(--v-grad) !important; }

/* Ergebnis-Banner */
.result-card {
  border: 1px solid var(--v-border); border-radius: 16px; padding: 18px 20px;
  background: linear-gradient(180deg, rgba(34,211,238,0.06), transparent), var(--v-panel);
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
}
.result-card .big { font-size: 1.6rem; font-weight: 800; }
.section-title {
  display: flex; align-items: center; gap: 10px;
  font-weight: 750; font-size: 1.12rem; margin: 22px 0 8px; color: var(--v-text);
}
.section-title .bar { width: 4px; height: 18px; border-radius: 3px; background: var(--v-grad); }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Wiederverwendbare Render-Helfer
# ---------------------------------------------------------------------------

def _hero() -> None:
    st.markdown(
        """
        <div class="vault-hero">
          <span class="vault-badge"><span class="dot"></span>Docling · Obsidian Vault · RAG-ready</span>
          <h1>Docling Vault Tool</h1>
          <p><span class="kicker">Aus Dokumenten wird ein Wissens-Vault — nicht Textbrei.</span>
          Batch-Konvertierung von PDF/DOCX/XLSX/PPTX nach strukturiertem Markdown,
          mit extrahierten Bildern, Obsidian-Properties und Rückverweis zum Original.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _features() -> None:
    cards = [
        ("🧭", "Struktur statt Textbrei", "Überschriften & Tabellen bleiben erhalten — die Basis für gutes Chunking."),
        ("🖼️", "Bilder extrahiert", "Eingebettete Grafiken landen als eigene Dateien in <code>assets/</code>."),
        ("🔗", "Obsidian-native", "YAML-Properties + Rückverweis (<code>original_path</code>) zum Quelldokument."),
        ("⚡", "Echt parallel", "ProcessPool nutzt alle Kerne — ein Docling-Modell pro Prozess."),
        ("🩺", "Transparente Fehler", "Echte Ursache je Datei + klickbarer Link in den Ursprungsordner."),
    ]
    html = '<div class="feature-grid">'
    for ic, ttl, sub in cards:
        html += (
            f'<div class="feature-card"><div class="ic">{ic}</div>'
            f'<div class="ttl">{ttl}</div><div class="sub">{sub}</div></div>'
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _pipeline(src_count: int | None = None) -> None:
    src_meta = f"{src_count} Datei(en)" if src_count is not None else "PDF · DOCX · XLSX · PPTX"
    st.markdown(
        f"""
        <div class="pipeline">
          <div class="pnode">
            <div class="lbl">Quelle</div>
            <div class="main">📚 Dokumente</div>
            <div class="meta">{src_meta}</div>
          </div>
          <div class="parrow">▸</div>
          <div class="pnode mid">
            <div class="lbl">Verarbeitung</div>
            <div class="main">⚙️ Docling</div>
            <div class="meta">Layout · Tabellen · Bilder</div>
          </div>
          <div class="parrow">▸</div>
          <div class="pnode">
            <div class="lbl">Ziel</div>
            <div class="main">🗄️ Vault</div>
            <div class="meta">.md + assets + Properties</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _section(title: str) -> None:
    st.markdown(
        f'<div class="section-title"><span class="bar"></span>{title}</div>',
        unsafe_allow_html=True,
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


# ---------------------------------------------------------------------------
# Kopfbereich
# ---------------------------------------------------------------------------
_hero()
_features()

# ---------------------------------------------------------------------------
# Sidebar-Konfiguration
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ Konfiguration")
    input_dir = st.text_input(
        "Quellordner",
        value=st.session_state.get("input_dir", ""),
        placeholder="/pfad/zu/den/dokumenten",
        help="Ordner mit den PDF/DOCX/XLSX-Dateien (wird rekursiv durchsucht).",
    )
    output_dir = st.text_input(
        "Ziel-Vault-Ordner",
        value=st.session_state.get("output_dir", ""),
        placeholder="/pfad/zum/obsidian/vault",
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
    do_ocr = st.toggle(
        "OCR aktivieren",
        value=False,
        help="Nur fuer gescannte PDFs ohne Textlayer. Deutlich langsamer.",
    )

    st.markdown("### 🧹 Nach erfolgreicher Konvertierung")
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
            placeholder="/pfad/zum/archiv",
            help="Struktur des Quellordners wird hier gespiegelt.",
        )
        st.session_state["archive_dir"] = archive_dir
    elif on_success == "delete":
        st.warning("⚠️ Originale werden nach Erfolg unwiderruflich gelöscht.")

    st.divider()
    st.caption(
        "Unterstützte Formate: "
        + ", ".join(sorted(e.lstrip(".") for e in dw.SUPPORTED_EXTENSIONS))
    )

# Eingaben fuer den naechsten Rerun merken.
st.session_state["input_dir"] = input_dir
st.session_state["output_dir"] = output_dir

# ---------------------------------------------------------------------------
# Pipeline-Visual + Aktionen
# ---------------------------------------------------------------------------
scanned = st.session_state.get("scanned_files")
_pipeline(len(scanned) if scanned else None)

col_scan, col_start = st.columns([1, 1])
scan = col_scan.button("🔍 Dateien scannen", use_container_width=True)
start = col_start.button(
    "🚀 Konvertierung starten", type="primary", use_container_width=True
)

if scan:
    if not input_dir or not Path(input_dir).is_dir():
        st.error("Bitte einen gültigen Quellordner angeben.")
    else:
        files = dw.discover_files(input_dir)
        st.session_state["scanned_files"] = [str(f) for f in files]
        st.success(f"{len(files)} unterstützte Datei(en) gefunden.")

if st.session_state.get("scanned_files"):
    st.caption(f"📦 Zuletzt gescannt: {len(st.session_state['scanned_files'])} Datei(en).")

# ---------------------------------------------------------------------------
# Konvertierung
# ---------------------------------------------------------------------------
if start:
    if not input_dir or not Path(input_dir).is_dir():
        st.error("Bitte einen gültigen Quellordner angeben.")
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
        st.warning("Keine unterstützten Dateien gefunden.")
        st.stop()

    config = dw.ConverterConfig(
        do_ocr=do_ocr,
        on_success=on_success,
        archive_dir=str(Path(archive_dir).resolve()) if archive_dir else None,
    )

    _section("Fortschritt")
    progress = st.progress(0.0)
    m1, m2, m3, m4 = st.columns(4)
    ph_done = m1.empty()
    ph_ok = m2.empty()
    ph_fail = m3.empty()
    ph_eta = m4.empty()
    ph_current = st.empty()

    ok = 0
    moved = 0
    images_total = 0
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
                images_total += res.num_images
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

    # Ergebnis-Banner (custom, "Vault gefüllt").
    icon = "✅" if not failures else "⚠️"
    st.markdown(
        f"""
        <div class="result-card">
          <div class="big">{icon}</div>
          <div>
            <div style="font-weight:750; font-size:1.05rem;">
              Vault aktualisiert in {_format_duration(total_time)}
            </div>
            <div style="color:var(--v-muted); font-size:0.9rem;">
              {ok} Dokument(e) konvertiert · {images_total} Bild(er) extrahiert · {len(failures)} Fehler
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if moved:
        verb = "gelöscht" if on_success == "delete" else "ins Archiv verschoben"
        st.info(f"{moved} Originaldatei(en) {verb}.")

    # -------------------- Fehlerprotokoll --------------------
    if failures:
        _section("⚠️ Fehlerprotokoll")

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
                    st.markdown(
                        f"[📄 Datei öffnen]({uri}) · "
                        f"[📂 Ordner öffnen]({_file_uri(str(p.parent))})"
                    )
                st.code(r.error_detail or r.error or "", language="text")

        st.download_button(
            "⬇️ Fehlerprotokoll (CSV) herunterladen",
            data=_errors_to_csv(failures),
            file_name="docling_fehler.csv",
            mime="text/csv",
        )
