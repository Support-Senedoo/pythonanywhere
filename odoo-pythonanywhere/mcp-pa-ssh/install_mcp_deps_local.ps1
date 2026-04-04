# npm install sur disque LOCAL (évite TAR_ENTRY_ERROR / EBADF sur Google Drive « Mon Drive »).
#
# Usage (PowerShell) :
#   .\install_mcp_deps_local.ps1
# Autre cible :
#   .\install_mcp_deps_local.ps1 -Dest "D:\dev\mcp-pa-ssh"

param(
    [string]$Dest = "C:\tools\mcp-pa-ssh"
)

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

Write-Host ">>> Copie depuis : $src"
Write-Host ">>> Vers         : $Dest"

$files = @("package.json", "index.mjs", "INSTALL.txt")
foreach ($f in $files) {
    $p = Join-Path $src $f
    if (Test-Path $p) {
        Copy-Item -LiteralPath $p -Destination (Join-Path $Dest $f) -Force
    }
}

Push-Location $Dest
try {
    if (Test-Path "node_modules") {
        Write-Host ">>> Suppression d'un node_modules partiel/corrompu..."
        Remove-Item -Recurse -Force "node_modules"
    }
    Write-Host ">>> npm install..."
    npm install
    if ($LASTEXITCODE -ne 0) {
        throw "npm install a échoué (code $LASTEXITCODE)."
    }
} finally {
    Pop-Location
}

$argPath = ($Dest + "\index.mjs") -replace "\\", "/"
Write-Host ""
Write-Host ">>> OK. Dans %USERPROFILE%\.cursor\mcp.json (pythonanywhere-ssh), utiliser :"
Write-Host ('  "command": "C:\\Program Files\\nodejs\\node.exe"')
Write-Host ('  "args": [ "' + $argPath + '" ]')
Write-Host ""
Write-Host ">>> Puis redémarrer le serveur MCP (ou Cursor)."
Write-Host ""
