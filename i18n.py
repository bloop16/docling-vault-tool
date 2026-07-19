"""Leichtgewichtige Zweisprachigkeit fuer die Oberflaeche (Deutsch/Englisch).

Design: Die deutschen Originaltexte sind die Schluessel -- ``tr("Text")``
liefert bei Sprache "de" den Text unveraendert und schlaegt bei "en" im
Woerterbuch nach (Fallback: Deutsch, damit fehlende Uebersetzungen nie zu
Luecken fuehren). Platzhalter laufen ueber ``str.format``::

    tr("{n} Datei(en) gefunden.", n=5)

Die Sprache waehlt das Dashboard (Seitenleiste); Vorbelegung ueber die
Umgebungsvariable ``DOC2VAULT_LANG`` (``de``/``en``). CLI-Ausgaben und die
Fehlerhinweise der Konvertierung bleiben in dieser Ausbaustufe Deutsch --
die Hinweise werden aber bei der Anzeige im Dashboard mituebersetzt, wenn
ein Eintrag existiert.
"""

from __future__ import annotations

import os

LANGUAGES = {"de": "Deutsch", "en": "English"}

_current = os.environ.get("DOC2VAULT_LANG", "de").lower()
if _current not in LANGUAGES:
    _current = "de"


def set_language(lang: str) -> None:
    global _current
    if lang in LANGUAGES:
        _current = lang


def get_language() -> str:
    return _current


def tr(text: str, **kwargs) -> str:
    """Uebersetzt ``text`` in die aktive Sprache (Fallback: Original)."""
    if _current != "de":
        text = _TRANSLATIONS.get(_current, {}).get(text, text)
    return text.format(**kwargs) if kwargs else text


