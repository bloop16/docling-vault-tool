🇩🇪 [Deutsche Version](README.md) — the dashboard is available in **English and German** (sidebar switch or `DOC2VAULT_LANG=en`); CLI output is currently German.

# doc2vault

**Turn a folder full of documents into a finished, searchable Obsidian
vault.** doc2vault converts PDF, Word, Excel and PowerPoint files (plus
images/scans, HTML, CSV, AsciiDoc, e-mail and EPUB) to structured Markdown
and takes care of everything that usually remains after conversion: filing,
linking, metadata and a search index — local, file-based, no external
database.

## The pipeline

```
Documents          Conversion           Vault build             Search index
(PDF, DOCX,   →    Docling:        →    Inbox/, Attachments/, → FTS5 full text,
XLSX, PPTX)        Markdown+images      wikilinks, frontmatter  INDEX.md
                                                                 + optional AI
                                                                 (Ollama)
```

- **Conversion** ([Docling](https://github.com/docling-project/docling)):
  headings and tables are preserved, embedded images are extracted; OCR for
  scans via EasyOCR or Tesseract.
- **Vault build**: notes land in `Inbox/`, images in `Attachments/` with
  Obsidian wikilinks (`![[image.png]]`); every note gets frontmatter with a
  back-reference to the original. Name collisions are resolved
  automatically, existing notes are never touched.
- **Search index**: SQLite full-text search over the complete content plus
  a compact `INDEX.md` — so an AI model (or you) can find things without
  reading everything. Ollama optionally adds semantic search and automatic
  tagging.
- **Automation**: jobs watch an inbox folder and only process new/changed
  files — drop a file in, the vault keeps itself up to date.

## Quick start

**Linux/macOS:** `./install_and_run.sh` · **Windows:** `.\install_and_run.ps1`

Sets up the environment and opens the dashboard in your browser. Or:

```bash
pip install .              # commands: doc2vault, doc2vault-ui, doc2vault-jobs, …
doc2vault-ui               # start the dashboard

docker compose up -d       # or as a container: http://<server-ip>:8501
```

One-liner without the dashboard:

```bash
doc2vault -i /path/to/documents -o /path/to/vault --build-vault
```

## More

All features, CLI reference, Docker/server operation, Ollama integration:
**[MANUAL.md](MANUAL.md)** (German). Security notes: **[SECURITY.md](SECURITY.md)**.

## License

GPL-3.0 — see [LICENSE](LICENSE).
