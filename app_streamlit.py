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
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import streamlit as st

import docling_worker as dw
import job_manager as jm

st.set_page_config(
    page_title="Docling Vault Tool",
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
# Render-Helfer
# ---------------------------------------------------------------------------

def _overline(text: str) -> None:
    st.markdown(f'<div class="overline">{text}</div>', unsafe_allow_html=True)


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
    """file://-URI zum direkten Oeffnen im Ursprungsordner."""
    try:
        return Path(path).resolve().as_uri()
    except Exception:  # noqa: BLE001 -- z. B. ungueltiger Pfad
        return ""


def _render_failures(failures: list) -> None:
    """Fehlerprotokoll: Kategorien, Tabelle mit Quellenlinks, Details, CSV."""
    _overline("Fehlerprotokoll")

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
        width="stretch",
        hide_index=True,
        column_config={
            "Datei öffnen": st.column_config.LinkColumn(
                "Datei öffnen", display_text="Datei öffnen"
            ),
            "Ordner öffnen": st.column_config.LinkColumn(
                "Ordner öffnen", display_text="Ordner öffnen"
            ),
        },
    )
    st.caption(
        "Hinweis: Manche Browser blockieren file://-Links. In dem Fall den "
        "Pfad aus der Spalte „Pfad“ kopieren."
    )

    st.markdown("**Details je Datei**")
    for r in failures:
        p = Path(r.source_path)
        with st.expander(f"{p.name} – {r.error or 'Fehler'}"):
            st.write(f"**Kategorie:** {r.error_category or 'fehler'}")
            if r.error_hint:
                st.write(f"**Hinweis:** {r.error_hint}")
            st.write(f"**Original:** `{p}`")
            uri = _file_uri(str(p))
            if uri:
                st.markdown(
                    f"[Datei öffnen]({uri}) · "
                    f"[Ordner öffnen]({_file_uri(str(p.parent))})"
                )
            st.code(r.error_detail or r.error or "", language="text")

    st.download_button(
        "Fehlerprotokoll als CSV herunterladen",
        data=_errors_to_csv(failures),
        file_name="docling_fehler.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------------------------
# Kopfbereich
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div class="app-header">
      <div class="app-kicker">Batch-Konvertierung für Wissens-Vaults</div>
      <h1>Docling Vault Tool</h1>
      <p>Konvertiert PDF-, Word-, Excel- und PowerPoint-Dokumente in strukturiertes
      Markdown für Obsidian-kompatible Vaults. Überschriften und Tabellen bleiben
      erhalten, eingebettete Bilder werden extrahiert, jede Notiz erhält Metadaten
      mit Rückverweis auf das Original.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar: Einstellungen
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="side-label">Verzeichnisse</div>', unsafe_allow_html=True)
    input_dir = st.text_input(
        "Quellordner",
        value=st.session_state.get("input_dir", ""),
        placeholder="/pfad/zu/den/dokumenten",
        help="Wird rekursiv nach unterstützten Dateien durchsucht.",
    )
    output_dir = st.text_input(
        "Ziel-Vault-Ordner",
        value=st.session_state.get("output_dir", ""),
        placeholder="/pfad/zum/vault",
        help="Zielordner für die Markdown-Dateien. Bestehende Vaults werden "
        "analysiert und die Dateien entsprechend eingegliedert.",
    )

    st.markdown('<div class="side-label">Verarbeitung</div>', unsafe_allow_html=True)
    cpu_count = os.cpu_count() or 2
    max_workers = st.slider(
        "Parallele Prozesse",
        min_value=1,
        max_value=cpu_count,
        value=max(1, cpu_count - 1),
        help="Docling ist CPU- und speicherintensiv. Bei knappem RAM reduzieren.",
    )
    do_ocr = st.toggle(
        "OCR für gescannte PDFs",
        value=False,
        help="Nur für Scans ohne Textebene aktivieren – deutlich langsamer.",
    )

    st.markdown(
        '<div class="side-label">Nach erfolgreicher Konvertierung</div>',
        unsafe_allow_html=True,
    )
    on_success_label = st.radio(
        "Originaldateien",
        options=["Behalten", "In Archiv verschieben", "Löschen"],
        index=0,
        help="Betrifft nur erfolgreich konvertierte Dateien. Fehlgeschlagene "
        "Dateien bleiben immer unangetastet.",
    )
    on_success = {
        "Behalten": "keep",
        "In Archiv verschieben": "archive",
        "Löschen": "delete",
    }[on_success_label]
    archive_dir = ""
    if on_success == "archive":
        archive_dir = st.text_input(
            "Archiv-Ordner",
            value=st.session_state.get("archive_dir", ""),
            placeholder="/pfad/zum/archiv",
            help="Die Struktur des Quellordners wird im Archiv gespiegelt.",
        )
        st.session_state["archive_dir"] = archive_dir
    elif on_success == "delete":
        st.warning("Originale werden nach Erfolg unwiderruflich gelöscht.")

    st.divider()
    st.caption(
        "Unterstützte Formate: "
        + ", ".join(sorted(e.lstrip(".") for e in dw.SUPPORTED_EXTENSIONS))
    )

st.session_state["input_dir"] = input_dir
st.session_state["output_dir"] = output_dir

# Fuer den Jobs-Tab: Plan aus dem Konvertierungs-Tab.
profile = None
config: dw.ConverterConfig | None = None

tab_convert, tab_jobs = st.tabs(["Konvertierung", "Jobs & Überwachung"])

# ===========================================================================
# Tab 1: Konvertierung
# ===========================================================================
with tab_convert:
    col_scan, col_analyze = st.columns(2)
    scan = col_scan.button("Dateien scannen", width="stretch")
    analyze = col_analyze.button("Ziel analysieren", type="primary", width="stretch")

    if scan:
        if not input_dir or not Path(input_dir).is_dir():
            st.error("Bitte einen gültigen Quellordner angeben.")
        else:
            files = dw.discover_files(
                input_dir, exclude_dirs=(output_dir, archive_dir)
            )
            st.session_state["scanned_files"] = [str(f) for f in files]
            st.success(f"{len(files)} unterstützte Datei(en) gefunden.")
    elif st.session_state.get("scanned_files"):
        st.caption(
            f"Letzter Scan: {len(st.session_state['scanned_files'])} Datei(en)."
        )

    # --- Schritt 1: Ziel analysieren --------------------------------------
    if analyze:
        if not output_dir:
            st.error("Bitte einen Ziel-Vault-Ordner angeben.")
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

        _overline("Zielordner-Analyse")
        type_label = {
            "obsidian": "Obsidian-Vault",
            "logseq": "Logseq-Graph",
            "folder": "Bestehender Ordner",
            "new": "Neuer Ordner",
        }.get(profile.vault_type, profile.vault_type)
        a1, a2, a3 = st.columns(3)
        a1.metric("Zieltyp", type_label)
        a2.metric("Vorhandene Notizen", profile.note_count)
        a3.metric("Ordner auf oberster Ebene", len(profile.top_level_folders))
        for obs in profile.observations:
            st.caption(f"– {obs}")
        if profile.top_level_folders:
            st.caption(
                "Bestehende Ordner: "
                + ", ".join(profile.top_level_folders[:12])
                + (" …" if len(profile.top_level_folders) > 12 else "")
            )

        _overline("Integrationsplan")
        if profile.vault_type in ("obsidian", "logseq") and not profile.is_empty:
            st.info(
                "Bestehender Vault erkannt. Die Dateien werden entsprechend der "
                "Vault-Konventionen eingegliedert – bitte den Plan prüfen und "
                "einmal für den gesamten Batch bestätigen."
            )

        c1, c2 = st.columns(2)
        with c1:
            placement = st.radio(
                "Ablage der Notizen",
                options=["Eigener Unterordner", "Ziel-Wurzel"],
                index=0 if reco.notes_subdir else 1,
                help="Ein eigener Unterordner hält einen kuratierten Vault "
                "sauber. Die Ziel-Wurzel fügt sich in bestehende gleichnamige "
                "Ordner ein.",
            )
            notes_subdir = ""
            if placement == "Eigener Unterordner":
                notes_subdir = st.text_input(
                    "Name des Unterordners",
                    value=reco.notes_subdir or dw.DEFAULT_IMPORT_SUBDIR,
                )
            add_frontmatter = st.toggle(
                "Frontmatter-Properties schreiben",
                value=reco.add_frontmatter,
                help="source, original_path und assets_folder als "
                "Obsidian-Properties.",
            )
        with c2:
            attach_adjacent = st.toggle(
                "Anhänge neben der Notiz ablegen",
                value=(reco.attachments_mode == "adjacent"),
                help="Aktiviert: ein Ordner je Notiz (Obsidian-Einstellung "
                "„neben der Notiz“). Deaktiviert: ein zentraler Anhang-Ordner.",
            )
            attachments_subdir = reco.attachments_subdir
            if not attach_adjacent:
                attachments_subdir = st.text_input(
                    "Zentraler Anhang-Ordner",
                    value=reco.attachments_subdir or "assets",
                )
            mirror = st.toggle(
                "Quellstruktur spiegeln",
                value=reco.mirror_structure,
                help="Unterordner des Quellordners im Ziel nachbilden.",
            )

        config = dw.ConverterConfig(
            do_ocr=do_ocr,
            on_success=on_success,
            archive_dir=str(Path(archive_dir).resolve()) if archive_dir else None,
            notes_subdir=notes_subdir,
            mirror_structure=mirror,
            attachments_mode="adjacent" if attach_adjacent else "central",
            attachments_subdir=attachments_subdir,
            add_frontmatter=add_frontmatter,
        )

        with st.container(border=True):
            st.markdown("**Zusammenfassung**")
            for line in dw.describe_plan(profile, config):
                st.markdown(f"- {line}")

        confirm = st.button(
            "Plan bestätigen und Konvertierung starten",
            type="primary",
            width="stretch",
        )
    else:
        st.caption(
            "Ziel-Vault-Ordner angeben und „Ziel analysieren“ ausführen. "
            "Der Integrationsplan wird anschließend zur Bestätigung angezeigt."
        )

    # --- Schritt 3: Konvertierung (nach Bestaetigung) ----------------------
    if confirm and config is not None:
        if not input_dir or not Path(input_dir).is_dir():
            st.error("Bitte einen gültigen Quellordner angeben.")
            st.stop()
        if on_success == "archive" and not archive_dir:
            st.error("Für „In Archiv verschieben“ bitte einen Archiv-Ordner angeben.")
            st.stop()

        input_root = Path(input_dir).resolve()
        out_root = Path(output_dir).resolve()
        out_root.mkdir(parents=True, exist_ok=True)

        files = dw.discover_files(
            input_root, exclude_dirs=(out_root, config.archive_dir)
        )
        total = len(files)
        if total == 0:
            st.warning("Keine unterstützten Dateien gefunden.")
            st.stop()

        _overline("Fortschritt")
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
                        source_path=str(futures[future]),
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
                ph_eta.metric("Restzeit", _format_duration(eta))
                ph_current.caption(f"Zuletzt: {Path(res.source_path).name}")

        st.session_state["last_run"] = {
            "target": str(out_root),
            "duration": time.perf_counter() - start_time,
            "ok": ok,
            "images": images_total,
            "moved": moved,
            "on_success": on_success,
            "failures": failures,
        }

    # --- Ergebnis (persistiert ueber Reruns) -------------------------------
    last = st.session_state.get("last_run")
    if last:
        _overline("Ergebnis")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Konvertiert", last["ok"])
        r2.metric("Bilder extrahiert", last["images"])
        r3.metric("Fehler", len(last["failures"]))
        r4.metric("Dauer", _format_duration(last["duration"]))
        st.caption(f"Ziel: {last['target']}")
        if last["moved"]:
            verb = (
                "gelöscht" if last["on_success"] == "delete"
                else "ins Archiv verschoben"
            )
            st.caption(f"{last['moved']} Originaldatei(en) {verb}.")
        if last["failures"]:
            _render_failures(last["failures"])

# ===========================================================================
# Tab 2: Jobs & Ueberwachung
# ===========================================================================
with tab_jobs:
    st.caption(
        "Jobs verknüpfen Quell- und Zielordner mit dem bestätigten "
        "Integrationsplan und verarbeiten bei jedem Lauf nur neue oder "
        "geänderte Dateien – wiederaufsetzbar, mit Sperre gegen Doppelläufe. "
        "Zieldateien werden nie automatisch entfernt."
    )

    with st.expander("Neuen Job anlegen"):
        if not input_dir or not output_dir:
            st.info("Quell- und Ziel-Ordner in der Seitenleiste angeben.")
        elif config is None:
            st.info(
                "Im Tab „Konvertierung“ zuerst „Ziel analysieren“ ausführen – "
                "der Job übernimmt den dort bestätigten Integrationsplan."
            )
        else:
            jn_col, jp_col = st.columns([2, 1])
            job_name = jn_col.text_input(
                "Job-Name",
                value=(Path(output_dir).name or "Import"),
                key="new_job_name",
            )
            poll = jp_col.number_input(
                "Watch-Intervall (Sekunden)",
                min_value=5, value=30, step=5,
                key="new_job_poll",
            )
            for line in dw.describe_plan(profile, config):
                st.caption(f"– {line}")
            if st.button("Job speichern", key="save_job"):
                new_job = jm.add_job(
                    job_name, input_dir, output_dir, config,
                    poll_interval=int(poll), max_workers=max_workers,
                )
                st.success(f"Job „{new_job.name}“ angelegt ({new_job.id}).")

    jobs = jm.load_jobs()
    if not jobs:
        st.caption("Noch keine Jobs angelegt.")

    for j in jobs:
        with st.container(border=True):
            head, act = st.columns([3, 2])
            head.markdown(f"**{j.name}** · `{j.id}`")
            head.caption(f"{j.source} → {j.target}")

            b1, b2, b3 = act.columns(3)
            check_clicked = b1.button(
                "Prüfen", key=f"plan_{j.id}",
                help="Dry-Run: zeigt, was beim nächsten Lauf anstünde.",
            )
            run_clicked = b2.button(
                "Ausführen", key=f"run_{j.id}",
                help="Neue und geänderte Dateien jetzt konvertieren.",
            )
            del_clicked = b3.button(
                "Löschen", key=f"del_{j.id}",
                help="Job samt Manifest und Verlauf entfernen. "
                "Konvertierte Dateien bleiben erhalten.",
            )

            if del_clicked:
                jm.remove_job(j.id)
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
                    st.warning(str(exc))
                else:
                    run_bar.progress(1.0)
                    if summary.converted_ok or summary.converted_failed:
                        st.success(
                            f"{summary.converted_ok} konvertiert, "
                            f"{summary.converted_failed} Fehler "
                            f"(neu: {summary.changes['neu']}, "
                            f"geändert: {summary.changes['geaendert']})."
                        )
                    else:
                        st.info("Keine neuen oder geänderten Dateien.")

            # Status nach eventuellen Aktionen laden (aktuelle Zahlen).
            manifest = jm.load_manifest(j.id)
            done_n = sum(1 for e in manifest.values() if e.get("status") == "ok")
            job_fresh = jm.get_job(j.id) or j
            st.caption(
                f"Bereits konvertiert: {done_n} · "
                f"Letzter Lauf: {job_fresh.last_run_at or '–'} · "
                f"Watch-Intervall: {j.poll_interval}s"
            )

            pending = st.session_state.get(f"check_{j.id}")
            if pending:
                st.caption(
                    "Anstehend – "
                    + " · ".join(f"{k}: {v}" for k, v in pending.items())
                )

            history = jm.load_history(j.id)
            with st.expander(f"Verlauf ({len(history)} Läufe)"):
                if history:
                    hist_rows = [
                        {
                            "Zeitpunkt": rec.get("started_at", "–"),
                            "Auslöser": rec.get("trigger", "–"),
                            "Neu": rec.get("changes", {}).get("neu", 0),
                            "Geändert": rec.get("changes", {}).get("geaendert", 0),
                            "Konvertiert": rec.get("converted_ok", 0),
                            "Fehler": rec.get("converted_failed", 0),
                            "Dauer (s)": rec.get("duration_s", 0),
                        }
                        for rec in reversed(history)
                    ]
                    st.dataframe(hist_rows, width="stretch", hide_index=True)
                    last_fail = next(
                        (rec for rec in reversed(history) if rec.get("failures")),
                        None,
                    )
                    if last_fail:
                        st.caption("Fehler im letzten fehlerhaften Lauf:")
                        for f in last_fail["failures"]:
                            st.caption(
                                f"– {Path(f.get('file', '')).name}: "
                                f"{f.get('error', '')}"
                            )
                else:
                    st.caption("Noch keine Läufe protokolliert.")

            st.caption("Dauerhafte Überwachung (eigener Prozess oder Dienst):")
            st.code(f"python job_manager.py watch {j.id}", language="bash")
