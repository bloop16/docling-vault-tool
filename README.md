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
| `requirements.txt`  | Abhängigkeiten (Docling + Streamlit) |
| `.streamlit/config.toml` | Basis-Theme (dunkel/technisch) für das Dashboard |

## Dashboard

Modernes, dunkles „Vault"-Frontend, das auf einen Blick zeigt, was das Tool
besser kann: Hero mit Kurzbeschreibung, Feature-Karten (Struktur statt Textbrei,
Bildextraktion, Obsidian-native Properties + Rückverweis, echte Parallelisierung,
transparente Fehler) und eine **Quelle ▸ Docling ▸ Vault**-Pipeline. Fortschritt,
ETA und Fehlerprotokoll erscheinen live während der Konvertierung. Das Basis-Theme
kommt aus `.streamlit/config.toml`, der Feinschliff (Hero, Karten, Pipeline) per
CSS direkt in `app_streamlit.py`.

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

Im Dashboard: **„🔎 Ziel analysieren & Plan erstellen"** → Plan prüfen/anpassen →
**„🚀 Plan bestätigen & konvertieren"**. In der CLI wird der Plan ausgegeben und
einmal abgefragt (mit `--yes` überspringbar).

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
| `--on-success`    | Was mit erfolgreich konvertierten Originalen passiert: `keep` (Default), `archive`, `delete` |
| `--archive-dir`   | Zielordner für `--on-success archive` (spiegelt die Quellstruktur) |
| `--notes-subdir`  | Unterordner im Ziel für die Notizen (überschreibt Empfehlung; `""` = Wurzel) |
| `--attachments-subdir` | Name des zentralen Anhang-Ordners (überschreibt Empfehlung) |
| `--no-frontmatter`| Kein YAML-Frontmatter voranstellen |
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

**Im Dashboard:** Abschnitt *Automatisierung: Jobs & Ordnerüberwachung* – Job aus
den aktuellen Einstellungen anlegen, „🔍 Prüfen" (Dry-Run), „▶️ Ausführen"
(inkrementell), löschen; der Watch-Befehl wird pro Job angezeigt.

**CLI:**

```bash
python job_manager.py add   --name "Berichte" --source SRC --target VAULT
python job_manager.py list
python job_manager.py plan  Berichte      # Dry-Run: was würde passieren?
python job_manager.py run   Berichte      # inkrementell konvertieren
python job_manager.py watch Berichte -n 30  # Ordner überwachen (alle 30 s)
python job_manager.py rm    Berichte
```

Für dauerhaften Betrieb `watch` als Dienst starten (z. B. systemd-Service,
`cron @reboot`, Docker-Container oder n8n-Exec-Node).

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
