# Enregistre ta clé publique sur PythonAnywhere (UNE fois).
# Utilise uniquement le mot de passe du compte PA — pas les clés locales — pour éviter
# les échecs "publickey" avant même la demande de mot de passe.
#
# Usage (dans ce dossier) :
#   .\install_pa_ssh_key.ps1
#   .\install_pa_ssh_key.ps1 -IdentityFile "C:\Users\toi\.ssh\id_ed25519"

param(
    [string]$IdentityFile = (Join-Path $env:USERPROFILE ".ssh\id_ed25519"),
    [string]$UserHost = "senedoo@ssh.pythonanywhere.com"
)

$ErrorActionPreference = "Stop"
$pub = "${IdentityFile}.pub"
if (-not (Test-Path $pub)) {
    Write-Error "Fichier manquant : $pub`nCrée une clé : ssh-keygen -t ed25519 -f `"$IdentityFile`""
}

$raw = Get-Content -Raw -LiteralPath $pub
$line = ($raw -replace "`r`n", "`n" -replace "`r", "`n").Trim()
if (-not $line) {
    Write-Error "Clé publique vide dans $pub"
}
if ($line -notmatch '^(ssh-(ed25519|rsa|ecdsa|dss)|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)') {
    Write-Error "Contenu inattendu dans $pub (clé OpenSSH attendue, une seule ligne)."
}

$tmp = Join-Path $env:TEMP "pa_pubkey_$PID.txt"
[System.IO.File]::WriteAllText($tmp, $line + "`n", [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host ">>> Mot de passe PythonAnywhere demandé UNE fois (connexion sans essai de clés locales)."
Write-Host ">>> Compte : $UserHost"
Write-Host ""

$sshOpts = @(
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "PubkeyAuthentication=no"
)
$remote = 'mkdir -p .ssh && chmod 700 .ssh && umask 077 && cat >> .ssh/authorized_keys && chmod 600 .ssh/authorized_keys'

try {
    Get-Content -Raw -LiteralPath $tmp | & ssh.exe @sshOpts $UserHost $remote
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ssh a échoué (code $LASTEXITCODE)."
    }
} finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host ">>> Terminé. Lance ensuite : .\deploy_pa.ps1"
Write-Host "    (si la clé privée n'a pas de phrase secrète, plus aucune saisie compte PA)."
Write-Host ""
