"""Streamlit-Dashboard fuer die Docling-Batch-Konvertierung.

Zwei Bereiche: *Konvertierung* (Scan, Zielanalyse, Integrationsplan mit
einmaliger Bestaetigung, Fortschritt, Fehlerprotokoll) und *Jobs &
Ueberwachung* (inkrementelle Jobs mit Lauf-Historie). Die Konvertierungs-
und Job-Logik liegt in ``docling_worker.py`` bzw. ``job_manager.py`` und wird
hier nur orchestriert.

Start::

    streamlit run app_streamlit.py
"""

from __future__ import annotations

import csv
import io
import multiprocessing
import os
import time
from pathlib import Path

if multiprocessing.current_process().name != "MainProcess":
    # Windows-Spawn-Worker importieren dieses Skript beim Prozessstart als
    # Hauptmodul erneut ("bare mode"). Streamlit wuerde dann pro Worker
    # dutzendfach "to view a Streamlit app..." / "Session state does not
    # function" / "No runtime found" ins Log schreiben. Ein setLevel auf dem
    # "streamlit"-Logger reicht NICHT: Streamlit konfiguriert seine Logger
    # beim Import selbst neu. logging.disable wirkt global und nur in
    # diesem Worker-Prozess -- der braucht keinerlei Log unterhalb ERROR.
    import logging as _logging

    _logging.disable(_logging.WARNING)

import streamlit as st

import docling_worker as dw
import file_transfer as ft
import i18n
import job_manager as jm
import vault_builder as vb
import vault_index as vi
from i18n import LANGUAGES
from i18n import tr as _

