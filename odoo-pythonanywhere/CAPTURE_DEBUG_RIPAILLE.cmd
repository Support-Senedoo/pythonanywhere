@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0set_python_venv.cmd"
echo Python: %PY_EXE%
echo.
if not exist "debug_odoo_defaults.json" (
  echo Fichier debug_odoo_defaults.json absent.
  echo Copiez debug_odoo_defaults.example.json en debug_odoo_defaults.json
  echo puis renseignez report_url une fois ^(URL du rapport dans Odoo^).
  pause
  exit /b 1
)
"%PY_EXE%" run_debug_capture.py
if errorlevel 1 pause
pause
