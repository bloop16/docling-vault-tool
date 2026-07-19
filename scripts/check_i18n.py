#!/usr/bin/env python3
"""Konsistenzpruefung der Uebersetzungen (wie bei ioBroker-Adaptern).

Prueft fuer jede Sprachdatei ``i18n/<lang>.json``:

1. **Vollstaendigkeit**: jeder im Dashboard verwendete ``tr("...")``-/
   ``_("...")``-Schluessel (per AST aus ``app_streamlit.py`` extrahiert)
   und jeder statische Fehlerhinweis aus ``docling_worker._ERROR_RULES``
   hat einen Eintrag.
2. **Keine Waisen**: kein Eintrag, dessen Schluessel nirgends verwendet wird.
3. **Platzhalter-Treue**: ``{n}``-artige Platzhalter sind in Schluessel und
   Uebersetzung identisch (sonst wirft ``str.format`` zur Laufzeit).
4. **Paritaet**: alle Sprachdateien haben exakt dieselben Schluessel wie
   ``en.json`` (Referenz).

Exit-Code 0 = alles konsistent. Laeuft auch als Test (tests/test_i18n.py).
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_PLACEHOLDER = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")

# tr()-Aliasnamen im Dashboard-Code.
_TR_NAMES = {"tr", "_"}


def used_keys() -> set[str]:
    """Alle statisch ermittelbaren Uebersetzungs-Schluessel des Projekts."""
    keys: set[str] = set()
    tree = ast.parse((ROOT / "app_streamlit.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _TR_NAMES
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)

    # Statische Fehlerhinweise (werden bei der Anzeige uebersetzt).
    sys.path.insert(0, str(ROOT))
    import docling_worker as dw  # noqa: E402

    for _keywords, _category, hint in dw._ERROR_RULES:
        keys.add(hint)
    return keys


def check() -> list[str]:
    problems: list[str] = []
    keys = used_keys()
    lang_files = sorted((ROOT / "i18n").glob("*.json"))
    if not lang_files:
        return ["Keine Sprachdateien unter i18n/*.json gefunden."]

    reference = json.loads((ROOT / "i18n" / "en.json").read_text(encoding="utf-8"))
    ref_keys = set(reference)

    missing_in_ref = keys - ref_keys
    for k in sorted(missing_in_ref):
        problems.append(f"en.json: fehlender Schluessel: {k[:80]!r}")

    # Waisen-Pruefung auf Quelltext-Ebene: viele Schluessel erreichen tr()
    # dynamisch (Options-Werte via format_func=_, Platzhaltertexte in
    # Variablen, Backend-Meldungen) und sind im AST unsichtbar.
    all_sources = " ".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("app_streamlit.py", "docling_worker.py",
                     "job_manager.py", "vault_index.py", "vault_builder.py")
    )
    for k in sorted(ref_keys - keys):
        if k not in all_sources:
            problems.append(f"en.json: verwaister Schluessel: {k[:80]!r}")

    for path in lang_files:
        table = json.loads(path.read_text(encoding="utf-8"))
        if path.name != "en.json":
            missing = ref_keys - set(table)
            extra = set(table) - ref_keys
            for k in sorted(missing):
                problems.append(f"{path.name}: fehlt: {k[:80]!r}")
            for k in sorted(extra):
                problems.append(f"{path.name}: ueberzaehlig: {k[:80]!r}")
        for key, value in table.items():
            if not isinstance(value, str) or not value.strip():
                problems.append(f"{path.name}: leere Uebersetzung: {key[:80]!r}")
                continue
            if set(_PLACEHOLDER.findall(key)) != set(_PLACEHOLDER.findall(value)):
                problems.append(
                    f"{path.name}: Platzhalter weichen ab: {key[:80]!r}"
                )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print(f"{len(problems)} Problem(e):")
        for p in problems:
            print(f"  - {p}")
        return 1
    langs = sorted(p.stem for p in (ROOT / "i18n").glob("*.json"))
    print(f"i18n konsistent: {len(used_keys())} Schluessel, "
          f"Sprachen: {', '.join(langs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
