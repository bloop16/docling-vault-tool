# Changelog

Alle nennenswerten Änderungen an doc2vault. Format nach
[Keep a Changelog](https://keepachangelog.com/de/), Versionierung nach
[SemVer](https://semver.org/lang/de/).

## [1.6.0] – 2026-07-21

### Added
- **„Vault im Quellordner anlegen"** (Checkbox unter dem Quellordner):
  alles in einem Ordner — der Vault entsteht als Unterordner der Quelle
  (Name wählbar, Standard „Vault") und zieht bei einem Umzug automatisch
  mit. Keine Schleife: erzeugte Notizen werden beim Scan ausgeschlossen
  (bestehender Selbstausschluss des Zielordners).

## [1.5.0] – 2026-07-21

### Added
- **Fortsetzen nach Abbruch** (auch nach hartem Stopp): gleiche Quelle +
  gleiches Ziel überspringt bereits konvertierte, aktuelle Notizen —
  Dashboard meldet „N Datei(en) bereits konvertiert", CLI-Flag
  `--rerun-all` erzwingt Neuaufbau.
- **Parallele Prozesse auf max. 3 begrenzt** (Dashboard-Regler; CLI- und
  Job-Default ebenso gekappt, explizit höhere Werte per `-w` möglich).

### Fixed
- **Windows: absolute Bild-Links in Notizen.** Die Link-Relativierung
  griff nur bei `/`-Pfaden; Docling schreibt auf Windows aber
  `C:\…\assets\…`. Bild-Links sind jetzt in beiden Separator-Formen
  notiz-relativ mit `/` — der Vault übersteht Verschieben/Synchronisieren.
- Frontmatter: `original_path` ist jetzt **relativ zum Quellordner**
  (portabel über Systeme/Verschiebungen); der absolute Pfad steht in
  `original_path_abs`.

## [1.4.0] – 2026-07-21

### Added
- **Fortschritt je Datei**: Das Dashboard zeigt für jede aktive Datei
  einen eigenen Balken mit %-Schätzung und ~Seitenangabe (Worker melden
  Datei + Seitenzahl über Statusdateien; die Zeit pro Seite wird aus
  abgeschlossenen Dateien gelernt). Sichtbar, dass große Dokumente
  vorangehen.
- **Portable Ordnerangaben**: `~`/`$VAR`/`%VAR%` werden in allen
  Pfadfeldern expandiert; relative Quellangaben beziehen sich auf den
  Ziel-Vault-Ordner (`../Dokumente` = parallel zum Vault, systemübergreifend
  identisch). Jobs speichern die Relativ-Beziehung und finden ihre Quelle
  auch, wenn der absolute Pfad auf einem anderen System abweicht.

## [1.3.1] – 2026-07-21

Auswertung eines Windows-Laufs mit aktivem EasyOCR unter Speicherdruck.

### Fixed
- **Teilkonvertierungen werden nicht mehr still als Erfolg gewertet**:
  Scheitern einzelne Seiten in Docling (z. B. `Stage preprocess failed …
  std::bad_alloc` bei RAM-Mangel), entstand bisher eine Notiz mit
  fehlenden Seiten ohne jede Meldung. Jetzt gilt die Datei als
  Speicherfehler und durchläuft automatisch den reduzierten Zweitversuch
  im isolierten Einzelprozess.
- Weitere Speicherfehler-Texte klassifiziert (`not enough memory`,
  `Unable to allocate`, `DefaultCPUAllocator`).
- Log-Hygiene Windows-Worker: Streamlit-Bare-Mode-Meldungen jetzt
  wirksam stumm (Streamlit rekonfiguriert seine Logger beim Import —
  `logging.disable` nur im Worker-Prozess), torch-Quantisierungs-Warnung
  gefiltert, „Loading weights"-Fortschrittsbalken je Worker deaktiviert.

### Added
- RAM-Hinweis in Einstellungen und CLI-Plan, wenn OCR mit mehr als
  2 parallelen Prozessen kombiniert wird (je Prozess ein eigener
  Modellstapel).

## [1.3.0] – 2026-07-19

### Added
- **11 Oberflächensprachen** (ioBroker-Stil): Übersetzungen liegen als
  `i18n/<sprache>.json` vor — Deutsch (Quelle), Englisch, Französisch,
  Spanisch, Italienisch, Niederländisch, Polnisch, Portugiesisch,
  Russisch, Ukrainisch, Chinesisch (vereinfacht). Konsistenzprüfung per
  `scripts/check_i18n.py` (läuft als Test in der CI): Vollständigkeit,
  keine Waisen, Platzhalter-Treue, Schlüssel-Parität aller Sprachen.
- **Einstellungs-Seite**: alle Verarbeitungs-Optionen (Parallele Prozesse,
  Bilder/Auflösung, Tabellen, OCR + Engine + Sprachen, Excel-Limits,
  Umgang mit Originaldateien) sind in einen eigenen Tab „Einstellungen"
  gezogen; die Seitenleiste bleibt schlank (Sprache + Verzeichnisse).
  Der Konvertierungs-Tab führt mit einer ①-②-③-Leiste durch den Ablauf.
- Neue Fehlerkategorie für blockierte EasyOCR-Modell-Downloads mit
  Hinweis auf manuelle Modell-Installation bzw. Tesseract.
- **`doc2vault-service`**: Dashboard und Ordnerüberwachung als
  Hintergrunddienst einrichten — Linux: systemd-Benutzerdienste
  (Auto-Restart, kein Root), Windows: Aufgabenplanung (Start bei
  Anmeldung). Das Terminal kann danach geschlossen werden.
  `install ui|watch <job>`, `uninstall`, `status`.

### Fixed
- Packaging: das `i18n`-Paket (inkl. Sprachdateien) fehlte in der
  Wheel-Konfiguration — `pip install doc2vault` hätte das Dashboard ohne
  Übersetzungsmodul installiert.
- Übersetzungsbestand bereinigt: 9 veraltete Einträge entfernt, 5 fehlende
  Fehlerhinweis-Übersetzungen ergänzt (vom Prüfskript gefunden).

### Verifiziert (OCR/Last, real mit Docling)
- Tesseract und RapidOCR erkennen deutschen Text aus Bild-PDFs (E2E).
- A0-CAD-Scan (35 MPixel): Riesenseiten-Erkennung → reduzierter Modus →
  OCR liest Schriftfeld/Zeichnungsnummer; ~28 s, stabiler Speicher.
- Massenlauf 122 Dateien (78 MB, bis 120 Seiten/21 MB je Datei) ohne
  Ausfälle.

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