st.set_page_config(
    page_title="doc2vault",
    page_icon="🗂",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Erscheinungsbild: dunkel, nuechtern, eine Akzentfarbe, keine Effekte.
# ---------------------------------------------------------------------------
_CSS = """
<style>
:root {
  --bg: #12151c;
  --panel: #181c25;
  --panel-2: #141821;
  --border: #262c38;
  --text: #d8dee8;
  --muted: #8b93a3;
  --accent: #4c8bf5;
}

.stApp { background: var(--bg); }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.4rem; max-width: 1150px; }

/* Kopfzeile */
.app-header { border-bottom: 1px solid var(--border); padding-bottom: 18px; }
.app-kicker {
  font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--muted); font-weight: 600;
}
.app-header h1 {
  font-size: 1.55rem; font-weight: 650; letter-spacing: -.01em;
  margin: .35rem 0 .3rem; color: var(--text);
}
.app-header p { margin: 0; color: var(--muted); font-size: .95rem; max-width: 78ch; }

/* Abschnitts-Label */
.overline {
  font-size: 11px; letter-spacing: .12em; text-transform: uppercase;
  color: var(--muted); font-weight: 650; margin: 1.5rem 0 .5rem;
}

/* Sidebar */
section[data-testid="stSidebar"] {
  background: var(--panel-2); border-right: 1px solid var(--border);
}
.side-label {
  font-size: 11px; letter-spacing: .1em; text-transform: uppercase;
  color: var(--muted); font-weight: 650; margin: 1.2rem 0 .1rem;
}

/* Kennzahlen */
div[data-testid="stMetric"] {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px;
}
div[data-testid="stMetric"] label p { color: var(--muted) !important; font-size: .75rem !important; }
div[data-testid="stMetricValue"] { font-size: 1.3rem; font-variant-numeric: tabular-nums; }

/* Buttons */
.stButton > button, .stDownloadButton > button {
  border-radius: 6px; border: 1px solid var(--border);
  background: var(--panel); color: var(--text); font-weight: 500;
  box-shadow: none;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: #39415250; color: #ffffff; background: #1d2230;
}
.stButton > button[kind="primary"] {
  background: var(--accent); border-color: var(--accent); color: #ffffff;
}
.stButton > button[kind="primary"]:hover {
  background: #3d7ce6; border-color: #3d7ce6;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] { gap: 2px; border-bottom: 1px solid var(--border); }
.stTabs [data-baseweb="tab"] { padding: 6px 14px; color: var(--muted); font-weight: 500; }
.stTabs [aria-selected="true"] { color: var(--text); }
.stTabs [data-baseweb="tab-highlight"] { background-color: var(--accent); }

/* Fortschritt, Expander */
.stProgress > div > div > div > div { background: var(--accent) !important; }
div[data-testid="stExpander"] {
  border: 1px solid var(--border); border-radius: 8px; background: var(--panel);
}
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sprachwahl: allererstes Sidebar-Element -- muss VOR dem ersten uebersetzten
# Text laufen, sonst rendert der Lauf gemischt.
# ---------------------------------------------------------------------------
with st.sidebar:
    _ui_lang = st.selectbox(
        "Sprache / Language",
        options=list(LANGUAGES),
        format_func=LANGUAGES.get,
        index=list(LANGUAGES).index(i18n.get_language()),
        key="ui_lang",
    )
    i18n.set_language(_ui_lang)


# ---------------------------------------------------------------------------
# Render-Helfer
# ---------------------------------------------------------------------------

def _overline(text: str) -> None:
    st.markdown(f'<div class="overline">{text}</div>', unsafe_allow_html=True)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_folder_size(folder: str) -> int:
    """Ordnergroesse mit kurzem Cache -- der rekursive Scan grosser Vaults
    darf nicht bei jedem Streamlit-Rerun erneut laufen."""
    return ft.folder_size(folder)


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


# Manifest/Historie grosser Jobs nicht bei jedem Rerun neu parsen: der
# mtime-Schluessel invalidiert den Cache genau dann, wenn sich die Datei
# tatsaechlich geaendert hat.
@st.cache_data(show_spinner=False)
def _cached_manifest_ok(job_id: str, mtime: float) -> int:
    manifest = jm.load_manifest(job_id)
    return sum(1 for e in manifest.values() if e.get("status") == "ok")


@st.cache_data(show_spinner=False)
def _cached_history(job_id: str, mtime: float) -> list:
    return jm.load_history(job_id)


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
        [_("datei"), _("kategorie"), _("hinweis"), _("fehler"), _("pfad"),
         "traceback", _("dauer_s")]
    )
    for r in results:
        writer.writerow(
            [
                Path(r.source_path).name,
                r.error_category or "",
                _(r.error_hint) if r.error_hint else "",
                r.error or "",
                r.source_path,
                (r.error_detail or "").replace("\r\n", "\n"),
                f"{r.duration_s:.2f}",
            ]
        )
    return buf.getvalue().encode("utf-8")


def _file_uri(path: str) -> str:
    """file://-URI zum direkten Oeffnen im Ursprungsordner."""
    try:
        return Path(path).resolve().as_uri()
    except Exception:  # noqa: BLE001 -- z. B. ungueltiger Pfad
        return ""


def _ensure_dir(path_str: str) -> tuple[bool, str]:
    """Legt einen Ordner (samt Eltern) an, falls er fehlt. -> (ok, meldung)."""
    try:
        Path(path_str).mkdir(parents=True, exist_ok=True)
        return True, ""
    except OSError as exc:
        return False, str(exc)


def _pick_folder_native(initial: str) -> str | None:
    """Nativer Ordner-Auswahldialog (tkinter).

    Funktioniert, wenn das Dashboard auf dem Rechner des Nutzers laeuft
    (typischer Windows-/Desktop-Fall). Auf Headless-Servern/Containern gibt
    es kein GUI -> None, dann greift der In-App-Ordnerbrowser.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        picked = filedialog.askdirectory(
            initialdir=initial if initial and Path(initial).is_dir() else None,
            master=root,
        )
        root.destroy()
        return picked or None
    except Exception:  # noqa: BLE001 -- kein Display/tkinter -> Fallback
        return None


def _browse_clicked(session_key: str, current: str) -> None:
    """Durchsuchen-Klick: nativer Dialog, sonst In-App-Browser oeffnen."""
    picked = _pick_folder_native(current)
    if picked:
        st.session_state[session_key] = picked
        st.session_state.pop(f"fb_open_{session_key}", None)
    else:
        st.session_state[f"fb_open_{session_key}"] = True
        start = current if current and Path(current).is_dir() else str(Path.home())
        st.session_state[f"fb_cwd_{session_key}"] = start
    st.rerun()


def _folder_browser(session_key: str) -> None:
    """In-App-Ordnerbrowser (Fallback ohne GUI, z. B. Docker/Headless)."""
    cwd = Path(st.session_state.get(f"fb_cwd_{session_key}") or Path.home())
    st.caption(_("Ordner wählen: `{cwd}`", cwd=cwd))
    try:
        subdirs = sorted(
            p.name for p in cwd.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
    except OSError:
        subdirs = []

    choice = st.selectbox(
        _("Unterordner öffnen"),
        ["–"] + subdirs,
        key=f"fb_sel_{session_key}_{cwd}",
        label_visibility="collapsed",
    )
    b1, b2, b3 = st.columns(3)
    if b1.button(_("Öffnen"), key=f"fb_go_{session_key}") and choice != "–":
        st.session_state[f"fb_cwd_{session_key}"] = str(cwd / choice)
        st.rerun()
    if b2.button(_("Ebene hoch"), key=f"fb_up_{session_key}"):
        st.session_state[f"fb_cwd_{session_key}"] = str(cwd.parent)
        st.rerun()
    if b3.button(_("Schließen"), key=f"fb_close_{session_key}"):
        st.session_state.pop(f"fb_open_{session_key}", None)
        st.rerun()

    new_name = st.text_input(
        _("Neuen Unterordner anlegen"),
        key=f"fb_new_{session_key}",
        placeholder=_("Name des neuen Ordners"),
    )
    if st.button(_("Anlegen und übernehmen"), key=f"fb_mk_{session_key}") and new_name:
        target = cwd / new_name.strip()
        ok, msg = _ensure_dir(str(target))
        if ok:
            st.session_state[session_key] = str(target)
            st.session_state.pop(f"fb_open_{session_key}", None)
            st.rerun()
        else:
            st.error(_("Konnte Ordner nicht anlegen: {msg}", msg=msg))

    if st.button(_("Diesen Ordner übernehmen"), type="primary",
                 key=f"fb_take_{session_key}"):
        st.session_state[session_key] = str(cwd)
        st.session_state.pop(f"fb_open_{session_key}", None)
        st.rerun()


def _dir_field(label: str, session_key: str, env_var: str,
               placeholder: str, help_text: str) -> str:
    """Pfad-Eingabefeld mit Durchsuchen-Button und Fallback-Browser."""
    value = st.text_input(
        _(label),
        value=st.session_state.get(session_key, os.environ.get(env_var, "")),
        placeholder=_(placeholder),
        help=_(help_text),
    )
    if st.button(_("Durchsuchen…"), key=f"browse_{session_key}"):
        _browse_clicked(session_key, value)
    if st.session_state.get(f"fb_open_{session_key}"):
        with st.container(border=True):
            _folder_browser(session_key)
    return value


def _render_failures(failures: list) -> None:
    """Fehlerprotokoll: Kategorien, Tabelle mit Quellenlinks, Details, CSV."""
    _overline(_("Fehlerprotokoll"))

    cat_counts: dict[str, int] = {}
    for r in failures:
        cat = r.error_category or "fehler"
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    st.caption(
        _("Kategorien: {items}", items=" · ".join(
            f"{cat} ({n})"
            for cat, n in sorted(cat_counts.items(), key=lambda kv: -kv[1])
        ))
    )

    rows = []
    for r in failures:
        p = Path(r.source_path)
        rows.append(
            {
                _("Datei"): p.name,
                _("Kategorie"): r.error_category or "fehler",
                _("Hinweis"): _(r.error_hint) if r.error_hint else "",
                _("Fehler"): r.error or "",
                _("Datei öffnen"): _file_uri(str(p)),
                _("Ordner öffnen"): _file_uri(str(p.parent)),
                _("Pfad"): str(p),
            }
        )
    st.dataframe(
        rows,
        width="stretch",
        hide_index=True,
        column_config={
            _("Datei öffnen"): st.column_config.LinkColumn(
                _("Datei öffnen"), display_text=_("Datei öffnen")
            ),
            _("Ordner öffnen"): st.column_config.LinkColumn(
                _("Ordner öffnen"), display_text=_("Ordner öffnen")
            ),
        },
    )
    st.caption(_(
        "Hinweis: Manche Browser blockieren file://-Links. In dem Fall den "
        "Pfad aus der Spalte „Pfad“ kopieren."
    ))

    st.markdown(f"**{_('Details je Datei')}**")
    for r in failures:
        p = Path(r.source_path)
        with st.expander(f"{p.name} – {r.error or _('Fehler')}"):
            st.write(f"**{_('Kategorie')}:** {r.error_category or 'fehler'}")
            if r.error_hint:
                st.write(f"**{_('Hinweis')}:** {_(r.error_hint)}")
            st.write(f"**Original:** `{p}`")
            uri = _file_uri(str(p))
            if uri:
                st.markdown(
                    f"[{_('Datei öffnen')}]({uri}) · "
                    f"[{_('Ordner öffnen')}]({_file_uri(str(p.parent))})"
                )
            st.code(r.error_detail or r.error or "", language="text")

    st.download_button(
        _("Fehlerprotokoll als CSV herunterladen"),
        data=_errors_to_csv(failures),
        file_name="doc2vault_fehler.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------------------------
# Kopfbereich
# ---------------------------------------------------------------------------
_kicker = _("Batch-Konvertierung für Wissens-Vaults")
_intro = _(
    "Konvertiert PDF-, Word-, Excel- und PowerPoint-Dokumente in "
    "strukturiertes Markdown für Obsidian-kompatible Vaults. Überschriften "
    "und Tabellen bleiben erhalten, eingebettete Bilder werden extrahiert, "
    "jede Notiz erhält Metadaten mit Rückverweis auf das Original."
)
st.markdown(
    f"""
    <div class="app-header">
      <div class="app-kicker">{_kicker}</div>
      <h1>doc2vault</h1>
      <p>{_intro}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar: Einstellungen
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        f'<div class="side-label">{_("Verzeichnisse")}</div>',
        unsafe_allow_html=True,
    )
    # Vorbelegung aus Umgebungsvariablen: im Container zeigen die Felder damit
    # direkt auf die gemounteten Ordner (docker-compose setzt DOC2VAULT_*_DIR).
    input_dir = _dir_field(
        "Quellordner", "input_dir", "DOC2VAULT_SOURCE_DIR",
        "/pfad/zu/den/dokumenten",
        "Wird rekursiv nach unterstützten Dateien durchsucht. "
        "„Durchsuchen…“ öffnet die Ordnerauswahl.",
    )
    output_dir = _dir_field(
        "Ziel-Vault-Ordner", "output_dir", "DOC2VAULT_TARGET_DIR",
        "/pfad/zum/vault",
        "Zielordner für die Markdown-Dateien; wird bei Bedarf automatisch "
        "angelegt. Bestehende Vaults werden analysiert und die Dateien "
        "entsprechend eingegliedert.",
    )

    st.divider()
    st.caption(_(
        "Alle Verarbeitungs-Optionen (OCR, Bilder, Excel, Originaldateien) "
        "stehen im Tab „Einstellungen“."
    ))
    st.caption(_(
        "Unterstützte Formate: {formats}",
        formats=", ".join(sorted(e.lstrip(".") for e in dw.SUPPORTED_EXTENSIONS)),
    ))

