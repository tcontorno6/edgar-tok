# One-time setup for edgar-tok (run from this folder in PowerShell):
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
Set-Location $PSScriptRoot

# venv (py launcher picks the newest 3.x; use `py -3.11` to force 3.11)
if (-not (Test-Path .venv)) {
    py -3 -m venv .venv
    Write-Host "created .venv"
}
.\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# git
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (-not (Test-Path .git)) {
        git init | Out-Null
        Write-Host "initialized git repository"
    }
} else {
    Write-Host "git not found on PATH - skipping git init"
}

Write-Host ""
Write-Host "Done. Activate with:  .\.venv\Scripts\Activate.ps1"
