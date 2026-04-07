# Capture + bundle. Si debug_odoo_defaults.json existe : aucune question (sauf -Interactive).
# Sinon : questions comme avant.
param(
    [switch]$Interactive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPy = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$py = if (Test-Path $venvPy) { $venvPy } else { "python" }

if (-not (Test-Path ".env")) {
    Write-Host "ERREUR: fichier .env absent dans ce dossier." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path "odoo_browser_state.json")) {
    Write-Host "ERREUR: lancez d'abord CONNEXION_ODOO_UNE_FOIS.cmd" -ForegroundColor Red
    exit 1
}

if (-not $Interactive -and (Test-Path "debug_odoo_defaults.json")) {
    Write-Host "Utilisation de debug_odoo_defaults.json (sans questions)…" -ForegroundColor Cyan
    Write-Host "Python: $py" -ForegroundColor Cyan
    & $py "run_debug_capture.py"
    exit $LASTEXITCODE
}

Write-Host "Mode questions (pas de debug_odoo_defaults.json, ou -Interactive)." -ForegroundColor Yellow
Write-Host "Python: $py" -ForegroundColor Cyan
$base = Read-Host "URL de base Odoo (ex. https://xxx.odoo.com)"
$report = Read-Host "URL complete du rapport (barre d'adresse)"
$aname = Read-Host "Nom ou code du compte analytique (comme dans Odoo, ex. Aliments PP)"
$d1 = Read-Host "Date debut YYYY-MM-DD"
$d2 = Read-Host "Date fin YYYY-MM-DD"

if ([string]::IsNullOrWhiteSpace($base) -or [string]::IsNullOrWhiteSpace($report)) {
    Write-Host "URL vide." -ForegroundColor Red
    exit 1
}
if ([string]::IsNullOrWhiteSpace($aname)) {
    Write-Host "Nom analytique vide." -ForegroundColor Red
    exit 1
}

& $py "capture_odoo_report_view.py" "--base-url" $base "--report-url" $report
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py "odoo_pl_debug_bundle.py" "--analytic-name" $aname "--date-from" $d1 "--date-to" $d2
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$out = Join-Path $PSScriptRoot "debug_pl_bundle.json"
Write-Host ""
Write-Host "TERMINE : $out" -ForegroundColor Green
Start-Process explorer.exe "/select,`"$out`""
