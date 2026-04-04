# Raccourci : meme chose que odoo-pythonanywhere\deploy_pa.ps1
# Depuis la racine du depot :  .\deploy.ps1
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Passthrough
)
$ErrorActionPreference = "Stop"
$target = Join-Path $PSScriptRoot "odoo-pythonanywhere\deploy_pa.ps1"
if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "Missing: $target"
}
if ($null -ne $Passthrough -and $Passthrough.Count -gt 0) {
    & $target @Passthrough
} else {
    & $target
}
exit $LASTEXITCODE
