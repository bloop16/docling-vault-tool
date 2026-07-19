🇬🇧 [English version](README.en.md)

# doc2vault

**Aus einem Ordner voller Dokumente wird ein fertiger, durchsuchbarer
Obsidian-Vault.** doc2vault konvertiert PDF-, Word-, Excel- und
PowerPoint-Dateien (dazu Bilder/Scans, HTML, CSV, AsciiDoc, E-Mail und
EPUB) in strukturiertes Markdown und übernimmt alles, was danach
noch fehlt: Ablage, Verlinkung, Metadaten und einen Such-Index — lokal,
dateibasiert, ohne externe Datenbank.

## Die Pipeline

```
Dokumente          Konvertierung        Vault-Build             Such-Index
(PDF, DOCX,   →    Docling:        →    Inbox/, Attachments/, → FTS5-Volltext,
XLSX, PPTX)        Markdown+Bilder      Wikilinks, Frontmatter  INDEX.md
                                                                 + optional KI
                                                                 (Ollama)
```

- **Konvertierung** ([Docling](https://github.com/DS4SD/docling)): Überschriften
  und Tabellen bleiben erhalten, eingebettete Bilder werden extrahiert;
  OCR für Scans über EasyOCR/Tesseract wählbar.
- **Vault-Build**: Notizen landen in `Inbox/`, Bilder in `Attachments/` mit
  Obsidian-Wikilinks (`![[bild.png]]`), jede Notiz bekommt Frontmatter mit
  Rückverweis auf das Original. Namenskonflikte werden automatisch aufgelöst,
  bestehende Notizen bleiben unangetastet.
- **Such-Index**: SQLite-Volltextsuche über den kompletten Inhalt plus eine
  kompakte `INDEX.md` — damit ein KI-Modell (oder du) gezielt findet, statt
  alles zu lesen. Optional ergänzt Ollama semantische Suche und automatisches
  Tagging.
- **Automatisierung**: Jobs überwachen einen Eingangsordner und verarbeiten
  nur Neues/Geändertes — Datei ablegen genügt, der Vault hält sich selbst
  aktuell.

## Schnellstart

**Linux/macOS:** `./install_and_run.sh` &nbsp;·&nbsp; **Windows:** `.\install_and_run.ps1`

Richtet die Umgebung ein und öffnet das Dashboard im Browser. Alternativ:

```bash
pip install .              # Befehle: doc2vault, doc2vault-ui, doc2vault-jobs, …
doc2vault-ui               # Dashboard starten

docker compose up -d       # oder als Container: http://<server-ip>:8501
```

## Erste Schritte

1. Im Dashboard **Quellordner** und **Ziel-Vault-Ordner** angeben.
2. **„Ziel analysieren"** — bestehende Vaults werden erkannt und der
   Integrationsplan passt sich ihren Konventionen an.
3. Plan prüfen, **„Vault-Build nach der Konvertierung"** aktivieren und
   bestätigen. Fertig: Der Vault liegt bereit, inklusive Index.

Ohne Dashboard geht dasselbe in einer Zeile:

```bash
doc2vault -i /pfad/zu/dokumenten -o /pfad/zum/vault --build-vault
```

Für den Dauerbetrieb legt man im Dashboard einen **Job** mit Ordnerüberwachung
an (oder `doc2vault-jobs add … --build-vault` + `watch`) — und richtet beides
per `doc2vault-service install ui` / `install watch <job>` als
**Hintergrunddienst** ein (Linux: systemd, Windows: Aufgabenplanung), sodass
das Terminal geschlossen werden kann.

## Mehr

Alle Funktionen, CLI-Referenz, Docker-/Server-Betrieb, Ollama-Anbindung und
Betriebsdetails: **[MANUAL.md](MANUAL.md)**

## Roadmap

Geplant nach 1.x (Reihenfolge offen): REST-API für Automatisierung,
Ablage-Regeln je Job (Muster → Zielordner/Tags), LLM-/VLM-gestützte
OCR-Nachkorrektur über die vorhandene Ollama-Anbindung, optionale
Dashboard-Authentifizierung, englische CLI-Ausgaben sowie ein
Curator-Agent, der Inbox-Notizen in die Vault-Struktur einsortiert.
Das Dashboard selbst ist bereits zweisprachig (Deutsch/Englisch,
Seitenleiste bzw. `DOC2VAULT_LANG`).

## Lizenz

GPL-3.0 — siehe [LICENSE](LICENSE).
