@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0set_python_venv.cmd"
echo Installation de Playwright (navigateur pour capture Odoo)...
echo Python utilise : %PY_EXE%
echo.
"%PY_EXE%" -m pip install -r requirements-capture-browser.txt
if errorlevel 1 goto fin
"%PY_EXE%" -m playwright install chromium
if errorlevel 1 goto fin
echo.
echo OK. Vous pouvez passer a l'etape 2 (CONNEXION_ODOO_UNE_FOIS.cmd).
:fin
pause
