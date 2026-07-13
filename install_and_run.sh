#!/usr/bin/env bash
#
# Ein-Klick-Setup + Start fuer Linux/macOS.
#
# Prueft Python, legt ein virtuelles Environment an, installiert die
# Abhaengigkeiten (Docling + Streamlit) und startet das Dashboard.
#
# Anders als frueher (Heredoc-Variante) werden docling_worker.py und
# app_streamlit.py NICHT mehr eingebettet, sondern aus dem Repo verwendet --
# eine einzige Quelle der Wahrheit statt duplizierter Konvertierungslogik.
#
# Nutzung:
#   ./install_and_run.sh            # Setup + Streamlit-Dashboard
#   ./install_and_run.sh --cli -i <quelle> -o <vault> [--ocr]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

# --- Python finden ---------------------------------------------------------
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  echo "FEHLER: Kein Python 3 gefunden. Bitte Python 3.10+ installieren." >&2
  echo "  macOS:  brew install python" >&2
  echo "  Debian: sudo apt-get install python3 python3-venv python3-pip" >&2
  exit 1
fi
echo "Verwende Python: $($PYTHON_BIN --version)"

# --- venv anlegen ----------------------------------------------------------
if [[ ! -d "$VENV_DIR" ]]; then
  echo "Lege virtuelles Environment an ($VENV_DIR)..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# --- Abhaengigkeiten installieren -----------------------------------------
python -m pip install --upgrade pip >/dev/null
echo "Installiere Abhaengigkeiten (Docling + Streamlit)... das kann dauern."
python -m pip install -r requirements.txt

# --- Start -----------------------------------------------------------------
if [[ "${1:-}" == "--cli" ]]; then
  shift
  echo "Starte CLI-Konvertierung..."
  exec python docling_worker.py "$@"
else
  echo "Starte Streamlit-Dashboard (Strg+C zum Beenden)..."
  exec streamlit run app_streamlit.py
fi
