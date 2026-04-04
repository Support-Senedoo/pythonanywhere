# Déploie la toolbox Flask sur PythonAnywhere via SSH (clé privée locale).
# À lancer dans PowerShell sur VOTRE PC (pas uniquement via un agent distant sans accès SSH).
#
# Après chaque modification du code : commit + push sur GitHub, puis lancer ce script.
# Sur le serveur, deploy_pa.sh exécute systématiquement « git pull » dans le clone PA
# (alignement sur la branche distante), puis pip et vous rappelle de faire « Reload » Web.
#
# Si SSH/scp demande encore le mot de passe PA à chaque fois : une fois seulement
#   .\install_pa_ssh_key.ps1
#
# Pour réutiliser la même cible (alias « pa ») : fusionner ssh_config.pythonanywhere.example
# dans %USERPROFILE%\.ssh\config puis : .\deploy_pa.ps1 -UserHost pa
#
# Clé sans phrase (agent / MCP) : exécuter une fois  .\setup_pa_automation_key.ps1
# puis  .\install_pa_ssh_key.ps1 -IdentityFile "$env:USERPROFILE\.ssh\id_ed25519_pa_cursor"
# Si ce fichier existe, il est utilisé automatiquement à la place de id_ed25519.
#
# Usage (depuis ce dossier odoo-pythonanywhere) :
#   .\deploy_pa.ps1
# Forcer ta clé personnelle :
#   .\deploy_pa.ps1 -IdentityFile "C:\Users\patri\.ssh\id_ed25519"

param(
    [string]$IdentityFile,
    [string]$UserHost = "senedoo@ssh.pythonanywhere.com"
)

$ErrorActionPreference = "Stop"
$cursorKey = Join-Path $env:USERPROFILE ".ssh\id_ed25519_pa_cursor"
if (-not $PSBoundParameters.ContainsKey("IdentityFile") -or [string]::IsNullOrWhiteSpace($IdentityFile)) {
    if (Test-Path -LiteralPath $cursorKey) {
        $IdentityFile = $cursorKey
    } else {
        $IdentityFile = Join-Path $env:USERPROFILE ".ssh\id_ed25519"
    }
}
if (-not (Test-Path -LiteralPath $IdentityFile)) {
    Write-Error "Clé introuvable : $IdentityFile"
}
$deploySh = Join-Path $PSScriptRoot "deploy_pa.sh"
if (-not (Test-Path $deploySh)) {
    Write-Error "Fichier manquant : $deploySh"
}

# IdentitiesOnly : n’essaie que cette clé (évite trop d’échecs publickey avec plusieurs clés).
$sshOpts = @(
    "-i", $IdentityFile,
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "IdentitiesOnly=yes"
)
Write-Host ">>> Clé : $IdentityFile"
Write-Host ">>> Cible : $UserHost"

# Éviter Get-Content | ssh (conflit stdin si phrase secrète ou certains clients).
# Forcer LF : CRLF Windows casse bash (ex. set -o pipefail -> "invalid option name").
$remoteName = "deploy_pa_run.sh"
$tmpUnix = Join-Path $env:TEMP "deploy_pa_unix_$PID.sh"
$raw = Get-Content -Raw -LiteralPath $deploySh
$unix = $raw -replace "`r`n", "`n" -replace "`r", "`n"
[System.IO.File]::WriteAllText($tmpUnix, $unix, [System.Text.UTF8Encoding]::new($false))

Write-Host ">>> Copie du script sur PA..."
try {
    & scp.exe @sshOpts $tmpUnix "${UserHost}:~/${remoteName}"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "scp a échoué (exit $LASTEXITCODE)."
    }
} finally {
    Remove-Item -LiteralPath $tmpUnix -Force -ErrorAction SilentlyContinue
}

Write-Host ">>> Exécution sur PA (git pull + pip dans le clone)..."
Write-Host "    Vérifiez que vos commits sont bien poussés sur GitHub avant de compter sur la mise à jour."
& ssh.exe @sshOpts $UserHost "chmod +x ~/${remoteName} && bash ~/${remoteName}; ec=`$?; rm -f ~/${remoteName}; exit `$ec"
$code = $LASTEXITCODE
Write-Host ">>> Terminé (code $code)."
exit $code
