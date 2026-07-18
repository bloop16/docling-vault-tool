# doc2vault – Handbuch

Referenz für alle Funktionen. Der schnelle Einstieg steht im
[README](README.md).

## Inhalt

1. [Konzept & Pipeline](#1-konzept--pipeline)
2. [Installation](#2-installation)
3. [Dashboard](#3-dashboard)
4. [Konvertierung](#4-konvertierung)
5. [Zielordner-Analyse & Integrationsplan](#5-zielordner-analyse--integrationsplan)
6. [Vault-Build](#6-vault-build)
7. [Such-Index & KI](#7-such-index--ki)
8. [Jobs & Ordnerüberwachung](#8-jobs--ordnerüberwachung)
9. [Headless-Server & Docker](#9-headless-server--docker)
10. [Datenaustausch](#10-datenaustausch)
11. [CLI-Referenz](#11-cli-referenz)
12. [Umgebungsvariablen](#12-umgebungsvariablen)
13. [Fehlerbehebung](#13-fehlerbehebung-troubleshooting)
14. [Entwicklung & Tests](#14-entwicklung--tests)

---

## 1. Konzept & Pipeline

doc2vault verarbeitet Dokumentbestände in vier Stufen, die einzeln oder als
Ganzes laufen:

| Stufe | Was passiert | Werkzeug |
|---|---|---|
| **Konvertierung** | PDF/DOCX/XLSX/PPTX → Markdown + Bilder; Struktur (Überschriften, Tabellen) bleibt erhalten | `doc2vault` / Dashboard |
| **Vault-Build** | Roh-Output → Obsidian-Vault: `Inbox/`, `Attachments/`, Wikilinks, Frontmatter | `doc2vault-build` bzw. `--build-vault` |
| **Such-Index** | FTS5-Volltext (`.vault-index/index.db`) + lesbare Übersicht `INDEX.md` | `doc2vault-index update` (läuft beim Build automatisch mit) |
| **KI (optional)** | Semantische Suche (Embeddings) und automatisches Tagging via Ollama | `doc2vault-index embed / tag / similar` |

Alles ist dateibasiert und liegt im Vault selbst — keine externe Datenbank,
kein Server. Jede Stufe ist idempotent: erneute Läufe verarbeiten nur
Neues/Geändertes.

Unterstützte Formate: `pdf`, `docx`, `xlsx`, `pptx`, `html`/`htm`, `md`.

## 2. Installation

**Setup-Skripte** (legen ein venv an, installieren alles, starten das Dashboard):

```bash
./install_and_run.sh          # Linux/macOS; --cli für Direktkonvertierung
.\install_and_run.ps1         # Windows (installiert Python bei Bedarf via winget)
```

**Als Paket:**

```bash
pip install .                 # Extras: .[watch] (Ereignis-Überwachung), .[embed] (numpy)
```

| Befehl | Zweck |
|---|---|
| `doc2vault` | Batch-Konvertierung (CLI) |
| `doc2vault-ui` | Dashboard starten (Streamlit-Optionen anhängbar, z. B. `--server.port 8080`) |
| `doc2vault-jobs` | Jobs verwalten: `add`, `list`, `plan`, `run`, `history`, `watch`, `rm` |
| `doc2vault-build` | Vault-Build standalone auf einen Docling-Output-Ordner |
| `doc2vault-index` | Index: `update`, `query`, `models`, `embed`, `similar`, `tag` |

**Docker:** siehe [Abschnitt 9](#9-headless-server--docker).

**Migration von „docling-vault-tool":** Beim ersten Start wird das alte
Konfigurationsverzeichnis automatisch übernommen (Jobs, Manifeste, Verläufe);
die alte Variable `DOCLING_VAULT_HOME` wird weiterhin als Fallback gelesen.

## 3. Dashboard

Start: `doc2vault-ui` (bzw. `streamlit run app_streamlit.py`). Vier Bereiche:

- **Konvertierung** — Dateien scannen, Ziel analysieren, Integrationsplan
  bestätigen (einmal für den gesamten Batch), Fortschritt/Restzeit live,
  Ergebnis bleibt stehen. Toggle „Vault-Build nach der Konvertierung" für die
  komplette Pipeline in einem Durchgang.
- **Jobs & Überwachung** — Jobs anlegen (übernimmt den bestätigten Plan),
  Dry-Run („Prüfen"), inkrementell ausführen, Lauf-Verlauf einsehen.
- **Suche & KI** — Index-Status/-Aktualisierung, Volltext- und semantische
  Suche mit Trefferkarten; Ollama-Verbindungsprüfung, Modellauswahl live vom
  Server, Embeddings-/Tagging-Läufe mit Fortschrittsanzeige.
- **Datenaustausch** — Datei-/ZIP-Upload und Vault-Download für den
  Server-Betrieb ohne gemountete Ordner.

Die Seitenleiste bündelt alle Einstellungen: Verzeichnisse, parallele
Prozesse, Docling-Funktionen (Bilder + Auflösung, Tabellenerkennung, OCR),
Excel-Sheet-Limit und den Umgang mit Originaldateien.

## 4. Konvertierung

**Docling-Funktionen** (Seitenleiste bzw. CLI-Flags):

- **Bilder extrahieren** (`--no-images` zum Abschalten): eingebettete Grafiken
  werden eigene Dateien; `--images-scale` steuert die Auflösung (Default 2.0).
- **Tabellenstruktur erkennen** (`--no-tables`): rekonstruiert Tabellen als
  Markdown; abgeschaltet ist die Verarbeitung schneller.
- **OCR** (`--ocr`): nur für gescannte PDFs ohne Textebene — deutlich langsamer.

**Excel-Arbeitsmappen:** Über das Sheet-Limit (`--xlsx-sheet-limit`, 0 = alle)
lassen sich Mappen mit sehr vielen Blättern begrenzen. Bei Überschreitung
wahlweise nur die ersten Blätter konvertieren (getrimmte Kopie, Original
unangetastet, Vermerk `sheets_total`/`sheets_converted` im Frontmatter) oder
die Datei überspringen (`--xlsx-on-limit limit|skip`).

**Fehleranalyse:** Fehlgeschlagene Dateien brechen den Batch nie ab. Je Datei
werden Kategorie (z. B. `passwortgeschützt`, `beschädigt`, `speicher`,
`timeout`), ein Handlungshinweis und der vollständige Traceback festgehalten —
im Dashboard mit klickbaren `file://`-Links zur Originaldatei, als
CSV-Download und per `--error-log` als JSON.

**Originale aufräumen:** Nach erfolgreicher Konvertierung optional ins Archiv
verschieben (Struktur bleibt erhalten) oder löschen
(`--on-success keep|archive|delete`, `--archive-dir`). Fehlgeschlagene
Dateien bleiben immer erhalten.

**Parallelisierung:** Ein Docling-Converter je Prozess
(`--workers`, Default: CPU-Kerne − 1). Docling lädt Modelle pro Prozess in den
RAM — bei knappem Speicher reduzieren.

## 5. Zielordner-Analyse & Integrationsplan

Vor jeder Konvertierung wird der Zielordner analysiert und ein Plan
abgeleitet, der **einmal für den gesamten Batch** bestätigt wird:

- **Obsidian-Vault** (`.obsidian/`): Anhang-Konvention aus
  `.obsidian/app.json` wird übernommen (zentraler Ordner oder „neben der
  Notiz"), Frontmatter nur, wenn der Vault es nutzt; Notizen kommen
  standardmäßig in einen Import-Unterordner, damit der kuratierte Bestand
  sauber bleibt.
- **Logseq-Graph** (`logseq/`): Notizen → `pages/`, Anhänge → `assets/`.
- **Leerer/neuer Ordner**: Struktur wird frisch aufgebaut.
- **Bestehender Ordner**: erkannter Anhang-Ordner wird wiederverwendet.

Liegt der Zielordner innerhalb des Quellordners, wird er beim Scan
automatisch ausgenommen (keine Selbst-Verarbeitung erzeugter Dateien);
dasselbe gilt für den Archiv-Ordner. Plan-Overrides per CLI:
`--notes-subdir`, `--attachments-subdir`, `--no-frontmatter`, `--yes`.

## 6. Vault-Build

Macht aus rohem Docling-Output einen funktionierenden Obsidian-Vault:

```bash
doc2vault -i <quellen> -o <vault> --build-vault      # integriert
doc2vault-build --input <output> --vault <vault>      # standalone
```

- **Frontmatter** (via `python-frontmatter`): `title`, `source_path`,
  `converted_at` (ISO 8601), `tags`; vorhandene Felder bleiben erhalten.
- **Attachments**: Bilder nach `Attachments/<notiz-slug>/`, Referenzen als
  Obsidian-Einbettung `![[bild.png]]`; Bildnamen vault-weit eindeutig
  (Hash-Suffix bei Konflikt, inhaltsgleiche Bilder dedupliziert).
- **Kollisionsschutz**: Notizname = Slug des Quellnamens, bei Konflikt
  Kurz-Hash-Suffix — es wird nie überschrieben.
- **Inbox**: Alle neuen Notizen landen in `Inbox/`; Einsortieren/Verlinken
  übernimmt ein nachgelagerter Curator-Schritt (nicht Teil dieses Tools).
- **Sicher & idempotent**: Nur der frisch konvertierte Bereich wird gebaut,
  bestehende Vault-Notizen bleiben unangetastet; ein zweiter Lauf ändert nichts.

Ergebnisstruktur:

```
vault/
├── Inbox/
│   ├── Q1-Bericht.md              # ![[diagramm.png]], Frontmatter
│   └── Q1-Bericht-a1b2c3d4.md     # Namenskonflikt → Hash-Suffix
├── Attachments/Q1-Bericht/diagramm.png
├── INDEX.md                       # kompakte Übersicht (siehe unten)
└── .vault-index/index.db          # SQLite-Volltextindex
```

## 7. Such-Index & KI

Ziel: Ein KI-Modell mit Ordnerzugriff soll **gezielt navigieren statt alles
einzulesen**.

**Volltextindex** `.vault-index/index.db` (SQLite FTS5, Standardbibliothek) —
indexiert Pfad, Titel, Tags, automatisch extrahierte Schlagwörter
(stoppwort-gefiltert, ohne LLM), Summary und den **kompletten Inhalt**:

```sql
SELECT path, title FROM notes WHERE notes MATCH 'suchbegriff'
```

```bash
doc2vault-index update --vault <vault>          # inkrementell (Content-Hash)
doc2vault-index query  --vault <vault> "begriff"
```

**`INDEX.md`** im Vault-Root: aus der Datenbank regenerierte Übersicht (Titel,
Pfad, Tags, Schlagwörter, Summary je Notiz) — für Modelle ohne
Code-Ausführung: erst die Übersicht lesen, dann gezielt Notizen nachladen.
Index und `INDEX.md` werden bei jedem Vault-Build automatisch aktualisiert.

**Ollama (optional, additiv):** Ist Ollama nicht erreichbar, laufen
Konvertierung, Build und Volltextsuche vollständig durch (Warnung statt
Abbruch).

```bash
export DOC2VAULT_OLLAMA_URL=http://ollama.lan:11434   # Default: localhost:11434
export DOC2VAULT_EMBED_MODEL=nomic-embed-text
export DOC2VAULT_TAG_MODEL=llama3.2

doc2vault-index models                     # verfügbare Modelle (/api/tags)
doc2vault-index embed   --vault <vault> -m nomic-embed-text
doc2vault-index similar --vault <vault> "Wie wird die Anlage gewartet?"
doc2vault-index tag     --vault <vault> -m llama3.2 --write-notes
```

- **Embeddings**: Notizen werden an Überschriften in Chunks gesplittet
  (überlange Abschnitte mit Overlap); Embeddings liegen als Float32-BLOBs in
  derselben `index.db`, Ähnlichkeitssuche via Cosine (numpy). Idempotent über
  Chunk-Hashes; die Dimension wird beim ersten Aufruf vom Server ermittelt.
- **Tagging**: 3–7 Tags + 1–2-Satz-Summary je Notiz aus dem Inhalt; mit
  `--write-notes` zusätzlich ins Frontmatter (neue Tags werden mit manuellen
  **gemergt**, nie ersetzt). Unbrauchbare Modell-Antworten überspringen die
  Notiz.

## 8. Jobs & Ordnerüberwachung

Ein **Job** verknüpft Quell- und Zielordner mit dem bestätigten Plan und
verarbeitet bei jedem Lauf nur neue/geänderte Dateien.

```bash
doc2vault-jobs add     --name "Berichte" --source SRC --target VAULT --build-vault
doc2vault-jobs plan    Berichte           # Dry-Run
doc2vault-jobs run     Berichte           # einmalig inkrementell
doc2vault-jobs watch   Berichte           # dauerhafte Überwachung
doc2vault-jobs history Berichte -n 20     # Lauf-Verlauf
```

**Sicherheitsmerkmale:** Manifest je Job (Größe/mtime/SHA-256 → idempotent),
atomar geschrieben und wiederaufsetzbar; Lockfile gegen Doppelläufe;
gelöschte Quelldateien werden nur gemeldet (nie werden Zieldateien entfernt);
dauerhaft fehlerhafte Dateien werden nach 3 Versuchen nicht endlos wiederholt.

**Komplette Pipeline je Lauf:** Mit `--build-vault` (bzw. Dashboard-Toggle)
folgt auf jeden Lauf mit Neukonvertierungen automatisch Vault-Build + Index —
Datei in den Eingangsordner legen genügt. Leerzyklen bleiben billig,
Build-Fehler brechen den Lauf nicht ab und stehen im Verlauf.

**Überwachungsmodi:** Ereignisbasiert (watchdog installiert; Intervall dient
nur als Sicherheits-Rescan, `--events` erzwingt) oder Polling (`--poll`,
empfohlen für Netzlaufwerke).

**Dauerbetrieb:** Vorlagen unter `deploy/` — systemd-Template
(`systemctl enable --now doc2vault-watch@<job-id>`) und Windows-Aufgabe
(`deploy/windows/register_watch_task.ps1 -JobId <job-id>`); alternativ der
`watch`-Service im Docker-Compose.

**Lauf-Historie:** Zeitpunkt, Auslöser (`cli`/`dashboard`/`watch`), Zahlen,
Fehler samt Grund, Build-Ergebnis, Dauer — je Job die letzten 200 Läufe.

## 9. Headless-Server & Docker

```bash
docker compose up -d                    # Dashboard: http://<server-ip>:8501
DOC2VAULT_JOB=<job-id> docker compose --profile watch up -d   # + Überwachung
```

Das Image ist CPU-only (~3–4 GB). Beim ersten Lauf lädt Docling seine Modelle
in das Volume `doc2vault-models` (einmalig einige Minuten); Jobs/Verläufe
liegen in `doc2vault-config`. Healthcheck:
`http://<server-ip>:8501/_stcore/health`. Ohne Docker:
`doc2vault-ui --server.address 0.0.0.0 --server.port 8501`.

**Daten effizient zum Server (und zurück):** Grundprinzip — mounten statt
kopieren.

| Datenquelle | Empfohlener Weg |
|---|---|
| NAS / anderer Host | SMB/NFS-Share auf dem Host mounten → Bind-Mount in `docker-compose.yml` |
| SharePoint / OneDrive | `rclone sync` (Cron/n8n) oder `rclone mount` in den Eingangsordner |
| Client-PCs | Syncthing-Ordner oder Server-Freigabe als Eingangsordner |
| Ad-hoc / klein | Upload/Download im Dashboard-Tab „Datenaustausch" (bis ~2 GB) |

Liegt der Ziel-Vault auf einem Share/Syncthing-Ordner, öffnet Obsidian ihn
direkt — nichts muss zurückgeladen werden.

**Sicherheit:** Streamlit hat keine Authentifizierung. Nur im LAN/VPN
betreiben oder einen Reverse-Proxy mit Login davorschalten (Caddy, Traefik,
nginx + Basic Auth).

## 10. Datenaustausch

Für kleine Mengen ohne gemountete Ordner (Dashboard-Tab):

- **Upload**: Dokumente oder ZIP-Archive hochladen; ZIPs werden serverseitig
  entpackt (mit Zip-Slip-Schutz), Ablage unter `<Quellordner>/uploads/`.
- **Download**: beliebigen Ordner (Default: Import-Bereich des Vaults) als
  ZIP herunterladen, mit Größenschätzung und Warnung ab 2 GB.

## 11. CLI-Referenz

### `doc2vault` (Konvertierung)

| Flag | Bedeutung |
|---|---|
| `--input/-i`, `--output/-o` | Quellordner, Ziel-Vault |
| `--workers/-w` | Parallele Prozesse (Default: Kerne − 1) |
| `--ocr` | OCR für gescannte PDFs |
| `--no-images`, `--images-scale` | Bildextraktion aus / Auflösung (Default 2.0) |
| `--no-tables` | Tabellenerkennung aus |
| `--xlsx-sheet-limit`, `--xlsx-on-limit` | Sheet-Limit; `limit` = erste Blätter, `skip` = überspringen |
| `--notes-subdir`, `--attachments-subdir`, `--no-frontmatter` | Plan-Overrides |
| `--on-success`, `--archive-dir` | Originale: `keep`/`archive`/`delete` |
| `--build-vault` | Vault-Build + Index nach der Konvertierung |
| `--embed [MODELL]` | Zusätzlich Ollama-Embeddings (additiv) |
| `--yes/-y` | Plan ohne Rückfrage bestätigen |
| `--error-log` | JSON-Fehlerprotokoll |

### `doc2vault-build`

`--input <docling-output> --vault <vault> [--inbox NAME] [--attachments NAME]`

### `doc2vault-index`

| Subkommando | Bedeutung |
|---|---|
| `update --vault X` | Index + `INDEX.md` aktualisieren (inkrementell) |
| `query --vault X "…" [-n N]` | FTS5-Volltextsuche mit Snippets |
| `models [--ollama-url U]` | Verfügbare Ollama-Modelle |
| `embed --vault X -m MODELL` | Embeddings berechnen (idempotent) |
| `similar --vault X "…" [-n N]` | Semantische Suche |
| `tag --vault X -m MODELL [--write-notes]` | Tags + Summary aus dem Inhalt |

### `doc2vault-jobs`

`add` (`--name --source --target` + Konvertierungs-Flags + `--build-vault`
`--poll-interval --workers`), `list`, `plan <job>`, `run <job>`,
`history <job> [-n N]`, `watch <job> [-n Sek] [--events|--poll]`,
`show <job>`, `rm <job>`.

## 12. Umgebungsvariablen

| Variable | Zweck | Default |
|---|---|---|
| `DOC2VAULT_HOME` | Konfig-/Statusverzeichnis (Jobs, Manifeste) | OS-Standard (`~/.config/doc2vault`, `%APPDATA%`, `~/Library/…`) |
| `DOC2VAULT_SOURCE_DIR` / `_TARGET_DIR` / `_ARCHIVE_DIR` | Pfad-Vorbelegung im Dashboard (Container-Mounts) | – |
| `DOC2VAULT_OLLAMA_URL` | Ollama-Server | `http://localhost:11434` |
| `DOC2VAULT_EMBED_MODEL` / `_TAG_MODEL` | Standard-Modelle für `embed`/`tag` | – |
| `DOC2VAULT_JOB` | Job-ID für den `watch`-Service in Docker Compose | – |

## 13. Fehlerbehebung (Troubleshooting)

**Viele Dateien scheitern als „prozessabsturz" / „terminated abruptly":**
Ein einzelnes Problemdokument (meist eine riesige/komplexe PDF, z. B.
CAD-Zeichnung) hat einen Worker-Prozess mit Speicherfehler (`std::bad_alloc`)
zum Absturz gebracht. doc2vault startet den Pool automatisch neu und
verarbeitet die restlichen Dateien weiter; nur die Verursacher werden
markiert. Abhilfe für die markierten Dateien: parallele Prozesse auf 1–2 und
die Bildauflösung auf 1.0 reduzieren, Datei einzeln erneut konvertieren.

**„cloud-platzhalter" / `unexpected EOF, expected N more bytes`:**
Die Quelldatei liegt in OneDrive nur als Platzhalter vor („Dateien bei
Bedarf") und ist lokal unvollständig. doc2vault liest jede Datei vor der
Konvertierung einmal komplett ein, was den Download normalerweise auslöst —
schlägt das fehl: den Quellordner in OneDrive per Rechtsklick auf **„Immer
auf diesem Gerät behalten"** stellen, Synchronisierung abwarten, erneut
ausführen.

**„ocr-modelle" / `storage has wrong byte size` / `pickle data was truncated`:**
Die RapidOCR-Modelldateien sind beschädigt — typischerweise weil der Download
von `modelscope.cn` (China-CDN) im Firmen-/Heimnetz blockiert war und eine
halbe Datei liegen blieb. Danach scheitert jeder OCR-Lauf an der kaputten
Datei. Abhilfe: entweder **OCR deaktivieren** (Standard; nur für gescannte
PDFs nötig) oder den Modellordner löschen
(`.venv\Lib\site-packages\rapidocr\models\`) und mit funktionierendem
Netzzugang erneut konvertieren.

**Ordner lässt sich nicht per Maus wählen:** Der Button **„Durchsuchen…"**
neben jedem Pfadfeld öffnet den nativen Ordnerdialog des Betriebssystems
(wenn das Dashboard lokal läuft) bzw. einen eingebauten Ordnerbrowser (beim
Server-/Docker-Betrieb) — dort lassen sich auch neue Ordner anlegen.
Fehlende Ziel-Vault-Ordner werden generell automatisch angelegt.

## 14. Entwicklung & Tests

```bash
pip install -r requirements-dev.txt
pytest                     # läuft komplett ohne installiertes Docling
```

Die Suite deckt Discovery, Ablage-Varianten, Fehlerklassifizierung,
Vault-Analyse, Vault-Build, Index/FTS, Embeddings/Tagging (Fake-Client) und
die Job-Logik ab. Docling wird in den Tests durch einen Stub ersetzt
(`tests/conftest.py`).
