"""Such-Index fuer KI-Retrieval: SQLite-FTS5-Volltext + lesbares INDEX.md.

Damit ein KI-Modell mit Ordnerzugriff **nicht den gesamten Vault einlesen
muss**, pflegt dieses Modul einen dateibasierten Index im Vault selbst --
keine externe Datenbank, kein Server:

* ``.vault-index/index.db`` -- SQLite mit FTS5-Volltext ueber Pfad, Titel,
  Tags, automatisch extrahierte Schlagwoerter, Summary und den **kompletten
  Notiz-Inhalt**. Gezielte Abfragen statt Volltext-Grep::

      SELECT path, title FROM notes WHERE notes MATCH 'suchbegriff'

* ``INDEX.md`` -- kompakte, aus der DB generierte Uebersicht im Vault-Root
  fuer Modelle, die keinen Code ausfuehren koennen: erst die Uebersicht lesen,
  dann gezielt einzelne Notizen nachladen.

Der Index wird inkrementell gepflegt (Content-Hash je Notiz); bei jedem
``--build-vault``-Lauf laeuft die Aktualisierung automatisch mit.

CLI::

    docling-vault-index update --vault <vault>
    docling-vault-index query  --vault <vault> "suchbegriff"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter

INDEX_DIR = ".vault-index"
INDEX_DB = "index.db"
INDEX_MD = "INDEX.md"

_SCHEMA_VERSION = "1"

# ---------------------------------------------------------------------------
# Schlagwort-Extraktion (Stdlib, ohne LLM)
# ---------------------------------------------------------------------------
# Bewusst kompakte Stoppwortlisten (DE/EN) -- es geht um brauchbare
# inhaltsbasierte Schlagwoerter fuer Uebersicht/Suche, nicht um Linguistik.
_STOPWORDS = {
    # Deutsch
    "aber", "alle", "allem", "allen", "aller", "alles", "als", "also", "auch",
    "auf", "aus", "bei", "beim", "bis", "das", "dass", "dem", "den", "der",
    "des", "die", "dies", "diese", "diesem", "diesen", "dieser", "dieses",
    "doch", "dort", "durch", "ein", "eine", "einem", "einen", "einer",
    "eines", "er", "es", "etwa", "fuer", "für", "gegen", "haben", "hat",
    "hier", "ich", "ihr", "ihre", "im", "in", "ist", "ja", "jede", "jedem",
    "jeden", "jeder", "jedes", "kann", "kein", "keine", "koennen", "können",
    "mehr", "mit", "muss", "nach", "nicht", "noch", "nur", "oder", "ohne",
    "sehr", "sein", "seine", "sich", "sie", "sind", "so", "sowie", "ueber",
    "über", "um", "und", "uns", "unter", "vom", "von", "vor", "war", "waren",
    "wenn", "werden", "wie", "wird", "wurde", "wurden", "zu", "zum", "zur",
    "zwischen",
    # Englisch
    "a", "about", "after", "all", "also", "an", "and", "any", "are", "as",
    "at", "be", "been", "but", "by", "can", "could", "for", "from", "had",
    "has", "have", "if", "into", "is", "it", "its", "may", "more", "most",
    "not", "of", "on", "or", "other", "our", "should", "such", "than",
    "that", "the", "their", "then", "there", "these", "they", "this", "to",
    "was", "were", "which", "will", "with", "would",
}

_WORD = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\-]{2,}")
_MD_NOISE = re.compile(r"!\[\[[^\]]*\]\]|!\[[^\]]*\]\([^)]*\)|\[[^\]]*\]\([^)]*\)|[`*_>#|]")


def extract_keywords(content: str, top_n: int = 15) -> list[str]:
    """Haeufigste inhaltstragende Woerter einer Notiz (stoppwort-gefiltert).

    Markdown-Syntax und Links werden vorab entfernt, damit Dateinamen und
    URLs die Schlagwoerter nicht dominieren.
    """
    text = _MD_NOISE.sub(" ", content)
    counts: Counter[str] = Counter()
    for match in _WORD.finditer(text):
        word = match.group(0)
        lower = word.lower()
        if lower in _STOPWORDS or lower.isdigit():
            continue
        counts[lower] += 1
    return [word for word, _ in counts.most_common(top_n)]


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------

def _db_path(vault_dir: os.PathLike | str) -> Path:
    return Path(vault_dir) / INDEX_DIR / INDEX_DB


def open_db(vault_dir: os.PathLike | str) -> sqlite3.Connection:
    """Oeffnet (und initialisiert bei Bedarf) die Index-Datenbank."""
    path = _db_path(vault_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS notes USING fts5("
        "path, title, tags, keywords, summary, content)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS note_meta("
        "path TEXT PRIMARY KEY, content_hash TEXT, mtime REAL, indexed_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chunks("
        "path TEXT, chunk_index INTEGER, heading TEXT, text TEXT, "
        "text_hash TEXT, embedding BLOB, PRIMARY KEY(path, chunk_index))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS index_meta(key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO index_meta(key, value) VALUES('schema_version', ?)",
        (_SCHEMA_VERSION,),
    )
    return conn


@dataclass
class IndexSummary:
    """Ergebnis eines Index-Laufs."""

    indexed: int = 0        # neu oder geaendert
    unchanged: int = 0
    removed: int = 0
    total: int = 0
    indexed_paths: list[str] = field(default_factory=list)


def _note_fields(md_path: Path, rel_path: str) -> dict:
    """Liest eine Notiz und baut die Index-Felder (inkl. Volltext-Inhalt)."""
    post = frontmatter.load(md_path)
    tags = post.get("tags")
    if isinstance(tags, str):
        tags = [tags]
    elif not isinstance(tags, list):
        tags = []
    content = post.content.strip()
    return {
        "path": rel_path,
        "title": str(post.get("title") or md_path.stem),
        "tags": " ".join(str(t) for t in tags),
        "keywords": " ".join(extract_keywords(content)),
        "summary": str(post.get("summary") or ""),
        "content": content,
    }


def update_index(vault_dir: os.PathLike | str) -> IndexSummary:
    """Aktualisiert den FTS5-Index inkrementell (Content-Hash je Notiz).

    Nur neue/geaenderte Notizen werden neu indexiert; fuer verschwundene
    Notizen werden alle Index-Daten (inkl. Embedding-Chunks) entfernt. Bei
    geaenderten Notizen bleiben vorhandene Chunk-Embeddings erhalten, soweit
    sich der jeweilige Chunk-Text nicht geaendert hat (Abgleich passiert im
    Embedding-Schritt ueber text_hash).
    """
    import docling_worker as dw

    vault = Path(vault_dir)
    conn = open_db(vault)
    summary = IndexSummary()
    try:
        known: dict[str, str] = dict(
            conn.execute("SELECT path, content_hash FROM note_meta")
        )
        seen: set[str] = set()

        for md_path in dw.discover_files(vault, extensions={".md"}):
            if md_path.name == INDEX_MD and md_path.parent == vault:
                continue
            rel = md_path.relative_to(vault).as_posix()
            seen.add(rel)
            raw = md_path.read_bytes()
            content_hash = hashlib.sha256(raw).hexdigest()
            if known.get(rel) == content_hash:
                summary.unchanged += 1
                continue

            fields = _note_fields(md_path, rel)
            conn.execute("DELETE FROM notes WHERE path = ?", (rel,))
            conn.execute(
                "INSERT INTO notes(path, title, tags, keywords, summary, content) "
                "VALUES(:path, :title, :tags, :keywords, :summary, :content)",
                fields,
            )
            conn.execute(
                "INSERT INTO note_meta(path, content_hash, mtime, indexed_at) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(path) DO UPDATE SET "
                "content_hash=excluded.content_hash, mtime=excluded.mtime, "
                "indexed_at=excluded.indexed_at",
                (rel, content_hash, md_path.stat().st_mtime,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            summary.indexed += 1
            summary.indexed_paths.append(rel)

        for rel in set(known) - seen:
            conn.execute("DELETE FROM notes WHERE path = ?", (rel,))
            conn.execute("DELETE FROM note_meta WHERE path = ?", (rel,))
            conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
            summary.removed += 1

        summary.total = conn.execute("SELECT count(*) FROM note_meta").fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return summary


def query_index(
    vault_dir: os.PathLike | str, term: str, limit: int = 10
) -> list[dict]:
    """FTS5-Suche ueber alle Spalten (inkl. Volltext) mit Treffer-Snippet."""
    conn = open_db(vault_dir)
    try:
        rows = conn.execute(
            "SELECT path, title, tags, "
            "snippet(notes, 5, '»', '«', ' … ', 12) AS snippet "
            "FROM notes WHERE notes MATCH ? ORDER BY rank LIMIT ?",
            (term, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"path": r[0], "title": r[1], "tags": r[2], "snippet": r[3]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# INDEX.md -- lesbarer Export
# ---------------------------------------------------------------------------

_INDEX_MD_HEADER = """\
# Vault-Index