st.session_state["input_dir"] = input_dir
st.session_state["output_dir"] = output_dir

# Fuer den Jobs-Tab: Plan aus dem Konvertierungs-Tab.
profile = None
config: dw.ConverterConfig | None = None

tab_convert, tab_jobs, tab_search, tab_transfer, tab_settings = st.tabs(
    [_("Konvertierung"), _("Jobs & Überwachung"), _("Suche & KI"),
     _("Datenaustausch"), _("Einstellungen")]
)

# ===========================================================================
# Tab 5: Einstellungen -- IM CODE ZUERST befuellt, damit die Werte in allen
# anderen Tabs bereitstehen (die visuelle Tab-Reihenfolge ist davon
# unabhaengig). Widget-Keys machen die Auswahl ueber Reruns hinweg stabil.
# ===========================================================================
with tab_settings:
    st.caption(_(
        "Gilt für Konvertierungen und neue Jobs. Auswahl bleibt während der "
        "Sitzung erhalten."
    ))
    col_left, col_right = st.columns(2, gap="large")

    with col_left:
        _overline(_("Verarbeitung"))
        cpu_count = os.cpu_count() or 2
        max_workers = st.slider(
            _("Parallele Prozesse"),
            min_value=1,
            max_value=cpu_count,
            value=max(1, cpu_count - 1),
            key="set_workers",
            help=_("Docling ist CPU- und speicherintensiv. Bei knappem RAM reduzieren."),
        )

        _overline(_("Docling-Funktionen"))
        extract_images = st.toggle(
            _("Bilder extrahieren"),
            value=True,
            key="set_images",
            help=_(
                "Eingebettete Grafiken als eigene Dateien ablegen und in den "
                "Notizen verlinken. Deaktiviert: reine Textkonvertierung."
            ),
        )
        images_scale = 2.0
        if extract_images:
            images_scale = st.slider(
                _("Bildauflösung (Skalierung)"),
                min_value=1.0,
                max_value=4.0,
                value=2.0,
                step=0.5,
                key="set_scale",
                help=_(
                    "Höhere Werte liefern schärfere Bilder, brauchen aber mehr "
                    "Zeit und Speicherplatz."
                ),
            )
        table_structure = st.toggle(
            _("Tabellenstruktur erkennen"),
            value=True,
            key="set_tables",
            help=_(
                "Rekonstruiert Tabellen als Markdown-Tabellen. Deaktiviert ist "
                "die Verarbeitung schneller, Tabellen werden aber zu Fließtext."
            ),
        )
        do_ocr = st.toggle(
            _("OCR für gescannte PDFs"),
            value=False,
            key="set_ocr",
            help=_("Nur für Scans ohne Textebene aktivieren – deutlich langsamer."),
        )
        ocr_engine = "easyocr"
        ocr_languages = "de,en"
        if do_ocr:
            ocr_engine = st.selectbox(
                _("OCR-Engine"),
                options=["easyocr", "tesseract", "rapidocr"],
                index=0,
                key="set_engine",
                help=_(
                    "EasyOCR (Standard): Modelle werden von GitHub geladen. "
                    "Tesseract: erfordert lokale Installation, Sprachcodes wie "
                    "„deu,eng“. RapidOCR: lädt Modelle von modelscope.cn – in "
                    "vielen Netzen blockiert."
                ),
            )
            ocr_languages = st.text_input(
                _("OCR-Sprachen"),
                value="deu,eng" if ocr_engine == "tesseract" else "de,en",
                key="set_langs",
                help=_("Kommaliste der Erkennungssprachen."),
            )
            # Sofort warnen statt spaeter 1000+ Einzelfehler produzieren.
            _engine_warning = dw.check_ocr_engine(dw.ConverterConfig(
                do_ocr=True, ocr_engine=ocr_engine, ocr_languages=ocr_languages,
            ))
            if _engine_warning:
                st.warning(_(_engine_warning), icon="⚠️")
            if max_workers > 2:
                st.info(_(
                    "OCR mit {n} parallelen Prozessen braucht viel "
                    "Arbeitsspeicher – jeder Prozess lädt einen eigenen "
                    "Modellstapel. Bei Speicherfehlern (std::bad_alloc) "
                    "1–2 Prozesse verwenden.",
                    n=max_workers,
                ))

    with col_right:
        _overline(_("Excel-Arbeitsmappen"))
        xlsx_sheet_limit = st.number_input(
            _("Sheet-Limit je Arbeitsmappe"),
            min_value=0,
            value=0,
            step=5,
            key="set_xlsx_limit",
            help=_(
                "0 = alle Blätter konvertieren. Ein Limit begrenzt Laufzeit und "
                "Notizgröße bei Arbeitsmappen mit sehr vielen Blättern."
            ),
        )
        xlsx_on_limit = "limit"
        if xlsx_sheet_limit > 0:
            # Optionswerte bleiben deutsch (werden unten gemappt) -- nur die
            # Anzeige laeuft ueber format_func durch die Uebersetzung.
            xlsx_on_limit_label = st.radio(
                _("Bei Überschreitung"),
                options=["Nur erste Blätter konvertieren", "Datei überspringen"],
                index=0,
                format_func=_,
                key="set_xlsx_mode",
                help=_(
                    "Übersprungene Dateien erscheinen im Fehlerprotokoll. Bei "
                    "„nur erste Blätter“ vermerkt das Frontmatter die Gesamtzahl."
                ),
            )
            xlsx_on_limit = (
                "limit" if xlsx_on_limit_label.startswith("Nur") else "skip"
            )

        _overline(_("Nach erfolgreicher Konvertierung"))
        on_success_label = st.radio(
            _("Originaldateien"),
            options=["Behalten", "In Archiv verschieben", "Löschen"],
            index=0,
            format_func=_,
            key="set_on_success",
            help=_(
                "Betrifft nur erfolgreich konvertierte Dateien. Fehlgeschlagene "
                "Dateien bleiben immer unangetastet."
            ),
        )
        on_success = {
            "Behalten": "keep",
            "In Archiv verschieben": "archive",
            "Löschen": "delete",
        }[on_success_label]
        archive_dir = ""
        if on_success == "archive":
            archive_dir = _dir_field(
                "Archiv-Ordner", "archive_dir", "DOC2VAULT_ARCHIVE_DIR",
                "/pfad/zum/archiv",
                "Die Struktur des Quellordners wird im Archiv gespiegelt; der "
                "Ordner wird bei Bedarf angelegt.",
            )
            st.session_state["archive_dir"] = archive_dir
        elif on_success == "delete":
            st.warning(_("Originale werden nach Erfolg unwiderruflich gelöscht."))

        _overline(_("Sprache"))
        st.caption(_(
            "Die Oberflächensprache wird oben in der Seitenleiste gewählt; "
            "Vorbelegung über DOC2VAULT_LANG."
        ))

