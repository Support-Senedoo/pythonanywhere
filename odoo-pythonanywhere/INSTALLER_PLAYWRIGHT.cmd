@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Installation de Playwright (navigateur pour capture Odoo)...
python -m pip install -r requirements-capture-browser.txt
if errorlevel 1 goto fin
python -m playwright install chromium
if errorlevel 1 goto fin
echo.
echo OK. Vous pouvez passer a l'etape 2 (CONNEXION_ODOO_UNE_FOIS.cmd).
:fin
pause
