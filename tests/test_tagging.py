"""Tests fuer den Tagging-Schritt von vault_index (Fake-Client, ohne Ollama)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import frontmatter
import pytest

import vault_index as vi


class FakeTagger:
    """LLM-Ersatz: liefert JSON mit Tags/Summary, umgeben von Plaudertext."""

    def __init__(self, broken: bool = False) -> None:
        self.calls = 0
        self.broken = broken

    def list_models(self):
        return ["llama3.2:latest"]

    def generate(self, model, prompt):
        self.calls += 1
        if self.broken:
            return "Tut mir leid, hier sind ein paar Gedanken ohne JSON."
        return (
            "Gerne! Hier ist das Ergebnis:\n"
            + json.dumps({"tags": ["Photovoltaik", "#energie", "wartung plan"],
                          "summary": "Wartungsplan der Solaranlage."})
        )


def _note(path: Path, body: str, tags: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tag_line = f"tags: [{', '.join(tags)}]\n" if tags else ""
    path.write_text(f"---\ntitle: {path.stem}\n{tag_line}---\n{body}\n",
                    encoding="utf-8")


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    _note(v / "Inbox" / "solar.md", "Die Anlage wird halbjährlich gewartet.",
          tags=["bestand"])
    vi.update_index(v)
    return v


def test_parse_tag_response_tolerant():
    ok = vi._parse_tag_response('bla {"tags": ["A B", "#x"], "summary": "S."} bla')
    assert ok == (["a-b", "x"], "S.")
    assert vi._parse_tag_response("kein json hier") is None
    assert vi._parse_tag_response('{"tags": "falsch", "summary": 1}') is None


def test_tag_vault_updates_db(vault):
    client = FakeTagger()
    s = vi.tag_vault(vault, client, "fake-llm")
    assert s.tagged == 1 and s.parse_errors == 0

    conn = sqlite3.connect(vault / vi.INDEX_DIR / vi.INDEX_DB)
    tags, summary = conn.execute(
        "SELECT tags, summary FROM notes WHERE path='Inbox/solar.md'"
    ).fetchone()
    conn.close()
    assert "bestand" in tags            # manueller Tag bleibt
    assert "photovoltaik" in tags       # neuer Tag dazu
    assert summary == "Wartungsplan der Solaranlage."

    # Notiz-Datei selbst unveraendert (kein --write-notes).
    post = frontmatter.load(vault / "Inbox" / "solar.md")
    assert post.get("summary") is None


def test_tag_vault_write_notes_merges_frontmatter(vault):
    client = FakeTagger()
    vi.tag_vault(vault, client, "fake-llm", write_notes=True)

    post = frontmatter.load(vault / "Inbox" / "solar.md")
    assert post["summary"] == "Wartungsplan der Solaranlage."
    assert post["tags"][0] == "bestand"             # manuell zuerst, erhalten
    assert "photovoltaik" in post["tags"]
    assert len(post["tags"]) == len(set(post["tags"]))  # keine Duplikate

    # Rueckschreiben darf keine Reindex-/Retag-Schleife ausloesen.
    s_idx = vi.update_index(vault)
    assert s_idx.indexed == 0
    calls_before = client.calls
    s_tag = vi.tag_vault(vault, client, "fake-llm", write_notes=True)
    assert s_tag.tagged == 0 and s_tag.unchanged == 1
    assert client.calls == calls_before


def test_tag_vault_idempotent_and_rearms_on_change(vault):
    client = FakeTagger()
    vi.tag_vault(vault, client, "fake-llm")
    assert client.calls == 1

    s = vi.tag_vault(vault, client, "fake-llm")     # nichts geaendert
    assert s.tagged == 0 and s.unchanged == 1
    assert client.calls == 1

    # Inhaltsaenderung -> Notiz wird erneut getaggt.
    note = vault / "Inbox" / "solar.md"
    note.write_text(note.read_text(encoding="utf-8") + "\nNeuer Absatz.",
                    encoding="utf-8")
    vi.update_index(vault)
    s = vi.tag_vault(vault, client, "fake-llm")
    assert s.tagged == 1
    assert client.calls == 2


def test_broken_llm_response_skips_note(vault):
    client = FakeTagger(broken=True)
    s = vi.tag_vault(vault, client, "fake-llm")
    assert s.tagged == 0 and s.parse_errors == 1

    # Naechster Lauf versucht es erneut (kein tagged_hash gesetzt).
    s = vi.tag_vault(vault, client, "fake-llm")
    assert s.parse_errors == 1
