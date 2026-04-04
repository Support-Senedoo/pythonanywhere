# Deploy Flask toolbox to PythonAnywhere via SSH (local private key).
# Run in PowerShell on YOUR PC (not only from a remote agent without SSH).
#
# Flow:
#   1) git push from repo root (so GitHub has latest commits);
#   2) on PA: deploy_pa.sh runs git fetch + pull --ff-only, then pip.
# Commit before run (uncommitted files are not pushed).
# To skip local push: -SkipGitPush
#
# If SSH/scp still asks PA password each time: run once
#   .\install_pa_ssh_key.ps1
#
# Reuse target (host alias "pa"): merge ssh_config.pythonanywhere.example
# into %USERPROFILE%\.ssh\config then: .\deploy_pa.ps1 -UserHost pa
#
# Key without passphrase (agent / MCP): run once .\setup_pa_automation_key.ps1
# then .\install_pa_ssh_key.ps1 -IdentityFile "$env:USERPROFILE\.ssh\id_ed25519_pa_cursor"
# If that file exists, it is used instead of id_ed25519.
#
# Usage (from this folder odoo-pythonanywhere):
#   .\deploy_pa.ps1
# Force your key:
#   .\deploy_pa.ps1 -IdentityFile "C:\Users\patri\.ssh\id_ed25519"
# No local push:
#   .\deploy_pa.ps1 -SkipGitPush
#
# NOTE: User-visible strings are ASCII-only so PowerShell 5.1 parses this file
# correctly when opened from Google Drive / paths where UTF-8 without BOM fails.

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

# IdentitiesOnly: use only this key (fewer publickey failures with many keys).
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
        Write-Host ">>> Git push (origin) so PythonAnywhere pull gets latest..."
        & git @("-C", $gitTop, "push")
        if ($LASTEXITCODE -ne 0) {
            Write-Error "git push failed (network, no upstream, or conflict). Fix or use -SkipGitPush."
        }
    } else {
        Write-Host ">>> No Git repo from $PSScriptRoot - push step skipped." -ForegroundColor DarkYellow
    }
} else {
    Write-Host ">>> SkipGitPush: no local git push."
}

# Avoid Get-Content | ssh (stdin issues with passphrase keys).
# Force LF: Windows CRLF breaks bash (e.g. set -o pipefail -> invalid option).
$remoteName = "deploy_pa_run.sh"
$tmpUnix = Join-Path $env:TEMP "deploy_pa_unix_$PID.sh"
$raw = Get-Content -Raw -LiteralPath $deploySh
$unix = $raw -replace "`r`n", "`n" -replace "`r", "`n"
[System.IO.File]::WriteAllText($tmpUnix, $unix, [System.Text.UTF8Encoding]::new($false))

Write-Host ">>> Uploading script to PA..."
try {
    & scp.exe @sshOpts $tmpUnix "${UserHost}:~/${remoteName}"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "scp failed (exit $LASTEXITCODE)."
    }
} finally {
    Remove-Item -LiteralPath $tmpUnix -Force -ErrorAction SilentlyContinue
}

Write-Host ">>> Running on PA (git fetch + pull + pip)..."
& ssh.exe @sshOpts $UserHost "chmod +x ~/${remoteName} && bash ~/${remoteName}; ec=`$?; rm -f ~/${remoteName}; exit `$ec"
$code = $LASTEXITCODE
Write-Host ">>> Done (exit code $code)."
exit $code
