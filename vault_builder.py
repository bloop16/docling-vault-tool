"""Post-Processing: macht aus rohem Docling-Output einen Obsidian-Vault.

Docling liefert ``.md``-Dateien plus Bilder -- fuer einen funktionierenden
Obsidian-Vault fehlen danach noch:

1. **Frontmatter** im normierten Schema (``title``, ``source_path``,
   ``converted_at``, ``tags``) -- geschrieben mit ``python-frontmatter``.
2. **Attachment-Handling**: Bilder wandern nach
   ``Attachments/<notiz-slug>/``, Referenzen werden zu Obsidian-Einbettungen
   ``![[dateiname.png]]`` umgeschrieben; Bildnamen sind vault-weit eindeutig
   (Hash-Suffix bei Duplikaten, Dedup bei inhaltsgleichen Dateien).
3. **Kollisionsschutz** bei Notiznamen: Slug aus dem Quelldateinamen, bei
   Konflikt Suffix mit Kurz-Hash -- niemals ueberschreiben.
4. **Inbox-Ablage**: alle Notizen landen in ``Inbox/``. Linking/Filing ist
   bewusst NICHT Teil dieses Schritts -- das uebernimmt der nachgelagerte
   Vault-Curator-Agent.

Nutzung::

    # integriert (nach der Konvertierung):
    doc2vault -i <quelle> -o <vault> --build-vault

    # standalone auf einen bestehenden Docling-Output-Ordner:
    doc2vault-build --input <docling-output> --vault <zielvault>

Der Builder ist idempotent: liegt der Output-Ordner im Ziel-Vault (oder ist
identisch mit ihm), werden ``Inbox/`` und ``Attachments/`` beim Scan
ausgenommen -- ein zweiter Lauf aendert nichts.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter

# Bild-Endungen, die als Attachment behandelt werden.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tiff"}

# Markdown-Bildreferenz: ![alt](ziel) -- Ziel ohne schliessende Klammer.
_IMAGE_REF = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# In Obsidian-Dateinamen/Wikilinks problematische Zeichen.
_FORBIDDEN = re.compile(r"[\[\]#^|\\/:*?\"<>]")


def slugify(name: str, max_length: int = 120) -> str:
    """Lesbarer, Obsidian-sicherer Notizname aus einem Quelldateinamen.

    Umlaute bleiben erhalten (Lesbarkeit im Vault); nur fuer Wikilinks/
    Dateisysteme problematische Zeichen werden ersetzt, Whitespace kollabiert.
    """
    slug = _FORBIDDEN.sub("-", name)
    slug = re.sub(r"\s+", " ", slug).strip(" .-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:max_length].strip(" .-") or "notiz"


def short_hash(path: os.PathLike | str, length: int = 8) -> str:
    """Erste ``length`` Hex-Zeichen des SHA-256 ueber den Dateiinhalt."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:length]


@dataclass
class BuildResult:
    """Ergebnis fuer eine einzelne Notiz."""

    note_path: str                 # Zielpfad in Inbox/
    original_md: str               # urspruengliche .md im Output-Ordner
    images_moved: int = 0
    note_renamed: bool = False     # Hash-Suffix wegen Namenskonflikt
    images_renamed: int = 0        # Hash-Suffix wegen Bildnamen-Konflikt


@dataclass
class BuildSummary:
    """Zusammenfassung eines Build-Laufs."""

    notes: int = 0
    images: int = 0
    note_collisions: int = 0
    image_collisions: int = 0
    results: list[BuildResult] = field(default_factory=list)


