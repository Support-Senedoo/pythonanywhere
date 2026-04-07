@echo off
REM Assemble capture UI (odoo_report_capture.json) + calcul API -> debug_pl_bundle.json
REM Usage : pl_debug_odoo.cmd ANALYTIC_ID DATE_FROM DATE_TO
REM Exemple : pl_debug_odoo.cmd 42 2026-01-01 2026-04-06
REM Prérequis : .env avec ODOO_* ; capture navigateur déjà effectuée (capture_odoo_report_view.py)
cd /d "%~dp0"
call "%~dp0set_python_venv.cmd"
if "%~3"=="" (
  echo Usage: pl_debug_odoo.cmd ANALYTIC_ID DATE_FROM DATE_TO
  exit /b 1
)
"%PY_EXE%" odoo_pl_debug_bundle.py --analytic-id %1 --date-from %2 --date-to %3 %4 %5 %6 %7 %8 %9
if errorlevel 1 exit /b %errorlevel%
echo.
echo Joindre debug_pl_bundle.json a la conversation assistant.
