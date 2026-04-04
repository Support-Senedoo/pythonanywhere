@echo off
REM Senedoo — une seule action : commit (si besoin) + push + deploy PythonAnywhere
REM Double-clic sur ce fichier, ou : glisser-deposer dans cmd, ou : cmd /c "chemin\complet\publication-une-fois.cmd"
chcp 65001 >nul
setlocal EnableDelayedExpansion

cd /d "%~dp0"
for /f "delims=" %%i in ('git rev-parse --show-toplevel 2^>nul') do set "GITROOT=%%i"
if not defined GITROOT (
  echo [ERREUR] Ce dossier n'est pas dans un depot Git. Ouvrez publication-une-fois.cmd depuis odoo-pythonanywhere.
  pause
  exit /b 1
)

echo.
echo === 1/3 Git : enregistrer les changements ===
cd /d "!GITROOT!"
git add -A
git status -sb
git commit -m "Publication %date% %time%"
if errorlevel 1 echo (aucun nouveau commit — normal si rien n'a change)

echo.
echo === 2/3 Git : push vers origin ===
git push
if errorlevel 1 (
  echo [ERREUR] git push a echoue — corrigez puis relancez ce script.
  pause
  exit /b 1
)

echo.
echo === 3/3 PythonAnywhere : deploy_pa.ps1 ===
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy_pa.ps1"
set "EC=%ERRORLEVEL%"

echo.
if %EC% NEQ 0 ( echo [ATTENTION] Code sortie deploy : %EC% ) else ( echo [OK] Pipeline termine. )
pause
exit /b %EC%
