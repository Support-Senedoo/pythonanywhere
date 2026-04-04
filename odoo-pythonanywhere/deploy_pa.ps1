# Déploie la toolbox Flask sur PythonAnywhere via SSH (clé privée locale).
# À lancer dans PowerShell sur VOTRE PC (pas uniquement via un agent distant sans accès SSH).
#
# Si SSH/scp demande encore le mot de passe PA à chaque fois : une fois seulement
#   .\install_pa_ssh_key.ps1
#
# Pour réutiliser la même cible (alias « pa ») : fusionner ssh_config.pythonanywhere.example
# dans %USERPROFILE%\.ssh\config puis : .\deploy_pa.ps1 -UserHost pa
#
# Usage (depuis ce dossier odoo-pythonanywhere) :
#   .\deploy_pa.ps1
# Autre clé :
#   .\deploy_pa.ps1 -IdentityFile "C:\Users\patri\.ssh\autre_cle"

param(
    [string]$IdentityFile = (Join-Path $env:USERPROFILE ".ssh\id_ed25519"),
    [string]$UserHost = "senedoo@ssh.pythonanywhere.com"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $IdentityFile)) {
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

Write-Host ">>> Exécution sur PA..."
& ssh.exe @sshOpts $UserHost "chmod +x ~/${remoteName} && bash ~/${remoteName}; ec=`$?; rm -f ~/${remoteName}; exit `$ec"
$code = $LASTEXITCODE
Write-Host ">>> Terminé (code $code)."
exit $code
