#!/usr/bin/env bash
# À lancer sur PythonAnywhere (Bash) OU via deploy_pa.ps1 (scp + ssh) — pas de tube stdin vers ssh.
# À chaque exécution : git pull (si dépôt déjà cloné) pour refléter les commits poussés sur GitHub.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Support-Senedoo/pythonanywhere.git}"
TARGET="${HOME}/pythonanywhere"
APP_DIR="${TARGET}/odoo-pythonanywhere"

if [[ -d "${TARGET}/.git" ]]; then
  echo ">>> git pull dans ${TARGET} (mise à jour obligatoire après chaque push GitHub)"
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
echo "0) Code : git pull vient d’être exécuté — après une nouvelle modif, push puis relancer ce script."
echo "1) Onglet Web : fichier WSGI ="
echo "   ${APP_DIR}/pythonanywhere_wsgi.py"
echo "2) Variables (onglet Web) : TOOLBOX_SECRET_KEY + chemins si besoin"
echo "3) Fichiers sur le serveur (hors Git) : toolbox_users.json, toolbox_clients.json"
echo "4) Cliquer Reload sur le site web"
