<#
    Registriert eine Windows-Aufgabe, die die Ordnerueberwachung eines Jobs
    bei der Anmeldung startet und bei Fehlern neu anlaeuft.

    Nutzung (PowerShell, aus dem Repo-Verzeichnis):
        .\deploy\windows\register_watch_task.ps1 -JobId berichte-2024

    Optional:
        -PythonExe   Pfad zur python.exe (Default: .venv des Repos)
        -WorkingDir  Arbeitsverzeichnis (Default: Repo-Wurzel)

    Entfernen:
        Unregister-ScheduledTask -TaskName "DoclingVaultWatch-<JobId>"
#>

param(
    [Parameter(Mandatory = $true)][string]$JobId,
    [string]$PythonExe = (Join-Path (Resolve-Path "$PSScriptRoot\..\..") ".venv\Scripts\python.exe"),
    [string]$WorkingDir = (Resolve-Path "$PSScriptRoot\..\..")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Python nicht gefunden: $PythonExe (erst install_and_run.ps1 ausfuehren oder -PythonExe angeben)"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "job_manager.py watch $JobId" `
    -WorkingDirectory $WorkingDir

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "DoclingVaultWatch-$JobId" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Docling Vault Ordnerueberwachung fuer Job $JobId" `
    -Force | Out-Null

Write-Host "Aufgabe 'DoclingVaultWatch-$JobId' registriert (Start bei Anmeldung)."
Write-Host "Sofort starten:  Start-ScheduledTask -TaskName 'DoclingVaultWatch-$JobId'"
