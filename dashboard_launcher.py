"""Einstiegspunkt fuer den ``docling-vault-ui``-Konsolenbefehl.

Startet das Streamlit-Dashboard aus der installierten Paketumgebung. Da die
``.streamlit/config.toml`` des Repos bei einer Paketinstallation nicht im
Arbeitsverzeichnis liegt, werden Theme und Toolbar-Einstellung hier als
Kommandozeilen-Optionen mitgegeben. Eigene Streamlit-Optionen (z. B.
``--server.port 8080``) koennen angehaengt werden und ueberschreiben die
Voreinstellungen.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THEME_ARGS = [
    "--theme.base=dark",
    "--theme.primaryColor=#4c8bf5",
    "--theme.backgroundColor=#12151c",
    "--theme.secondaryBackgroundColor=#181c25",
    "--theme.textColor=#d8dee8",
    "--client.toolbarMode=minimal",
    "--browser.gatherUsageStats=false",
]


def main() -> int:
    from streamlit.web import cli as stcli

    app = Path(__file__).with_name("app_streamlit.py")
    sys.argv = ["streamlit", "run", str(app), *_THEME_ARGS, *sys.argv[1:]]
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