# ===========================================================================
# Tab 1: Konvertierung
# ===========================================================================
with tab_convert:
    st.caption(_(
        "① Quell- und Ziel-Ordner in der Seitenleiste wählen · "
        "② „Dateien scannen“ zeigt, was gefunden wird · "
        "③ „Ziel analysieren“, Plan prüfen und einmal für den ganzen "
        "Batch bestätigen. Verarbeitungs-Optionen: Tab „Einstellungen“."
    ))
    if not input_dir or not output_dir:
        st.info(_(
            "Zum Start: Quell- und Ziel-Vault-Ordner in der Seitenleiste "
            "angeben (oder per „Durchsuchen…“ auswählen)."
        ))
    col_scan, col_analyze = st.columns(2)
    scan = col_scan.button(_("Dateien scannen"), width="stretch")
    analyze = col_analyze.button(
        _("Ziel analysieren"), type="primary", width="stretch"
    )

    if scan:
        path_error = dw.check_paths(input_dir, output_dir)
        if not input_dir or not Path(input_dir).is_dir():
            st.error(_("Bitte einen gültigen Quellordner angeben."))
        elif path_error:
            st.error(_(path_error))
        else:
            files = dw.discover_files(
                input_dir, exclude_dirs=(output_dir, archive_dir)
            )
            st.session_state["scanned_files"] = [str(f) for f in files]
            st.success(_("{n} unterstützte Datei(en) gefunden.", n=len(files)))
            dup_groups = dw.find_duplicate_files(files)
            if dup_groups:
                dup_total = sum(len(p) for p in dup_groups.values())
                st.caption(_(
                    "{n} Duplikatgruppe(n) mit {m} inhaltsgleichen Dateien "
                    "gefunden (per CLI-Flag `--duplicates skip` bzw. "
                    "Job-Option überspringbar).",
                    n=len(dup_groups), m=dup_total,
                ))
            if not do_ocr and any(
                Path(f).suffix.lower() in dw.IMAGE_INPUT_EXTENSIONS
                for f in files
            ):
                st.warning(_(
                    "Bilddateien im Quellordner, aber OCR ist aus – "
                    "gescannte Bilder ergeben leere Notizen. OCR in der "
                    "Seitenleiste aktivieren."
                ))
    elif st.session_state.get("scanned_files"):
        st.caption(_(
            "Letzter Scan: {n} Datei(en).",
            n=len(st.session_state["scanned_files"]),
        ))

    # --- Schritt 1: Ziel analysieren --------------------------------------
    if analyze:
        if not output_dir:
            st.error(_("Bitte einen Ziel-Vault-Ordner angeben."))
        else:
            vault_profile = dw.analyze_vault(output_dir)
            st.session_state["vault_profile"] = vault_profile
            st.session_state["vault_profile_target"] = output_dir
            st.session_state["plan_reco"] = dw.recommend_config(vault_profile)

    profile = st.session_state.get("vault_profile")
    profile_valid = (
        profile is not None
        and st.session_state.get("vault_profile_target") == output_dir
    )

    # --- Schritt 2: Plan pruefen und einmal bestaetigen --------------------
    confirm = False
    if profile_valid:
        reco = st.session_state["plan_reco"]

        _overline(_("Zielordner-Analyse"))
        type_label = {
            "obsidian": "Obsidian-Vault",
            "logseq": "Logseq-Graph",
            "folder": "Bestehender Ordner",
            "new": "Neuer Ordner",
        }.get(profile.vault_type, profile.vault_type)
        a1, a2, a3 = st.columns(3)
        a1.metric(_("Zieltyp"), _(type_label))
        a2.metric(_("Vorhandene Notizen"), profile.note_count)
        a3.metric(_("Ordner auf oberster Ebene"), len(profile.top_level_folders))
        for obs in profile.observations:
            st.caption(f"– {_(obs)}")
        if profile.top_level_folders:
            st.caption(_(
                "Bestehende Ordner: {folders}",
                folders=", ".join(profile.top_level_folders[:12])
                + (" …" if len(profile.top_level_folders) > 12 else ""),
            ))

        _overline(_("Integrationsplan"))
        if profile.vault_type in ("obsidian", "logseq") and not profile.is_empty:
            st.info(_(
                "Bestehender Vault erkannt. Die Dateien werden entsprechend der "
                "Vault-Konventionen eingegliedert – bitte den Plan prüfen und "
                "einmal für den gesamten Batch bestätigen."
            ))

        c1, c2 = st.columns(2)
        with c1:
            # Optionswerte bleiben deutsch (Vergleich unten) -- nur die
            # Anzeige laeuft ueber format_func durch die Uebersetzung.
            placement = st.radio(
                _("Ablage der Notizen"),
                options=["Eigener Unterordner", "Ziel-Wurzel"],
                index=0 if reco.notes_subdir else 1,
                format_func=_,
                help=_(
                    "Ein eigener Unterordner hält einen kuratierten Vault "
                    "sauber. Die Ziel-Wurzel fügt sich in bestehende "
                    "gleichnamige Ordner ein."
                ),
            )
            notes_subdir = ""
            if placement == "Eigener Unterordner":
                notes_subdir = st.text_input(
                    _("Name des Unterordners"),
                    value=reco.notes_subdir or dw.DEFAULT_IMPORT_SUBDIR,
                )
            add_frontmatter = st.toggle(
                _("Frontmatter-Properties schreiben"),
                value=reco.add_frontmatter,
                help=_(
                    "source, original_path und assets_folder als "
                    "Obsidian-Properties."
                ),
            )
        with c2:
            attach_adjacent = st.toggle(
                _("Anhänge neben der Notiz ablegen"),
                value=(reco.attachments_mode == "adjacent"),
                help=_(
                    "Aktiviert: ein Ordner je Notiz (Obsidian-Einstellung "
                    "„neben der Notiz“). Deaktiviert: ein zentraler "
                    "Anhang-Ordner."
                ),
            )
            attachments_subdir = reco.attachments_subdir
            if not attach_adjacent:
                attachments_subdir = st.text_input(
                    _("Zentraler Anhang-Ordner"),
                    value=reco.attachments_subdir or "assets",
                )
            mirror = st.toggle(
                _("Quellstruktur spiegeln"),
                value=reco.mirror_structure,
                help=_("Unterordner des Quellordners im Ziel nachbilden."),
            )

        config = dw.ConverterConfig(
            do_ocr=do_ocr,
            ocr_engine=ocr_engine,
            ocr_languages=ocr_languages,
            generate_picture_images=extract_images,
            images_scale=images_scale,
            do_table_structure=table_structure,
            xlsx_sheet_limit=int(xlsx_sheet_limit),
            xlsx_on_limit=xlsx_on_limit,
            on_success=on_success,
            archive_dir=str(Path(archive_dir).resolve()) if archive_dir else None,
            notes_subdir=notes_subdir,
            mirror_structure=mirror,
            attachments_mode="adjacent" if attach_adjacent else "central",
            attachments_subdir=attachments_subdir,
            add_frontmatter=add_frontmatter,
        )

        build_after = st.toggle(
            _("Vault-Build nach der Konvertierung"),
            value=st.session_state.get("build_after", False),
            help=_(
                "Post-Processing: Notizen nach Inbox/, Bilder nach "
                "Attachments/ mit Obsidian-Wikilinks, normiertes Frontmatter; "
                "Such-Index und INDEX.md werden automatisch aktualisiert. "
                "Bestehende Notizen des Vaults bleiben unangetastet."
            ),
        )
        st.session_state["build_after"] = build_after

        with st.container(border=True):
            st.markdown(f"**{_('Zusammenfassung')}**")
            for line in dw.describe_plan(profile, config):
                st.markdown(f"- {_(line)}")
            if build_after:
                st.markdown("- " + _(
                    "Danach: Vault-Build (Inbox/, Attachments/, Wikilinks) "
                    "+ Such-Index"
                ))

        confirm = st.button(
            _("Plan bestätigen und Konvertierung starten"),
            type="primary",
            width="stretch",
        )
    else:
        st.caption(_(
            "Ziel-Vault-Ordner angeben und „Ziel analysieren“ ausführen. "
            "Der Integrationsplan wird anschließend zur Bestätigung angezeigt."
        ))

    # --- Schritt 3: Konvertierung (nach Bestaetigung) ----------------------
    # War beim letzten Skriptlauf eine Konvertierung aktiv, die nicht sauber
    # zu Ende kam, wurde sie unterbrochen -- durch den Abbrechen-Button oder
    # eine andere Interaktion waehrend des Laufs.
    if st.session_state.pop("run_active", False) and not confirm:
        if st.session_state.get("cancel_run"):
            st.info(_(
                "Konvertierung abgebrochen. Bereits fertig konvertierte "
                "Dateien bleiben erhalten."
            ))
        else:
            st.warning(_(
                "Der letzte Lauf wurde unterbrochen. Bereits konvertierte "
                "Dateien bleiben erhalten – einfach erneut starten."
            ))

    if confirm and config is not None:
        if not input_dir or not Path(input_dir).is_dir():
            st.error(_("Bitte einen gültigen Quellordner angeben."))
            st.stop()
        if on_success == "archive" and not archive_dir:
            st.error(_(
                "Für „In Archiv verschieben“ bitte einen Archiv-Ordner angeben."
            ))
            st.stop()
        engine_warning = dw.check_ocr_engine(config)
        if engine_warning:
            # Sonst wuerde JEDE Datei einzeln an der fehlenden Engine
            # scheitern (real passiert: 3000+ identische Fehler).
            st.error(_(engine_warning))
            st.stop()
        path_error = dw.check_paths(input_dir, output_dir)
        if path_error:
            st.error(_(path_error))
            st.stop()

        input_root = Path(input_dir).resolve()
        out_root = Path(output_dir).resolve()
        out_root.mkdir(parents=True, exist_ok=True)

        files = dw.discover_files(
            input_root, exclude_dirs=(out_root, config.archive_dir)
        )
        total = len(files)
        if total == 0:
            st.warning(_("Keine unterstützten Dateien gefunden."))
            st.stop()

        _overline(_("Fortschritt"))
        st.session_state["run_active"] = True
        progress = st.progress(0.0)
        m1, m2, m3, m4 = st.columns(4)
        ph_done = m1.empty()
        ph_ok = m2.empty()
        ph_fail = m3.empty()
        ph_eta = m4.empty()
        ph_current = st.empty()
        # Klick unterbricht das laufende Skript an der naechsten UI-Ausgabe
        # (Heartbeat/Fortschritt); der Runner beendet die Worker dann sofort.
        st.button(_("Konvertierung abbrechen"), key="cancel_run")

        stats = {"done": 0, "ok": 0, "moved": 0, "images": 0,
                 "reduced": 0, "pdfium": 0}
        failures: list = []
        start_time = time.perf_counter()

        def _ui_progress(done: int, total_n: int, res) -> None:
            stats["done"] = done
            if res.success:
                stats["ok"] += 1
                stats["images"] += res.num_images
                if res.moved_to:
                    stats["moved"] += 1
                if getattr(res, "reduced_mode", False):
                    stats["reduced"] += 1
                if getattr(res, "pdf_backend", None):
                    stats["pdfium"] += 1
            else:
                failures.append(res)

            elapsed = time.perf_counter() - start_time
            rate = done / elapsed if elapsed else 0
            eta = (total_n - done) / rate if rate else 0

            progress.progress(done / total_n)
            ph_done.metric(_("Verarbeitet"), f"{done}/{total_n}")
            ph_ok.metric(_("Erfolgreich"), stats["ok"])
            ph_fail.metric(_("Fehler"), len(failures))
            ph_eta.metric(_("Restzeit"), _format_duration(eta))
            ph_current.caption(
                _("Zuletzt: {name}", name=Path(res.source_path).name)
            )

        def _ui_heartbeat() -> None:
            # Sekuendlicher Tick, solange die Worker rechnen: haelt die
            # Restzeit aktuell und ist der Punkt, an dem ein Abbrechen-Klick
            # das Skript tatsaechlich unterbricht.
            elapsed = time.perf_counter() - start_time
            rate = stats["done"] / elapsed if elapsed else 0
            if rate:
                eta = (total - stats["done"]) / rate
                ph_eta.metric(_("Restzeit"), _format_duration(eta))
            else:
                ph_eta.metric(_("Restzeit"), "…")

        # Absturzsicherer Runner: uebersteht harte Worker-Abstuerze (z. B.
        # Speicher bei riesigen PDFs), statt den ganzen Batch zu verlieren.
        dw.run_conversion_batch(
            files, config, out_root, input_root, max_workers,
            progress=_ui_progress, heartbeat=_ui_heartbeat,
        )
        st.session_state["run_active"] = False

        last_run = {
            "target": str(out_root),
            "duration": time.perf_counter() - start_time,
            "ok": stats["ok"],
            "images": stats["images"],
            "moved": stats["moved"],
            "reduced": stats["reduced"],
            "pdfium": stats["pdfium"],
            "on_success": on_success,
            "failures": failures,
        }

        # Optionaler Vault-Build + Index (siehe Toggle im Plan-Bereich).
        if st.session_state.get("build_after"):
            with st.spinner(_("Vault-Build und Such-Index…")):
                try:
                    build_source = (
                        out_root / config.notes_subdir
                        if config.notes_subdir else out_root
                    )
                    bsum = vb.build_vault(build_source, out_root)
                    isum = vi.update_index(out_root)
                    vi.write_index_md(out_root)
                    last_run["build"] = {
                        "notes": bsum.notes,
                        "images": bsum.images,
                        "collisions": bsum.note_collisions + bsum.image_collisions,
                        "index_total": isum.total,
                    }
                except Exception as exc:  # noqa: BLE001 -- Ergebnis anzeigen
                    last_run["build_error"] = str(exc)

        st.session_state["last_run"] = last_run

    # --- Ergebnis (persistiert ueber Reruns) -------------------------------
    last = st.session_state.get("last_run")
    if last:
        _overline(_("Ergebnis"))
        r1, r2, r3, r4 = st.columns(4)
        r1.metric(_("Konvertiert"), last["ok"])
        r2.metric(_("Bilder extrahiert"), last["images"])
        r3.metric(_("Fehler"), len(last["failures"]))
        r4.metric(_("Dauer"), _format_duration(last["duration"]))
        st.caption(_("Ziel: {target}", target=last["target"]))
        if last["moved"]:
            moved_key = (
                "{n} Originaldatei(en) gelöscht."
                if last["on_success"] == "delete"
                else "{n} Originaldatei(en) ins Archiv verschoben."
            )
            st.caption(_(moved_key, n=last["moved"]))
        if last.get("reduced"):
            st.caption(_(
                "{n} Datei(en) mit reduzierten Einstellungen konvertiert "
                "(riesige Seiten, z. B. CAD-Pläne: Bildskalierung 1.0, "
                "ohne Bildextraktion).",
                n=last["reduced"],
            ))
        if last.get("pdfium"):
            st.caption(_(
                "{n} PDF(s) über den alternativen pypdfium-Parser "
                "konvertiert (Standard-Parser lehnte die Datei ab).",
                n=last["pdfium"],
            ))
        build = last.get("build")
        if build:
            build_line = _(
                "Vault-Build: {notes} Notiz(en) → Inbox/, {images} Bild(er) "
                "→ Attachments/ · Such-Index: {index_total} Notizen, "
                "INDEX.md aktualisiert",
                notes=build["notes"], images=build["images"],
                index_total=build["index_total"],
            )
            if build["collisions"]:
                build_line += " · " + _(
                    "{n} Kollision(en) aufgelöst", n=build["collisions"]
                )
            st.caption(build_line)
        if last.get("build_error"):
            st.error(_(
                "Vault-Build fehlgeschlagen: {error}",
                error=last["build_error"],
            ))
        if last["failures"]:
            _render_failures(last["failures"])

