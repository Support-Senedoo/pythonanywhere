# Déploie la toolbox Flask sur PythonAnywhere via SSH (clé privée locale).
# À lancer dans PowerShell sur VOTRE PC (pas uniquement via un agent distant sans accès SSH).
#
# Enchaînement automatique :
#   1) git push depuis la racine du dépôt (pour que GitHub ait les derniers commits) ;
#   2) sur PA : deploy_pa.sh fait git fetch + pull --ff-only, puis pip.
# Pensez à committer avant de lancer le script (les fichiers non commités ne partent pas au push).
# Pour sauter l’étape push (réseau indisponible, dépôt en lecture seule) : -SkipGitPush
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
# Sans push local :
#   .\deploy_pa.ps1 -SkipGitPush

param(
    [string]$IdentityFile,
    [string]$UserHost = "senedoo@ssh.pythonanywhere.com",
    [switch]$SkipGitPush
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

if (-not $SkipGitPush) {
    $gitTop = ""
    try {
        $gitTop = (& git @("-C", $PSScriptRoot, "rev-parse", "--show-toplevel") 2>$null)
        if ($gitTop) { $gitTop = $gitTop.Trim() }
    } catch {
        $gitTop = ""
    }
    if ($gitTop) {
        Write-Host ">>> Git : dépôt $gitTop"
        $dirty = ""
        try {
            $dirty = (& git @("-C", $gitTop, "status", "--porcelain") 2>$null)
        } catch {
            $dirty = ""
        }
        if ($dirty) {
            Write-Host ">>> ATTENTION : modifications non commitées — elles ne seront pas poussées. Committez puis relancez." -ForegroundColor Yellow
        }
        Write-Host ">>> Git push (origin) pour que le pull sur PythonAnywhere récupère le dernier code..."
        & git @("-C", $gitTop, "push")
        if ($LASTEXITCODE -ne 0) {
            Write-Error "git push a échoué (réseau, branche sans upstream, ou conflit). Corrigez ou relancez avec -SkipGitPush."
        }
    } else {
        Write-Host ">>> Aucun dépôt Git détecté depuis $PSScriptRoot — étape push ignorée." -ForegroundColor DarkYellow
    }
} else {
    Write-Host ">>> SkipGitPush : pas de git push local."
}

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

Write-Host ">>> Exécution sur PA (git fetch + pull + pip)..."
& ssh.exe @sshOpts $UserHost "chmod +x ~/${remoteName} && bash ~/${remoteName}; ec=`$?; rm -f ~/${remoteName}; exit `$ec"
$code = $LASTEXITCODE
Write-Host ">>> Terminé (code $code)."
exit $code
