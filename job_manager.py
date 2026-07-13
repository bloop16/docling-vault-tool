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
(``DOCLING_VAULT_HOME`` oder OS-Standard), sodass das Tool nutzerunabhaengig ist.

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
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import docling_worker as dw

# Felder von ConverterConfig, die pro Job gespeichert/rekonstruiert werden.
_CONFIG_FIELDS = (
    "do_ocr", "generate_picture_images", "images_scale", "do_table_structure",
    "on_success", "archive_dir", "notes_subdir", "mirror_structure",
    "attachments_mode", "attachments_subdir", "add_frontmatter",
)


# ---------------------------------------------------------------------------
# Speicherorte (nutzerspezifisch)
# ---------------------------------------------------------------------------

def config_dir() -> Path:
    """Konfig-/Statusverzeichnis (``DOCLING_VAULT_HOME`` oder OS-Standard)."""
    env = os.environ.get("DOCLING_VAULT_HOME")
    if env:
        base = Path(env)
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home())) / "docling-vault-tool"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "docling-vault-tool"
    else:
        base = Path(
            os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        ) / "docling-vault-tool"
    base.mkdir(parents=True, exist_ok=True)
    (base / "manifests").mkdir(exist_ok=True)
    return base


def _jobs_file() -> Path:
    return config_dir() / "jobs.json"


def _manifest_file(job_id: str) -> Path:
    return config_dir() / "manifests" / f"{job_id}.json"


def _lock_file(job_id: str) -> Path:
    return config_dir() / "manifests" / f"{job_id}.lock"


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
    max_workers: Optional[int] = None
    created_at: str = ""
    last_run_at: Optional[str] = None

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

    @property
    def todo(self) -> list[str]:
        """Dateien, die tatsaechlich (neu) konvertiert werden."""
        return self.new + self.changed + self.retry

    def counts(self) -> dict[str, int]:
        return {
            "neu": len(self.new),
            "geaendert": len(self.changed),
            "unveraendert": len(self.unchanged),
            "entfernt": len(self.removed),
            "wiederholung": len(self.retry),
        }


@dataclass
class JobRunSummary:
    """Zusammenfassung eines Job-Laufs."""

    job_id: str
    started_at: str
    duration_s: float
    changes: dict[str, int]
    converted_ok: int
    converted_failed: int
    failures: list = field(default_factory=list)
    dry_run: bool = False
    skipped_locked: bool = False


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
        return []
    return [Job(**j) for j in data]


def save_jobs(jobs: list[Job]) -> None:
    _jobs_file().write_text(
        json.dumps([asdict(j) for j in jobs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_job(job_ref: str) -> Optional[Job]:
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
    config: Optional[dw.ConverterConfig] = None,
    poll_interval: int = 30,
    max_workers: Optional[int] = None,
) -> Job:
    """Legt einen Job an. Ist keine Config angegeben, wird sie aus dem Ziel
    (``analyze_vault`` -> ``recommend_config``) empfohlen."""
    if config is None:
        config = dw.recommend_config(dw.analyze_vault(target))
    cfg_dict = {k: getattr(config, k) for k in _CONFIG_FIELDS}
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
        target=str(Path(target).resolve()),
        config=cfg_dict, poll_interval=poll_interval, max_workers=max_workers,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    jobs.append(job)
    save_jobs(jobs)
    return job


def remove_job(job_ref: str) -> bool:
    jobs = load_jobs()
    job = get_job(job_ref)
    if not job:
        return False
    save_jobs([j for j in jobs if j.id != job.id])
    _manifest_file(job.id).unlink(missing_ok=True)
    _lock_file(job.id).unlink(missing_ok=True)
    return True


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
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


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


def scan_changes(job: Job, manifest: Optional[dict] = None) -> ChangeSet:
    """Vergleicht den Quellordner mit dem Manifest (schnell via Groesse/mtime,
    Hash nur bei Verdacht)."""
    if manifest is None:
        manifest = load_manifest(job.id)
    cs = ChangeSet()
    seen: set[str] = set()

    for path in dw.discover_files(job.source):
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

    for key in manifest:
        if key not in seen:
            cs.removed.append(key)
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
            raise JobLockedError(f"Job '{job_id}' laeuft bereits (Lock: {lock}).")
        lock.unlink(missing_ok=True)  # veraltete Sperre entfernen
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}".encode())
    os.close(fd)
    return lock


def _default_convert_batch(
    files: list[str],
    job: Job,
    max_workers: Optional[int],
    progress: Optional[Callable[[int, int, "dw.ConversionResult"], None]],
) -> list["dw.ConversionResult"]:
    """Konvertiert eine Liste von Dateien parallel (ein Docling-Converter je Prozess)."""
    from concurrent.futures import ProcessPoolExecutor, as_completed

    config = job.converter_config()
    workers = max_workers or job.max_workers or max(1, (os.cpu_count() or 2) - 1)
    results: list[dw.ConversionResult] = []
    total = len(files)
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=dw.init_worker,
        initargs=(config, job.target, job.source),
    ) as pool:
        futures = {pool.submit(dw.convert_file_task, f): f for f in files}
        for done, fut in enumerate(as_completed(futures), start=1):
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001
                res = dw.ConversionResult(
                    source_path=futures[fut], success=False,
                    error=f"Pool-Fehler: {exc}",
                )
            results.append(res)
            if progress:
                progress(done, total, res)
    return results