# ===========================================================================
# Tab 2: Jobs & Ueberwachung
# ===========================================================================
with tab_jobs:
    st.caption(_(
        "Jobs verknüpfen Quell- und Zielordner mit dem bestätigten "
        "Integrationsplan und verarbeiten bei jedem Lauf nur neue oder "
        "geänderte Dateien – wiederaufsetzbar, mit Sperre gegen Doppelläufe. "
        "Zieldateien werden nie automatisch entfernt."
    ))

    with st.expander(_("Neuen Job anlegen")):
        if not input_dir or not output_dir:
            st.info(_("Quell- und Ziel-Ordner in der Seitenleiste angeben."))
        elif config is None:
            st.info(_(
                "Im Tab „Konvertierung“ zuerst „Ziel analysieren“ ausführen – "
                "der Job übernimmt den dort bestätigten Integrationsplan."
            ))
        else:
            jn_col, jp_col = st.columns([2, 1])
            job_name = jn_col.text_input(
                _("Job-Name"),
                value=(Path(output_dir).name or "Import"),
                key="new_job_name",
            )
            poll = jp_col.number_input(
                _("Watch-Intervall (Sekunden)"),
                min_value=5, value=30, step=5,
                key="new_job_poll",
            )
            job_build = st.toggle(
                _("Vault-Build + Such-Index nach jedem Lauf"),
                value=st.session_state.get("build_after", False),
                key="new_job_build",
                help=_(
                    "Nach jedem Lauf mit Neukonvertierungen: Notizen nach "
                    "Inbox/, Bilder nach Attachments/ mit Wikilinks, Index "
                    "und INDEX.md aktualisieren. Die Watch-Pipeline liefert "
                    "damit direkt den fertigen, durchsuchbaren Vault."
                ),
            )
            for line in dw.describe_plan(profile, config):
                st.caption(f"– {_(line)}")
            if st.button(_("Job speichern"), key="save_job"):
                try:
                    new_job = jm.add_job(
                        job_name, input_dir, output_dir, config,
                        poll_interval=int(poll), max_workers=max_workers,
                        build_vault=job_build,
                    )
                except ValueError as exc:
                    # z. B. Quell- und Zielordner identisch
                    st.error(_(str(exc)))
                else:
                    st.success(_(
                        "Job „{name}“ angelegt ({id}).",
                        name=new_job.name, id=new_job.id,
                    ))

    jobs = jm.load_jobs()
    if not jobs:
        st.caption(_("Noch keine Jobs angelegt."))

    for j in jobs:
        with st.container(border=True):
            head, act = st.columns([3, 2])
            head.markdown(f"**{j.name}** · `{j.id}`")
            head.caption(f"{j.source} → {j.target}")

            b1, b2, b3 = act.columns(3)
            check_clicked = b1.button(
                _("Prüfen"), key=f"plan_{j.id}",
                help=_("Dry-Run: zeigt, was beim nächsten Lauf anstünde."),
            )
            run_clicked = b2.button(
                _("Ausführen"), key=f"run_{j.id}",
                help=_("Neue und geänderte Dateien jetzt konvertieren."),
            )
            del_clicked = b3.button(
                _("Löschen"), key=f"del_{j.id}",
                help=_(
                    "Job samt Manifest und Verlauf entfernen. "
                    "Konvertierte Dateien bleiben erhalten."
                ),
            )

            if del_clicked:
                jm.remove_job(j.id)
                st.session_state.pop(f"check_{j.id}", None)
                st.rerun()

            if check_clicked:
                summary = jm.run_job(j, dry_run=True)
                st.session_state[f"check_{j.id}"] = summary.changes

            if run_clicked:
                run_bar = st.progress(0.0)
                run_txt = st.empty()

                def _cb(done, total, res, _bar=run_bar, _txt=run_txt):
                    _bar.progress(done / total)
                    _txt.caption(
                        f"{done}/{total} · {Path(res.source_path).name}"
                    )

                try:
                    summary = jm.run_job(j, progress=_cb, trigger="dashboard")
                except jm.JobLockedError as exc:
                    st.warning(_(str(exc)))
                except RuntimeError as exc:
                    # z. B. konfigurierte OCR-Engine nicht installiert
                    st.error(_(str(exc)))
                else:
                    run_bar.progress(1.0)
                    # Dry-Run-Ergebnis ist nach einem echten Lauf veraltet.
                    st.session_state.pop(f"check_{j.id}", None)
                    if summary.converted_ok or summary.converted_failed:
                        msg = _(
                            "{ok} konvertiert, {failed} Fehler "
                            "(neu: {new}, geändert: {changed}).",
                            ok=summary.converted_ok,
                            failed=summary.converted_failed,
                            new=summary.changes["neu"],
                            changed=summary.changes["geaendert"],
                        )
                        if summary.build_notes is not None:
                            msg += " " + _(
                                "Vault-Build: {notes} → Inbox/, "
                                "Index: {total} Notizen.",
                                notes=summary.build_notes,
                                total=summary.index_total,
                            )
                        st.success(msg)
                        if summary.build_error:
                            st.warning(_(
                                "Vault-Build fehlgeschlagen: {error}",
                                error=summary.build_error,
                            ))
                    else:
                        st.info(_("Keine neuen oder geänderten Dateien."))

            # Status nach eventuellen Aktionen laden (aktuelle Zahlen).
            done_n = _cached_manifest_ok(
                j.id, _file_mtime(jm._manifest_file(j.id))
            )
            job_fresh = jm.get_job(j.id) or j
            st.caption(
                _(
                    "Bereits konvertiert: {n} · Letzter Lauf: {last} · "
                    "Watch-Intervall: {poll}s",
                    n=done_n, last=job_fresh.last_run_at or "–",
                    poll=j.poll_interval,
                )
                + (" · " + _("Vault-Build + Index: aktiv")
                   if j.build_vault else "")
            )

            pending = st.session_state.get(f"check_{j.id}")
            if pending:
                st.caption(_(
                    "Anstehend – {items}",
                    items=" · ".join(f"{k}: {v}" for k, v in pending.items()),
                ))

            # Nachjustieren ohne rm + add: Manifest und Historie bleiben
            # erhalten, bereits Konvertiertes wird nicht wiederholt.
            # Wichtigster Fall: falsche OCR-Engine im gespeicherten Plan.
            job_cfg = job_fresh.converter_config()
            with st.expander(_("Job-Einstellungen ändern")):
                s_ocr = st.toggle(
                    _("OCR aktiv"), value=job_cfg.do_ocr, key=f"set_ocr_{j.id}",
                )
                engines = ["easyocr", "tesseract", "rapidocr"]
                s_engine = st.selectbox(
                    _("OCR-Engine"), options=engines,
                    index=(engines.index(job_cfg.ocr_engine)
                           if job_cfg.ocr_engine in engines else 0),
                    key=f"set_engine_{j.id}",
                )
                s_langs = st.text_input(
                    _("OCR-Sprachen"), value=job_cfg.ocr_languages,
                    key=f"set_langs_{j.id}",
                )
                s_dedup = st.toggle(
                    _("Inhaltsgleiche neue Dateien überspringen"),
                    value=job_fresh.skip_duplicates,
                    key=f"set_dedup_{j.id}",
                    help=_(
                        "Neue Dateien, deren Inhalt (SHA-256) bereits "
                        "konvertiert wurde, werden übersprungen und im Lauf "
                        "als „duplikate“ ausgewiesen."
                    ),
                )
                if st.button(_("Übernehmen"), key=f"set_save_{j.id}"):
                    jm.update_job(j.id, skip_duplicates=s_dedup, config_updates={
                        "do_ocr": s_ocr,
                        "ocr_engine": s_engine,
                        "ocr_languages": s_langs,
                    })
                    warn = dw.check_ocr_engine(dw.ConverterConfig(
                        do_ocr=s_ocr, ocr_engine=s_engine, ocr_languages=s_langs,
                    ))
                    if warn:
                        st.warning(_(warn))
                    else:
                        st.success(_("Job aktualisiert – gilt ab dem nächsten Lauf."))

            history = _cached_history(j.id, _file_mtime(jm._history_file(j.id)))
            with st.expander(_("Verlauf ({n} Läufe)", n=len(history))):
                if history:
                    def _build_cell(rec: dict) -> str:
                        if rec.get("build_error"):
                            return _("Fehler")
                        build = rec.get("build")
                        if build:
                            return (f"{build.get('notes', 0)} → Inbox "
                                    f"(Index {build.get('index_total', 0)})")
                        return "–"

                    hist_rows = [
                        {
                            _("Zeitpunkt"): rec.get("started_at", "–"),
                            _("Auslöser"): rec.get("trigger", "–"),
                            _("Neu"): rec.get("changes", {}).get("neu", 0),
                            _("Geändert"): rec.get("changes", {}).get("geaendert", 0),
                            _("Konvertiert"): rec.get("converted_ok", 0),
                            _("Fehler"): rec.get("converted_failed", 0),
                            "Build": _build_cell(rec),
                            _("Dauer (s)"): rec.get("duration_s", 0),
                        }
                        for rec in reversed(history)
                    ]
                    st.dataframe(hist_rows, width="stretch", hide_index=True)
                    last_fail = next(
                        (rec for rec in reversed(history) if rec.get("failures")),
                        None,
                    )
                    if last_fail:
                        st.caption(_("Fehler im letzten fehlerhaften Lauf:"))
                        for f in last_fail["failures"]:
                            st.caption(
                                f"– {Path(f.get('file', '')).name}: "
                                f"{f.get('error', '')}"
                            )
                else:
                    st.caption(_("Noch keine Läufe protokolliert."))

            st.caption(_("Dauerhafte Überwachung (eigener Prozess oder Dienst):"))
            st.code(f"doc2vault-jobs watch {j.id}", language="bash")

