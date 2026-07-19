"""Mehrsprachigkeit fuer die Oberflaeche (ioBroker-Stil: JSON je Sprache).

Design: Die deutschen Originaltexte sind die Schluessel -- ``tr("Text")``
liefert bei Sprache "de" den Text unveraendert und schlaegt sonst in
``i18n/<sprache>.json`` nach (Fallback: Deutsch, damit fehlende
Uebersetzungen nie zu Luecken fuehren). Platzhalter laufen ueber
``str.format``::

    tr("{n} Datei(en) gefunden.", n=5)

Die Sprache waehlt das Dashboard (Seitenleiste); Vorbelegung ueber die
Umgebungsvariable ``DOC2VAULT_LANG`` (z. B. ``en``, ``fr``, ``zh-cn``).
Neue Sprache hinzufuegen = eine JSON-Datei mit denselben Schluesseln wie
``en.json`` ablegen und in ``LANGUAGES`` eintragen; das Pruefskript
``scripts/check_i18n.py`` (laeuft auch als Test) haelt alle Dateien
konsistent. CLI-Ausgaben bleiben in dieser Ausbaustufe Deutsch; die
Fehlerhinweise der Konvertierung werden bei der Anzeige im Dashboard
mituebersetzt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_DIR = Path(__file__).resolve().parent

# Anzeigename je Sprachcode; Deutsch ist Quell- und Fallback-Sprache.
LANGUAGES = {
    "de": "Deutsch",
    "en": "English",
    "fr": "Français",
    "es": "Español",
    "it": "Italiano",
    "nl": "Nederlands",
    "pl": "Polski",
    "pt": "Português",
    "ru": "Русский",
    "uk": "Українська",
    "zh-cn": "简体中文",
}

_current = os.environ.get("DOC2VAULT_LANG", "de").lower()
if _current not in LANGUAGES:
    _current = "de"

_cache: dict[str, dict[str, str]] = {}


def _table(lang: str) -> dict[str, str]:
    """Laedt die Sprachdatei einmalig (fehlend/kaputt -> leer = Fallback)."""
    if lang not in _cache:
        try:
            _cache[lang] = json.loads(
                (_DIR / f"{lang}.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            _cache[lang] = {}
    return _cache[lang]


def set_language(lang: str) -> None:
    global _current
    if lang in LANGUAGES:
        _current = lang


def get_language() -> str:
    return _current


def tr(text: str, **kwargs) -> str:
    """Uebersetzt ``text`` in die aktive Sprache (Fallback: Original)."""
    if _current != "de":
        text = _table(_current).get(text, text)
    return text.format(**kwargs) if kwargs else text
