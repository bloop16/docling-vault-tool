"""Tests fuer die Uebersetzungsschicht (Deutsch/Englisch)."""

from __future__ import annotations

import i18n


def test_default_language_is_passthrough():
    i18n.set_language("de")
    assert i18n.tr("Dateien scannen") == "Dateien scannen"
    assert i18n.tr("{n} unterstützte Datei(en) gefunden.", n=3) == (
        "3 unterstützte Datei(en) gefunden."
    )


def test_english_lookup_and_fallback():
    i18n.set_language("en")
    try:
        assert i18n.tr("Dateien scannen") == "Scan files"
        assert i18n.tr("{n} unterstützte Datei(en) gefunden.", n=3) == (
            "3 supported file(s) found."
        )
        # Unbekannte Texte fallen unveraendert (deutsch) zurueck -- niemals
        # ein KeyError, niemals eine Luecke in der Oberflaeche.
        assert i18n.tr("Nur intern bekannter Text") == "Nur intern bekannter Text"
    finally:
        i18n.set_language("de")


def test_invalid_language_is_ignored():
    i18n.set_language("fr")            # nicht vorhanden -> bleibt wie es war
    assert i18n.get_language() == "de"
    assert set(i18n.LANGUAGES) == {"de", "en"}


def test_error_hints_have_translations():
    """Die statischen Fehlerhinweise der Konvertierung sind uebersetzt."""
    import docling_worker as dw

    i18n.set_language("en")
    try:
        translated = 0
        for _keywords, _category, hint in dw._ERROR_RULES:
            if i18n.tr(hint) != hint:
                translated += 1
        # Mindestens die haeufigen Klassiker muessen uebersetzt sein.
        assert translated >= 5
    finally:
        i18n.set_language("de")