_EN: dict[str, str] = {
    # --- Kopf & Navigation --------------------------------------------------
    "Batch-Konvertierung für Wissens-Vaults": "Batch conversion for knowledge vaults",
    "Sprache": "Language",
    "Konvertierung": "Conversion",
    "Jobs & Überwachung": "Jobs & Watching",
    "Suche & KI": "Search & AI",
    "Datenaustausch": "File Transfer",
    "Konvertiert PDF-, Word-, Excel- und PowerPoint-Dokumente in strukturiertes Markdown für Obsidian-kompatible Vaults. Überschriften und Tabellen bleiben erhalten, eingebettete Bilder werden extrahiert, jede Notiz erhält Metadaten mit Rückverweis auf das Original.":
        "Converts PDF, Word, Excel and PowerPoint documents into structured Markdown for Obsidian-compatible vaults. Headings and tables are preserved, embedded images are extracted, and every note gets metadata with a back-reference to the original.",
    # --- Seitenleiste -------------------------------------------------------
    "/pfad/zu/den/dokumenten": "/path/to/the/documents",
    "/pfad/zum/archiv": "/path/to/the/archive",
    "/pfad/zum/vault": "/path/to/the/vault",
    "0 = alle Blätter konvertieren. Ein Limit begrenzt Laufzeit und Notizgröße bei Arbeitsmappen mit sehr vielen Blättern.":
        "0 = convert all sheets. A limit bounds runtime and note size for workbooks with very many sheets.",
    "Betrifft nur erfolgreich konvertierte Dateien. Fehlgeschlagene Dateien bleiben immer unangetastet.":
        "Affects only successfully converted files. Failed files are always left untouched.",
    "Die Struktur des Quellordners wird im Archiv gespiegelt; der Ordner wird bei Bedarf angelegt.":
        "The source folder structure is mirrored in the archive; the folder is created if needed.",
    "Docling ist CPU- und speicherintensiv. Bei knappem RAM reduzieren.":
        "Docling is CPU- and memory-intensive. Reduce when RAM is tight.",
    "EasyOCR (Standard): Modelle werden von GitHub geladen. Tesseract: erfordert lokale Installation, Sprachcodes wie „deu,eng“. RapidOCR: lädt Modelle von modelscope.cn – in vielen Netzen blockiert.":
        "EasyOCR (default): models are downloaded from GitHub. Tesseract: requires a local installation, language codes like “deu,eng”. RapidOCR: downloads models from modelscope.cn – blocked in many networks.",
    "Eingebettete Grafiken als eigene Dateien ablegen und in den Notizen verlinken. Deaktiviert: reine Textkonvertierung.":
        "Store embedded graphics as separate files and link them in the notes. Disabled: text-only conversion.",
    "Höhere Werte liefern schärfere Bilder, brauchen aber mehr Zeit und Speicherplatz.":
        "Higher values produce sharper images but need more time and disk space.",
    "Kommaliste der Erkennungssprachen.": "Comma-separated list of recognition languages.",
    "Nur erste Blätter konvertieren": "Convert first sheets only",
    "Nur für Scans ohne Textebene aktivieren – deutlich langsamer.":
        "Enable only for scans without a text layer – much slower.",
    "Originale werden nach Erfolg unwiderruflich gelöscht.":
        "Originals are irreversibly deleted after success.",
    "Rekonstruiert Tabellen als Markdown-Tabellen. Deaktiviert ist die Verarbeitung schneller, Tabellen werden aber zu Fließtext.":
        "Reconstructs tables as Markdown tables. Disabled, processing is faster but tables become plain text.",
    "Übersprungene Dateien erscheinen im Fehlerprotokoll. Bei „nur erste Blätter“ vermerkt das Frontmatter die Gesamtzahl.":
        "Skipped files appear in the error log. With “first sheets only” the frontmatter records the total count.",
    "Unterstützte Formate: {formats}": "Supported formats: {formats}",
    "Wird rekursiv nach unterstützten Dateien durchsucht. „Durchsuchen…“ öffnet die Ordnerauswahl.":
        "Searched recursively for supported files. “Browse…” opens the folder picker.",
    "Zielordner für die Markdown-Dateien; wird bei Bedarf automatisch angelegt. Bestehende Vaults werden analysiert und die Dateien entsprechend eingegliedert.":
        "Target folder for the Markdown files; created automatically if needed. Existing vaults are analyzed and the files integrated accordingly.",
    "Verzeichnisse": "Directories",
    "Quellordner": "Source folder",
    "Ziel-Vault-Ordner": "Target vault folder",
    "Archiv-Ordner": "Archive folder",
    "Durchsuchen…": "Browse…",
    "Verarbeitung": "Processing",
    "Parallele Prozesse": "Parallel processes",
    "Docling-Funktionen": "Docling features",
    "Bilder extrahieren": "Extract images",
    "Bildauflösung (Skalierung)": "Image resolution (scale)",
    "Tabellenstruktur erkennen": "Detect table structure",
    "OCR für gescannte PDFs": "OCR for scanned PDFs",
    "OCR-Engine": "OCR engine",
    "OCR-Sprachen": "OCR languages",
    "Excel-Arbeitsmappen": "Excel workbooks",
    "Sheet-Limit je Arbeitsmappe": "Sheet limit per workbook",
    "Bei Überschreitung": "When exceeded",
    "Nur erste Blätter": "First sheets only",
    "Datei überspringen": "Skip file",
    "Nach erfolgreicher Konvertierung": "After successful conversion",
    "Originaldateien": "Original files",
    "Behalten": "Keep",
    "In Archiv verschieben": "Move to archive",
    "Löschen": "Delete",
    # --- Konvertierungs-Tab -------------------------------------------------
    "Ablage der Notizen": "Note placement",
    "Aktiviert: ein Ordner je Notiz (Obsidian-Einstellung „neben der Notiz“). Deaktiviert: ein zentraler Anhang-Ordner.":
        "Enabled: one folder per note (Obsidian setting “next to the note”). Disabled: one central attachments folder.",
    "Anhänge neben der Notiz ablegen": "Store attachments next to the note",
    "Bestehende Ordner: {folders}": "Existing folders: {folders}",
    "Bestehender Ordner": "Existing folder",
    "Bestehender Vault erkannt. Die Dateien werden entsprechend der Vault-Konventionen eingegliedert – bitte den Plan prüfen und einmal für den gesamten Batch bestätigen.":
        "Existing vault detected. The files will be integrated following the vault conventions – please review the plan and confirm once for the whole batch.",
    "Bitte einen Ziel-Vault-Ordner angeben.": "Please provide a target vault folder.",
    "Danach: Vault-Build (Inbox/, Attachments/, Wikilinks) + Such-Index":
        "Then: vault build (Inbox/, Attachments/, wikilinks) + search index",
    "Eigener Unterordner": "Dedicated subfolder",
    "Ein eigener Unterordner hält einen kuratierten Vault sauber. Die Ziel-Wurzel fügt sich in bestehende gleichnamige Ordner ein.":
        "A dedicated subfolder keeps a curated vault tidy. The target root merges into existing folders of the same name.",
    "Frontmatter-Properties schreiben": "Write frontmatter properties",
    "Logseq-Graph": "Logseq graph",
    "Name des Unterordners": "Subfolder name",
    "Neuer Ordner": "New folder",
    "Obsidian-Vault": "Obsidian vault",
    "Post-Processing: Notizen nach Inbox/, Bilder nach Attachments/ mit Obsidian-Wikilinks, normiertes Frontmatter; Such-Index und INDEX.md werden automatisch aktualisiert. Bestehende Notizen des Vaults bleiben unangetastet.":
        "Post-processing: notes to Inbox/, images to Attachments/ with Obsidian wikilinks, normalized frontmatter; search index and INDEX.md are updated automatically. Existing notes in the vault are left untouched.",
    "Quellstruktur spiegeln": "Mirror source structure",
    "source, original_path und assets_folder als Obsidian-Properties.":
        "source, original_path and assets_folder as Obsidian properties.",
    "Unterordner des Quellordners im Ziel nachbilden.":
        "Recreate the source folder's subfolders in the target.",
    "Vault-Build: {notes} Notiz(en) → Inbox/, {images} Bild(er) → Attachments/ · Such-Index: {index_total} Notizen, INDEX.md aktualisiert":
        "Vault build: {notes} note(s) → Inbox/, {images} image(s) → Attachments/ · search index: {index_total} notes, INDEX.md updated",
    "{n} Kollision(en) aufgelöst": "{n} collision(s) resolved",
    "Zentraler Anhang-Ordner": "Central attachments folder",
    "Ziel-Vault-Ordner angeben und „Ziel analysieren“ ausführen. Der Integrationsplan wird anschließend zur Bestätigung angezeigt.":
        "Provide a target vault folder and run “Analyze target”. The integration plan is then shown for confirmation.",
    "Ziel-Wurzel": "Target root",
    "Vault-Build und Such-Index…": "Vault build and search index…",
    "Dateien scannen": "Scan files",
    "Ziel analysieren": "Analyze target",
    "{n} unterstützte Datei(en) gefunden.": "{n} supported file(s) found.",
    "Letzter Scan: {n} Datei(en).": "Last scan: {n} file(s).",
    "Bitte einen gültigen Quellordner angeben.": "Please provide a valid source folder.",
    "Zielordner-Analyse": "Target folder analysis",
    "Zieltyp": "Target type",
    "Vorhandene Notizen": "Existing notes",
    "Ordner auf oberster Ebene": "Top-level folders",
    "Integrationsplan": "Integration plan",
    "Zusammenfassung": "Summary",
    "Plan bestätigen und Konvertierung starten": "Confirm plan and start conversion",
    "Vault-Build nach der Konvertierung": "Vault build after conversion",
    "Fortschritt": "Progress",
    "Verarbeitet": "Processed",
    "Erfolgreich": "Successful",
    "Fehler": "Errors",
    "Restzeit": "Time left",
    "Zuletzt: {name}": "Last: {name}",
    "Konvertierung abbrechen": "Cancel conversion",
    "Ergebnis": "Result",
    "Konvertiert": "Converted",
    "Bilder extrahiert": "Images extracted",
    "Dauer": "Duration",
    "Ziel: {target}": "Target: {target}",
    "Keine unterstützten Dateien gefunden.": "No supported files found.",
    "Konvertierung abgebrochen. Bereits fertig konvertierte Dateien bleiben erhalten.":
        "Conversion cancelled. Files already converted are kept.",
    "Der letzte Lauf wurde unterbrochen. Bereits konvertierte Dateien bleiben erhalten – einfach erneut starten.":
        "The last run was interrupted. Files already converted are kept – just start again.",
    "{n} Originaldatei(en) gelöscht.": "{n} original file(s) deleted.",
    "{n} Originaldatei(en) ins Archiv verschoben.": "{n} original file(s) moved to the archive.",
    "{n} Datei(en) mit reduzierten Einstellungen konvertiert (riesige Seiten, z. B. CAD-Pläne: Bildskalierung 1.0, ohne Bildextraktion).":
        "{n} file(s) converted with reduced settings (huge pages, e.g. CAD drawings: image scale 1.0, no image extraction).",
    "{n} PDF(s) über den alternativen pypdfium-Parser konvertiert (Standard-Parser lehnte die Datei ab).":
        "{n} PDF(s) converted via the alternative pypdfium parser (default parser rejected the file).",
    "{n} Duplikatgruppe(n) mit {m} inhaltsgleichen Dateien gefunden (per CLI-Flag `--duplicates skip` bzw. Job-Option überspringbar).":
        "{n} duplicate group(s) with {m} identical files found (skippable via CLI flag `--duplicates skip` or the job option).",
    "Bilddateien im Quellordner, aber OCR ist aus – gescannte Bilder ergeben leere Notizen. OCR in der Seitenleiste aktivieren.":
        "Image files in the source folder but OCR is off – scanned images produce empty notes. Enable OCR in the sidebar.",
    "Für „In Archiv verschieben“ bitte einen Archiv-Ordner angeben.":
        "Please provide an archive folder for “Move to archive”.",
    "Vault-Build fehlgeschlagen: {error}": "Vault build failed: {error}",
    # --- Fehlerprotokoll ----------------------------------------------------
    "Fehlerdetails": "Error details",
    "Fehlerprotokoll": "Error log",
    "Datei": "File",
    "Datei öffnen": "Open file",
    "Details je Datei": "Details per file",
    "Hinweis: Manche Browser blockieren file://-Links. In dem Fall den Pfad aus der Spalte „Pfad“ kopieren.":
        "Note: some browsers block file:// links. In that case copy the path from the “Path” column.",
    "Kategorie": "Category",
    "Kategorien: {items}": "Categories: {items}",
    "Hinweis": "Hint",
    "Ordner öffnen": "Open folder",
    "Pfad": "Path",
    "Fehlerprotokoll als CSV herunterladen": "Download error log as CSV",
    # CSV-Spaltenkoepfe des Fehlerprotokolls
    "datei": "file",
    "dauer_s": "duration_s",
    "fehler": "error",
    "hinweis": "hint",
    "kategorie": "category",
    "pfad": "path",
    # --- Jobs-Tab -----------------------------------------------------------
    "Anstehend – {items}": "Pending – {items}",
    "Dry-Run: zeigt, was beim nächsten Lauf anstünde.":
        "Dry run: shows what the next run would process.",
    "Fehler im letzten fehlerhaften Lauf:": "Errors in the last failed run:",
    "Im Tab „Konvertierung“ zuerst „Ziel analysieren“ ausführen – der Job übernimmt den dort bestätigten Integrationsplan.":
        "Run “Analyze target” in the “Conversion” tab first – the job adopts the integration plan confirmed there.",
    "Job samt Manifest und Verlauf entfernen. Konvertierte Dateien bleiben erhalten.":
        "Remove the job including manifest and history. Converted files are kept.",
    "Jobs verknüpfen Quell- und Zielordner mit dem bestätigten Integrationsplan und verarbeiten bei jedem Lauf nur neue oder geänderte Dateien – wiederaufsetzbar, mit Sperre gegen Doppelläufe. Zieldateien werden nie automatisch entfernt.":
        "Jobs link source and target folders to the confirmed integration plan and process only new or changed files on each run – resumable, with a lock against duplicate runs. Target files are never removed automatically.",
    "Nach jedem Lauf mit Neukonvertierungen: Notizen nach Inbox/, Bilder nach Attachments/ mit Wikilinks, Index und INDEX.md aktualisieren. Die Watch-Pipeline liefert damit direkt den fertigen, durchsuchbaren Vault.":
        "After every run with new conversions: notes to Inbox/, images to Attachments/ with wikilinks, update index and INDEX.md. The watch pipeline then directly delivers the finished, searchable vault.",
    "Neue und geänderte Dateien jetzt konvertieren.":
        "Convert new and changed files now.",
    "Neue Dateien, deren Inhalt (SHA-256) bereits konvertiert wurde, werden übersprungen und im Lauf als „duplikate“ ausgewiesen.":
        "New files whose content (SHA-256) was already converted are skipped and reported as “duplikate” in the run.",
    "Quell- und Ziel-Ordner in der Seitenleiste angeben.":
        "Provide source and target folders in the sidebar.",
    "Vault-Build + Index: aktiv": "Vault build + index: enabled",
    "Vault-Build: {notes} → Inbox/, Index: {total} Notizen.":
        "Vault build: {notes} → Inbox/, index: {total} notes.",
    "{ok} konvertiert, {failed} Fehler (neu: {new}, geändert: {changed}).":
        "{ok} converted, {failed} errors (new: {new}, changed: {changed}).",
    "Neuen Job anlegen": "Create new job",
    "Job-Name": "Job name",
    "Watch-Intervall (Sekunden)": "Watch interval (seconds)",
    "Vault-Build + Such-Index nach jedem Lauf": "Vault build + search index after every run",
    "Job speichern": "Save job",
    "Job „{name}“ angelegt ({id}).": "Job “{name}” created ({id}).",
    "Noch keine Jobs angelegt.": "No jobs created yet.",
    "Prüfen": "Check",
    "Ausführen": "Run",
    "Job-Einstellungen ändern": "Change job settings",
    "OCR aktiv": "OCR enabled",
    "Inhaltsgleiche neue Dateien überspringen": "Skip new files with identical content",
    "Übernehmen": "Apply",
    "Job aktualisiert – gilt ab dem nächsten Lauf.": "Job updated – takes effect on the next run.",
    "Bereits konvertiert: {n} · Letzter Lauf: {last} · Watch-Intervall: {poll}s":
        "Already converted: {n} · Last run: {last} · Watch interval: {poll}s",
    "Verlauf ({n} Läufe)": "History ({n} runs)",
    "Noch keine Läufe protokolliert.": "No runs recorded yet.",
    "Keine neuen oder geänderten Dateien.": "No new or changed files.",
    "Zeitpunkt": "Time",
    "Auslöser": "Trigger",
    "Neu": "New",
    "Geändert": "Changed",
    "Dauer (s)": "Duration (s)",
    "Dauerhafte Überwachung (eigener Prozess oder Dienst):": "Continuous watching (separate process or service):",
    # --- Suche & KI ---------------------------------------------------------
    "Additiv: Ohne erreichbares Ollama funktionieren Konvertierung, Vault-Build und Volltextsuche uneingeschränkt.":
        "Additive: without a reachable Ollama, conversion, vault build and full-text search work without restriction.",
    "Auch per Umgebungsvariable DOC2VAULT_OLLAMA_URL setzbar.":
        "Can also be set via the DOC2VAULT_OLLAMA_URL environment variable.",
    "Berechne Embeddings…": "Computing embeddings…",
    "Embedding-Modell": "Embedding model",
    "Embeddings berechnen": "Compute embeddings",
    "Erzeuge Tags und Zusammenfassungen…": "Generating tags and summaries…",
    "In der Seitenleiste einen Ziel-Vault-Ordner angeben – Suche und Index beziehen sich auf diesen Vault.":
        "Provide a target vault folder in the sidebar – search and index refer to this vault.",
    "Indexiere Notizen…": "Indexing notes…",
    "Modellauswahl und Aktionen erscheinen nach erfolgreicher Verbindungsprüfung (Liste kommt live vom Server, /api/tags).":
        "Model selection and actions appear after a successful connection check (list comes live from the server, /api/tags).",
    "Modus": "Mode",
    "Neue Tags werden mit vorhandenen manuellen Tags gemergt, nie ersetzt. Ohne diese Option landet das Ergebnis nur im Such-Index.":
        "New tags are merged with existing manual tags, never replaced. Without this option the result only goes into the search index.",
    "Noch kein Index vorhanden – „Index aktualisieren“ ausführen oder die Konvertierung mit Vault-Build starten.":
        "No index yet – run “Update index” or start the conversion with vault build.",
    "Ollama (Embeddings & Tagging)": "Ollama (embeddings & tagging)",
    "Ollama-URL": "Ollama URL",
    "Semantisch": "Semantic",
    "Suchbegriff oder Frage": "Search term or question",
    "Suche": "Search",
    "Such-Index": "Search index",
    "Tagging ausführen": "Run tagging",
    "Tagging-Modell": "Tagging model",
    "Tags/Summary im Frontmatter aktualisiert.": "Tags/summary updated in the frontmatter.",
    "Tags/Summary ins Frontmatter der Notizen schreiben":
        "Write tags/summary into the notes' frontmatter",
    "Treffer": "Hits",
    "Verbunden – {n} Modell(e) verfügbar.": "Connected – {n} model(s) available.",
    "Volltext": "Full text",
    "Volltext: FTS5 über Titel, Tags, Schlagwörter und den kompletten Inhalt. Semantisch: Ähnlichkeitssuche über die Ollama-Embeddings (unten zuerst berechnen).":
        "Full text: FTS5 over titles, tags, keywords and the full content. Semantic: similarity search over the Ollama embeddings (compute them below first).",
    "z. B. Wartungsplan Photovoltaik": "e.g. photovoltaics maintenance plan",
    "zuletzt {ts}": "last {ts}",
    "Ziel-Vault-Ordner kann nicht angelegt werden: {path}":
        "Target vault folder cannot be created: {path}",
    "{indexed} neu/geändert, {unchanged} unverändert, {removed} entfernt ({total} Notizen gesamt). INDEX.md aktualisiert.":
        "{indexed} new/changed, {unchanged} unchanged, {removed} removed ({total} notes in total). INDEX.md updated.",
    "{n} Chunks mit Embeddings ({model})": "{n} chunks with embeddings ({model})",
    "{n} Notiz(en) indexiert": "{n} note(s) indexed",
    "{new} Chunks neu, {reused} wiederverwendet (Modell {model}, Dimension {dim}).":
        "{new} chunks new, {reused} reused (model {model}, dimension {dim}).",
    "{tagged} Notiz(en) getaggt, {unchanged} unverändert, {errors} unbrauchbare Antworten.":
        "{tagged} note(s) tagged, {unchanged} unchanged, {errors} unusable responses.",
    "Volltextsuche": "Full-text search",
    "Suchbegriff": "Search term",
    "Suchen": "Search",
    "Keine Treffer.": "No results.",
    "Index aktualisieren": "Update index",
    "Semantische Suche": "Semantic search",
    "Ähnliche Notizen finden": "Find similar notes",
    "Verbindung prüfen": "Check connection",
    "Automatisches Tagging": "Automatic tagging",
    # --- Datenaustausch -----------------------------------------------------
    "Der Ordner wird rekursiv als ZIP verpackt (versteckte Ordner wie .obsidian ausgenommen).":
        "The folder is packed recursively into a ZIP (hidden folders like .obsidian excluded).",
    "Dokumente oder ZIP-Archive": "Documents or ZIP archives",
    "Für kleine Datenmengen ohne gemountete Ordner: Dateien hochladen, konvertieren, Ergebnis als ZIP herunterladen. Große Bestände gehören auf gemountete Ordner oder Netzwerk-Shares – siehe README, Abschnitt „Headless-Server & Docker“.":
        "For small amounts of data without mounted folders: upload files, convert, download the result as a ZIP. Large collections belong on mounted folders or network shares – see the README, section “Headless server & Docker”.",
    "ZIP-Archive werden serverseitig entpackt (Ordnerstruktur bleibt erhalten). Ablage unter {path}":
        "ZIP archives are unpacked server-side (folder structure is preserved). Stored under {path}",
    "Zuerst in der Seitenleiste einen Quellordner angeben – Uploads werden in dessen Unterordner „uploads“ abgelegt.":
        "First provide a source folder in the sidebar – uploads are stored in its “uploads” subfolder.",
    "{n} Datei(en) abgelegt unter `{path}`. Der Ordner liegt im Quellordner und wird beim nächsten Scan bzw. Lauf mit verarbeitet.":
        "{n} file(s) stored under `{path}`. The folder is inside the source folder and is included in the next scan or run.",
    "{name} herunterladen ({size})": "Download {name} ({size})",
    "Dateien hochladen": "Upload files",
    "Hochladen und ablegen": "Upload and store",
    "ZIP abgelehnt: {error}": "ZIP rejected: {error}",
    "Ergebnis herunterladen": "Download result",
    "Ordner für den Download": "Folder to download",
    "Ordner existiert nicht.": "Folder does not exist.",
    "Geschätzte Größe (unkomprimiert): {size}": "Estimated size (uncompressed): {size}",
    "ZIP erstellen": "Create ZIP",
    "Verpacke Ordner…": "Packing folder…",
    "Über 2 GB – der Browser-Download wird zäh. Für große Vaults besser einen gemounteten Ordner oder ein Netzwerk-Share verwenden.":
        "Over 2 GB – browser downloads get sluggish. For large vaults prefer a mounted folder or network share.",
    # --- Ordnerbrowser ------------------------------------------------------
    "Anlegen und übernehmen": "Create and use",
    "Diesen Ordner übernehmen": "Use this folder",
    "Ebene hoch": "Up one level",
    "Eine Ebene nach oben": "One level up",
    "Konnte Ordner nicht anlegen: {msg}": "Could not create folder: {msg}",
    "Name des neuen Ordners": "Name of the new folder",
    "Neuen Ordner anlegen": "Create new folder",
    "Neuen Unterordner anlegen": "Create new subfolder",
    "Öffnen": "Open",
    "Ordner übernehmen": "Use this folder",
    "Ordner wählen: `{cwd}`": "Choose folder: `{cwd}`",
    "Schließen": "Close",
    "Unterordner öffnen": "Open subfolder",
    # --- Fehlerhinweise (aus docling_worker, bei Anzeige uebersetzt) --------
    "Datei liegt vermutlich nur als Cloud-Platzhalter vor (OneDrive „Dateien bei Bedarf“) und ist lokal unvollständig. Ordner in OneDrive auf „Immer auf diesem Gerät behalten“ stellen und erneut ausführen.":
        "The file is probably only a cloud placeholder (OneDrive “Files On-Demand”) and incomplete locally. Set the folder to “Always keep on this device” in OneDrive and run again.",
    "Datei ist passwortgeschützt oder verschlüsselt – vor der Konvertierung entsperren.":
        "The file is password-protected or encrypted – unlock it before conversion.",
    "Datei nicht gefunden oder keine Leserechte.": "File not found or no read permission.",
    "Zu wenig Arbeitsspeicher – Anzahl paralleler Prozesse reduzieren.":
        "Not enough memory – reduce the number of parallel processes.",
    "Zeitüberschreitung bei der Verarbeitung – Datei ist möglicherweise sehr groß oder komplex.":
        "Processing timed out – the file may be very large or complex.",
    "Format/Variante wird von Docling nicht unterstützt.": "Format/variant not supported by Docling.",
    "Datei ist vermutlich beschädigt oder kein gültiges Dokument.":
        "The file is probably corrupted or not a valid document.",
    "Unerwarteter Fehler – vollständige Ursache siehe Traceback.":
        "Unexpected error – see the traceback for the full cause.",
}

_TRANSLATIONS: dict[str, dict[str, str]] = {"en": _EN}