> Automatisch generiert – nicht von Hand bearbeiten.
>
> **Für KI-Modelle mit Ordnerzugriff:** Diese Datei ist die kompakte
> Übersicht über alle Notizen. Zuerst hier die relevanten Einträge
> identifizieren, dann gezielt einzelne Notizen über den angegebenen Pfad
> nachladen – nicht den gesamten Vault einlesen. Modelle, die Code ausführen
> können, nutzen stattdessen die SQLite-Volltextsuche:
> `.vault-index/index.db`, z. B.
> `SELECT path, title FROM notes WHERE notes MATCH 'suchbegriff'`.

"""


def write_index_md(vault_dir: os.PathLike | str) -> Path:
    """Regeneriert ``INDEX.md`` im Vault-Root aus der Index-Datenbank."""
    vault = Path(vault_dir)
    conn = open_db(vault)
    try:
        rows = conn.execute(
            "SELECT path, title, tags, keywords, summary FROM notes ORDER BY path"
        ).fetchall()
    finally:
        conn.close()

    lines = [_INDEX_MD_HEADER]
    for path, title, tags, keywords, summary in rows:
        parts = [f"- **{title}** – `{path}`"]
        if tags:
            parts.append(" ".join(f"#{t}" for t in tags.split()))
        if keywords:
            parts.append("Schlagwörter: " + ", ".join(keywords.split()[:8]))
        if summary:
            parts.append(summary)
        lines.append(" – ".join(parts))
    lines.append("")

    out = vault / INDEX_MD
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Such-Index fuer den Vault: SQLite-FTS5-Volltext "
        "(.vault-index/index.db) plus lesbares INDEX.md."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_update = sub.add_parser("update", help="Index + INDEX.md aktualisieren")
    p_update.add_argument("--vault", "-o", required=True, help="Vault-Ordner")

    p_query = sub.add_parser("query", help="Volltextsuche (FTS5)")
    p_query.add_argument("--vault", "-o", required=True, help="Vault-Ordner")
    p_query.add_argument("term", help="Suchbegriff (FTS5-Syntax erlaubt)")
    p_query.add_argument("-n", "--limit", type=int, default=10)

    args = parser.parse_args(argv)
    vault = Path(args.vault).resolve()
    if not vault.is_dir():
        parser.error(f"Vault-Ordner existiert nicht: {vault}")

    if args.cmd == "update":
        summary = update_index(vault)
        write_index_md(vault)
        print(f"Index aktualisiert: {summary.indexed} neu/geändert, "
              f"{summary.unchanged} unverändert, {summary.removed} entfernt "
              f"({summary.total} Notizen insgesamt).")
        print(f"Übersicht: {vault / INDEX_MD}")
        return 0

    if args.cmd == "query":
        results = query_index(vault, args.term, limit=args.limit)
        if not results:
            print("Keine Treffer.")
            return 1
        for r in results:
            print(f"{r['path']}")
            print(f"  Titel: {r['title']}" + (f"  Tags: {r['tags']}" if r["tags"] else ""))
            print(f"  … {r['snippet']}")
        return 0

    return 0


def main() -> int:
    """Einstiegspunkt fuer den ``docling-vault-index``-Konsolenbefehl."""
    return _run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
