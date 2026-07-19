"""Tests fuer vault_index: FTS5-Volltext, Keywords, Inkrement, INDEX.md."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import vault_index as vi


def _note(path: Path, title: str, body: str, tags: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_tags = f"tags: [{tags}]\n" if tags else "tags: []\n"
    path.write_text(
        f"---\ntitle: {title}\n{fm_tags}---\n{body}\n", encoding="utf-8"
    )
    return path


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    _note(v / "Inbox" / "Bericht.md", "Quartalsbericht",
          "# Umsatz\n\nDie Photovoltaik-Anlage lieferte im März deutlich "
          "mehr Ertrag als geplant. Wartungskosten blieben stabil.",
          tags="energie, bericht")
    _note(v / "Inbox" / "Protokoll.md", "Team-Protokoll",
          "Besprechung zum Serverumzug. Proxmox-Cluster wird erweitert, "
          "Speicherplatz verdoppelt.")
    return v


def test_fulltext_hits_body_not_just_title(vault):
    """Der Inhalt ist indexiert: Treffer fuer Begriff, der NUR im Body steht."""
    vi.update_index(vault)
    results = vi.query_index(vault, "Photovoltaik")
    assert len(results) == 1
    assert results[0]["path"] == "Inbox/Bericht.md"
    assert "Photovoltaik" in results[0]["snippet"]

    results = vi.query_index(vault, "Proxmox")
    assert results[0]["path"] == "Inbox/Protokoll.md"


def test_literal_example_query_from_spec(vault):
    """Die woertliche Beispiel-Query der Anforderung funktioniert."""
    vi.update_index(vault)
    conn = sqlite3.connect(vault / vi.INDEX_DIR / vi.INDEX_DB)
    rows = conn.execute(
        "SELECT path, title FROM notes WHERE notes MATCH 'Serverumzug'"
    ).fetchall()
    conn.close()
    assert rows == [("Inbox/Protokoll.md", "Team-Protokoll")]


def test_keyword_extraction():
    text = ("Die Photovoltaik Anlage liefert Strom. Photovoltaik ist wichtig. "
            "Der Strom wird gespeichert und die Anlage überwacht. "
            "![[bild.png]] [Link](http://example.org/sehrlangeurl)")
    kws = vi.extract_keywords(text)
    assert "photovoltaik" in kws and "anlage" in kws and "strom" in kws
    assert "die" not in kws and "wird" not in kws     # Stoppwoerter raus
    assert not any("example.org" in k for k in kws)   # Links entfernt


def test_keywords_in_index_and_searchable(vault):
    vi.update_index(vault)
    conn = sqlite3.connect(vault / vi.INDEX_DIR / vi.INDEX_DB)
    kws = conn.execute(
        "SELECT keywords FROM notes WHERE path='Inbox/Bericht.md'"
    ).fetchone()[0]
    conn.close()
    assert "photovoltaik" in kws


def test_incremental_update(vault):
    s1 = vi.update_index(vault)
    assert s1.indexed == 2 and s1.unchanged == 0

    s2 = vi.update_index(vault)               # nichts geaendert
    assert s2.indexed == 0 and s2.unchanged == 2

    # Aenderung -> genau eine Notiz neu indexiert.
    note = vault / "Inbox" / "Bericht.md"
    note.write_text(note.read_text(encoding="utf-8") + "\nWindkraft kommt dazu.",
                    encoding="utf-8")
    s3 = vi.update_index(vault)
    assert s3.indexed == 1 and s3.unchanged == 1
    assert vi.query_index(vault, "Windkraft")

    # Loeschung -> Eintrag inkl. Chunks entfernt.
    conn = vi.open_db(vault)
    conn.execute("INSERT INTO chunks(path, chunk_index, heading, text, text_hash) "
                 "VALUES('Inbox/Protokoll.md', 0, '', 'x', 'h')")
    conn.commit()
    conn.close()
    (vault / "Inbox" / "Protokoll.md").unlink()
    s4 = vi.update_index(vault)
    assert s4.removed == 1 and s4.total == 1
    conn = sqlite3.connect(vault / vi.INDEX_DIR / vi.INDEX_DB)
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
    assert not conn.execute(
        "SELECT * FROM notes WHERE path='Inbox/Protokoll.md'").fetchall()
    conn.close()


def test_index_md_written_and_not_selfindexed(vault):
    vi.update_index(vault)
    out = vi.write_index_md(vault)
    text = out.read_text(encoding="utf-8")
    assert "**Quartalsbericht** – `Inbox/Bericht.md`" in text
    assert "#energie" in text
    assert "Schlagwörter:" in text

    # INDEX.md und .vault-index duerfen sich nicht selbst indexieren.
    s = vi.update_index(vault)
    assert s.total == 2
    assert not vi.query_index(vault, "Automatisch generiert")


def test_index_status(vault):
    assert vi.index_status(vault)["exists"] is False
    vi.update_index(vault)
    status = vi.index_status(vault)
    assert status["exists"] and status["notes"] == 2
    assert status["last_indexed"]
    assert status["embedded_chunks"] == 0 and status["embed_model"] is None


def test_cli_update_and_query(vault, capsys):
    assert vi._run_cli(["update", "--vault", str(vault)]) == 0
    out = capsys.readouterr().out
    assert "2 neu/geändert" in out

    assert vi._run_cli(["query", "--vault", str(vault), "Photovoltaik"]) == 0
    out = capsys.readouterr().out
    assert "Inbox/Bericht.md" in out

    assert vi._run_cli(["query", "--vault", str(vault), "nichtvorhanden"]) == 1
