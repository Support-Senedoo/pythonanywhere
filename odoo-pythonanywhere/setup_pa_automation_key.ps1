# Crée une clé SSH SANS phrase secrète, réservée à PythonAnywhere + Cursor/agent/MCP.
# Comme ça : deploy_pa.ps1 et l’outil MCP peuvent se connecter sans interaction.
#
# Sécurité : clé faible si quelqu’un vole le fichier — garde-la sur ta machine, ne la commite pas.
#
# Une fois la clé créée :
#   .\install_pa_ssh_key.ps1 -IdentityFile "$env:USERPROFILE\.ssh\id_ed25519_pa_cursor"
#   (mot de passe compte PythonAnywhere UNE dernière fois pour ajouter la .pub sur PA)
#
# Usage :
#   .\setup_pa_automation_key.ps1
# Régénérer (écrase l’ancienne) :
#   .\setup_pa_automation_key.ps1 -Force

param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$dir = Join-Path $env:USERPROFILE ".ssh"
$key = Join-Path $dir "id_ed25519_pa_cursor"
$pub = "${key}.pub"

if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

if ((Test-Path $key) -and -not $Force) {
    Write-Host ">>> Existe déjà : $key"
    Write-Host ">>> Pour régénérer : .\setup_pa_automation_key.ps1 -Force"
    Write-Host ""
    Get-Content -Raw $pub
    exit 0
}

if ((Test-Path $key) -and $Force) {
    Remove-Item -LiteralPath $key, $pub -Force -ErrorAction SilentlyContinue
}

Write-Host ">>> Génération (sans phrase secrète) : $key"
& ssh-keygen.exe -t ed25519 -f $key -N '""' -C "pa-cursor-automation"
if ($LASTEXITCODE -ne 0) {
    Write-Error "ssh-keygen a échoué (code $LASTEXITCODE)."
}

Write-Host ""
Write-Host ">>> Clé publique (déjà enregistrée sur PA après install_pa_ssh_key) :"
Write-Host ""
Get-Content -Raw $pub
Write-Host ""
Write-Host ">>> Prochaine étape obligatoire (une fois) :"
Write-Host "    .\install_pa_ssh_key.ps1 -IdentityFile `"$key`""
Write-Host ""
Write-Host ">>> Puis redémarrer Cursor ; l’agent utilisera cette clé pour deploy_pa + MCP."
Write-Host ""
