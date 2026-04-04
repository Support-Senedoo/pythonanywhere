#!/usr/bin/env bash
# À lancer sur PythonAnywhere (Bash) OU via deploy_pa.ps1 (scp + ssh) — pas de tube stdin vers ssh.
# À chaque exécution : git pull (si dépôt déjà cloné) pour refléter les commits poussés sur GitHub.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Support-Senedoo/pythonanywhere.git}"
TARGET="${HOME}/pythonanywhere"
APP_DIR="${TARGET}/odoo-pythonanywhere"

if [[ -d "${TARGET}/.git" ]]; then
  echo ">>> git fetch + pull --ff-only dans ${TARGET}"
  git -C "${TARGET}" fetch origin
  git -C "${TARGET}" pull --ff-only
  echo ">>> HEAD actuel :"
  git -C "${TARGET}" log -1 --oneline
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

# Reload Web optionnel : token API PythonAnywhere (Account → API token), jamais dans Git.
# Sur PA (Bash) : export PYTHONANYWHERE_API_TOKEN='votre_token'
# Compte EU : définir aussi PYTHONANYWHERE_API_HOST=https://eu.pythonanywhere.com
if [[ -n "${PYTHONANYWHERE_API_TOKEN:-}" ]]; then
  PA_USER="${PYTHONANYWHERE_API_USER:-${USER}}"
  PA_HOST="${PYTHONANYWHERE_WEBAPP_HOST:-${PA_USER}.pythonanywhere.com}"
  PA_API_BASE="${PYTHONANYWHERE_API_HOST:-https://www.pythonanywhere.com}"
  echo ">>> Reload Web via API (${PA_HOST})..."
  if curl -fsS -X POST \
    "${PA_API_BASE}/api/v0/user/${PA_USER}/webapps/${PA_HOST}/reload/" \
    -H "Authorization: Token ${PYTHONANYWHERE_API_TOKEN}" \
    -H "Content-Length: 0"; then
    echo ""
    echo ">>> Reload API : OK"
  else
    echo "" >&2
    echo ">>> ATTENTION : Reload API a échoué (token, domaine ou hôte API). Rechargez à la main dans l’onglet Web." >&2
  fi
else
  echo ">>> Pas de PYTHONANYWHERE_API_TOKEN : pensez à cliquer Reload dans l’onglet Web."
fi

echo ""
echo "=== OK ==="
echo "0) Code : fetch + pull exécutés — depuis Windows, lancez deploy_pa.ps1 (push local puis ce script)."
echo "1) Onglet Web : fichier WSGI ="
echo "   ${APP_DIR}/pythonanywhere_wsgi.py"
echo "2) Variables (onglet Web) : TOOLBOX_SECRET_KEY + chemins si besoin"
echo "3) Fichiers sur le serveur (hors Git) : toolbox_users.json, toolbox_clients.json"
echo "4) Reload : automatique si PYTHONANYWHERE_API_TOKEN est défini sur PA, sinon bouton Reload Web"
