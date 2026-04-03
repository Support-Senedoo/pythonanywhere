#!/usr/bin/env bash
# À lancer sur PythonAnywhere (Bash) OU via : Get-Content deploy_pa.sh | ssh senedoo@ssh.pythonanywhere.com bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Support-Senedoo/pythonanywhere.git}"
TARGET="${HOME}/pythonanywhere"
APP_DIR="${TARGET}/odoo-pythonanywhere"

if [[ -d "${TARGET}/.git" ]]; then
  echo ">>> git pull dans ${TARGET}"
  git -C "${TARGET}" pull --ff-only
else
  echo ">>> git clone vers ${TARGET}"
  git clone "${REPO_URL}" "${TARGET}"
fi

cd "${APP_DIR}"

# Sur PA, aligner avec la version Python de l’onglet Web (souvent 3.10).
PY="${PYTHONANYWHERE_PYTHON:-python3.10}"
if ! command -v "${PY}" &>/dev/null; then
  PY="python3"
fi
echo ">>> pip (${PY}) install --user"
"${PY}" -m pip install --user -r requirements.txt

echo ""
echo "=== OK ==="
echo "1) Onglet Web : fichier WSGI ="
echo "   ${APP_DIR}/pythonanywhere_wsgi.py"
echo "2) Variables (onglet Web) : TOOLBOX_SECRET_KEY + chemins si besoin"
echo "3) Fichiers sur le serveur (hors Git) : toolbox_users.json, toolbox_clients.json"
echo "4) Cliquer Reload sur le site web"
