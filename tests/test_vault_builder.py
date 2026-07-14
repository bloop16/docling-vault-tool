"""Tests fuer vault_builder: Frontmatter, Wikilinks, Kollisionen, Idempotenz."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

import vault_builder as vb

PNG_A = b"\x89PNG\r\n\x1a\nAAAA"
PNG_B = b"\x89PNG\r\n\x1a\nBBBB"


def _raw_note(
    md_path: Path,
    image: Path | None = None,
    with_frontmatter: bool = False,
    source: str = "",
    image_ref: str | None = None,
) -> Path:
    """Synthetischer Docling-Output: eine Notiz, optional mit Bildreferenz."""
    body = "# Titel\n\nEin Absatz.\n"
    if image is not None:
        ref = image_ref if image_ref is not None else Path(
            "..", image.parent.name, image.name
        ).as_posix() if image.parent != md_path.parent else image.name
        body += f"\n![Abb]({ref})\n"
    if with_frontmatter:
        body = (
            "---\n"
            f'source: "{Path(source).name}"\n'
            f'original_path: "{source}"\n'
            'assets_folder: "assets/x"\n'
            'converted_at: "2026-01-01T00:00:00+00:00"\n'
            "extra_feld: 42\n"
            "---\n" + body
        )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(body, encoding="utf-8")
    return md_path


def test_slugify():
    assert vb.slugify("Bericht Q1/2024: Umsatz [final]") == "Bericht Q1-2024- Umsatz -final"
    assert vb.slugify("Übersicht  März") == "Übersicht März"   # Umlaute bleiben
    assert vb.slugify("###") == "notiz"
    assert len(vb.slugify("x" * 500)) <= 120


def test_frontmatter_schema_and_preservation(tmp_path):
    out = tmp_path / "out"
    md = _raw_note(out / "bericht.md", with_frontmatter=True,
                   source="/quelle/Bericht 2024.pdf")
    vault = tmp_path / "vault"
    summary = vb.build_vault(out, vault)
    assert summary.notes == 1

    note = vault / "Inbox" / "Bericht 2024.md"
    assert note.exists()
    post = frontmatter.load(note)
    assert post["title"] == "Bericht 2024"
    assert post["source_path"] == "/quelle/Bericht 2024.pdf"
    assert post["converted_at"] == "2026-01-01T00:00:00+00:00"   # uebernommen
    assert post["tags"] == []
    assert post["extra_feld"] == 42                # Zusatzfelder bleiben
    assert "assets_folder" not in post.metadata    # veraltet -> entfernt
    assert not md.exists()                          # Original verschoben


def test_frontmatter_added_when_missing(tmp_path):
    out = tmp_path / "out"
    _raw_note(out / "roh.md", with_frontmatter=False)
    vault = tmp_path / "vault"
    vb.build_vault(out, vault)
    post = frontmatter.load(vault / "Inbox" / "roh.md")
    assert post["title"] == "roh"
    assert post["source_path"] == ""
    assert post["converted_at"]                    # ISO-Zeitstempel gesetzt
    assert post["tags"] == []


def test_wikilink_rewrite_and_attachment_move(tmp_path):
    out = tmp_path / "out"
    assets = out / "assets" / "doc"
    assets.mkdir(parents=True)
    img = assets / "bild 1.png"
    img.write_bytes(PNG_A)
    # URL-encodierter relativer Link + eine Web-URL, die bleiben muss.
    md = out / "doc.md"
    md.write_text(
        "# T\n\n![Abb](assets/doc/bild%201.png)\n\n"
        "![extern](https://example.org/logo.png)\n",
        encoding="utf-8",
    )
    vault = tmp_path / "vault"
    summary = vb.build_vault(out, vault)
    assert summary.images == 1

    body = frontmatter.load(vault / "Inbox" / "doc.md").content
    assert "![[bild 1.png]]" in body
    assert "https://example.org/logo.png" in body   # Web-URL unangetastet
    assert (vault / "Attachments" / "doc" / "bild 1.png").exists()
    assert not img.exists()
    assert not assets.exists()                      # leerer Asset-Ordner weg


def test_image_name_collision_and_dedup(tmp_path):
    out = tmp_path / "out"
    for stem, payload in (("eins", PNG_A), ("zwei", PNG_B), ("drei", PNG_A)):
        d = out / stem
        d.mkdir(parents=True)
        (d / "img.png").write_bytes(payload)
        (d / f"{stem}.md").write_text(f"![x](img.png)\n", encoding="utf-8")

    vault = tmp_path / "vault"
    summary = vb.build_vault(out, vault)
    assert summary.notes == 3

    names = sorted(p.name for p in (vault / "Attachments").rglob("*.png"))
    # eins: img.png; zwei: anderer Inhalt -> Hash-Suffix; drei: inhaltsgleich
    # zu eins -> dedupliziert (kein drittes Bild).
    assert len(names) == 2
    assert "img.png" in names
    assert any(n.startswith("img-") for n in names)
    assert summary.image_collisions == 1

    drei_body = frontmatter.load(vault / "Inbox" / "drei.md").content
    assert "![[img.png]]" in drei_body              # wiederverwendeter Name


def test_note_name_collision_uses_hash_suffix(tmp_path):
    out = tmp_path / "out"
    _raw_note(out / "a" / "Bericht.md", with_frontmatter=False)
    _raw_note(out / "b" / "Bericht.md", with_frontmatter=False)
    vault = tmp_path / "vault"
    summary = vb.build_vault(out, vault)
    assert summary.notes == 2
    assert summary.note_collisions == 1

    notes = sorted(p.name for p in (vault / "Inbox").glob("*.md"))
    assert "Bericht.md" in notes
    assert any(n.startswith("Bericht-") and n != "Bericht.md" for n in notes)
    # Nichts wurde ueberschrieben: beide Inhalte vorhanden.
    assert len(notes) == 2


def test_idempotent_when_output_equals_vault(tmp_path):
    vault = tmp_path / "vault"
    _raw_note(vault / "doc.md", with_frontmatter=False)
    s1 = vb.build_vault(vault, vault)
    assert s1.notes == 1
    s2 = vb.build_vault(vault, vault)               # zweiter Lauf: No-op
    assert s2.notes == 0
    assert (vault / "Inbox" / "doc.md").exists()


def test_cli_smoke(tmp_path, capsys):
    out = tmp_path / "out"
    _raw_note(out / "n.md", with_frontmatter=False)
    rc = vb._run_cli(["--input", str(out), "--vault", str(tmp_path / "v")])
    assert rc == 0
    assert "1 Notiz(en)" in capsys.readouterr().out
    assert (tmp_path / "v" / "Inbox" / "n.md").exists()
