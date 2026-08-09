# Changelog

Alle nennenswerten Änderungen an doc2vault. Format nach
[Keep a Changelog](https://keepachangelog.com/de/), Versionierung nach
[SemVer](https://semver.org/lang/de/).

## [1.8.2] – 2026-08-09

### Fixed
- **Speicher-Wache reagiert schneller und rechnet realistischer.**
  Realbetrieb: Mit 3 Prozessen (Empfehlung aus 1.8.1) lief eine große,
  seitenreiche OCR-Datei eine volle Minute unbeaufsichtigt, bis die
  60-Sekunden-Schonfrist endete — zu diesem Zeitpunkt war der
  Commit-Speicher bereits bei 0,0 GB und es hatte sich eine lange Kette
  von `std::bad_alloc` aufgebaut. Drei Korrekturen, alle aus den
  gemessenen Werten dieses Laufs kalibriert:
  - Schonfrist 60 s → 20 s (deckt nur die Modell-Ladephase, nicht mehr
    die eigentliche Verarbeitung).
  - Prüfintervall 5 s → 3 s, Reserve-Schwelle 2 GB → 4 GB — die Wache
    reagiert, bevor der Speicher komplett aufgebraucht ist, statt erst
    danach.
  - Angenommener Commit-Bedarf je Prozess 8 GB → 12 GB (OCR auf großen
    Dokumenten reserviert mehr, als der bisherige Wert vorsah) — die
    automatische Empfehlung startet dadurch von vornherein vorsichtiger.

## [1.8.1] – 2026-08-09

### Fixed
- **Drossel-Kaskade behoben (Dateien blieben bei „95 %" hängen).**
  Realbetrieb nach 1.8.0: 8 Prozesse fraßen 34 GB Commit in 30 s, die
  Live-Wache halbierte dann im 5-Sekunden-Takt 8→4→2→1 und brach dabei
  jedes Mal alle angefangenen Dateien ab — nichts wurde je fertig. Drei
  Korrekturen:
  - Der Start-Deckel rechnet mit dem realen Commit-Fussabdruck je
    Prozess (~8 GB Reservierung statt 4 GB physisch) und greift auch
    bei **fest zu kleiner** Auslagerungsdatei (Commit frei < RAM frei),
    nicht nur bei fehlender.
  - Schonfrist nach jedem Pool-Start (60 s): die Ladephase der Modelle
    ist selbst die Commit-Spitze und löst keine Kaskade mehr aus; echte
    Speicherfehler drosseln weiterhin sofort.
  - `WinError 1455` („Auslagerungsdatei zu klein", torch-DLL-Ladefehler)
    wird als Speicherfehler erkannt; bricht der Pool unter Speicherdruck,
    wird vor dem Neustart ebenfalls gedrosselt statt mit gleicher
    Prozesszahl erneut zu scheitern.
  - Commit-Regeln gelten nur unter Windows (Linux erlaubt Overcommit).

## [1.8.0] – 2026-08-09

### Added
- **Betrieb ohne Auslagerungsdatei: adaptive Speicher-Drosselung.**
  Für Maschinen, deren Windows-Auslagerungsdatei bewusst deaktiviert ist
  (Commit-Limit = physischer RAM, kann nicht wachsen):
  - Beim Start wird die Prozesszahl am tatsächlich freien
    Commit-Speicher ausgerichtet statt an der Kernzahl.
  - Während des Laufs überwacht der Batch-Runner den nutzbaren Speicher
    (~alle 5 s) und halbiert die Prozesszahl **präventiv**, bevor
    Windows Allokationen verweigert.
  - Speicherfehler bei paralleler Arbeit gelten zuerst als Folge des
    Gesamt-Speicherdrucks: Die Dateien werden mit weniger Prozessen in
    **voller Qualität** wiederholt; die reduzierten Einstellungen
    bleiben der letzte Ausweg.

## [1.7.7] – 2026-08-09

### Fixed
- **Prozessbegrenzung rechnet jetzt mit dem Commit-Speicher.** Die
  Diagnose aus 1.7.6 bestätigte im Realbetrieb den Verdacht: 34,5 GB
  RAM frei, aber nur 0,6 GB Commit (Auslagerungsdatei deaktiviert) —
  maßgeblich für `std::bad_alloc` ist der kleinere der beiden Werte.
  Der Standardwert für „Parallele Prozesse", die Empfehlung in den
  Einstellungen und die CLI-Warnung nutzen jetzt min(freier RAM,
  freier Commit) statt nur den physischen RAM.

## [1.7.6] – 2026-08-09

### Added
- **Diagnose für Speicherfehler trotz freiem RAM.** Realbetrieb: massen-
  hafte `std::bad_alloc` bei 63 GB freiem RAM — dann limitiert nicht der
  physische Speicher, sondern ein Pro-Prozess-Limit (32-Bit-Python:
  ~2 GB Adressraum) oder das Windows-Commit-Limit (Auslagerungsdatei
  deaktiviert/zu klein), beides im Task-Manager unsichtbar. doc2vault
  erkennt jetzt beide Fälle: deutliche Warnung in den Einstellungen und
  auf der CLI, und am Anfang jedes Laufs eine Umgebungszeile im Log
  (Python-Bitbreite, freier RAM, freier Commit, freier Adressraum).

## [1.7.5] – 2026-08-09

### Added
- **RAM-basierte Prozessbegrenzung.** Der Standardwert für „Parallele
  Prozesse" richtet sich jetzt zusätzlich nach dem tatsächlich freien
  Arbeitsspeicher (~4 GB je Prozess mit OCR) — auf knappen Maschinen
  startete der rein kernbasierte Default sonst direkt in massenhafte
  `std::bad_alloc`-Fehler. Die Einstellungen zeigen den freien RAM samt
  Empfehlung an und warnen, wenn mehr Prozesse gewählt sind, als der
  Speicher trägt; CLI warnt analog. Nach einem Lauf mit Speicherfehlern
  landet ein konkreter Hinweis (Anzahl, Prozesszahl, freier RAM) im Log.

## [1.7.4] – 2026-08-09

### Added
- **Fehler laufen live im Startterminal durch.** Wer das Dashboard normal
  im Terminal startet (`doc2vault-ui`), sieht dort jetzt jede
  fehlgeschlagene Datei (Kategorie + Meldung) und die Zusammenfassung
  jedes Laufs in Echtzeit — zusätzlich zur Logdatei aus 1.7.3.

## [1.7.3] – 2026-08-09

### Added
- **Persistentes Datei-Log**: Fehler und Batch-Zusammenfassungen werden
  jetzt dauerhaft in `<Konfig-Verzeichnis>/logs/doc2vault.log`
  protokolliert (rotierend, 2 MB × 3 Dateien) — unter Windows
  `%APPDATA%\doc2vault\logs\`, unter Linux `~/.config/doc2vault/logs/`
  bzw. `$DOC2VAULT_HOME/logs/`. Bisher gingen Fehlermeldungen verloren,
  sobald das Dashboard geschlossen wurde oder abstürzte. Der Pfad zur
  Logdatei wird im Einstellungen-Tab angezeigt; CLI-Läufe (`doc2vault`)
  loggen in dieselbe Datei.

## [1.7.2] – 2026-08-03

### Fixed
- **Waisen-Prozesse beim Beenden (Windows)**: Worker überleben das Ende
  der Anwendung nicht mehr — jeder Worker überwacht den Elternprozess
  (Sentinel) und beendet sich sofort selbst, wenn dieser stirbt (Ctrl+C,
  Fenster zu, Absturz). Zurückbleibende Waisen mit je 2–3 GB geladener
  Modelle waren die wahrscheinliche Ursache der bad_alloc-Kaskaden in
  Folgeläufen.
## [1.7.1] – 2026-08-03

### Fixed
- **`torch.compile`-Absturz bei jeder Datei unter Windows ohne C++-Compiler.**
  Docling versucht standardmäßig, seine Torch-Modelle beim ersten Aufruf per
  `torch.compile()` zu kompilieren (`InvalidCxxCompiler: Compiler: cl is not
  found`, wenn die Visual Studio Build Tools fehlen — der Normalfall). Der
  Fehlschlag landete als „Teilkonvertierung“ im Fehlerprotokoll und löste
  zusätzlich den (ebenfalls scheiternden) reduzierten Wiederholungsversuch
  aus — pro betroffener Datei doppelt verschenkte Zeit. `build_converter()`
  schaltet die Kompilierung jetzt global ab; ohne installierte C++-Toolchain
  bringt sie ohnehin nichts.

## [1.7.0] – 2026-08-03

### Changed
- **Deckel für parallele Prozesse gelockert.** Der Dashboard-Regler
  „Parallele Prozesse" erlaubte bisher maximal 3 Prozesse, egal wie viele
  Kerne/RAM die Maschine hat. Die Obergrenze richtet sich jetzt nach der
  tatsächlichen Kernzahl (Kerne − 1); der Standardwert bleibt konservativ
  bei `min(8, Kerne − 1)`, damit bestehende Installationen sich nicht
  plötzlich anders verhalten. Wer mehr Kerne/RAM zur Verfügung hat, kann
  im Regler jetzt bewusst höher gehen. CLI-Default (`--workers`) folgt
  derselben Formel.

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
