@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".env" (
  echo ERREUR : fichier .env absent dans ce dossier.
  echo Creez-le avec ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD
  echo (voir toolbox-env-exemple.txt)
  pause
  exit /b 1
)

if not exist "odoo_browser_state.json" (
  echo ERREUR : pas encore de session Odoo.
  echo Lancez d'abord CONNEXION_ODOO_UNE_FOIS.cmd  ^(une seule fois^).
  pause
  exit /b 1
)

echo.
echo --- URL de base Odoo (meme que pour l'etape 2, ex. https://xxx.odoo.com)
set /p OURL="> "
echo.
echo --- URL COMPLETE du rapport (copiee depuis la barre d'adresse du navigateur Odoo)
set /p RURL="> "
echo.
echo --- ID du compte analytique / projet (nombre entier, comme dans la toolbox)
set /p AID="> "
echo.
echo --- Date DEBUT periode (YYYY-MM-DD), ex. 2026-01-01
set /p D1="> "
echo.
echo --- Date FIN periode (YYYY-MM-DD), ex. 2026-04-06
set /p D2="> "

echo.
echo Capture de l'ecran Odoo en cours...
python capture_odoo_report_view.py --base-url "%OURL%" --report-url "%RURL%"
if errorlevel 1 goto fin

echo.
echo Calcul API + comparaison...
python odoo_pl_debug_bundle.py --analytic-id %AID% --date-from %D1% --date-to %D2%
if errorlevel 1 goto fin

echo.
echo ============================================================
echo   TERMINE
echo   Envoyez le fichier  debug_pl_bundle.json  dans le chat Cursor.
echo ============================================================
:fin
pause
