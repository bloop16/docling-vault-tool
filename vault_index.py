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

Optional (additiv, keine Hard-Dependency): semantische Suche via Ollama-
Embeddings -- Notizen werden heading-basiert in Chunks gesplittet, Embeddings
liegen als Float32-BLOBs in derselben ``index.db``, die Aehnlichkeitssuche
laeuft mit numpy (Cosine) direkt in Python. Ist Ollama nicht erreichbar,
laufen Vault-Build und FTS5-Index trotzdem vollstaendig durch.

CLI::

    docling-vault-index update  --vault <vault>
    docling-vault-index query   --vault <vault> "suchbegriff"
    docling-vault-index models  [--ollama-url http://host:11434]
    docling-vault-index embed   --vault <vault> --model nomic-embed-text
    docling-vault-index similar --vault <vault> "frage" [-n 5]
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

from typing import Callable

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
    # tagged_hash: Content-Stand, fuer den der Tagging-Schritt zuletzt lief
    # (Idempotenz). Nachtraegliche Migration bestehender Datenbanken.
    try:
        conn.execute("ALTER TABLE note_meta ADD COLUMN tagged_hash TEXT")
    except sqlite3.OperationalError:
        pass  # Spalte existiert bereits
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


def index_status(vault_dir: os.PathLike | str) -> dict:
    """Kompakter Status des Index (fuer Dashboard/CLI-Anzeigen)."""
    if not _db_path(vault_dir).is_file():
        return {"exists": False, "notes": 0, "embedded_chunks": 0,
                "embed_model": None, "last_indexed": None}
    conn = open_db(vault_dir)
    try:
        notes = conn.execute("SELECT count(*) FROM note_meta").fetchone()[0]
        last = conn.execute("SELECT max(indexed_at) FROM note_meta").fetchone()[0]
        chunks = conn.execute(
            "SELECT count(*) FROM chunks WHERE embedding IS NOT NULL"
        ).fetchone()[0]
        model = conn.execute(
            "SELECT value FROM index_meta WHERE key='embed_model'"
        ).fetchone()
    finally:
        conn.close()
    return {"exists": True, "notes": notes, "embedded_chunks": chunks,
            "embed_model": model[0] if model else None, "last_indexed": last}


def query_index(
    vault_dir: os.PathLike | str, term: str, limit: int = 10
) -> list[dict]:
    """FTS5-Suche ueber alle Spalten (inkl. Volltext) mit Treffer-Snippet.

    FTS5-Syntax (AND/OR/NEAR, Spaltenfilter) wird durchgereicht; ist der
    Begriff keine gueltige FTS5-Query (z. B. "Solar-Module" -- Bindestrich
    ist ein Operator), wird er automatisch als Phrase gequotet.
    """
    sql = ("SELECT path, title, tags, "
           "snippet(notes, 5, '»', '«', ' … ', 12) AS snippet "
           "FROM notes WHERE notes MATCH ? ORDER BY rank LIMIT ?")
    conn = open_db(vault_dir)
    try:
        try:
            rows = conn.execute(sql, (term, limit)).fetchall()
        except sqlite3.OperationalError:
            phrase = '"' + term.replace('"', '""') + '"'
            rows = conn.execute(sql, (phrase, limit)).fetchall()
    finally:
        conn.close()
    return [
        {"path": r[0], "title": r[1], "tags": r[2], "snippet": r[3]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Ollama-Anbindung (optional, fuer Embeddings und Tagging)
# ---------------------------------------------------------------------------

DEFAULT_OLLAMA_URL = "http://localhost:11434"


class OllamaError(RuntimeError):
    """Ollama nicht erreichbar oder Antwort unbrauchbar."""


class OllamaClient:
    """Minimaler Ollama-HTTP-Client (Stdlib urllib, Timeout + Retry).

    ``base_url`` kommt aus dem CLI-Flag bzw. ``DOCLING_OLLAMA_URL``.
    In Tests wird der Client durch ein Fake-Objekt mit derselben Schnittstelle
    ersetzt (``list_models``/``embed``/``generate``).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        retries: int = 2,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("DOCLING_OLLAMA_URL") or DEFAULT_OLLAMA_URL
        ).rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def _request(self, path: str, payload: Optional[dict] = None) -> dict:
        import urllib.error
        import urllib.request

        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                req = urllib.request.Request(
                    url, data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST" if data is not None else "GET",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
        raise OllamaError(
            f"Ollama unter {self.base_url} nicht erreichbar: {last_error}"
        )

    def list_models(self) -> list[str]:
        data = self._request("/api/tags")
        return [m.get("name", "") for m in data.get("models", [])]

    def embed(self, model: str, text: str) -> list[float]:
        data = self._request("/api/embeddings", {"model": model, "prompt": text})
        embedding = data.get("embedding")
        if not embedding:
            raise OllamaError(f"Leeres Embedding von Modell {model!r}.")
        return embedding

    def generate(self, model: str, prompt: str) -> str:
        data = self._request(
            "/api/generate", {"model": model, "prompt": prompt, "stream": False}
        )
        return str(data.get("response", ""))


def _resolve_model(
    client, model: Optional[str], env_var: str, purpose: str
) -> str:
    """Modellnamen aus Flag/ENV aufloesen; sonst verfuegbare Modelle anzeigen.

    Die Modellwahl passiert bewusst erst NACH erfolgreicher Verbindung --
    die Liste kommt live aus ``/api/tags``.
    """
    resolved = model or os.environ.get(env_var)
    available = client.list_models()
    if resolved:
        return resolved
    listing = "\n".join(f"  - {m}" for m in available) or "  (keine Modelle)"
    raise OllamaError(
        f"Kein Modell fuer {purpose} angegeben. Verfuegbar auf dem Server:\n"
        f"{listing}\nAuswahl per --model bzw. {env_var}."
    )


# ---------------------------------------------------------------------------
# Chunking + Embeddings
# ---------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def split_chunks(
    content: str, max_chars: int = 1500, overlap: int = 200
) -> list[tuple[str, str]]:
    """Splittet eine Notiz in ``(heading, text)``-Chunks.

    Primaer an Markdown-Headings (das Heading gibt jedem Chunk Kontext);
    ueberlange Abschnitte werden zusaetzlich als Sliding-Window mit Overlap
    geteilt -- eine ganze Docling-Konvertierung als EIN Vektor waere fuer
    Aehnlichkeitssuche zu grob.
    """
    sections: list[tuple[str, str]] = []
    matches = list(_HEADING.finditer(content))
    if not matches:
        sections.append(("", content.strip()))
    else:
        preamble = content[: matches[0].start()].strip()
        if preamble:
            sections.append(("", preamble))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            body = content[m.end():end].strip()
            if body:
                sections.append((m.group(2).strip(), body))

    chunks: list[tuple[str, str]] = []
    for heading, text in sections:
        if len(text) <= max_chars:
            chunks.append((heading, text))
            continue
        step = max_chars - overlap
        for start in range(0, len(text), step):
            window = text[start:start + max_chars]
            if window.strip():
                chunks.append((heading, window))
            if start + max_chars >= len(text):
                break
    return chunks


def _to_blob(vector: list[float]) -> bytes:
    import numpy as np

    return np.asarray(vector, dtype=np.float32).tobytes()


def _from_blob(blob: bytes):
    import numpy as np

    return np.frombuffer(blob, dtype=np.float32)


@dataclass
class EmbedSummary:
    """Ergebnis eines Embedding-Laufs."""

    notes: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0
    model: str = ""
    dimension: int = 0


def embed_vault(
    vault_dir: os.PathLike | str,
    client,
    model: str,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> EmbedSummary:
    """Berechnet Embeddings fuer alle Notiz-Chunks (sequenziell, idempotent).

    Pro Chunk wird der ``text_hash`` geprueft -- vorhandene Embeddings mit
    gleichem Hash werden wiederverwendet, nur Neues geht an Ollama. Ein
    Modellwechsel (``index_meta.embed_model``) invalidiert alle Embeddings.
    Die Embedding-Dimension wird beim ersten Call ermittelt und gespeichert,
    nicht hartcodiert.
    """
    vault = Path(vault_dir)
    conn = open_db(vault)
    summary = EmbedSummary(model=model)
    try:
        prev_model = conn.execute(
            "SELECT value FROM index_meta WHERE key='embed_model'"
        ).fetchone()
        if prev_model and prev_model[0] != model:
            conn.execute("UPDATE chunks SET embedding = NULL")

        # Dimension per Test-Call ermitteln (und Verbindung verifizieren).
        probe = client.embed(model, "dimension probe")
        summary.dimension = len(probe)

        note_paths = [r[0] for r in conn.execute("SELECT path FROM note_meta")]
        for done, rel in enumerate(note_paths, start=1):
            md_path = vault / rel
            if not md_path.is_file():
                continue
            content = frontmatter.load(md_path).content
            chunks = split_chunks(content)

            # Vorhandene Embeddings nach text_hash fuer Wiederverwendung.
            existing = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT text_hash, embedding FROM chunks "
                    "WHERE path = ? AND embedding IS NOT NULL", (rel,)
                )
            }
            conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
            for idx, (heading, text) in enumerate(chunks):
                text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                blob = existing.get(text_hash)
                if blob is not None:
                    summary.chunks_reused += 1
                else:
                    blob = _to_blob(client.embed(model, text))
                    summary.chunks_embedded += 1
                conn.execute(
                    "INSERT INTO chunks(path, chunk_index, heading, text, "
                    "text_hash, embedding) VALUES(?, ?, ?, ?, ?, ?)",
                    (rel, idx, heading, text, text_hash, blob),
                )
            summary.notes += 1
            conn.commit()   # pro Notiz committen -- Abbruch verliert wenig
            if progress:
                progress(done, len(note_paths), rel)

        conn.execute(
            "INSERT INTO index_meta(key, value) VALUES('embed_model', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (model,)
        )
        conn.execute(
            "INSERT INTO index_meta(key, value) VALUES('embed_dim', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(summary.dimension),),
        )
        conn.commit()
    finally:
        conn.close()
    return summary


def similar(
    vault_dir: os.PathLike | str,
    query: str,
    client,
    model: Optional[str] = None,
    top_k: int = 5,
) -> list[dict]:
    """Semantische Suche: Cosine-Similarity (numpy) ueber alle Chunk-Embeddings."""
    import numpy as np

    conn = open_db(vault_dir)
    try:
        stored_model = conn.execute(
            "SELECT value FROM index_meta WHERE key='embed_model'"
        ).fetchone()
        if not stored_model:
            raise OllamaError(
                "Noch keine Embeddings vorhanden -- zuerst "
                "'docling-vault-index embed --model …' ausfuehren."
            )
        model = model or stored_model[0]
        rows = conn.execute(
            "SELECT path, heading, text, embedding FROM chunks "
            "WHERE embedding IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return []

    query_vec = np.asarray(client.embed(model, query), dtype=np.float32)
    matrix = np.vstack([_from_blob(r[3]) for r in rows])
    norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query_vec) or 1.0)
    norms[norms == 0] = 1.0
    scores = matrix @ query_vec / norms

    order = np.argsort(scores)[::-1][:top_k]
    return [
        {
            "path": rows[i][0],
            "heading": rows[i][1],
            "text": rows[i][2][:200],
            "score": float(scores[i]),
        }
        for i in order
    ]


# ---------------------------------------------------------------------------
# Inhaltsbasiertes Tagging + Summary via Ollama (optional)
# ---------------------------------------------------------------------------

_TAG_PROMPT = """Du bist ein Verschlagwortungs-Assistent für einen Obsidian-Vault.
Analysiere die folgende Notiz und antworte NUR mit einem JSON-Objekt in
exakt diesem Format, ohne weiteren Text:
{{"tags": ["tag1", "tag2"], "summary": "Ein bis zwei Sätze."}}

Regeln: 3 bis 7 Tags, kleingeschrieben, Deutsch, ohne #-Zeichen.
Die Zusammenfassung: 1-2 Sätze auf Deutsch, sachlich.

Titel: {title}

Inhalt:
{content}
"""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_tag_response(response: str) -> Optional[tuple[list[str], str]]:
    """Extrahiert tags/summary aus einer LLM-Antwort (tolerant, None bei Murks)."""
    match = _JSON_BLOCK.search(response)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    tags = data.get("tags")
    summary = data.get("summary")
    if not isinstance(tags, list) or not isinstance(summary, str):
        return None
    clean = [str(t).strip().lstrip("#").lower().replace(" ", "-")
             for t in tags if str(t).strip()]
    return clean[:7], summary.strip()


@dataclass
class TagSummary:
    """Ergebnis eines Tagging-Laufs."""

    tagged: int = 0
    unchanged: int = 0
    parse_errors: int = 0
    model: str = ""


def tag_vault(
    vault_dir: os.PathLike | str,
    client,
    model: str,
    write_notes: bool = False,
    max_content_chars: int = 4000,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> TagSummary:
    """Erzeugt Tags + 1-2-Satz-Summary je Notiz aus dem INHALT (Ollama).

    Idempotent: pro Notiz wird der Content-Hash gemerkt (``tagged_hash``);
    nur neue/geaenderte Notizen gehen erneut ans Modell. Mit ``write_notes``
    werden Tags (gemergt mit vorhandenen manuellen Tags, nie ersetzt) und
    ``summary`` zusaetzlich ins Notiz-Frontmatter geschrieben -- damit sind
    sie in Obsidian echte Tags/Properties und Grundlage fuer die Zuweisung
    durch den Curator. Unbrauchbare LLM-Antworten ueberspringen die Notiz,
    der Lauf laeuft weiter.
    """
    vault = Path(vault_dir)
    conn = open_db(vault)
    summary = TagSummary(model=model)
    try:
        rows = conn.execute(
            "SELECT path, content_hash, tagged_hash FROM note_meta"
        ).fetchall()
        for done, (rel, content_hash, tagged_hash) in enumerate(rows, start=1):
            if progress:
                progress(done, len(rows), rel)
            if tagged_hash == content_hash:
                summary.unchanged += 1
                continue
            md_path = vault / rel
            if not md_path.is_file():
                continue

            post = frontmatter.load(md_path)
            title = str(post.get("title") or md_path.stem)
            response = client.generate(
                model,
                _TAG_PROMPT.format(
                    title=title, content=post.content[:max_content_chars]
                ),
            )
            parsed = _parse_tag_response(response)
            if parsed is None:
                summary.parse_errors += 1
                continue
            new_tags, new_summary = parsed

            # Vorhandene manuelle Tags mergen, nie ersetzen.
            existing = post.get("tags")
            if isinstance(existing, str):
                existing = [existing]
            elif not isinstance(existing, list):
                existing = []
            merged = list(existing) + [t for t in new_tags if t not in existing]

            if write_notes:
                post["tags"] = merged
                post["summary"] = new_summary
                md_path.write_text(
                    frontmatter.dumps(post) + "\n", encoding="utf-8"
                )
                # Neuen Dateistand einfrieren, damit weder update_index noch
                # der naechste Tagging-Lauf die Notiz erneut anfassen.
                content_hash = hashlib.sha256(md_path.read_bytes()).hexdigest()
                conn.execute(
                    "UPDATE note_meta SET content_hash=?, mtime=? WHERE path=?",
                    (content_hash, md_path.stat().st_mtime, rel),
                )

            # FTS-Zeile mit neuen Tags/Summary neu schreiben.
            fields = _note_fields(md_path, rel)
            fields["tags"] = " ".join(str(t) for t in merged)
            fields["summary"] = new_summary
            conn.execute("DELETE FROM notes WHERE path = ?", (rel,))
            conn.execute(
                "INSERT INTO notes(path, title, tags, keywords, summary, content) "
                "VALUES(:path, :title, :tags, :keywords, :summary, :content)",
                fields,
            )
            conn.execute(
                "UPDATE note_meta SET tagged_hash=? WHERE path=?",
                (content_hash, rel),
            )
            summary.tagged += 1
            conn.commit()
    finally:
        conn.close()
    return summary


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

    p_models = sub.add_parser(
        "models", help="Verfuegbare Ollama-Modelle anzeigen (/api/tags)"
    )
    p_models.add_argument("--ollama-url", default=None,
                          help=f"Ollama-URL (ENV DOCLING_OLLAMA_URL, "
                          f"Default {DEFAULT_OLLAMA_URL})")

    p_embed = sub.add_parser(
        "embed", help="Embeddings fuer alle Notiz-Chunks berechnen (Ollama)"
    )
    p_embed.add_argument("--vault", "-o", required=True, help="Vault-Ordner")
    p_embed.add_argument("--model", "-m", default=None,
                         help="Embedding-Modell (ENV DOCLING_EMBED_MODEL)")
    p_embed.add_argument("--ollama-url", default=None)

    p_similar = sub.add_parser(
        "similar", help="Semantische Suche ueber die Embeddings"
    )
    p_similar.add_argument("--vault", "-o", required=True, help="Vault-Ordner")
    p_similar.add_argument("query", help="Frage/Suchtext")
    p_similar.add_argument("-n", "--top", type=int, default=5)
    p_similar.add_argument("--model", "-m", default=None)
    p_similar.add_argument("--ollama-url", default=None)

    p_tag = sub.add_parser(
        "tag", help="Tags + Summary je Notiz aus dem Inhalt erzeugen (Ollama)"
    )
    p_tag.add_argument("--vault", "-o", required=True, help="Vault-Ordner")
    p_tag.add_argument("--model", "-m", default=None,
                       help="Sprachmodell (ENV DOCLING_TAG_MODEL)")
    p_tag.add_argument("--write-notes", action="store_true",
                       help="Tags/Summary zusaetzlich ins Notiz-Frontmatter "
                       "schreiben (Tags werden gemergt, nie ersetzt)")
    p_tag.add_argument("--ollama-url", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "models":
        client = OllamaClient(args.ollama_url)
        try:
            models = client.list_models()
        except OllamaError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"Modelle auf {client.base_url}:")
        for name in models or ["(keine Modelle installiert)"]:
            print(f"  - {name}")
        return 0

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

    if args.cmd == "embed":
        client = OllamaClient(args.ollama_url)
        try:
            model = _resolve_model(client, args.model, "DOCLING_EMBED_MODEL",
                                   "Embeddings")
            summary = embed_vault(vault, client, model)
        except OllamaError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"Embeddings aktualisiert (Modell {summary.model}, "
              f"Dimension {summary.dimension}): {summary.chunks_embedded} neu, "
              f"{summary.chunks_reused} wiederverwendet "
              f"({summary.notes} Notizen).")
        return 0

    if args.cmd == "similar":
        client = OllamaClient(args.ollama_url)
        try:
            results = similar(vault, args.query, client,
                              model=args.model or os.environ.get("DOCLING_EMBED_MODEL"),
                              top_k=args.top)
        except OllamaError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if not results:
            print("Keine Embeddings vorhanden oder keine Treffer.")
            return 1
        for r in results:
            heading = f" › {r['heading']}" if r["heading"] else ""
            print(f"{r['score']:.3f}  {r['path']}{heading}")
            print(f"       {r['text'][:120]}")
        return 0

    if args.cmd == "tag":
        client = OllamaClient(args.ollama_url)
        try:
            model = _resolve_model(client, args.model, "DOCLING_TAG_MODEL",
                                   "Tagging")
            summary = tag_vault(vault, client, model,
                                write_notes=args.write_notes)
        except OllamaError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        write_index_md(vault)
        print(f"Tagging abgeschlossen (Modell {summary.model}): "
              f"{summary.tagged} Notiz(en) getaggt, "
              f"{summary.unchanged} unverändert übersprungen, "
              f"{summary.parse_errors} unbrauchbare Antworten.")
        if args.write_notes:
            print("Tags/Summary wurden ins Frontmatter der Notizen geschrieben.")
        return 0

    return 0


def main() -> int:
    """Einstiegspunkt fuer den ``docling-vault-index``-Konsolenbefehl."""
    return _run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
