# Publier sur PythonAnywhere depuis votre PC : git push puis SSH qui lance deploy_pa.sh sur le serveur.
# Sur PA, deploy_pa.sh fait : git pull, pip, puis RELOAD WEB AUTOMATIQUE si ~/.pythonanywhere_api_token existe.
#
# Usage :  .\deploy_pa.ps1
# Sans push local (deja fait ailleurs) :  .\deploy_pa.ps1 -SkipGitPush
#
# Cle SSH : par defaut %USERPROFILE%\.ssh\id_ed25519_pa_cursor si present, sinon id_ed25519
#   .\deploy_pa.ps1 -IdentityFile "C:\Users\...\id_ed25519"
# Alias SSH :  .\deploy_pa.ps1 -UserHost pa
#
# NOTE: messages ASCII-only (PowerShell 5.1 + Google Drive).

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
    Write-Error "Key not found: $IdentityFile"
}
$deploySh = Join-Path $PSScriptRoot "deploy_pa.sh"
if (-not (Test-Path $deploySh)) {
    Write-Error "Missing file: $deploySh"
}

$sshOpts = @(
    "-i", $IdentityFile,
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "IdentitiesOnly=yes"
)
Write-Host ">>> Key: $IdentityFile"
Write-Host ">>> Target: $UserHost"

if (-not $SkipGitPush) {
    $gitTop = ""
    try {
        $gitTop = (& git @("-C", $PSScriptRoot, "rev-parse", "--show-toplevel") 2>$null)
        if ($gitTop) { $gitTop = $gitTop.Trim() }
    } catch {
        $gitTop = ""
    }
    if ($gitTop) {
        Write-Host ">>> Git repo: $gitTop"
        $dirty = ""
        try {
            $dirty = (& git @("-C", $gitTop, "status", "--porcelain") 2>$null)
        } catch {
            $dirty = ""
        }
        if ($dirty) {
            Write-Host ">>> WARNING: uncommitted changes will not be pushed. Commit then re-run." -ForegroundColor Yellow
        }
        Write-Host ">>> Git push (origin)..."
        & git @("-C", $gitTop, "push")
        if ($LASTEXITCODE -ne 0) {
            Write-Error "git push failed. Fix or use -SkipGitPush."
        }
    } else {
        Write-Host ">>> No Git repo - push skipped." -ForegroundColor DarkYellow
    }
} else {
    Write-Host ">>> SkipGitPush."
}

$remoteName = "deploy_pa_run.sh"
$tmpUnix = Join-Path $env:TEMP "deploy_pa_unix_$PID.sh"
$raw = Get-Content -Raw -LiteralPath $deploySh
$unix = $raw -replace "`r`n", "`n" -replace "`r", "`n"
[System.IO.File]::WriteAllText($tmpUnix, $unix, [System.Text.UTF8Encoding]::new($false))

Write-Host ">>> Upload deploy script to PA..."
try {
    & scp.exe @sshOpts $tmpUnix "${UserHost}:~/${remoteName}"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "scp failed (exit $LASTEXITCODE)."
    }
} finally {
    Remove-Item -LiteralPath $tmpUnix -Force -ErrorAction SilentlyContinue
}

Write-Host ">>> On PA: pull + pip + reload (if token configured on server)..."
& ssh.exe @sshOpts $UserHost "chmod +x ~/${remoteName} && bash ~/${remoteName}; ec=`$?; rm -f ~/${remoteName}; exit `$ec"
$code = $LASTEXITCODE
Write-Host ">>> Finished (exit code $code)."
exit $code