class _AttachmentStore:
    """Verwaltet vault-weit eindeutige Bildnamen im Attachments-Baum."""

    def __init__(self, attachments_root: Path) -> None:
        self.root = attachments_root
        # Vorhandene Namen einsammeln (Obsidian loest Wikilinks ueber den
        # Dateinamen auf -- der muss deshalb im ganzen Baum eindeutig sein).
        self._by_name: dict[str, Path] = {}
        if attachments_root.is_dir():
            for p in attachments_root.rglob("*"):
                if p.is_file():
                    self._by_name.setdefault(p.name, p)

    def add(self, image: Path, note_slug: str) -> tuple[str, bool]:
        """Verschiebt ``image`` nach ``<root>/<note_slug>/`` und liefert
        ``(finaler Dateiname, umbenannt?)``.

        Bei Namenskonflikt: inhaltsgleiche Datei -> vorhandenen Namen
        wiederverwenden (Dedup, Quelle wird geloescht); sonst Hash-Suffix.
        """
        dest_dir = self.root / note_slug
        name = image.name
        renamed = False
        existing = self._by_name.get(name)
        if existing is not None and existing.exists():
            if short_hash(existing) == short_hash(image):
                image.unlink()          # identischer Inhalt -> deduplizieren
                return existing.name, False
            name = f"{image.stem}-{short_hash(image)}{image.suffix}"
            renamed = True
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / name
        shutil.move(str(image), str(target))
        self._by_name[name] = target
        return name, renamed


def _resolve_image(md_path: Path, raw_target: str) -> Optional[Path]:
    """Loest ein Markdown-Bildziel relativ zur Notiz auf (None = nicht lokal)."""
    if raw_target.startswith(("http://", "https://", "data:")):
        return None
    target = urllib.parse.unquote(raw_target)
    path = Path(target)
    if not path.is_absolute():
        path = (md_path.parent / path).resolve()
    if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
        return None
    return path


def _unique_note_path(
    inbox: Path, slug: str, source_for_hash: Path, taken: set[str]
) -> tuple[Path, bool]:
    """Kollisionsfreier Notizpfad in der Inbox (niemals ueberschreiben)."""
    candidate = inbox / f"{slug}.md"
    if candidate.name not in taken and not candidate.exists():
        return candidate, False
    suffixed = inbox / f"{slug}-{short_hash(source_for_hash)}.md"
    n = 2
    while suffixed.name in taken or suffixed.exists():
        suffixed = inbox / f"{slug}-{short_hash(source_for_hash)}-{n}.md"
        n += 1
    return suffixed, True


