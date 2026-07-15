# docling-vault-tool

Docling-basierte Batch-Konvertierung (PDF/DOCX/XLSX/PPTX → Markdown) für Obsidian Vaults,
mit Streamlit-Dashboard und Ein-Klick-Setup (Linux/macOS/Windows).

Gedacht als Vorstufe zu einem RAG-Setup (Chunking + Embedding, z. B. via ChromaDB
oder für Langdock-Upload): Docling erhält die Dokumentstruktur (Überschriften,
Tabellen) statt reinem Textbrei und extrahiert eingebettete Bilder als eigene Dateien.

## Funktionsweise

- **Konvertierung:** [Docling](https://github.com/DS4SD/docling) (IBM Research, Open Source)
- **Bildextraktion:** aktiviert via `generate_picture_images=True`; Bilder landen in
  `assets/<key>/` pro Quelldatei (der `<key>` kodiert den relativen Pfad, damit
  gleichnamige Dateien aus verschiedenen Unterordnern nicht kollidieren)
- **Metadaten:** jede `.md` bekommt YAML-Frontmatter mit `source`, `original_path`
  und `assets_folder` — Obsidian liest das nativ als Properties und man findet
  jederzeit zurück zum Original
- **Struktur:** die Verzeichnisstruktur des Quellordners wird im Vault gespiegelt
- **Parallelisierung:** `ProcessPoolExecutor` (Docling ist CPU-lastig; ein Converter
  wird einmal pro Prozess gebaut)
- **OCR:** standardmäßig aus (`do_ocr=False`) — nur für gescannte PDFs ohne Textlayer
  gezielt aktivieren (deutlich langsamer)

## Dateien

| Datei | Zweck |
|-------|-------|
| `docling_worker.py` | Kernlogik + eigenständige CLI (`build_converter`, `discover_files`, `convert_single_file`) |
| `app_streamlit.py`  | Streamlit-Dashboard (Fortschritt, ETA, Erfolg/Fehler, Fehlerprotokoll-Download) |
| `install_and_run.sh`  | Ein-Klick-Setup + Start für Linux/macOS |
| `install_and_run.ps1` | Ein-Klick-Setup + Start für Windows (PowerShell) |
| `job_manager.py`    | Sichere, inkrementelle Jobs + Ordnerüberwachung (Kernlogik + CLI) |
| `dashboard_launcher.py` | Einstiegspunkt für den `docling-vault-ui`-Befehl |
| `file_transfer.py`  | Upload-Ablage und ZIP-Verpackung für den Server-Betrieb |
| `vault_builder.py`  | Post-Processing: Docling-Output → Obsidian-Vault (Inbox, Attachments, Wikilinks, Frontmatter) |
| `vault_index.py`    | Such-Index für KI-Retrieval: SQLite-FTS5 + INDEX.md, optional Ollama-Embeddings/-Tagging |
| `pyproject.toml`    | Paketdefinition mit Konsolenbefehlen |
| `Dockerfile` / `docker-compose.yml` | Container-Betrieb auf einem Headless-Server |
| `deploy/`           | Dienst-Vorlagen (systemd, Windows-Aufgabenplanung) |
| `tests/`            | Testsuite (läuft ohne installiertes Docling) |
| `requirements.txt`  | Abhängigkeiten (Docling + Streamlit) |
| `requirements-dev.txt` | Entwicklungsabhängigkeiten (pytest, watchdog) |
| `.streamlit/config.toml` | Theme für das Dashboard |

## Dashboard

Zwei Bereiche:

- **Konvertierung** – Dateien scannen, Zielordner analysieren, Integrationsplan
  prüfen und einmal für den gesamten Batch bestätigen. Während der Konvertierung
  laufen Fortschritt, Restzeit und Zähler live mit; danach bleibt das Ergebnis
  inklusive Fehlerprotokoll stehen.
- **Jobs & Überwachung** – Jobs anlegen, per Dry-Run prüfen, inkrementell
  ausführen und den Lauf-Verlauf einsehen; der Befehl für die dauerhafte
  Ordnerüberwachung wird pro Job angezeigt.
- **Suche & KI** – Index-Status und -Aktualisierung, Volltextsuche (FTS5 mit
  Treffer-Snippets) und semantische Suche; Ollama-Anbindung mit
  Verbindungsprüfung, Modellauswahl live vom Server (`/api/tags`) sowie
  Embeddings- und Tagging-Läufen mit Fortschrittsanzeige.
- **Datenaustausch** – für den Server-Betrieb ohne gemountete Ordner: Dateien
  oder ZIP-Archive hochladen (werden serverseitig entpackt) und den fertigen
  Vault als ZIP herunterladen.

Im Konvertierungs-Tab lässt sich der **Vault-Build direkt zuschalten**
(„Vault-Build nach der Konvertierung"): Inbox/Attachments/Wikilinks plus
automatische Index-Aktualisierung in einem Durchgang; bestehende Notizen des
Vaults bleiben dabei unangetastet.

In der Seitenleiste lassen sich die Docling-Funktionen je Lauf zuschalten:
**Bilder extrahieren** (inklusive Skalierung der Bildauflösung),
**Tabellenstruktur erkennen** und **OCR für gescannte PDFs**. Die Auswahl gilt
auch für Jobs, die aus den aktuellen Einstellungen angelegt werden.

Das Theme kommt aus `.streamlit/config.toml`, die Feinabstimmung per CSS in
`app_streamlit.py`.

## Installation als Paket

Alternativ zum Setup-Skript lässt sich das Tool als Python-Paket installieren
und stellt dann drei Konsolenbefehle bereit:

```bash
pip install .            # oder: pip install .[watch] für den Ereignismodus
```

| Befehl | Zweck |
|--------|-------|
| `docling-vault`      | Batch-Konvertierung per CLI (entspricht `docling_worker.py`) |
| `docling-vault-jobs` | Jobs verwalten: `add`, `list`, `plan`, `run`, `history`, `watch`, `rm` |
| `docling-vault-ui`   | Dashboard starten (Streamlit-Optionen wie `--server.port 8080` anhängbar) |
| `docling-vault-build` | Vault-Build standalone: Docling-Output → Obsidian-Vault (Inbox, Attachments, Wikilinks) |
| `docling-vault-index` | Such-Index: `update`, `query` (FTS5), `models`, `embed`, `similar`, `tag` (Ollama) |

> Hinweis: `docling_worker.py` und `app_streamlit.py` sind die einzige Quelle der
> Konvertierungslogik. Die Setup-Skripte bauen nur die Umgebung und starten diese
> Dateien — es gibt keine duplizierte (Heredoc-)Logik mehr, die auseinanderlaufen kann.

## Schnellstart

### Linux / macOS

```bash
./install_and_run.sh
```

Legt ein `.venv` an, installiert Docling + Streamlit und öffnet das Dashboard.
Quell- und Ziel-Ordner werden im Dashboard eingetragen.

### Windows (PowerShell)

```powershell
.\install_and_run.ps1
```

Installiert Python bei Bedarf via `winget`, richtet die Umgebung ein und startet das Dashboard.

## Headless-Server & Docker

Das Tool läuft auch auf einem Server ohne Bildschirm; das Dashboard wird dann
im Browser über `http://<server-ip>:8501` bedient.

**Docker (empfohlen):**

```bash
docker compose up -d                  # Dashboard auf Port 8501
docker compose --profile watch up -d  # zusätzlich Ordnerüberwachung
                                      # (vorher DOCLING_JOB=<job-id> setzen)
```

Das Image ist CPU-only (PyTorch aus dem CPU-Index, ~3–4 GB statt 8+ GB).
Beim ersten Lauf lädt Docling seine Modelle in das Volume `docling-models` –
das dauert einmalig einige Minuten, danach starten Läufe sofort. Jobs,
Manifeste und Verläufe liegen im Volume `docling-config` und überleben
Container-Neustarts. Healthcheck: `http://<server-ip>:8501/_stcore/health`.

**pip (ohne Docker):**

```bash
pip install .[watch]
docling-vault-ui --server.address 0.0.0.0 --server.port 8501
```

### Daten effizient zum Server und zurück

Grundprinzip: **Daten nicht hoch- und runterladen, sondern mounten.** Die
Konvertierung arbeitet dann direkt auf den Originalordnern, und der fertige
Vault liegt sofort dort, wo er gebraucht wird.

| Datenquelle | Empfohlener Weg |
|---|---|
| NAS / anderer Host | SMB/NFS-Share auf dem Docker-Host mounten und in `docker-compose.yml` als Bind-Mount eintragen (z. B. `/mnt/nas/dokumente:/data/source`) – kein Kopieren nötig |
| SharePoint / OneDrive | `rclone sync onedrive:Dokumente ./data/source` zeitgesteuert (Cron/n8n) oder `rclone mount` – der Eingangsordner füllt sich automatisch |
| Client-PCs | Syncthing-Ordner oder eine Server-Freigabe (SMB) als Eingangsordner; die Clients legen Dateien einfach dort ab |
| Ad-hoc / kleine Mengen | ZIP-/Datei-Upload und ZIP-Download im Dashboard-Tab **Datenaustausch** (bis ~2 GB je Upload) |

**Ergebnis zurückholen:** Liegt der Ziel-Vault auf einem Share oder in einem
Syncthing-Ordner, öffnet Obsidian ihn direkt – nichts muss heruntergeladen
werden. Für Ad-hoc-Fälle verpackt der Tab *Datenaustausch* einen beliebigen
Ordner als ZIP zum Download (mit Größenwarnung ab 2 GB).

In Kombination mit der Ordnerüberwachung entsteht so eine Pipeline ohne
manuelle Schritte: Client/rclone legt Dateien im Eingangsordner ab → der
`watch`-Container konvertiert sie inkrementell → der Vault auf dem Share ist
aktuell.

**Sicherheit:** Streamlit hat keine eingebaute Authentifizierung. Das
Dashboard nur im LAN/VPN erreichbar machen oder einen Reverse-Proxy mit
Login davorschalten (Caddy, Traefik, nginx + Basic Auth).

## Zielordner & Vault-Integration

Das Tool ist für beliebige Nutzer und Zielordner gedacht. Der angegebene
Zielordner wird **vor** der Konvertierung analysiert und daraus ein
Integrationsplan abgeleitet, der **einmal für den gesamten Batch** bestätigt wird
(keine Rückfrage pro Datei):

- **Neuer/leerer Ordner** → Struktur wird frisch aufgebaut (`assets/` für Bilder,
  gespiegelte Quellstruktur, YAML-Frontmatter).
- **Bestehender Obsidian-Vault** (`.obsidian/`) → wird analysiert und die Dateien
  werden **entsprechend der Vault-Konventionen** eingegliedert:
  - Anhang-Ordner aus `.obsidian/app.json` (`attachmentFolderPath`) wird
    übernommen — zentral (`attachments/`, `assets/`, …) oder „neben der Notiz".
  - Frontmatter/Properties nur, wenn der Vault sie ohnehin nutzt.
  - Notizen kommen standardmäßig in einen dedizierten Unterordner
    (`Docling Import/`), damit ein kuratierter Vault nicht zugemüllt wird —
    umstellbar auf die Vault-Wurzel (fügt sich dann in bestehende gleichnamige
    Ordner ein).
- **Logseq-Graph** (`logseq/`) → Notizen nach `pages/`, Anhänge nach `assets/`.
- **Bestehender Nicht-Vault-Ordner** → erkannter Anhang-Ordner wird
  wiederverwendet, sonst `assets/`.

Im Dashboard: **„Ziel analysieren"** → Plan prüfen/anpassen → **„Plan bestätigen
und Konvertierung starten"**. In der CLI wird der Plan ausgegeben und einmal
abgefragt (mit `--yes` überspringbar).

Liegt der Zielordner innerhalb des Quellordners, wird er beim Scan automatisch
ausgenommen – bereits erzeugte Markdown-Dateien werden also nie erneut als
Quelle verarbeitet. Dasselbe gilt für den Archiv-Ordner.

## Vault-Build (Post-Processing)

Der rohe Docling-Output (`.md` + Bilder) wird mit dem **Vault-Builder** in
einen funktionierenden Obsidian-Vault überführt. Der Schritt ist optional und
läuft getrennt von der Konvertierung – der reine Convert-Modus bleibt
unverändert.

```bash
# Integriert: Konvertierung + Build in einem Aufruf
docling-vault -i /pfad/zu/quellen -o /pfad/zum/vault --build-vault

# Getrennt: Build standalone auf einen bestehenden Docling-Output-Ordner
docling-vault-build --input /pfad/zum/docling-output --vault /pfad/zum/vault
```

Was der Builder tut:

- **Frontmatter** (geschrieben mit `python-frontmatter`): normiertes Schema
  `title`, `source_path`, `converted_at` (ISO 8601), `tags` – vorhandene
  Felder aus der Konvertierung (z. B. `original_path`) werden übernommen,
  Zusatzfelder bleiben erhalten.
- **Attachments**: Bilder wandern nach `Attachments/<notiz-slug>/`, alle
  Referenzen werden zu Obsidian-Einbettungen `![[bild.png]]` umgeschrieben.
  Bildnamen sind vault-weit eindeutig (Hash-Suffix bei Namenskonflikt,
  inhaltsgleiche Bilder werden dedupliziert); Web-URLs bleiben unangetastet.
- **Kollisionsschutz**: Notizname = Slug des Quelldateinamens; bei Konflikt
  Suffix mit Kurz-Hash der Quelldatei – es wird niemals überschrieben.
- **Inbox-Ablage**: Alle Notizen landen zunächst in `Inbox/`. Einsortieren und
  Verlinken übernimmt nachgelagert der Vault-Curator-Agent
  (nomic-embed-text/Ollama) – Embedding-basiertes Auto-Linking ist bewusst
  nicht Teil dieses Tools.

Ergebnisstruktur:

```
vault/
├── Inbox/
│   ├── Q1-Bericht.md            # ![[diagramm.png]], normiertes Frontmatter
│   └── Q1-Bericht-a1b2c3d4.md   # Namenskonflikt → Hash-Suffix
└── Attachments/
    └── Q1-Bericht/
        └── diagramm.png
```

Der Builder ist idempotent: `Inbox/` und `Attachments/` werden beim Scan
ausgenommen, ein zweiter Lauf ändert nichts.

## Such-Index & semantische Suche (KI-Retrieval)

Damit ein KI-Modell mit Ordnerzugriff **gezielt navigieren kann statt den
gesamten Vault einzulesen**, pflegt das Tool einen dateibasierten Index im
Vault selbst – keine externe Datenbank, kein Server. Der komplette Workflow:

```bash
docling-vault -i <quellen> -o <vault> --build-vault   # Convert + Build + Index
docling-vault-index update  --vault <vault>            # Index standalone pflegen
docling-vault-index query   --vault <vault> "begriff"  # Volltextsuche (FTS5)
docling-vault-index embed   --vault <vault> -m nomic-embed-text  # optional
docling-vault-index similar --vault <vault> "frage"    # semantische Suche
docling-vault-index tag     --vault <vault> -m llama3.2 --write-notes  # optional
```

**`.vault-index/index.db`** (SQLite mit FTS5, reine Python-Standardbibliothek):
Volltextindex über Pfad, Titel, Tags, automatisch extrahierte Schlagwörter,
Summary und den **kompletten Notiz-Inhalt**. Ein Modell, das Code ausführen
kann, fragt gezielt ab statt zu greppen:

```sql
SELECT path, title FROM notes WHERE notes MATCH 'suchbegriff'
```

**`INDEX.md`** im Vault-Root: kompakte, aus der Datenbank generierte Übersicht
(Titel, Pfad, Tags, Schlagwörter, Summary je Notiz) – für Modelle, die keinen
Code ausführen können: erst die Übersicht lesen, dann gezielt einzelne Notizen
nachladen. Beides wird bei jedem `--build-vault`-Lauf automatisch und
**inkrementell** aktualisiert (Content-Hash je Notiz – nur Neues/Geändertes
wird neu indexiert).

**Schlagwörter ohne LLM:** Aus jedem Notiz-Inhalt werden die häufigsten
inhaltstragenden Begriffe extrahiert (stoppwort-gefiltert, Deutsch/Englisch) –
sofort durchsuchbar und in `INDEX.md` sichtbar.

### Optional: Ollama-Anbindung (Embeddings + Tagging)

Beides ist **additiv** – ist Ollama nicht erreichbar, laufen Konvertierung,
Vault-Build und FTS5-Index vollständig durch (Warnung statt Abbruch).

```bash
# Konfiguration per ENV (oder CLI-Flags --ollama-url / --model)
export DOCLING_OLLAMA_URL=http://ollama.lan:11434   # Default: localhost:11434
export DOCLING_EMBED_MODEL=nomic-embed-text
export DOCLING_TAG_MODEL=llama3.2

docling-vault-index models                      # verfügbare Modelle (/api/tags)
docling-vault -i … -o … --build-vault --embed   # Build + Index + Embeddings
```

- **Embeddings** (`embed`/`similar`): Notizen werden an Markdown-Headings in
  Chunks gesplittet (überlange Abschnitte mit Overlap), Embeddings liegen als
  Float32-BLOBs in derselben `index.db`, die Ähnlichkeitssuche rechnet
  Cosine-Similarity in numpy. Idempotent über Chunk-Hashes (nur Geändertes
  geht an Ollama), die Embedding-Dimension wird beim ersten Aufruf vom Server
  ermittelt. Sequenzielle Calls mit Timeout und Retry.
- **Tagging** (`tag`): erzeugt aus dem Inhalt 3–7 Tags plus 1–2-Satz-Summary
  je Notiz und schreibt sie in den Index; mit `--write-notes` zusätzlich ins
  Notiz-Frontmatter (neue Tags werden mit vorhandenen manuellen Tags
  **gemergt**, nie ersetzt). Idempotent; unbrauchbare Modell-Antworten
  überspringen die Notiz, der Lauf läuft weiter.

**Abgrenzung:** Automatisches Verlinken/Einsortieren übernimmt der
nachgelagerte Vault-Curator-Agent – er greift direkt auf `index.db`
(FTS + Embeddings) zu und ist nicht Teil dieses Tools.

## Nutzung ohne Dashboard (CLI)

```bash
# nach dem ersten Setup: venv aktivieren
source .venv/bin/activate

python docling_worker.py \
  --input  /pfad/zu/quellen \
  --output /pfad/zum/vault \
  --workers 6 \
  --error-log fehler.json
```

Oder direkt über das Setup-Skript:

```bash
./install_and_run.sh --cli -i /pfad/zu/quellen -o /pfad/zum/vault --ocr
```

| Flag | Bedeutung |
|------|-----------|
| `--input` / `-i`  | Quellordner (wird rekursiv durchsucht) |
| `--output` / `-o` | Ziel-Vault-Ordner |
| `--workers` / `-w`| Parallele Prozesse (Default: CPU-Kerne − 1) |
| `--ocr`           | OCR aktivieren (langsam; nur für gescannte PDFs) |
| `--no-images`     | Keine eingebetteten Bilder extrahieren (reine Textkonvertierung) |
| `--images-scale`  | Skalierung der extrahierten Bilder (Default 2.0) |
| `--no-tables`     | Tabellenstruktur-Erkennung deaktivieren (schneller) |
| `--xlsx-sheet-limit` | Max. Blätter je XLSX-Arbeitsmappe (0 = alle) |
| `--xlsx-on-limit` | Bei Überschreitung: `limit` = nur erste Blätter, `skip` = Datei überspringen |
| `--on-success`    | Was mit erfolgreich konvertierten Originalen passiert: `keep` (Default), `archive`, `delete` |
| `--archive-dir`   | Zielordner für `--on-success archive` (spiegelt die Quellstruktur) |
| `--notes-subdir`  | Unterordner im Ziel für die Notizen (überschreibt Empfehlung; `""` = Wurzel) |
| `--attachments-subdir` | Name des zentralen Anhang-Ordners (überschreibt Empfehlung) |
| `--no-frontmatter`| Kein YAML-Frontmatter voranstellen |
| `--build-vault`   | Nach der Konvertierung den Vault-Build ausführen (Inbox, Attachments, Wikilinks, Such-Index) |
| `--embed [MODELL]`| Nach Build+Index zusätzlich Ollama-Embeddings berechnen (additiv; Ollama down → nur Warnung) |
| `--yes` / `-y`    | Integrationsplan ohne Rückfrage bestätigen |
| `--error-log`     | Pfad für ein JSON-Fehlerprotokoll fehlgeschlagener Dateien |

## Jobs & Ordnerüberwachung (sichere, inkrementelle Verarbeitung)

Ein **Job** verknüpft einen Quellordner mit einem Zielordner (Vault) plus dem
bestätigten Integrationsplan. Jobs laufen einmalig oder als **Ordnerüberwachung**
(Polling) und verarbeiten bei jedem Lauf nur **neue oder geänderte** Dateien.

Warum „sicher":

- **Inkrementell & idempotent** – ein Manifest je Job (Größe/mtime/SHA-256) sorgt
  dafür, dass unveränderte Dateien übersprungen werden.
- **Wiederaufsetzbar** – bricht ein Lauf ab, gelten noch nicht eingetragene
  Dateien beim nächsten Lauf wieder als offen; das Manifest wird atomar geschrieben.
- **Sperre** gegen parallele Läufe desselben Jobs (Lockfile, mit Stale-Erkennung).
- **Nicht-destruktiv** – gelöschte Quelldateien werden nur gemeldet, nie werden
  Zieldateien automatisch entfernt.
- **Begrenzte Wiederholung** – dauerhaft fehlerhafte Dateien werden nach
  `RETRY_LIMIT` Versuchen nicht endlos neu verarbeitet (eine echte Änderung
  reaktiviert sie).

Konfiguration/Status liegen nutzerspezifisch unter `DOCLING_VAULT_HOME` bzw. dem
OS-Standard (`~/.config/docling-vault-tool`, `%APPDATA%`, `~/Library/…`).

**Im Dashboard:** Tab *Jobs & Überwachung* – Job aus den aktuellen Einstellungen
anlegen, „Prüfen" (Dry-Run), „Ausführen" (inkrementell), löschen; der
Watch-Befehl wird pro Job angezeigt.

**Vault-Build + Index je Job:** Mit der Job-Option *Vault-Build + Such-Index
nach jedem Lauf* (Dashboard-Toggle beim Anlegen bzw. CLI-Flag `--build-vault`)
führt jeder Lauf mit Neukonvertierungen automatisch den Vault-Build und die
Index-Aktualisierung aus — die Überwachung liefert damit direkt den fertigen,
durchsuchbaren Vault: Datei landet im Eingangsordner → Notiz erscheint in
`Inbox/` mit Wikilinks und aktualisiertem `INDEX.md`. Bestehende Notizen des
Vaults bleiben unangetastet; Build-Fehler brechen den Lauf nicht ab und
stehen im Verlauf. Leerzyklen der Überwachung bleiben billig (kein Build ohne
Neukonvertierung).

**Lauf-Historie:** Jeder Lauf mit tatsächlicher Arbeit wird protokolliert
(Zeitpunkt, Auslöser wie `cli`/`dashboard`/`watch`, Anzahl neu/geändert,
Erfolge, Fehler samt Datei und Grund, Dauer). Einsehbar im Dashboard je Job
unter *Verlauf* oder per CLI (`history`). Leerläufe der Ordnerüberwachung
werden nicht protokolliert, damit der Verlauf aussagekräftig bleibt; gespeichert
werden die letzten 200 Läufe pro Job.

**CLI:**

```bash
python job_manager.py add     --name "Berichte" --source SRC --target VAULT \
                              --build-vault   # optional: fertiger Vault je Lauf
python job_manager.py list
python job_manager.py plan    Berichte        # Dry-Run: was würde passieren?
python job_manager.py run     Berichte        # inkrementell konvertieren
python job_manager.py history Berichte -n 20  # letzte Läufe anzeigen
python job_manager.py watch   Berichte -n 30  # Ordner überwachen
python job_manager.py rm      Berichte
```

(Bei Paketinstallation entsprechend `docling-vault-jobs add …` usw.)

### Überwachungsmodi: Ereignisse oder Polling

`watch` kennt zwei Betriebsarten:

- **Ereignisse** (automatisch aktiv, wenn das Paket `watchdog` installiert ist,
  z. B. via `pip install .[watch]`): Dateisystem-Ereignisse stoßen die
  Verarbeitung sofort an. Das Intervall (`-n`) dient nur noch als
  Sicherheits-Rescan und kann groß gewählt werden (z. B. 300 s).
- **Polling** (Fallback bzw. erzwingbar mit `--poll`): fester Rescan im
  Intervall. Empfohlen für Netzlaufwerke, auf denen Dateisystem-Ereignisse
  unzuverlässig ankommen.

`--events` erzwingt den Ereignismodus und bricht mit einer Meldung ab, falls
`watchdog` fehlt. Beim Start wird der aktive Modus ausgegeben.

### Dauerhafter Betrieb als Dienst

Vorlagen liegen unter `deploy/`:

- **Linux (systemd):** `deploy/systemd/docling-vault-watch@.service` anpassen,
  nach `/etc/systemd/system/` kopieren, dann
  `systemctl enable --now docling-vault-watch@<job-id>`.
- **Windows:** `deploy/windows/register_watch_task.ps1 -JobId <job-id>`
  registriert eine Aufgabe, die die Überwachung bei der Anmeldung startet und
  bei Fehlern neu anläuft.

Alternativ funktionieren auch `cron @reboot`, ein Docker-Container oder ein
n8n-Exec-Node.

## Excel-Arbeitsmappen mit vielen Blättern

Arbeitsmappen mit sehr vielen Blättern können Laufzeit und Notizgröße sprengen.
Über das **Sheet-Limit** (Seitenleiste bzw. `--xlsx-sheet-limit`) lässt sich die
Anzahl begrenzen; die Blattnamen werden dafür ohne vollständiges Öffnen der
Datei gezählt. Bei Überschreitung gibt es zwei Verhalten:

- **Nur erste Blätter konvertieren** (Standard): Es wird eine getrimmte Kopie
  verarbeitet, das Original bleibt unangetastet. Das Frontmatter vermerkt
  `sheets_total` und `sheets_converted`, sodass gekürzte Notizen im Vault
  auffindbar bleiben.
- **Datei überspringen**: Die Arbeitsmappe landet mit der Kategorie
  „zu viele sheets" im Fehlerprotokoll und kann gezielt einzeln konvertiert
  werden.

Ohne Limit (`0`, Standard) werden alle Blätter konvertiert.

## Fehleranalyse

Fehlgeschlagene Dateien brechen den Batch nicht ab. Für jede wird festgehalten,
**was wirklich schiefgelaufen ist**:

- **Kategorie** (automatisch klassifiziert): z. B. `passwortgeschützt`, `beschädigt`,
  `speicher`, `timeout`, `nicht unterstützt`
- **Klartext-Hinweis** zur Behebung
- **vollständiger Traceback** (die echte Ursache)
- **Quellenlink**: im Dashboard je Datei ein `file://`-Link zum direkten Öffnen der
  Datei bzw. des Ordners im Ursprungspfad (plus Klartext-Pfad zum Kopieren, falls der
  Browser `file://` blockiert)

Im Dashboard erscheint das als Tabelle (mit Öffnen-/Ordner-Links) plus aufklappbare
Details je Datei; zusätzlich als CSV-Download. In der CLI schreibt `--error-log` ein
JSON mit denselben Feldern und gibt eine Kategorie-Übersicht aus.

## Originale nach der Konvertierung aufräumen (optional)

Standardmäßig bleiben die Originale unangetastet. Optional lassen sich erfolgreich
konvertierte Originale automatisch **ins Archiv verschieben** (Struktur bleibt erhalten)
oder **löschen**. **Fehlgeschlagene Dateien bleiben immer erhalten** — es wird nur nach
erfolgreichem Schreiben der `.md` aufgeräumt.

- Dashboard: Sidebar → *Nach erfolgreicher Konvertierung*
- CLI: `--on-success archive --archive-dir /pfad/zum/archiv` bzw. `--on-success delete`

## Beispiel-Ausgabe

```
vault/
├── berichte/
│   └── 2024/
│       └── q1.md          # mit YAML-Frontmatter
└── assets/
    └── berichte__2024__q1/
        ├── image_000.png
        └── image_001.png
```

```yaml
---
source: "q1.pdf"
original_path: "/pfad/zu/quellen/berichte/2024/q1.pdf"
assets_folder: "assets/berichte__2024__q1"
converted_at: "2026-07-13T12:00:00+00:00"
converter: "docling"
---
```

## Hinweise für große Datensätze (~15 GB)

- **Speicher:** Docling lädt pro Prozess Modelle in den RAM. Bei knappem Speicher
  die Anzahl paralleler Prozesse reduzieren (Dashboard-Slider bzw. `--workers`).
- **Robustheit:** passwortgeschützte oder korrupte Dateien brechen den Batch nicht ab —
  sie landen im Fehlerprotokoll (CSV-Download im Dashboard bzw. `--error-log`).
- **OCR** nur gezielt für gescannte PDFs aktivieren, sonst vervielfacht sich die Laufzeit.

## Entwicklung & Tests

Die Testsuite deckt Discovery, Ablage-Varianten, Fehlerklassifizierung,
Vault-Analyse und die Job-Logik (Inkrement, Retry-Begrenzung, Sperre, Historie)
ab und läuft ohne installiertes Docling:

```bash
pip install -r requirements-dev.txt
pytest
```
