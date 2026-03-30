$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDirectory = Join-Path $projectRoot "logs"
$logPath = Join-Path $logDirectory "send_reminders.log"

if (-not (Test-Path $pythonPath)) {
    throw "Virtual environment Python was not found at $pythonPath"
}

if (-not (Test-Path $logDirectory)) {
    New-Item -ItemType Directory -Path $logDirectory | Out-Null
}

Push-Location $projectRoot
try {
    Add-Content -Path $logPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting reminder run."
    & $pythonPath manage.py send_reminders 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "manage.py send_reminders exited with code $LASTEXITCODE"
    }
    Add-Content -Path $logPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Reminder run completed successfully."
}
finally {
    Pop-Location
}
