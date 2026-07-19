"""Datei-Transfer fuer den Headless-Betrieb: Upload-Ablage und ZIP-Verpackung.

Beim Betrieb auf einem Server (Docker/pip, Zugriff via Browser) muessen kleine
Datenmengen ohne gemountete Shares hin- und zurueckkommen. Dieses Modul buendelt
die dafuer noetige, von Streamlit unabhaengige Kernlogik:

* ``safe_extract_zip``  -- ZIP entpacken mit Zip-Slip-Schutz
* ``store_uploads``     -- hochgeladene Dateien ablegen (ZIPs werden entpackt)
* ``zip_folder``        -- Ordner rekursiv als ZIP verpacken (fuer den Download)
* ``folder_size``       -- Groessenschaetzung (Warnung vor sehr grossen Downloads)

Fuer grosse Datenmengen (z. B. den 15-GB-Bestand) sind gemountete Ordner/Shares
der richtige Weg -- siehe README, Abschnitt "Headless-Server & Docker".
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import BinaryIO


class UnsafeZipError(ValueError):
    """ZIP-Eintrag wuerde ausserhalb des Zielordners landen (Zip-Slip),
    oder das Archiv ueberschreitet die Entpack-Limits (Zip-Bomb)."""


# Entpack-Limits: schuetzen den (Headless-)Server vor Zip-Bombs, die mit
# wenigen KB Upload die Platte fuellen. Grosszuegig bemessen -- reale
# Dokument-Archive bleiben weit darunter.
MAX_ZIP_ENTRIES = 50_000
MAX_ZIP_TOTAL_BYTES = 20 * 1024**3        # 20 GB unkomprimiert
MAX_ZIP_RATIO = 300                        # Kompressionsrate je Eintrag


def _member_target(dest: Path, member_name: str) -> Path:
    """Zielpfad eines ZIP-Eintrags, validiert gegen Zip-Slip.

    Lehnt absolute Pfade, Laufwerksangaben und ``..``-Ausbrueche ab, indem der
    aufgeloeste Zielpfad innerhalb von ``dest`` liegen muss.
    """
    # Windows-Separatoren normalisieren; fuehrende Slashes entfernen.
    name = member_name.replace("\\", "/").lstrip("/")
    target = (dest / name).resolve()
    dest_resolved = dest.resolve()
    if target != dest_resolved and dest_resolved not in target.parents:
        raise UnsafeZipError(
            f"ZIP-Eintrag zeigt aus dem Zielordner heraus: {member_name!r}"
        )
    return target


def safe_extract_zip(
    zip_source: os.PathLike | str | BinaryIO,
    dest_dir: os.PathLike | str,
) -> list[Path]:
    """Entpackt ein ZIP nach ``dest_dir`` und gibt die Dateipfade zurueck.

    Jeder Eintrag wird gegen Zip-Slip geprueft (``UnsafeZipError`` bei
    Ausbruchsversuchen); Verzeichniseintraege werden angelegt, aber nicht
    zurueckgegeben.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_source) as zf:
        # Erst ALLE Eintraege validieren, dann schreiben -- so bleibt bei einem
        # boesartigen Archiv gar nichts zurueck. Neben Zip-Slip werden auch
        # Zip-Bombs abgefangen (Anzahl, Gesamtgroesse, Kompressionsrate).
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise UnsafeZipError(
                f"ZIP enthält {len(infos)} Einträge (Limit {MAX_ZIP_ENTRIES})."
            )
        total = sum(i.file_size for i in infos)
        if total > MAX_ZIP_TOTAL_BYTES:
            raise UnsafeZipError(
                f"ZIP würde {format_size(total)} entpacken "
                f"(Limit {format_size(MAX_ZIP_TOTAL_BYTES)})."
            )
        targets: list[tuple[zipfile.ZipInfo, Path]] = []
        for info in infos:
            if (info.compress_size > 0
                    and info.file_size / info.compress_size > MAX_ZIP_RATIO
                    and info.file_size > 10 * 1024 * 1024):
                raise UnsafeZipError(
                    f"ZIP-Eintrag mit verdächtiger Kompressionsrate "
                    f"(mögliche Zip-Bomb): {info.filename!r}"
                )
            targets.append((info, _member_target(dest, info.filename)))
        for info, target in targets:
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)
            extracted.append(target)
    return extracted


def store_uploads(
    files: list[tuple[str, BinaryIO]],
    dest_dir: os.PathLike | str,
) -> list[Path]:
    """Legt hochgeladene Dateien unter ``dest_dir`` ab.

    ``files`` ist eine Liste aus (Dateiname, Dateiobjekt) -- passend zu
    Streamlits ``UploadedFile`` (hat ``.name`` und ist file-like). ZIP-Archive
    werden entpackt (mit Zip-Slip-Schutz), alle anderen Dateien unveraendert
    gespeichert. Gibt die abgelegten Dateipfade zurueck.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    stored: list[Path] = []
    for name, fh in files:
        safe_name = Path(name.replace("\\", "/")).name  # nur Basisname
        if safe_name.lower().endswith(".zip"):
            stored.extend(safe_extract_zip(fh, dest))
            continue
        target = dest / safe_name
        # Namenskollision (z. B. 2024/rechnung.pdf + 2025/rechnung.pdf aus
        # einem Ordner-Upload): niemals still ueberschreiben.
        n = 2
        while target.exists():
            target = dest / f"{Path(safe_name).stem}-{n}{Path(safe_name).suffix}"
            n += 1
        with open(target, "wb") as out:
            while chunk := fh.read(1 << 20):
                out.write(chunk)
        stored.append(target)
    return stored


def zip_folder(
    folder: os.PathLike | str,
    out_path: os.PathLike | str,
) -> Path:
    """Packt ``folder`` rekursiv als ZIP nach ``out_path`` (deflate).

    Versteckte Verzeichnisse (``.obsidian`` u. ae. bleiben bewusst AUSSEN vor,
    damit der Download nur Inhalte enthaelt) sowie versteckte Dateien werden
    uebersprungen. Die Pfade im Archiv sind relativ zu ``folder``.
    """
    root = Path(folder)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                path = Path(dirpath) / filename
                zf.write(path, path.relative_to(root).as_posix())
    return out


def folder_size(folder: os.PathLike | str) -> int:
    """Gesamtgroesse aller Dateien unterhalb von ``folder`` in Bytes.

    Versteckte Verzeichnisse werden wie in ``zip_folder`` uebersprungen, damit
    die Schaetzung zum spaeteren Archiv passt.
    """
    total = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if filename.startswith("."):
                continue
            try:
                total += (Path(dirpath) / filename).stat().st_size
            except OSError:
                continue
    return total


def format_size(num_bytes: int) -> str:
    """Menschlich lesbare Groesse (Basis 1024)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"
