@echo off
REM Definit PY_EXE : Python du dossier .venv a la racine du projet, sinon "python" du PATH.
set "PY_EXE=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=python"
