"""Sichere, inkrementelle Konvertierungs-Jobs fuer Ordner und Ordner-Aenderungen.

Ein *Job* verknuepft einen Quellordner mit einem Zielordner (Vault) plus dem
bestaetigten Integrationsplan. Jobs koennen einmalig ("run") oder als
Ordnerueberwachung ("watch", Polling) laufen. Ein *Manifest* je Job merkt sich,
welche Dateien bereits konvertiert wurden (Groesse, mtime, Hash) -- so werden
bei jedem Lauf nur **neue oder geaenderte** Dateien verarbeitet.

Sicherheitsmerkmale ("sichere Jobs"):

* **Inkrementell & idempotent** -- unveraenderte Dateien werden uebersprungen.
* **Wiederaufsetzbar** -- bricht ein Lauf ab, gelten noch nicht im Manifest
  eingetragene Dateien beim naechsten Lauf wieder als offen.
* **Sperre** -- ein Lockfile verhindert parallele Laeufe desselben Jobs.
* **Nicht-destruktiv** -- geloeschte Quelldateien werden nur gemeldet, nie
  werden Zieldateien automatisch entfernt.
* **Dry-Run** -- Aenderungen lassen sich vorab anzeigen (``plan``), bevor
  irgendetwas geschrieben wird.

Konfiguration/Status liegen pro Nutzer unter einem Konfigverzeichnis
(``DOC2VAULT_HOME`` oder OS-Standard), sodass das Tool nutzerunabhaengig ist.

CLI::

    python job_manager.py add   --name "Berichte" --source SRC --target VAULT
    python job_manager.py list
    python job_manager.py plan  <job>          # Dry-Run: was wuerde passieren?
    python job_manager.py run   <job>          # inkrementell konvertieren
    python job_manager.py watch <job> [-n 30]  # Ordner ueberwachen (Polling)
    python job_manager.py rm    <job>
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import docling_worker as dw

# Bibliotheks-Logging (Dashboard/Dienste); CLI-Nutzerausgabe bleibt print.
_LOG = logging.getLogger("doc2vault.jobs")

# Felder von ConverterConfig, die pro Job gespeichert/rekonstruiert werden.
_CONFIG_FIELDS = (
    "do_ocr", "ocr_engine", "ocr_languages", "generate_picture_images", "images_scale", "do_table_structure",
    "on_success", "archive_dir", "notes_subdir", "mirror_structure",
    "attachments_mode", "attachments_subdir", "add_frontmatter",
    "xlsx_sheet_limit", "xlsx_on_limit",
)


# ---------------------------------------------------------------------------
# Speicherorte (nutzerspezifisch)
# ---------------------------------------------------------------------------

def config_dir() -> Path:
    """Konfig-/Statusverzeichnis (``DOC2VAULT_HOME`` oder OS-Standard).

    Bestehende Daten der frueheren Installation ("docling-vault-tool",
    inkl. der alten Variable ``DOCLING_VAULT_HOME``) werden beim ersten
    Zugriff automatisch uebernommen -- Jobs, Manifeste und Verlaeufe gehen
    durch die Umbenennung nicht verloren.
    """
    env = os.environ.get("DOC2VAULT_HOME") or os.environ.get("DOCLING_VAULT_HOME")
    if env:
        base = Path(env)
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home())) / "doc2vault"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "doc2vault"
    else:
        base = Path(
            os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        ) / "doc2vault"

    if not base.exists():
        legacy = base.parent / "docling-vault-tool"
        if legacy.is_dir():
            try:
                legacy.rename(base)
            except OSError:
                pass  # z. B. anderes Dateisystem -- dann frisch starten

    base.mkdir(parents=True, exist_ok=True)
    (base / "manifests").mkdir(exist_ok=True)
    return base


def _jobs_file() -> Path:
    return config_dir() / "jobs.json"


def _manifest_file(job_id: str) -> Path:
    return config_dir() / "manifests" / f"{job_id}.json"


def _lock_file(job_id: str) -> Path:
    return config_dir() / "manifests" / f"{job_id}.lock"


def _history_file(job_id: str) -> Path:
    return config_dir() / "manifests" / f"{job_id}.history.json"


# ---------------------------------------------------------------------------
# Datentypen
# ---------------------------------------------------------------------------

@dataclass
class Job:
    """Definition eines Konvertierungs-Jobs (serialisierbar)."""

    id: str
    name: str
    source: str
    target: str
    config: dict = field(default_factory=dict)
    poll_interval: int = 30          # Sekunden, fuer watch
    max_workers: int | None = None
    created_at: str = ""
    last_run_at: str | None = None
    # Nach jedem Lauf mit Neukonvertierungen zusaetzlich Vault-Build
    # (Inbox/, Attachments/, Wikilinks) + Such-Index ausfuehren.
    build_vault: bool = False
    # Neue Dateien, deren Inhalt bereits konvertiert wurde (oder die
    # untereinander inhaltsgleich sind), ueberspringen statt konvertieren.
    skip_duplicates: bool = False

    def converter_config(self) -> dw.ConverterConfig:
        """Rekonstruiert die ``ConverterConfig`` aus dem gespeicherten Plan."""
        known = {k: v for k, v in self.config.items() if k in _CONFIG_FIELDS}
        return dw.ConverterConfig(**known)


@dataclass
class ChangeSet:
    """Ergebnis des Abgleichs Quelle <-> Manifest."""

    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)   # im Manifest, nicht mehr da
    retry: list[str] = field(default_factory=list)     # zuvor fehlgeschlagen
    # Inhaltsgleich mit bereits Konvertiertem bzw. anderer neuer Datei
    # (nur befuellt, wenn job.skip_duplicates aktiv ist).
    duplicates: list[str] = field(default_factory=list)

    @property
    def todo(self) -> list[str]:
        """Dateien, die tatsaechlich (neu) konvertiert werden."""
        return self.new + self.changed + self.retry

    def counts(self) -> dict[str, int]:
        result = {
            "neu": len(self.new),
            "geaendert": len(self.changed),
            "unveraendert": len(self.unchanged),
            "entfernt": len(self.removed),
            "wiederholung": len(self.retry),
        }
        if self.duplicates:
            result["duplikate"] = len(self.duplicates)
        return result


@dataclass
class JobRunSummary:
    """Zusammenfassung eines Job-Laufs."""

    job_id: str
    started_at: str
    duration_s: float
    changes: dict[str, int]
    converted_ok: int
    converted_failed: int
    # Davon mit reduzierten Einstellungen konvertiert (riesige PDF-Seiten).
    converted_reduced: int = 0
    failures: list = field(default_factory=list)
    dry_run: bool = False
    skipped_locked: bool = False
    # Ergebnis des optionalen Vault-Build-/Index-Schritts (job.build_vault):
    build_notes: int | None = None
    build_images: int | None = None
    index_total: int | None = None
    build_error: str | None = None


# ---------------------------------------------------------------------------
# Job-Store (jobs.json)
# ---------------------------------------------------------------------------

def load_jobs() -> list[Job]:
    path = _jobs_file()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Korrupte Datei NICHT still als "keine Jobs" werten: das naechste
        # save_jobs wuerde sonst alle Jobdefinitionen endgueltig verwerfen.
        # Stattdessen sichern, damit der Nutzer sie wiederherstellen kann.
        try:
            path.replace(path.with_suffix(".json.corrupt"))
        except OSError:
            pass
        return []
    return [Job(**j) for j in data]


def save_jobs(jobs: list[Job]) -> None:
    # Atomar (tmp -> replace): ein mitten im Schreiben gekillter Prozess
    # (watch-Dienst gestoppt, Stromausfall) darf jobs.json nicht abschneiden.
    path = _jobs_file()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps([asdict(j) for j in jobs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


@contextmanager
def _jobs_write_lock(timeout: float = 10.0):
    """Serialisiert Read-Modify-Write auf ``jobs.json``.

    Ohne Sperre kann ein watch-Prozess (schreibt ``last_run_at`` nach jedem
    Zyklus) eine parallel im Dashboard gemachte Aenderung (z. B. OCR-Engine-
    Wechsel) mit seinem aelteren Snapshot still ueberschreiben. Nach
    ``timeout`` wird notfalls ohne Sperre fortgefahren, damit ein verwaistes
    Lock niemals alle Job-Operationen blockiert.
    """
    lock = config_dir() / "jobs.json.lock"
    deadline = time.monotonic() + timeout
    acquired = False
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 60:
                    lock.unlink(missing_ok=True)   # verwaiste Sperre
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                break
            time.sleep(0.05)
    try:
        yield
    finally:
        if acquired:
            lock.unlink(missing_ok=True)


def get_job(job_ref: str) -> Job | None:
    """Findet einen Job per ID oder (eindeutigem) Namen."""
    jobs = load_jobs()
    for j in jobs:
        if j.id == job_ref:
            return j
    matches = [j for j in jobs if j.name == job_ref]
    return matches[0] if len(matches) == 1 else None


def _slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in name.strip()]
    slug = "".join(keep).strip("-") or "job"
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:40]


def add_job(
    name: str,
    source: str,
    target: str,
    config: dw.ConverterConfig | None = None,
    poll_interval: int = 30,
    max_workers: int | None = None,
    build_vault: bool = False,
) -> Job:
    """Legt einen Job an. Ist keine Config angegeben, wird sie aus dem Ziel
    (``analyze_vault`` -> ``recommend_config``) empfohlen."""
    path_error = dw.check_paths(source, target)
    if path_error:
        raise ValueError(path_error)
    if config is None:
        config = dw.recommend_config(dw.analyze_vault(target))
    cfg_dict = {k: getattr(config, k) for k in _CONFIG_FIELDS}
    target_path = Path(target).resolve()
    target_path.mkdir(parents=True, exist_ok=True)  # Ziel bei Bedarf anlegen
    with _jobs_write_lock():
        jobs = load_jobs()
        existing = {j.id for j in jobs}
        base = _slug(name)
        job_id = base
        n = 2
        while job_id in existing:
            job_id = f"{base}-{n}"
            n += 1
        job = Job(
            id=job_id, name=name,
            source=str(Path(source).resolve()),
            target=str(target_path),
            config=cfg_dict, poll_interval=poll_interval,
            max_workers=max_workers,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            build_vault=build_vault,
        )
        jobs.append(job)
        save_jobs(jobs)
    return job


def update_job(
    job_ref: str,
    config_updates: dict | None = None,
    poll_interval: int | None = None,
    max_workers: int | None = None,
    build_vault: bool | None = None,
    skip_duplicates: bool | None = None,
) -> Job | None:
    """Aendert Einstellungen eines bestehenden Jobs in-place.

    Wichtig gegenueber rm + add: Manifest und Historie bleiben erhalten --
    bereits konvertierte Dateien werden also NICHT neu konvertiert. Typischer
    Fall: falsch gewaehlte OCR-Engine (z. B. Tesseract ohne Installation)
    nachtraeglich auf EasyOCR umstellen.
    """
    if config_updates:
        unknown = set(config_updates) - set(_CONFIG_FIELDS)
        if unknown:
            raise ValueError(f"Unbekannte Konfig-Felder: {sorted(unknown)}")
    target = get_job(job_ref)
    if not target:
        return None
    with _jobs_write_lock():
        jobs = load_jobs()   # frisch laden: nicht mit altem Snapshot schreiben
        for job in jobs:
            if job.id != target.id:
                continue
            if config_updates:
                job.config.update(config_updates)
            if poll_interval is not None:
                job.poll_interval = poll_interval
            if max_workers is not None:
                job.max_workers = max_workers
            if build_vault is not None:
                job.build_vault = build_vault
            if skip_duplicates is not None:
                job.skip_duplicates = skip_duplicates
            save_jobs(jobs)
            return job
    return None


def remove_job(job_ref: str) -> bool:
    job = get_job(job_ref)
    if not job:
        return False
    with _jobs_write_lock():
        jobs = load_jobs()
        save_jobs([j for j in jobs if j.id != job.id])
    _manifest_file(job.id).unlink(missing_ok=True)
    _lock_file(job.id).unlink(missing_ok=True)
    _history_file(job.id).unlink(missing_ok=True)
    return True


# ---------------------------------------------------------------------------
# Lauf-Historie (je Job)
# ---------------------------------------------------------------------------

# Maximal gespeicherte Laeufe pro Job (aelteste werden verworfen).
HISTORY_LIMIT = 200


def load_history(job_id: str) -> list[dict]:
    """Laedt die Lauf-Historie eines Jobs (neueste zuletzt)."""
    path = _history_file(job_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _append_history(job_id: str, record: dict) -> None:
    history = load_history(job_id)
    history.append(record)
    if len(history) > HISTORY_LIMIT:
        history = history[-HISTORY_LIMIT:]
    path = _history_file(job_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Manifest (Zustand je Job)
# ---------------------------------------------------------------------------

def load_manifest(job_id: str) -> dict:
    path = _manifest_file(job_id)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_manifest(job_id: str, manifest: dict) -> None:
    # Atomar schreiben (tmp -> replace), damit ein Abbruch das Manifest nicht
    # korrumpiert.
    path = _manifest_file(job_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# Max. automatische Wiederholungen fuer eine unveraendert-fehlerhafte Datei.
# Verhindert, dass eine dauerhaft kaputte Datei im watch-Modus endlos erneut
# konvertiert wird. Eine tatsaechlich geaenderte Datei gilt als "changed" und
# wird davon unabhaengig wieder verarbeitet.
RETRY_LIMIT = 3


def _hash_file(path: Path, chunk: int = 1 << 20) -> str:
    # Delegiert an docling_worker.hash_file (eine Implementierung fuer
    # Manifest-Idempotenz UND Duplikaterkennung).
    return dw.hash_file(path, chunk)


def _content_changed(entry: dict, stat: os.stat_result, path: Path) -> bool:
    """True, wenn sich die Datei ggue. Manifest geaendert hat (Hash nur bei Verdacht)."""
    if entry.get("size") == stat.st_size and abs(
        float(entry.get("mtime", -1)) - stat.st_mtime
    ) < 1e-6:
        return False
    try:
        if entry.get("hash") and entry["hash"] == _hash_file(path):
            return False
    except OSError:
        pass
    return True


def scan_changes(job: Job, manifest: dict | None = None) -> ChangeSet:
    """Vergleicht den Quellordner mit dem Manifest (schnell via Groesse/mtime,
    Hash nur bei Verdacht)."""
    if manifest is None:
        manifest = load_manifest(job.id)
    cs = ChangeSet()
    seen: set[str] = set()

    # Ziel- und Archivordner ausblenden, sonst wuerden erzeugte .md-Dateien
    # bzw. archivierte Originale selbst als Quelle erkannt.
    cfg = job.converter_config()
    source_files = dw.discover_files(
        job.source, exclude_dirs=(job.target, cfg.archive_dir)
    )
    for path in source_files:
        key = str(path)
        seen.add(key)
        try:
            stat = path.stat()
        except OSError:
            continue
        entry = manifest.get(key)
        if entry is None:
            cs.new.append(key)
            continue
        changed = _content_changed(entry, stat, path)
        if entry.get("status") != "ok":
            # Fehlerhaft: geaendert -> normal neu; sonst begrenzt wiederholen.
            if changed:
                cs.changed.append(key)
            elif entry.get("attempts", 0) < RETRY_LIMIT:
                cs.retry.append(key)
            else:
                cs.unchanged.append(key)
            continue
        (cs.changed if changed else cs.unchanged).append(key)

    for key, entry in manifest.items():
        # Absichtlich verschobene/geloeschte Originale (on_success) sind kein
        # "entfernt" im Sinne einer verschwundenen Quelldatei.
        if key not in seen and not entry.get("moved_to"):
            cs.removed.append(key)

    # Duplikate: NEUE Dateien, deren Inhalt bereits konvertiert wurde (Hash
    # im Manifest) oder die untereinander inhaltsgleich sind. Nur neue
    # Dateien werden gehasht -- kein Vollscan. Nicht zu verwechseln mit
    # "unveraendert" (dieselbe Datei, Idempotenz).
    if job.skip_duplicates and cs.new:
        known_hashes = {
            e.get("hash") for e in manifest.values()
            if e.get("status") == "ok" and e.get("hash")
        }
        kept: list[str] = []
        seen_new_hashes: set[str] = set()
        for key in sorted(cs.new):
            try:
                digest = _hash_file(Path(key))
            except OSError:
                kept.append(key)
                continue
            if digest in known_hashes or digest in seen_new_hashes:
                cs.duplicates.append(key)
            else:
                seen_new_hashes.add(digest)
                kept.append(key)
        cs.new = kept
    return cs


# ---------------------------------------------------------------------------
# Ausfuehrung
# ---------------------------------------------------------------------------

class JobLockedError(RuntimeError):
    """Wird ausgeloest, wenn ein Job bereits laeuft (Lockfile vorhanden)."""


def _acquire_lock(job_id: str, stale_after: float = 6 * 3600) -> Path:
    lock = _lock_file(job_id)
    if lock.exists():
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            age = 0
        if age < stale_after:
            raise JobLockedError(f"Job '{job_id}' läuft bereits (Lock: {lock}).")
        lock.unlink(missing_ok=True)  # veraltete Sperre entfernen
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # Race-Fenster: ein zweiter Prozess (Dashboard-Klick + watch-Rescan
        # gleichzeitig) war schneller -- als normale Sperre melden, nicht als
        # unbehandelter Traceback.
        raise JobLockedError(
            f"Job '{job_id}' läuft bereits (Lock: {lock})."
        ) from None
    os.write(fd, f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}".encode())
    os.close(fd)
    return lock


def _default_convert_batch(
    files: list[str],
    job: Job,
    max_workers: int | None,
    progress: Callable[[int, int, dw.ConversionResult], None] | None,
) -> list[dw.ConversionResult]:
    """Konvertiert eine Dateiliste ueber den absturzsicheren Batch-Runner."""
    config = job.converter_config()
    workers = max_workers or job.max_workers or max(1, (os.cpu_count() or 2) - 1)
    return dw.run_conversion_batch(
        files, config, job.target, job.source, workers, progress=progress
    )


def run_job(
    job: Job,
    dry_run: bool = False,
    force: bool = False,
    max_workers: int | None = None,
    progress: Callable[[int, int, dw.ConversionResult], None] | None = None,
    convert_batch: Callable | None = None,
    trigger: str = "manuell",
) -> JobRunSummary:
    """Fuehrt einen Job inkrementell aus (oder zeigt bei ``dry_run`` nur den Plan).

    Konvertiert werden nur neue/geaenderte/zuvor fehlgeschlagene Dateien. Das
    Manifest wird atomar und in ``finally`` gespeichert, damit ein Abbruch den
    Zustand nicht verliert. Laeufe mit tatsaechlicher Arbeit landen in der
    Historie (``load_history``); ``trigger`` benennt den Ausloeser
    (cli/dashboard/watch/...). Leerlaeufe werden nicht protokolliert, damit der
    watch-Modus die Historie nicht flutet.
    """
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    manifest = load_manifest(job.id)
    changes = scan_changes(job, manifest)

    if dry_run:
        return JobRunSummary(
            job_id=job.id, started_at=started.isoformat(timespec="seconds"),
            duration_s=time.perf_counter() - t0, changes=changes.counts(),
            converted_ok=0, converted_failed=0, dry_run=True,
        )

    todo = changes.todo
    if not todo:
        _touch_last_run(job)
        return JobRunSummary(
            job_id=job.id, started_at=started.isoformat(timespec="seconds"),
            duration_s=time.perf_counter() - t0, changes=changes.counts(),
            converted_ok=0, converted_failed=0,
        )

    # Vorab-Pruefung statt tausendfach identischer Einzelfehler: fehlt die
    # konfigurierte OCR-Engine (z. B. Tesseract nicht installiert), ist kein
    # sinnvoller Lauf moeglich.
    engine_warning = dw.check_ocr_engine(job.converter_config())
    if engine_warning:
        raise RuntimeError(engine_warning)

    lock = None
    if not force:
        lock = _acquire_lock(job.id)
    batch = convert_batch or _default_convert_batch
    ok = 0
    reduced = 0
    failed = 0
    failures: list = []
    # Groesse/mtime VOR der Konvertierung erfassen: aendert sich die Quelle
    # waehrend des Laufs (grosse Datei wird noch auf das Netzlaufwerk
    # kopiert), muessen die Vor-Werte ins Manifest -- der naechste Scan sieht
    # die Datei dann als "geaendert" und konvertiert nach. Mit Nach-Werten
    # gaelte der halbfertige Stand faelschlich als aktuell.
    pre_stat: dict[str, tuple[int | None, float | None]] = {}
    for src in todo:
        try:
            st = Path(src).stat()
            pre_stat[src] = (st.st_size, st.st_mtime)
        except OSError:
            pre_stat[src] = (None, None)

    # Lock-Heartbeat: die Sperre gilt nach 6 h als verwaist -- ein legitimer
    # Langlauf (Erstkonvertierung tausender PDFs mit OCR) muss sie deshalb
    # periodisch anfassen, sonst startet ein Parallellauf.
    last_touch = time.monotonic()

    def _progress_with_heartbeat(done: int, total: int, res) -> None:
        nonlocal last_touch
        if lock is not None and time.monotonic() - last_touch > 60:
            try:
                os.utime(lock)
            except OSError:
                pass
            last_touch = time.monotonic()
        if progress:
            progress(done, total, res)

    try:
        try:
            Path(job.target).mkdir(parents=True, exist_ok=True)
            results = batch(todo, job, max_workers, _progress_with_heartbeat)
            for res in results:
                size, mtime = pre_stat.get(res.source_path, (None, None))
                entry = {
                    "status": "ok" if res.success else "error",
                    "size": size, "mtime": mtime,
                    "output_path": res.output_path,
                    "num_images": res.num_images,
                    "converted_at": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds"),
                }
                if res.moved_to:
                    entry["moved_to"] = res.moved_to
                if getattr(res, "post_action_error", None):
                    entry["post_action_error"] = res.post_action_error
                if res.success:
                    ok += 1
                    if getattr(res, "reduced_mode", False):
                        reduced += 1
                        entry["reduced"] = True
                    entry["attempts"] = 0
                    try:
                        entry["hash"] = _hash_file(Path(res.source_path))
                    except OSError:
                        entry["hash"] = None
                else:
                    failed += 1
                    prev = manifest.get(res.source_path, {})
                    entry["attempts"] = int(prev.get("attempts", 0)) + 1
                    entry["error"] = res.error
                    entry["error_category"] = res.error_category
                    failures.append(res)
                manifest[res.source_path] = entry
        finally:
            save_manifest(job.id, manifest)
    finally:
        # Eigenes finally: schlaegt save_manifest fehl (Platte voll,
        # Windows-Sharing-Violation), muss die Sperre trotzdem fallen --
        # sonst blockiert der Job bis zum 6-h-Stale-Timeout.
        if lock is not None:
            lock.unlink(missing_ok=True)
    _touch_last_run(job)

    summary = JobRunSummary(
        job_id=job.id, started_at=started.isoformat(timespec="seconds"),
        duration_s=time.perf_counter() - t0, changes=changes.counts(),
        converted_ok=ok, converted_failed=failed,
        converted_reduced=reduced, failures=failures,
    )

    # Optionaler Vault-Build + Such-Index -- nur wenn tatsaechlich etwas
    # konvertiert wurde (der Watch-Modus soll Leerzyklen billig halten).
    # Fehler hier brechen den Job-Lauf nicht ab, sie werden protokolliert.
    if job.build_vault and ok:
        try:
            import vault_builder
            import vault_index

            cfg = job.converter_config()
            target = Path(job.target)
            build_source = (
                target / cfg.notes_subdir if cfg.notes_subdir else target
            )
            bsum = vault_builder.build_vault(build_source, target)
            isum = vault_index.update_index(target)
            vault_index.write_index_md(target)
            summary.build_notes = bsum.notes
            summary.build_images = bsum.images
            summary.index_total = isum.total
        except Exception as exc:  # noqa: BLE001 -- Lauf bleibt erfolgreich
            summary.build_error = f"{type(exc).__name__}: {exc}"

    record = {
        "started_at": summary.started_at,
        "trigger": trigger,
        "duration_s": round(summary.duration_s, 2),
        "changes": summary.changes,
        "converted_ok": ok,
        "converted_failed": failed,
        **({"converted_reduced": reduced} if reduced else {}),
        "failures": [
            {"file": f.source_path, "error": f.error, "category": f.error_category}
            for f in failures[:25]
        ],
    }
    if summary.build_notes is not None:
        record["build"] = {
            "notes": summary.build_notes,
            "images": summary.build_images,
            "index_total": summary.index_total,
        }
    if summary.build_error:
        record["build_error"] = summary.build_error
    _append_history(job.id, record)
    return summary


def _touch_last_run(job: Job) -> None:
    with _jobs_write_lock():
        jobs = load_jobs()   # frisch laden: nicht mit altem Snapshot schreiben
        for j in jobs:
            if j.id == job.id:
                j.last_run_at = datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                )
                save_jobs(jobs)
                return


def watchdog_available() -> bool:
    """True, wenn das optionale ``watchdog``-Paket installiert ist."""
    try:
        import watchdog.observers  # noqa: F401
        return True
    except ImportError:
        return False


def watch_job(
    job: Job,
    stop: Callable[[], bool] | None = None,
    on_cycle: Callable[[JobRunSummary], None] | None = None,
    max_cycles: int | None = None,
    use_events: bool | str = "auto",
    convert_batch: Callable | None = None,
) -> None:
    """Ueberwacht den Quellordner und konvertiert Aenderungen laufend.

    Zwei Betriebsarten:

    * **Ereignisse** (``watchdog`` installiert): Dateisystem-Ereignisse wecken
      die Schleife sofort; ``poll_interval`` dient nur noch als Sicherheits-
      Rescan (wichtig fuer Netzlaufwerke, auf denen Events unzuverlaessig
      sind). Das Intervall kann damit gross gewaehlt werden.
    * **Polling** (Fallback bzw. ``use_events=False``): fester Rescan alle
      ``poll_interval`` Sekunden.

    Laeuft bis ``stop()`` True liefert bzw. ``max_cycles`` erreicht ist
    (Letzteres v. a. fuer Tests). Ohne beides: Endlosschleife (Ctrl+C beendet).
    """
    observer = None
    changed = None
    if use_events is True or (use_events == "auto" and watchdog_available()):
        try:
            import threading

            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            changed = threading.Event()

            class _AnyFileChange(FileSystemEventHandler):
                def on_any_event(self, event):  # noqa: D102
                    if not event.is_directory:
                        changed.set()

            observer = Observer()
            observer.schedule(_AnyFileChange(), job.source, recursive=True)
            observer.start()
        except Exception:
            if use_events is True:
                raise
            observer = None  # auto: still auf Polling zurueckfallen
            changed = None

    try:
        cycles = 0
        while True:
            if stop and stop():
                return
            try:
                summary = run_job(job, trigger="watch", convert_batch=convert_batch)
            except JobLockedError:
                summary = None
            except OSError as exc:
                # Transient (Netzlaufwerk kurz weg, Datei gesperrt): der
                # Dauerbetrieb-Dienst darf daran nicht sterben -- melden und
                # beim naechsten Intervall erneut versuchen. Konfigurations-
                # fehler (RuntimeError, z. B. fehlende OCR-Engine) brechen
                # weiterhin hart ab.
                _LOG.warning("watch: Zyklus übersprungen: %s", exc)
                summary = None
            if summary and on_cycle:
                on_cycle(summary)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return
            # Warten bis Ereignis oder Intervallende; in kleinen Schritten,
            # damit stop() zeitnah greift.
            slept = 0.0
            while slept < job.poll_interval:
                if stop and stop():
                    return
                if changed is not None and changed.is_set():
                    # Schreib-Burst abwarten (Datei wird evtl. noch kopiert).
                    time.sleep(1.0)
                    changed.clear()
                    break
                time.sleep(min(1.0, job.poll_interval - slept))
                slept += 1.0
    finally:
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(job: Job, s: JobRunSummary) -> None:
    print(f"Job '{job.name}' ({job.id}):")
    print("  Änderungen: " + ", ".join(f"{k}={v}" for k, v in s.changes.items()))
    if not s.dry_run:
        print(f"  Konvertiert: ok={s.converted_ok} fehler={s.converted_failed} "
              f"in {s.duration_s:.1f}s")
    if s.build_notes is not None:
        print(f"  Vault-Build: {s.build_notes} Notiz(en) → Inbox/, "
              f"{s.build_images} Bild(er) → Attachments/ · "
              f"Index: {s.index_total} Notizen")
    if s.build_error:
        print(f"  WARNUNG Vault-Build fehlgeschlagen: {s.build_error}",
              file=sys.stderr)


def _run_cli(argv: list[str] | None = None) -> int:
    # doc2vault-Logger sichtbar machen (z. B. watch-Warnungen im Dienstlog).
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(
        description="Sichere, inkrementelle Docling-Jobs (Ordner & Ordnerueberwachung)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Job anlegen")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--source", required=True)
    p_add.add_argument("--target", required=True)
    p_add.add_argument("--workers", type=int, default=None)
    p_add.add_argument("--poll-interval", type=int, default=30)
    p_add.add_argument("--ocr", action="store_true")
    p_add.add_argument("--ocr-engine", choices=["easyocr", "tesseract", "rapidocr"],
                       default=None, help="OCR-Engine (Default easyocr)")
    p_add.add_argument("--ocr-langs", default=None,
                       help="OCR-Sprachen als Kommaliste (de,en)")
    p_add.add_argument("--no-images", action="store_true",
                       help="Keine eingebetteten Bilder extrahieren")
    p_add.add_argument("--images-scale", type=float, default=None,
                       help="Skalierung der extrahierten Bilder (Default 2.0)")
    p_add.add_argument("--no-tables", action="store_true",
                       help="Tabellenstruktur-Erkennung deaktivieren")
    p_add.add_argument("--xlsx-sheet-limit", type=int, default=None,
                       help="Max. Blaetter je XLSX-Arbeitsmappe (0 = alle)")
    p_add.add_argument("--xlsx-on-limit", choices=["limit", "skip"], default=None,
                       help="Bei Ueberschreitung: limit = nur erste Blaetter, "
                       "skip = Datei ueberspringen")
    p_add.add_argument("--on-success", choices=["keep", "archive", "delete"], default=None)
    p_add.add_argument("--archive-dir", default=None)
    p_add.add_argument("--notes-subdir", default=None)
    p_add.add_argument("--attachments-subdir", default=None)
    p_add.add_argument("--no-frontmatter", action="store_true")
    p_add.add_argument("--build-vault", action="store_true",
                       help="Nach jedem Lauf mit Neukonvertierungen Vault-Build "
                       "(Inbox/Attachments/Wikilinks) + Such-Index ausfuehren")

    p_set = sub.add_parser(
        "set",
        help="Job-Einstellungen aendern (Manifest bleibt erhalten -- nichts "
        "wird neu konvertiert)",
    )
    p_set.add_argument("job", help="Job-ID oder Name")
    p_set.add_argument("--ocr", choices=["on", "off"], default=None,
                       help="OCR ein-/ausschalten")
    p_set.add_argument("--ocr-engine", choices=["easyocr", "tesseract", "rapidocr"],
                       default=None, help="OCR-Engine wechseln")
    p_set.add_argument("--ocr-langs", default=None,
                       help="OCR-Sprachen als Kommaliste (de,en)")
    p_set.add_argument("--images", choices=["on", "off"], default=None,
                       help="Bildextraktion ein-/ausschalten")
    p_set.add_argument("--images-scale", type=float, default=None,
                       help="Skalierung der extrahierten Bilder")
    p_set.add_argument("--workers", type=int, default=None)
    p_set.add_argument("--poll-interval", type=int, default=None)
    p_set.add_argument("--build-vault", choices=["on", "off"], default=None,
                       help="Vault-Build + Such-Index nach jedem Lauf")
    p_set.add_argument("--skip-duplicates", choices=["on", "off"], default=None,
                       help="Inhaltsgleiche neue Dateien ueberspringen "
                       "(Vergleich per SHA-256 gegen bereits Konvertiertes)")

    sub.add_parser("list", help="Jobs auflisten")
    for name, helptext in (("plan", "Dry-Run: anstehende Aenderungen zeigen"),
                           ("run", "Job inkrementell ausfuehren"),
                           ("show", "Jobdetails zeigen"),
                           ("rm", "Job loeschen")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("job", help="Job-ID oder Name")
    p_hist = sub.add_parser("history", help="Lauf-Verlauf eines Jobs zeigen")
    p_hist.add_argument("job", help="Job-ID oder Name")
    p_hist.add_argument("-n", "--limit", type=int, default=20,
                        help="Anzahl der letzten Laeufe (Default 20)")
    p_watch = sub.add_parser("watch", help="Ordner ueberwachen (Ereignisse oder Polling)")
    p_watch.add_argument("job")
    p_watch.add_argument("-n", "--poll-interval", type=int, default=None,
                         help="Rescan-Intervall in Sekunden (ueberschreibt Job-Wert)")
    mode = p_watch.add_mutually_exclusive_group()
    mode.add_argument("--events", action="store_true",
                      help="Dateisystem-Ereignisse erzwingen (erfordert watchdog)")
    mode.add_argument("--poll", action="store_true",
                      help="Polling erzwingen (z. B. fuer Netzlaufwerke)")

    args = parser.parse_args(argv)

    if args.cmd == "add":
        profile = dw.analyze_vault(args.target)
        config = dw.recommend_config(profile)
        if args.ocr:
            config.do_ocr = True
        if args.ocr_engine:
            config.ocr_engine = args.ocr_engine
        if args.ocr_langs:
            config.ocr_languages = args.ocr_langs
        if args.no_images:
            config.generate_picture_images = False
        if args.images_scale is not None:
            config.images_scale = args.images_scale
        if args.no_tables:
            config.do_table_structure = False
        if args.xlsx_sheet_limit is not None:
            config.xlsx_sheet_limit = args.xlsx_sheet_limit
        if args.xlsx_on_limit is not None:
            config.xlsx_on_limit = args.xlsx_on_limit
        if args.on_success:
            config.on_success = args.on_success
        if args.archive_dir:
            config.archive_dir = str(Path(args.archive_dir).resolve())
        if args.notes_subdir is not None:
            config.notes_subdir = args.notes_subdir
        if args.attachments_subdir is not None:
            config.attachments_subdir = args.attachments_subdir
            config.attachments_mode = "central"
        if args.no_frontmatter:
            config.add_frontmatter = False
        try:
            job = add_job(args.name, args.source, args.target, config,
                          poll_interval=args.poll_interval,
                          max_workers=args.workers,
                          build_vault=args.build_vault)
        except ValueError as exc:
            print(f"FEHLER: {exc}", file=sys.stderr)
            return 2
        print(f"Job angelegt: {job.id}")
        print("Integrationsplan:")
        for line in dw.describe_plan(profile, config):
            print(f"  {line}")
        return 0

    if args.cmd == "set":
        cfg_updates: dict = {}
        if args.ocr is not None:
            cfg_updates["do_ocr"] = args.ocr == "on"
        if args.ocr_engine is not None:
            cfg_updates["ocr_engine"] = args.ocr_engine
        if args.ocr_langs is not None:
            cfg_updates["ocr_languages"] = args.ocr_langs
        if args.images is not None:
            cfg_updates["generate_picture_images"] = args.images == "on"
        if args.images_scale is not None:
            cfg_updates["images_scale"] = args.images_scale
        if (not cfg_updates and args.workers is None
                and args.poll_interval is None and args.build_vault is None
                and args.skip_duplicates is None):
            print("Nichts zu aendern (siehe --help fuer verfuegbare Optionen).",
                  file=sys.stderr)
            return 2
        job = update_job(
            args.job, config_updates=cfg_updates or None,
            poll_interval=args.poll_interval, max_workers=args.workers,
            build_vault=(None if args.build_vault is None
                         else args.build_vault == "on"),
            skip_duplicates=(None if args.skip_duplicates is None
                             else args.skip_duplicates == "on"),
        )
        if not job:
            print(f"Job nicht gefunden: {args.job}", file=sys.stderr)
            return 2
        cfg = job.converter_config()
        print(f"Job {job.id} aktualisiert.")
        print(f"  OCR: {'an' if cfg.do_ocr else 'aus'}"
              + (f" ({cfg.ocr_engine}, {cfg.ocr_languages})" if cfg.do_ocr else ""))
        print(f"  Bilder: {'an' if cfg.generate_picture_images else 'aus'}"
              f" (Skalierung {cfg.images_scale})")
        warning = dw.check_ocr_engine(cfg)
        if warning:
            print(f"  WARNUNG: {warning}", file=sys.stderr)
        return 0

    if args.cmd == "list":
        jobs = load_jobs()
        if not jobs:
            print("Keine Jobs. Anlegen mit: job_manager.py add ...")
            return 0
        for j in jobs:
            m = load_manifest(j.id)
            done = sum(1 for e in m.values() if e.get("status") == "ok")
            print(f"  {j.id:24s} {j.name}")
            print(f"    {j.source}  ->  {j.target}")
            print(f"    konvertiert: {done}  letzter Lauf: {j.last_run_at or '-'}"
                  + ("  [Vault-Build+Index]" if j.build_vault else ""))
        return 0

    if args.cmd in ("plan", "run", "show", "rm", "watch", "history"):
        job = get_job(args.job)
        if not job:
            print(f"Job nicht gefunden: {args.job}", file=sys.stderr)
            return 2
        if args.cmd == "show":
            print(json.dumps(asdict(job), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "rm":
            remove_job(job.id)
            print(f"Job gelöscht: {job.id}")
            return 0
        if args.cmd == "history":
            history = load_history(job.id)
            if not history:
                print("Noch keine Läufe protokolliert.")
                return 0
            for rec in history[-args.limit:][::-1]:
                ch = rec.get("changes", {})
                print(f"  {rec.get('started_at', '-'):25s} "
                      f"{rec.get('trigger', '-'):10s} "
                      f"neu={ch.get('neu', 0)} geändert={ch.get('geaendert', 0)}  "
                      f"ok={rec.get('converted_ok', 0)} "
                      f"fehler={rec.get('converted_failed', 0)}  "
                      f"{rec.get('duration_s', 0):.1f}s")
                for f in rec.get("failures", []):
                    print(f"      FEHLER {f.get('file')}: {f.get('error')}")
            return 0
        if args.cmd == "plan":
            _print_summary(job, run_job(job, dry_run=True))
            return 0
        if args.cmd == "run":
            def _prog(done, total, res):
                mark = "ok" if res.success else "FEHLER"
                print(f"  [{done}/{total}] {mark}  {Path(res.source_path).name}", flush=True)
            try:
                s = run_job(job, progress=_prog, trigger="cli")
            except JobLockedError as exc:
                print(str(exc), file=sys.stderr)
                return 3
            except RuntimeError as exc:
                # z. B. konfigurierte OCR-Engine nicht installiert
                print(f"FEHLER: {exc}", file=sys.stderr)
                return 2
            _print_summary(job, s)
            return 1 if s.converted_failed else 0
        if args.cmd == "watch":
            if args.poll_interval:
                job.poll_interval = args.poll_interval
            if args.events and not watchdog_available():
                print("Ereignismodus erfordert das Paket 'watchdog' "
                      "(pip install watchdog).", file=sys.stderr)
                return 2
            use_events: bool | str = (
                True if args.events else False if args.poll else "auto"
            )
            events_active = use_events is True or (
                use_events == "auto" and watchdog_available()
            )
            mode_txt = (
                f"Ereignisse + Sicherheits-Rescan alle {job.poll_interval}s"
                if events_active else f"Polling alle {job.poll_interval}s"
            )
            print(f"Überwache {job.source} ({mode_txt}). Ctrl+C zum Beenden.")

            def _cycle(s: JobRunSummary):
                if s.converted_ok or s.converted_failed:
                    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                    extra = ""
                    if s.build_notes is not None:
                        extra = (f", Build: {s.build_notes} → Inbox/, "
                                 f"Index: {s.index_total}")
                    if s.build_error:
                        extra += f", BUILD-FEHLER: {s.build_error}"
                    print(f"  [{ts}] +{s.converted_ok} konvertiert, "
                          f"{s.converted_failed} Fehler{extra}", flush=True)
            try:
                watch_job(job, on_cycle=_cycle, use_events=use_events)
            except KeyboardInterrupt:
                print("\nBeendet.")
            return 0

    return 0


def main() -> int:
    """Einstiegspunkt fuer den ``doc2vault-jobs``-Konsolenbefehl."""
    return _run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
