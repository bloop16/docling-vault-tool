"""Tests fuer den Embedding-Teil von vault_index (Fake-Client, ohne Ollama)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("numpy")

import vault_index as vi


class FakeOllama:
    """Deterministische Embeddings: Vektor haengt vom Text-Schluesselwort ab."""

    VECTORS = {
        "solar": [1.0, 0.0, 0.0, 0.0],
        "server": [0.0, 1.0, 0.0, 0.0],
        "garten": [0.0, 0.0, 1.0, 0.0],
    }

    def __init__(self) -> None:
        self.embed_calls = 0

    def list_models(self):
        return ["nomic-embed-text:latest", "mxbai-embed-large"]

    def embed(self, model, text):
        self.embed_calls += 1
        lower = text.lower()
        for key, vec in self.VECTORS.items():
            if key in lower:
                return vec
        return [0.0, 0.0, 0.0, 1.0]


class DeadOllama:
    def list_models(self):
        raise vi.OllamaError("Ollama unter http://tot:11434 nicht erreichbar")

    def embed(self, model, text):
        raise vi.OllamaError("Ollama unter http://tot:11434 nicht erreichbar")


def _note(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: {path.stem}\n---\n{body}\n", encoding="utf-8")


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    _note(v / "Inbox" / "solar.md", "# Anlage\n\nDie Solar-Module liefern Strom.")
    _note(v / "Inbox" / "server.md", "# Cluster\n\nDer Server im Rack laeuft stabil.")
    vi.update_index(v)
    return v


def test_split_chunks_headings_and_overlap():
    content = "Einleitung.\n\n# A\n\nText A.\n\n# B\n\n" + ("x" * 3500)
    chunks = vi.split_chunks(content, max_chars=1500, overlap=200)
    headings = [h for h, _ in chunks]
    assert headings[0] == "" and "A" in headings and "B" in headings
    b_chunks = [t for h, t in chunks if h == "B"]
    assert len(b_chunks) >= 3                       # Sliding-Window griff
    assert b_chunks[1][:200] == b_chunks[0][-200:]  # Overlap vorhanden

    # Kurzer Text ohne Headings -> genau ein Chunk.
    assert vi.split_chunks("nur ein Satz") == [("", "nur ein Satz")]


def test_embed_vault_and_reuse(vault):
    client = FakeOllama()
    s1 = vi.embed_vault(vault, client, "fake-model")
    assert s1.notes == 2
    assert s1.chunks_embedded >= 2
    assert s1.dimension == 4                        # per Test-Call ermittelt
    first_calls = client.embed_calls

    # Zweiter Lauf ohne Aenderung: alles wiederverwendet, nur der Probe-Call.
    s2 = vi.embed_vault(vault, client, "fake-model")
    assert s2.chunks_embedded == 0
    assert s2.chunks_reused == s1.chunks_embedded
    assert client.embed_calls == first_calls + 1    # nur dimension probe

    # Modellwechsel invalidiert alle Embeddings.
    s3 = vi.embed_vault(vault, client, "anderes-model")
    assert s3.chunks_embedded == s1.chunks_embedded
    assert s3.chunks_reused == 0


def test_similar_ranking(vault):
    client = FakeOllama()
    vi.embed_vault(vault, client, "fake-model")

    results = vi.similar(vault, "Wieviel Strom liefert die Solar-Anlage?",
                         client, top_k=2)
    assert results[0]["path"] == "Inbox/solar.md"
    assert results[0]["score"] > results[-1]["score"]

    results = vi.similar(vault, "Ist der Server stabil?", client, top_k=2)
    assert results[0]["path"] == "Inbox/server.md"


def test_similar_without_embeddings_raises(vault):
    with pytest.raises(vi.OllamaError):
        vi.similar(vault, "frage", FakeOllama())


def test_dead_ollama_leaves_fts_intact(vault):
    with pytest.raises(vi.OllamaError):
        vi.embed_vault(vault, DeadOllama(), "egal")
    # FTS-Index funktioniert weiterhin.
    assert vi.query_index(vault, "Solar-Module")


def test_resolve_model_lists_available():
    client = FakeOllama()
    assert vi._resolve_model(client, "explizit", "X_ENV", "Test") == "explizit"
    with pytest.raises(vi.OllamaError) as exc:
        vi._resolve_model(client, None, "DOCLING_UNSET_ENV_VAR", "Test")
    assert "nomic-embed-text" in str(exc.value)


def test_cli_models_against_dead_host(capsys, monkeypatch):
    monkeypatch.setenv("DOCLING_OLLAMA_URL", "http://127.0.0.1:1")
    rc = vi._run_cli(["models"])
    assert rc == 2
    assert "nicht erreichbar" in capsys.readouterr().err