# ===========================================================================
# Tab 3: Suche & KI (Such-Index, Ollama-Embeddings und -Tagging)
# ===========================================================================
with tab_search:
    if not output_dir:
        st.info(_(
            "In der Seitenleiste einen Ziel-Vault-Ordner angeben – Suche und "
            "Index beziehen sich auf diesen Vault."
        ))
    elif not _ensure_dir(output_dir)[0]:
        st.error(_(
            "Ziel-Vault-Ordner kann nicht angelegt werden: {path}",
            path=output_dir,
        ))
    else:
        vault_path = Path(output_dir).resolve()

        # ---------------- Such-Index: Status + Aktualisierung -------------
        _overline(_("Such-Index"))
        status = vi.index_status(vault_path)
        if status["exists"]:
            line = _("{n} Notiz(en) indexiert", n=status["notes"])
            if status["last_indexed"]:
                line += " · " + _("zuletzt {ts}", ts=status["last_indexed"])
            if status["embedded_chunks"]:
                line += " · " + _(
                    "{n} Chunks mit Embeddings ({model})",
                    n=status["embedded_chunks"], model=status["embed_model"],
                )
            st.caption(line)
        else:
            st.caption(_(
                "Noch kein Index vorhanden – „Index aktualisieren“ ausführen "
                "oder die Konvertierung mit Vault-Build starten."
            ))
        if st.button(_("Index aktualisieren")):
            with st.spinner(_("Indexiere Notizen…")):
                isum = vi.update_index(vault_path)
                vi.write_index_md(vault_path)
            st.success(_(
                "{indexed} neu/geändert, {unchanged} unverändert, "
                "{removed} entfernt ({total} Notizen gesamt). "
                "INDEX.md aktualisiert.",
                indexed=isum.indexed, unchanged=isum.unchanged,
                removed=isum.removed, total=isum.total,
            ))

        # ---------------- Suche -------------------------------------------
        _overline(_("Suche"))
        q_col, m_col, n_col = st.columns([3, 1.5, 0.9])
        search_term = q_col.text_input(
            _("Suchbegriff oder Frage"), key="search_term",
            placeholder=_("z. B. Wartungsplan Photovoltaik"),
        )
        # Optionswerte bleiben deutsch (Vergleich unten) -- Anzeige via
        # format_func.
        search_mode = m_col.radio(
            _("Modus"),
            options=["Volltext", "Semantisch"],
            format_func=_,
            help=_(
                "Volltext: FTS5 über Titel, Tags, Schlagwörter und den "
                "kompletten Inhalt. Semantisch: Ähnlichkeitssuche über die "
                "Ollama-Embeddings (unten zuerst berechnen)."
            ),
        )
        search_top = n_col.number_input(_("Treffer"), 1, 50, 10)

        if st.button(_("Suchen"), type="primary") and search_term:
            if search_mode == "Volltext":
                hits = vi.query_index(vault_path, search_term,
                                      limit=int(search_top))
                if not hits:
                    st.info(_("Keine Treffer."))
                for h in hits:
                    with st.container(border=True):
                        title_line = f"**{h['title']}** · `{h['path']}`"
                        if h["tags"]:
                            title_line += " · " + " ".join(
                                f"#{t}" for t in h["tags"].split()
                            )
                        st.markdown(title_line)
                        st.caption(f"… {h['snippet']}")
            else:
                client = vi.OllamaClient(
                    st.session_state.get("ollama_url") or None
                )
                try:
                    hits = vi.similar(
                        vault_path, search_term, client,
                        model=st.session_state.get("embed_model"),
                        top_k=int(search_top),
                    )
                except vi.OllamaError as exc:
                    st.error(_(str(exc)))
                else:
                    if not hits:
                        st.info(_("Keine Treffer."))
                    for h in hits:
                        with st.container(border=True):
                            heading = f" › {h['heading']}" if h["heading"] else ""
                            st.markdown(
                                f"**{h['score']:.3f}** · `{h['path']}`{heading}"
                            )
                            st.caption(h["text"])

        # ---------------- Ollama: Verbindung, Embeddings, Tagging ---------
        _overline(_("Ollama (Embeddings & Tagging)"))
        st.caption(_(
            "Additiv: Ohne erreichbares Ollama funktionieren Konvertierung, "
            "Vault-Build und Volltextsuche uneingeschränkt."
        ))
        u_col, c_col = st.columns([3, 1])
        ollama_url = u_col.text_input(
            _("Ollama-URL"),
            value=st.session_state.get(
                "ollama_url",
                os.environ.get("DOC2VAULT_OLLAMA_URL", vi.DEFAULT_OLLAMA_URL),
            ),
            help=_("Auch per Umgebungsvariable DOC2VAULT_OLLAMA_URL setzbar."),
        )
        st.session_state["ollama_url"] = ollama_url
        c_col.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if c_col.button(_("Verbindung prüfen"), width="stretch"):
            try:
                found = vi.OllamaClient(ollama_url).list_models()
            except vi.OllamaError as exc:
                st.session_state.pop("ollama_models", None)
                st.error(_(str(exc)))
            else:
                st.session_state["ollama_models"] = found
                st.success(_("Verbunden – {n} Modell(e) verfügbar.", n=len(found)))

        models = st.session_state.get("ollama_models")
        if not models:
            st.caption(_(
                "Modellauswahl und Aktionen erscheinen nach erfolgreicher "
                "Verbindungsprüfung (Liste kommt live vom Server, /api/tags)."
            ))
        else:
            def _default_idx(candidates: list[str], want_embed: bool) -> int:
                env = os.environ.get(
                    "DOC2VAULT_EMBED_MODEL" if want_embed else "DOC2VAULT_TAG_MODEL"
                )
                for i, name in enumerate(candidates):
                    if env and name.startswith(env):
                        return i
                for i, name in enumerate(candidates):
                    if ("embed" in name.lower()) == want_embed:
                        return i
                return 0

            e_col, t_col = st.columns(2)
            embed_model = e_col.selectbox(
                _("Embedding-Modell"), models,
                index=_default_idx(models, want_embed=True),
                key="embed_model",
            )
            tag_model = t_col.selectbox(
                _("Tagging-Modell"), models,
                index=_default_idx(models, want_embed=False),
                key="tag_model",
            )
            write_notes = st.toggle(
                _("Tags/Summary ins Frontmatter der Notizen schreiben"),
                value=False,
                help=_(
                    "Neue Tags werden mit vorhandenen manuellen Tags "
                    "gemergt, nie ersetzt. Ohne diese Option landet das "
                    "Ergebnis nur im Such-Index."
                ),
            )

            a_col, b_col = st.columns(2)
            if a_col.button(_("Embeddings berechnen"), width="stretch"):
                bar = st.progress(0.0)
                txt = st.empty()

                def _emb_cb(done, total, rel, _b=bar, _t=txt):
                    _b.progress(done / max(total, 1))
                    _t.caption(f"{done}/{total} · {rel}")

                try:
                    with st.spinner(_("Berechne Embeddings…")):
                        esum = vi.embed_vault(
                            vault_path, vi.OllamaClient(ollama_url),
                            embed_model, progress=_emb_cb,
                        )
                except vi.OllamaError as exc:
                    st.error(_(str(exc)))
                else:
                    bar.progress(1.0)
                    st.success(_(
                        "{new} Chunks neu, {reused} wiederverwendet "
                        "(Modell {model}, Dimension {dim}).",
                        new=esum.chunks_embedded, reused=esum.chunks_reused,
                        model=esum.model, dim=esum.dimension,
                    ))

            if b_col.button(_("Tagging ausführen"), width="stretch"):
                bar = st.progress(0.0)
                txt = st.empty()

                def _tag_cb(done, total, rel, _b=bar, _t=txt):
                    _b.progress(done / max(total, 1))
                    _t.caption(f"{done}/{total} · {rel}")

                try:
                    with st.spinner(_("Erzeuge Tags und Zusammenfassungen…")):
                        tsum = vi.tag_vault(
                            vault_path, vi.OllamaClient(ollama_url),
                            tag_model, write_notes=write_notes,
                            progress=_tag_cb,
                        )
                        vi.write_index_md(vault_path)
                except vi.OllamaError as exc:
                    st.error(_(str(exc)))
                else:
                    bar.progress(1.0)
                    st.success(
                        _(
                            "{tagged} Notiz(en) getaggt, {unchanged} "
                            "unverändert, {errors} unbrauchbare Antworten.",
                            tagged=tsum.tagged, unchanged=tsum.unchanged,
                            errors=tsum.parse_errors,
                        )
                        + (" " + _("Tags/Summary im Frontmatter aktualisiert.")
                           if write_notes else "")
                    )

