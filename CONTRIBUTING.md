# Mitwirken an doc2vault

Beiträge sind willkommen — von Fehlerberichten über Doku bis zu Features.

## Entwicklungsumgebung

```bash
git clone https://github.com/bloop16/docling-vault-tool
cd docling-vault-tool
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt streamlit ruff
```

Die Testsuite läuft **ohne installiertes Docling** (Stub in
`tests/conftest.py`) — für reine Logik-Änderungen ist kein Modell-Download
nötig. Für End-to-End-Tests: `pip install -e .` (zieht Docling).

## Qualitätsanforderungen

- `ruff check .` und `pytest` müssen grün sein (die CI erzwingt beides auf
  Python 3.10–3.12).
- Neue Funktionalität bekommt Tests; Fehlerbehebungen einen Test, der den
  Fehler reproduziert.
- Code-Kommentare und Commit-Messages sind auf Deutsch, im Stil der
  bestehenden Historie: erste Zeile prägnant, danach das *Warum*.
- Keine Breaking Changes an CLI-Flags, Job-/Manifest-Formaten oder dem
  Vault-Layout ohne vorherige Diskussion in einem Issue.

## Pull Requests

1. Branch von `main` abzweigen.
2. Änderung + Tests + ggf. MANUAL.md/README-Anpassung.
3. PR mit kurzer Beschreibung: Problem, Lösung, Verifikation.
