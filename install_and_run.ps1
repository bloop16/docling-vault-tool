<#
    Ein-Klick-Setup + Start fuer Windows (PowerShell).

    Prueft Python (installiert es bei Bedarf via winget), legt ein virtuelles
    Environment an, installiert die Abhaengigkeiten (Docling + Streamlit) und
    startet das Dashboard.

    docling_worker.py und app_streamlit.py werden aus dem Repo verwendet --
    keine eingebettete/duplizierte Konvertierungslogik.

    Nutzung:
        .\install_and_run.ps1
        .\install_and_run.ps1 -Cli -i <quelle> -o <vault> [--ocr]
#>

param(
    [switch]$Cli,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$VenvDir = ".venv"

function Get-PythonCommand {
    foreach ($candidate in @("python", "python3", "py")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                $ver = & $candidate --version 2>&1
                if ($ver -match "Python 3") { return $candidate }
            } catch { }
        }
    }
    return $null
}

$PythonBin = Get-PythonCommand

if (-not $PythonBin) {
    Write-Host "Kein Python 3 gefunden. Versuche Installation via winget..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Python.Python.3.12 -e --source winget `
            --accept-package-agreements --accept-source-agreements
        Write-Host "Bitte PowerShell neu starten und Skript erneut ausfuehren." `
            -ForegroundColor Yellow
        exit 1
    } else {
        Write-Error "Weder Python 3 noch winget gefunden. Bitte Python 3.10+ von python.org installieren."
        exit 1
    }
}

Write-Host "Verwende Python: $(& $PythonBin --version)"

# --- venv anlegen ----------------------------------------------------------
if (-not (Test-Path $VenvDir)) {
    Write-Host "Lege virtuelles Environment an ($VenvDir)..."
    & $PythonBin -m venv $VenvDir
}
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

# --- Abhaengigkeiten installieren -----------------------------------------
& $VenvPython -m pip install --upgrade pip | Out-Null
Write-Host "Installiere Abhaengigkeiten (Docling + Streamlit)... das kann dauern."
& $VenvPython -m pip install -r requirements.txt

# --- Start -----------------------------------------------------------------
if ($Cli) {
    Write-Host "Starte CLI-Konvertierung..."
    & $VenvPython docling_worker.py @Rest
} else {
    Write-Host "Starte Streamlit-Dashboard (Strg+C zum Beenden)..."
    & $VenvPython -m streamlit run app_streamlit.py
}