def build_note(
    md_path: Path,
    inbox: Path,
    store: _AttachmentStore,
    taken_names: set[str],
) -> BuildResult:
    """Verarbeitet eine einzelne Notiz: Frontmatter, Bilder, Inbox-Ablage."""
    post = frontmatter.load(md_path)

    # --- Frontmatter-Schema (bestehende Zusatzfelder bleiben erhalten) -----
    source_path = str(post.get("original_path") or post.get("source_path") or "")
    title_base = Path(source_path).stem if source_path else md_path.stem
    post["title"] = post.get("title") or title_base
    post["source_path"] = source_path
    post["converted_at"] = str(
        post.get("converted_at")
        or datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    tags = post.get("tags")
    post["tags"] = tags if isinstance(tags, list) else ([tags] if tags else [])
    # assets_folder zeigt nach dem Verschieben ins Leere -> entfernen.
    post.metadata.pop("assets_folder", None)

    # --- Notizname mit Kollisionsschutz ------------------------------------
    slug = slugify(title_base)
    hash_source = Path(source_path) if source_path and Path(source_path).is_file() else md_path
    note_path, note_renamed = _unique_note_path(inbox, slug, hash_source, taken_names)
    note_slug = note_path.stem

    # --- Bilder verschieben + Referenzen auf Wikilinks umschreiben ---------
    moved = 0
    renamed_images = 0
    asset_dirs: set[Path] = set()

    def _rewrite(match: re.Match) -> str:
        nonlocal moved, renamed_images
        image = _resolve_image(md_path, match.group(2))
        if image is None:
            return match.group(0)       # Web-URL/fehlende Datei: unangetastet
        asset_dirs.add(image.parent)
        final_name, was_renamed = store.add(image, note_slug)
        moved += 1
        if was_renamed:
            renamed_images += 1
        return f"![[{final_name}]]"

    post.content = _IMAGE_REF.sub(_rewrite, post.content)

    # --- Ablegen ------------------------------------------------------------
    inbox.mkdir(parents=True, exist_ok=True)
    note_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    taken_names.add(note_path.name)
    md_path.unlink()

    # Leergewordene Asset-Ordner aufraeumen.
    for d in asset_dirs:
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass

    return BuildResult(
        note_path=str(note_path),
        original_md=str(md_path),
        images_moved=moved,
        note_renamed=note_renamed,
        images_renamed=renamed_images,
    )


def build_vault(
    output_dir: os.PathLike | str,
    vault_dir: os.PathLike | str,
    inbox_subdir: str = "Inbox",
    attachments_subdir: str = "Attachments",
) -> BuildSummary:
    """Verarbeitet alle ``.md`` unterhalb von ``output_dir`` in den Vault.

    ``Inbox/`` und ``Attachments/`` des Ziel-Vaults werden beim Scan
    ausgenommen -- der Builder ist damit idempotent, auch wenn Output- und
    Vault-Ordner identisch sind.
    """
    out_root = Path(output_dir)
    vault = Path(vault_dir)
    inbox = vault / inbox_subdir
    attachments = vault / attachments_subdir

    import docling_worker as dw

    md_files = dw.discover_files(
        out_root, extensions={".md"}, exclude_dirs=(inbox, attachments)
    )

    store = _AttachmentStore(attachments)
    taken: set[str] = set()
    summary = BuildSummary()
    for md_path in md_files:
        result = build_note(md_path, inbox, store, taken)
        summary.notes += 1
        summary.images += result.images_moved
        summary.note_collisions += int(result.note_renamed)
        summary.image_collisions += result.images_renamed
        summary.results.append(result)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Post-Processing: rohen Docling-Output in einen "
        "Obsidian-Vault ueberfuehren (Inbox, Attachments, Wikilinks, "
        "Frontmatter)."
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Docling-Output-Ordner (.md + Bilder)")
    parser.add_argument("--vault", "-o", required=True,
                        help="Ziel-Vault (Inbox/ und Attachments/ entstehen hier)")
    parser.add_argument("--inbox", default="Inbox",
                        help="Name des Inbox-Unterordners (Default: Inbox)")
    parser.add_argument("--attachments", default="Attachments",
                        help="Name des Attachment-Unterordners (Default: Attachments)")
    args = parser.parse_args(argv)

    out_root = Path(args.input).resolve()
    if not out_root.is_dir():
        parser.error(f"Output-Ordner existiert nicht: {out_root}")

    vault = Path(args.vault).resolve()
    summary = build_vault(out_root, vault,
                          inbox_subdir=args.inbox,
                          attachments_subdir=args.attachments)
    print(f"Vault-Build abgeschlossen: {summary.notes} Notiz(en) nach "
          f"{args.inbox}/, {summary.images} Bild(er) nach {args.attachments}/.")
    if summary.note_collisions or summary.image_collisions:
        print(f"  Kollisionen aufgeloest: {summary.note_collisions} Notiz(en), "
              f"{summary.image_collisions} Bild(er) (Hash-Suffix).")
    if summary.notes == 0:
        print("  Hinweis: keine .md-Dateien gefunden (bereits gebaut?).")

    # Such-Index nach jedem Build automatisch mitpflegen.
    import vault_index

    idx = vault_index.update_index(vault)
    vault_index.write_index_md(vault)
    print(f"Such-Index: {idx.indexed} neu/geändert, {idx.total} Notizen "
          f"insgesamt (INDEX.md aktualisiert).")
    return 0


def main() -> int:
    """Einstiegspunkt fuer den ``doc2vault-build``-Konsolenbefehl."""
    return _run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
