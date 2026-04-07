@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0set_python_venv.cmd"
echo Python utilise : %PY_EXE%
echo.
echo Collez l'URL de base de votre Odoo (exemple : https://monentreprise.odoo.com)
echo Puis ENTREE :
set /p OURL="> "
if "%OURL%"=="" (
  echo URL vide. Annule.
  pause
  exit /b 1
)
echo.
echo Navigateur va s'ouvrir : connectez-vous a Odoo.
echo Quand le menu principal est visible, revenez ICI et appuyez sur ENTREE.
echo.
"%PY_EXE%" capture_odoo_report_view.py --init --base-url "%OURL%"
echo.
echo Si tout va bien, session enregistree (odoo_browser_state.json).
echo Etape suivante quand vous voulez de l'aide : CAPTURE_ET_ENVOYER.cmd
pause
