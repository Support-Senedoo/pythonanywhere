@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0set_python_venv.cmd"

cls
echo.
echo ============================================================
echo   CAPTURE + FICHIER POUR CURSOR
echo ============================================================
echo.
echo IMPORTANT :
echo   - Double-cliquez sur CE fichier dans l'Explorateur Windows
echo     (dossier odoo-pythonanywhere).
echo   - Si vous le lancez depuis le terminal Cursor/PowerShell, les
echo     questions peuvent ne PAS s'afficher : dans ce cas, utilisez
echo     le fichier  CAPTURE_ET_ENVOYER_PS.ps1  a la place.
echo.
echo Python utilise : %PY_EXE%
echo.

if not exist ".env" (
  echo ERREUR : fichier .env absent dans ce dossier.
  echo Creez-le avec ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD
  echo (voir toolbox-env-exemple.txt)
  pause
  exit /b 1
)

if not exist "odoo_browser_state.json" (
  echo ERREUR : pas encore de session Odoo.
  echo Lancez d'abord CONNEXION_ODOO_UNE_FOIS.cmd (une seule fois).
  pause
  exit /b 1
)

echo --- URL de base Odoo (ex. https://la-ripaille-presences.odoo.com)
set /p OURL="> "
if "%OURL%"=="" (
  echo ERREUR : URL vide.
  pause
  exit /b 1
)

echo.
echo --- URL COMPLETE du rapport (barre d'adresse du navigateur, Ctrl+C puis collez ici)
set /p RURL="> "
if "%RURL%"=="" (
  echo ERREUR : URL du rapport vide.
  pause
  exit /b 1
)

echo.
echo --- Nom ou CODE du compte analytique (comme dans Odoo, ex. Aliments PP — pas besoin de l'ID)
set /p ANAME="> "
if "%ANAME%"=="" (
  echo ERREUR : nom analytique vide.
  pause
  exit /b 1
)

echo.
echo --- Date DEBUT periode (YYYY-MM-DD)
set /p D1="> "
if "%D1%"=="" (
  echo ERREUR : date debut vide.
  pause
  exit /b 1
)

echo.
echo --- Date FIN periode (YYYY-MM-DD)
set /p D2="> "
if "%D2%"=="" (
  echo ERREUR : date fin vide.
  pause
  exit /b 1
)

echo.
echo Capture de la page Odoo (navigateur en arriere-plan si pas --headless)...
"%PY_EXE%" capture_odoo_report_view.py --base-url "%OURL%" --report-url "%RURL%"
if errorlevel 1 (
  echo.
  echo ERREUR pendant la capture. Verifiez l'URL et que Playwright est installe :
  echo   INSTALLER_PLAYWRIGHT.cmd
  pause
  exit /b 1
)

echo.
echo Calcul API Odoo + comparaison...
"%PY_EXE%" odoo_pl_debug_bundle.py --analytic-name "%ANAME%" --date-from %D1% --date-to %D2%
if errorlevel 1 (
  echo.
  echo ERREUR pendant le calcul API. Verifiez le fichier .env et les dates.
  pause
  exit /b 1
)

set "OUT=%CD%\debug_pl_bundle.json"
if not exist "debug_pl_bundle.json" (
  echo ERREUR : debug_pl_bundle.json non cree.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   TERMINE
echo ============================================================
echo.
echo FICHIER A ENVOYER DANS CURSOR (copie du chemin ci-dessous) :
echo   %OUT%
echo.
start "" explorer /select,"%OUT%"
echo Une fenetre Explorateur s'ouvre sur le fichier.
echo.
pause
