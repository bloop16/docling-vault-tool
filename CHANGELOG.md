# Changelog

Alle nennenswerten Änderungen an doc2vault. Format nach
[Keep a Changelog](https://keepachangelog.com/de/), Versionierung nach
[SemVer](https://semver.org/lang/de/).

## [1.2.0] – 2026-07-19

### Added
- **Englische Oberfläche**: Sprachwahl (Deutsch/Englisch) oben in der
  Seitenleiste, Vorbelegung über `DOC2VAULT_LANG=de|en`. Deutsch bleibt
  Standard und Fallback — fehlende Übersetzungen führen nie zu Lücken.
  Auch die Fehlerhinweise der Konvertierung werden bei der Anzeige im
  Dashboard übersetzt. CLI-Ausgaben bleiben in dieser Ausbaustufe Deutsch.

## [1.1.0] – 2026-07-19

### Added
- **Neue Eingabeformate**: Bilder (PNG/JPG/JPEG/TIF/TIFF/WebP — mit
  OCR-Warnung, falls OCR aus), CSV, AsciiDoc (`.adoc`), E-Mail (`.eml`)
  und EPUB. Bilder laufen durch die PDF-Pipeline, OCR-Einstellungen
  greifen dort ebenso.
- **Duplikaterkennung**: inhaltsgleiche Quelldateien (SHA-256 mit
  Größen-Vorfilter) werden beim Scan gemeldet; `--duplicates skip` (CLI)
  bzw. die Job-Option „Inhaltsgleiche neue Dateien überspringen"
  konvertiert je Gruppe nur eine Datei. Job-Läufe weisen Duplikate als
  eigene Kategorie aus.
- **Logging-Grundgerüst**: Bibliothekspfade melden über
  `doc2vault.*`-Logger (z. B. Watch-Zyklus-Warnungen im Dienstlog);
  CLI-Ausgabe bleibt unverändert.

## [1.0.0] – 2026-07-19

Erste stabile Version. Der komplette Weg „Dokumentenordner → fertiger,
durchsuchbarer Obsidian-Vault" ist in mehreren realen Läufen (u. a. 3000+
Dokumente auf Windows/OneDrive) gehärtet worden.

### Added
- **Konvertierung**: Batch-Konvertierung PDF/DOCX/XLSX/PPTX/HTML/MD →
  Markdown via Docling; Bildextraktion mit Skalierung; Tabellenstruktur-
  erkennung; Excel-Sheet-Limit (`limit`/`skip`); Originale nach Erfolg
  behalten/archivieren/löschen.
- **OCR**: Engine wählbar — EasyOCR (Standard, Modelle von GitHub),
  Tesseract (lokal), RapidOCR; Sprachen konfigurierbar; Vorab-Prüfung der
  Engine mit klarer Meldung statt tausender Einzelfehler.
- **Zielordner-Analyse**: erkennt Obsidian-Vault/Logseq/bestehende Ordner
  und leitet einen Integrationsplan ab — eine Bestätigung pro Batch.
- **Vault-Build**: Notizen nach `Inbox/`, Bilder nach `Attachments/<slug>/`
  mit Obsidian-Wikilinks `![[...]]`, normiertes Frontmatter, vault-weiter
  Kollisionsschutz, idempotent.
- **Such-Index**: SQLite-FTS5-Volltext über den kompletten Inhalt +
  Schlagwortextraktion + generierte `INDEX.md`; optional Ollama-Embeddings
  (semantische Suche) und inhaltsbasiertes Auto-Tagging — additiv, ohne
  Ollama läuft alles Übrige vollständig.
- **Jobs & Überwachung**: inkrementelle Jobs mit Manifest
  (Größe/mtime/SHA-256), Lockfile, Lauf-Historie, Ordnerüberwachung
  (watchdog-Ereignisse oder Polling), nachträgliche Umkonfiguration
  (`doc2vault-jobs set`, Dashboard-Expander).
- **Dashboard** (Streamlit): Konvertierung mit Live-Fortschritt und
  Abbrechen-Button, Jobs, Suche & KI, Datenaustausch (ZIP-Upload/-Download
  mit Zip-Slip-/Zip-Bomb-Schutz); Ordnerwahl per nativem Dialog oder
  eingebautem Browser.
- **Deployment**: pip-Paket mit 5 Konsolenbefehlen, Docker/Compose
  (CPU-only), systemd-Template, Windows-Task-Registrierung,
  Installationsskripte für Linux/macOS/Windows.
- **Release-Infrastruktur**: CI (GitHub Actions: ruff + pytest auf
  Python 3.10–3.12 + Paket-Build), CHANGELOG, SECURITY.md, CONTRIBUTING.md,
  englisches README (`README.en.md`), PyPI-Metadaten.

### Fixed (Härtung aus Realläufen und Code-Reviews)
- Ein `std::bad_alloc` bei riesigen PDF-Seiten (CAD-Pläne) reißt weder den
  Batch noch die Datei: Vorab-Erkennung + automatischer reduzierter
  Zweitversuch in isoliertem Prozess.
- PDFs, die der Standard-Parser ablehnt („Inconsistent number of pages"),
  werden automatisch über den pypdfium-Parser konvertiert.
- OneDrive-Platzhalter („Dateien bei Bedarf") werden vor der Konvertierung
  vollständig geladen; klare Fehlerkategorie, falls das scheitert.
- Gleichnamige Quelldateien (`Report.pdf` + `Report.docx`) überschreiben
  sich nicht mehr; Quelle==Ziel wird klar gemeldet statt „0 Dateien".
- 20 Review-Funde behoben: u. a. atomare Job-Speicherung, Lock-Freigabe in
  Fehlerpfaden, Duplikat-sichere Bild-Ablage, Zip-Bomb-Limits,
  Ollama-Fehlertransparenz, Windows-reservierte Dateinamen.

## [0.x] – 2026-07

Iterative Entwicklung als „docling-vault-tool", ab 0.6 unter dem Namen
doc2vault: Aufbau von Konvertierung, Vault-Build, Index/KI, Jobs, Dashboard
und Deployment; Details in der Commit-Historie.