def run_job(
    job: Job,
    dry_run: bool = False,
    force: bool = False,
    max_workers: Optional[int] = None,
    progress: Optional[Callable[[int, int, "dw.ConversionResult"], None]] = None,
    convert_batch: Optional[Callable] = None,
) -> JobRunSummary:
    """Fuehrt einen Job inkrementell aus (oder zeigt bei ``dry_run`` nur den Plan).

    Konvertiert werden nur neue/geaenderte/zuvor fehlgeschlagene Dateien. Das
    Manifest wird atomar und in ``finally`` gespeichert, damit ein Abbruch den
    Zustand nicht verliert.
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

    lock = None
    if not force:
        lock = _acquire_lock(job.id)
    batch = convert_batch or _default_convert_batch
    ok = 0
    failed = 0
    failures: list = []
    try:
        Path(job.target).mkdir(parents=True, exist_ok=True)
        results = batch(todo, job, max_workers, progress)
        for res in results:
            try:
                stat = Path(res.source_path).stat()
                size, mtime = stat.st_size, stat.st_mtime
            except OSError:
                size, mtime = None, None
            entry = {
                "status": "ok" if res.success else "error",
                "size": size, "mtime": mtime,
                "output_path": res.output_path,
                "num_images": res.num_images,
                "converted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            if res.success:
                ok += 1
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
        if lock is not None:
            lock.unlink(missing_ok=True)
    _touch_last_run(job)

    return JobRunSummary(
        job_id=job.id, started_at=started.isoformat(timespec="seconds"),
        duration_s=time.perf_counter() - t0, changes=changes.counts(),
        converted_ok=ok, converted_failed=failed, failures=failures,
    )


def _touch_last_run(job: Job) -> None:
    jobs = load_jobs()
    for j in jobs:
        if j.id == job.id:
            j.last_run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            save_jobs(jobs)
            return


def watch_job(
    job: Job,
    stop: Optional[Callable[[], bool]] = None,
    on_cycle: Optional[Callable[[JobRunSummary], None]] = None,
    max_cycles: Optional[int] = None,
) -> None:
    """Ueberwacht den Quellordner per Polling und konvertiert Aenderungen laufend.

    Laeuft bis ``stop()`` True liefert bzw. bis ``max_cycles`` erreicht ist
    (Letzteres v. a. fuer Tests). Ohne beides: Endlosschleife (Ctrl+C beendet).
    """
    cycles = 0
    while True:
        if stop and stop():
            return
        try:
            summary = run_job(job)
        except JobLockedError:
            summary = None
        if summary and on_cycle:
            on_cycle(summary)
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            return
        # Reaktionsschnell schlafen (in kleinen Schritten, damit stop() greift).
        slept = 0.0
        while slept < job.poll_interval:
            if stop and stop():
                return
            time.sleep(min(1.0, job.poll_interval - slept))
            slept += 1.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(job: Job, s: JobRunSummary) -> None:
    print(f"Job '{job.name}' ({job.id}):")
    print("  Aenderungen: " + ", ".join(f"{k}={v}" for k, v in s.changes.items()))
    if not s.dry_run:
        print(f"  Konvertiert: ok={s.converted_ok} fehler={s.converted_failed} "
              f"in {s.duration_s:.1f}s")


def _run_cli(argv: Optional[list[str]] = None) -> int:
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
    p_add.add_argument("--on-success", choices=["keep", "archive", "delete"], default=None)
    p_add.add_argument("--archive-dir", default=None)
    p_add.add_argument("--notes-subdir", default=None)
    p_add.add_argument("--attachments-subdir", default=None)
    p_add.add_argument("--no-frontmatter", action="store_true")

    sub.add_parser("list", help="Jobs auflisten")
    for name, helptext in (("plan", "Dry-Run: anstehende Aenderungen zeigen"),
                           ("run", "Job inkrementell ausfuehren"),
                           ("show", "Jobdetails zeigen"),
                           ("rm", "Job loeschen")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("job", help="Job-ID oder Name")
    p_watch = sub.add_parser("watch", help="Ordner ueberwachen (Polling)")
    p_watch.add_argument("job")
    p_watch.add_argument("-n", "--poll-interval", type=int, default=None,
                         help="Intervall in Sekunden (ueberschreibt Job-Wert)")

    args = parser.parse_args(argv)

    if args.cmd == "add":
        profile = dw.analyze_vault(args.target)
        config = dw.recommend_config(profile)
        if args.ocr:
            config.do_ocr = True
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
        job = add_job(args.name, args.source, args.target, config,
                      poll_interval=args.poll_interval, max_workers=args.workers)
        print(f"Job angelegt: {job.id}")
        print("Integrationsplan:")
        for line in dw.describe_plan(profile, config):
            print(f"  {line}")
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
            print(f"    konvertiert: {done}  letzter Lauf: {j.last_run_at or '-'}")
        return 0

    if args.cmd in ("plan", "run", "show", "rm", "watch"):
        job = get_job(args.job)
        if not job:
            print(f"Job nicht gefunden: {args.job}", file=sys.stderr)
            return 2
        if args.cmd == "show":
            print(json.dumps(asdict(job), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "rm":
            remove_job(job.id)
            print(f"Job geloescht: {job.id}")
            return 0
        if args.cmd == "plan":
            _print_summary(job, run_job(job, dry_run=True))
            return 0
        if args.cmd == "run":
            def _prog(done, total, res):
                mark = "ok" if res.success else "FEHLER"
                print(f"  [{done}/{total}] {mark}  {Path(res.source_path).name}", flush=True)
            try:
                s = run_job(job, progress=_prog)
            except JobLockedError as exc:
                print(str(exc), file=sys.stderr)
                return 3
            _print_summary(job, s)
            return 1 if s.converted_failed else 0
        if args.cmd == "watch":
            if args.poll_interval:
                job.poll_interval = args.poll_interval
            print(f"Ueberwache {job.source} (Intervall {job.poll_interval}s). "
                  f"Ctrl+C zum Beenden.")

            def _cycle(s: JobRunSummary):
                if s.converted_ok or s.converted_failed:
                    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                    print(f"  [{ts}] +{s.converted_ok} konvertiert, "
                          f"{s.converted_failed} Fehler", flush=True)
            try:
                watch_job(job, on_cycle=_cycle)
            except KeyboardInterrupt:
                print("\nBeendet.")
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(_run_cli())
