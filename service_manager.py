"""Dienste einrichten: doc2vault laeuft weiter, wenn das Terminal zugeht.

Ein Befehl fuer beide Plattformen::

    doc2vault-service install ui [--port 8501]     # Dashboard als Dienst
    doc2vault-service install watch <job>          # Ordnerueberwachung als Dienst
    doc2vault-service uninstall ui|watch <job>
    doc2vault-service status

Umsetzung je Plattform:

* **Linux**: systemd-*Benutzerdienste* (kein Root noetig) unter
  ``~/.config/systemd/user/doc2vault-*.service`` mit ``Restart=on-failure``;
  aktiviert via ``systemctl --user enable --now``. Damit der Dienst auch
  ohne aktive Anmeldung laeuft: ``loginctl enable-linger $USER`` (wird als
  Hinweis ausgegeben). Systemweite Alternative: Vorlage ``deploy/systemd/``.
* **Windows**: Aufgabenplanung (``schtasks``) mit Start bei Anmeldung und
  sofortigem Erststart -- laeuft ohne offenes Terminalfenster weiter. Ein
  "echter" Windows-Dienst braeuchte Zusatzsoftware (NSSM); die geplante
  Aufgabe erfuellt denselben Zweck ohne Abhaengigkeiten.

Die Funktionen bauen reine Kommandolisten (testbar); nur die CLI fuehrt
sie aus.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

UI_UNIT = "doc2vault-ui"
WATCH_UNIT_PREFIX = "doc2vault-watch-"
WIN_UI_TASK = "Doc2VaultUI"
WIN_WATCH_PREFIX = "Doc2VaultWatch-"


def _find_command(name: str) -> str:
    """Absoluter Pfad eines doc2vault-Konsolenbefehls (venv-sicher)."""
    # Erst neben dem laufenden Interpreter suchen (venv/Scripts bzw. bin),
    # dann im PATH -- so zeigt der Dienst auf dieselbe Installation.
    candidates = [
        Path(sys.executable).parent / name,
        Path(sys.executable).parent / f"{name}.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"Befehl {name!r} nicht gefunden – ist doc2vault installiert "
        "(pip install .)?"
    )


# ---------------------------------------------------------------------------
# Linux (systemd-Benutzerdienste)
# ---------------------------------------------------------------------------

def systemd_unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def systemd_unit_text(description: str, exec_start: str) -> str:
    return (
        "[Unit]\n"
        f"Description={description}\n"
        "After=network.target\n\n"
        "[Service]\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def systemd_install_commands(unit: str) -> list[list[str]]:
    return [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", f"{unit}.service"],
    ]


def systemd_uninstall_commands(unit: str) -> list[list[str]]:
    return [
        ["systemctl", "--user", "disable", "--now", f"{unit}.service"],
        ["systemctl", "--user", "daemon-reload"],
    ]


# ---------------------------------------------------------------------------
# Windows (Aufgabenplanung)
# ---------------------------------------------------------------------------

def schtasks_create_commands(task: str, command_line: str) -> list[list[str]]:
    return [
        ["schtasks", "/Create", "/TN", task, "/TR", command_line,
         "/SC", "ONLOGON", "/RL", "LIMITED", "/F"],
        ["schtasks", "/Run", "/TN", task],
    ]


def schtasks_delete_commands(task: str) -> list[list[str]]:
    return [
        ["schtasks", "/End", "/TN", task],
        ["schtasks", "/Delete", "/TN", task, "/F"],
    ]


# ---------------------------------------------------------------------------
# Plattformuebergreifende Aktionen
# ---------------------------------------------------------------------------

def _run_all(commands: list[list[str]]) -> int:
    rc = 0
    for cmd in commands:
        print("  $", " ".join(cmd))
        result = subprocess.run(cmd, check=False)
        rc = rc or result.returncode
    return rc


def install(target: str, job: str | None, port: int, platform: str) -> int:
    if target == "ui":
        exec_cmd = (
            f"{_find_command('doc2vault-ui')} "
            f"--server.port {port} --server.headless true"
        )
        unit, task = UI_UNIT, WIN_UI_TASK
        description = "doc2vault Dashboard"
    else:
        if not job:
            print("FEHLER: install watch braucht eine Job-ID.", file=sys.stderr)
            return 2
        exec_cmd = f"{_find_command('doc2vault-jobs')} watch {job}"
        unit, task = f"{WATCH_UNIT_PREFIX}{job}", f"{WIN_WATCH_PREFIX}{job}"
        description = f"doc2vault Ordnerueberwachung ({job})"

    if platform.startswith("win"):
        rc = _run_all(schtasks_create_commands(task, exec_cmd))
        if rc == 0:
            print(f"Aufgabe {task!r} angelegt: startet bei Anmeldung, "
                  "laeuft ohne Terminalfenster weiter.")
        return rc

    if platform.startswith("linux"):
        unit_dir = systemd_unit_dir()
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_file = unit_dir / f"{unit}.service"
        unit_file.write_text(systemd_unit_text(description, exec_cmd),
                             encoding="utf-8")
        print(f"  Unit geschrieben: {unit_file}")
        rc = _run_all(systemd_install_commands(unit))
        if rc == 0:
            print(f"Dienst {unit!r} laeuft (Neustart bei Fehlern automatisch).")
            print("Damit er auch ohne aktive Anmeldung weiterlaeuft: "
                  "loginctl enable-linger $USER")
        return rc

    print(f"Plattform {platform!r} wird nicht automatisch eingerichtet. "
          "Vorlagen: deploy/ (systemd, Windows-Task) bzw. Docker Compose.",
          file=sys.stderr)
    return 2


def uninstall(target: str, job: str | None, platform: str) -> int:
    if target == "ui":
        unit, task = UI_UNIT, WIN_UI_TASK
    else:
        if not job:
            print("FEHLER: uninstall watch braucht eine Job-ID.", file=sys.stderr)
            return 2
        unit, task = f"{WATCH_UNIT_PREFIX}{job}", f"{WIN_WATCH_PREFIX}{job}"

    if platform.startswith("win"):
        return _run_all(schtasks_delete_commands(task))
    if platform.startswith("linux"):
        rc = _run_all(systemd_uninstall_commands(unit))
        (systemd_unit_dir() / f"{unit}.service").unlink(missing_ok=True)
        return rc
    print(f"Plattform {platform!r} nicht unterstuetzt.", file=sys.stderr)
    return 2


def status(platform: str) -> int:
    if platform.startswith("win"):
        return _run_all([
            ["schtasks", "/Query", "/TN", WIN_UI_TASK],
        ])
    if platform.startswith("linux"):
        return _run_all([
            ["systemctl", "--user", "--no-pager", "list-units",
             "doc2vault-*", "--all"],
        ])
    print(f"Plattform {platform!r} nicht unterstuetzt.", file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="doc2vault als Hintergrunddienst einrichten "
        "(Linux: systemd-Benutzerdienst, Windows: Aufgabenplanung)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="Dienst anlegen und starten")
    p_install.add_argument("target", choices=["ui", "watch"],
                           help="ui = Dashboard, watch = Ordnerueberwachung")
    p_install.add_argument("job", nargs="?", default=None,
                           help="Job-ID (nur fuer watch)")
    p_install.add_argument("--port", type=int, default=8501,
                           help="Dashboard-Port (Default 8501)")

    p_un = sub.add_parser("uninstall", help="Dienst stoppen und entfernen")
    p_un.add_argument("target", choices=["ui", "watch"])
    p_un.add_argument("job", nargs="?", default=None)

    sub.add_parser("status", help="Eingerichtete doc2vault-Dienste anzeigen")

    args = parser.parse_args(argv)
    platform = sys.platform

    if args.cmd == "install":
        return install(args.target, args.job, args.port, platform)
    if args.cmd == "uninstall":
        return uninstall(args.target, args.job, platform)
    return status(platform)


def main() -> int:
    """Einstiegspunkt fuer den ``doc2vault-service``-Konsolenbefehl."""
    return _run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