# ===========================================================================
# Tab 4: Datenaustausch (Ad-hoc-Upload/-Download fuer den Server-Betrieb)
# ===========================================================================
with tab_transfer:
    st.caption(_(
        "Für kleine Datenmengen ohne gemountete Ordner: Dateien hochladen, "
        "konvertieren, Ergebnis als ZIP herunterladen. Große Bestände gehören "
        "auf gemountete Ordner oder Netzwerk-Shares – siehe README, Abschnitt "
        "„Headless-Server & Docker“."
    ))

    _overline(_("Dateien hochladen"))
    if not input_dir:
        st.info(_(
            "Zuerst in der Seitenleiste einen Quellordner angeben – Uploads "
            "werden in dessen Unterordner „uploads“ abgelegt."
        ))
    else:
        upload_root = Path(input_dir) / "uploads"
        uploaded = st.file_uploader(
            _("Dokumente oder ZIP-Archive"),
            accept_multiple_files=True,
            type=[e.lstrip(".") for e in sorted(dw.SUPPORTED_EXTENSIONS)] + ["zip"],
            help=_(
                "ZIP-Archive werden serverseitig entpackt (Ordnerstruktur "
                "bleibt erhalten). Ablage unter {path}",
                path=upload_root,
            ),
        )
        if uploaded and st.button(_("Hochladen und ablegen"), type="primary"):
            try:
                stored = ft.store_uploads(
                    [(f.name, f) for f in uploaded], upload_root
                )
            except ft.UnsafeZipError as exc:
                st.error(_("ZIP abgelehnt: {error}", error=exc))
            else:
                st.success(_(
                    "{n} Datei(en) abgelegt unter `{path}`. Der Ordner liegt "
                    "im Quellordner und wird beim nächsten Scan bzw. Lauf "
                    "mit verarbeitet.",
                    n=len(stored), path=upload_root,
                ))

    _overline(_("Ergebnis herunterladen"))
    default_dl = ""
    if output_dir:
        import_dir = Path(output_dir) / dw.DEFAULT_IMPORT_SUBDIR
        default_dl = str(import_dir if import_dir.is_dir() else output_dir)
    download_dir = st.text_input(
        _("Ordner für den Download"),
        value=default_dl,
        placeholder=_("/pfad/zum/vault"),
        help=_(
            "Der Ordner wird rekursiv als ZIP verpackt (versteckte Ordner "
            "wie .obsidian ausgenommen)."
        ),
    )
    if download_dir:
        folder = Path(download_dir)
        if not folder.is_dir():
            st.error(_("Ordner existiert nicht."))
        else:
            # folder_size laeuft rekursiv ueber den ganzen Vault -- gecacht,
            # sonst wird JEDE Dashboard-Interaktion (Streamlit rendert alle
            # Tabs bei jedem Rerun) bei grossen Vaults sekundenlang zaeh.
            size = _cached_folder_size(str(folder))
            st.caption(_(
                "Geschätzte Größe (unkomprimiert): {size}",
                size=ft.format_size(size),
            ))
            if size > 2 * 1024**3:
                st.warning(_(
                    "Über 2 GB – der Browser-Download wird zäh. Für große "
                    "Vaults besser einen gemounteten Ordner oder ein "
                    "Netzwerk-Share verwenden."
                ))
            if st.button(_("ZIP erstellen")):
                import tempfile

                # Vorheriges Temp-ZIP (potenziell GB) aufraeumen, sonst
                # sammeln sich bei jedem Klick komplette Vault-Kopien an.
                old = st.session_state.get("download_zip")
                if old:
                    Path(old).unlink(missing_ok=True)
                with st.spinner(_("Verpacke Ordner…")):
                    fd, tmp_name = tempfile.mkstemp(suffix=".zip")
                    os.close(fd)   # mkstemp-Descriptor sofort schliessen
                    tmp = Path(tmp_name)
                    ft.zip_folder(folder, tmp)
                st.session_state["download_zip"] = str(tmp)
                st.session_state["download_zip_name"] = f"{folder.name or 'vault'}.zip"

            zip_path = st.session_state.get("download_zip")
            if zip_path and Path(zip_path).exists():
                with open(zip_path, "rb") as fh:
                    st.download_button(
                        _(
                            "{name} herunterladen ({size})",
                            name=st.session_state["download_zip_name"],
                            size=ft.format_size(Path(zip_path).stat().st_size),
                        ),
                        data=fh,
                        file_name=st.session_state["download_zip_name"],
                        mime="application/zip",
                        type="primary",
                    )
