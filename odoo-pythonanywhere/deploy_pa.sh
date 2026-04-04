#!/usr/bin/env bash
# À lancer sur PythonAnywhere (Bash) OU via deploy_pa.ps1 (scp + ssh) — pas de tube stdin vers ssh.
# À chaque exécution : git pull (si dépôt déjà cloné) pour refléter les commits poussés sur GitHub.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Support-Senedoo/pythonanywhere.git}"
TARGET="${HOME}/pythonanywhere"
APP_DIR="${TARGET}/odoo-pythonanywhere"

# Token API PA : ne jamais commiter. SSH non interactif ne charge pas toujours .bashrc → fichier home dédié.
PA_TOKEN_FILE="${HOME}/.pythonanywhere_api_token"
if [[ -z "${PYTHONANYWHERE_API_TOKEN:-}" ]] && [[ -f "${PA_TOKEN_FILE}" ]]; then
  PYTHONANYWHERE_API_TOKEN="$(head -n 1 "${PA_TOKEN_FILE}" | tr -d '\r\n')"
  export PYTHONANYWHERE_API_TOKEN
fi
# Compte Europe : une ligne https://eu.pythonanywhere.com (optionnel, sinon www).
PA_API_HOST_FILE="${HOME}/.pythonanywhere_api_host"
if [[ -z "${PYTHONANYWHERE_API_HOST:-}" ]] && [[ -f "${PA_API_HOST_FILE}" ]]; then
  PYTHONANYWHERE_API_HOST="$(head -n 1 "${PA_API_HOST_FILE}" | tr -d '\r\n')"
  export PYTHONANYWHERE_API_HOST
fi

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

# Reload Web : une seule fois à configurer sur PA — fichier ~/.pythonanywhere_api_token (token « Account → API »).
# Compte EU : fichier ~/.pythonanywhere_api_host avec une ligne https://eu.pythonanywhere.com
if [[ -n "${PYTHONANYWHERE_API_TOKEN:-}" ]]; then
  PA_USER="${PYTHONANYWHERE_API_USER:-${USER}}"
  PA_HOST="${PYTHONANYWHERE_WEBAPP_HOST:-${PA_USER}.pythonanywhere.com}"
  PA_API_BASE="${PYTHONANYWHERE_API_HOST:-https://www.pythonanywhere.com}"
  echo ">>> Reload du site Web (API PythonAnywhere) : ${PA_HOST}"
  if curl -fsS -X POST \
    "${PA_API_BASE}/api/v0/user/${PA_USER}/webapps/${PA_HOST}/reload/" \
    -H "Authorization: Token ${PYTHONANYWHERE_API_TOKEN}" \
    -H "Content-Length: 0"; then
    echo ""
    echo ">>> OK — le site a été rechargé, la nouvelle version est active."
  else
    echo "" >&2
    echo ">>> ECHEC reload API — ouvrez l’onglet Web sur pythonanywhere.com et cliquez le bouton vert « Reload »." >&2
  fi
else
  echo ">>> Pas de fichier ~/.pythonanywhere_api_token (ni variable PYTHONANYWHERE_API_TOKEN)."
  echo ">>> ACTION MANUELLE : onglet Web PythonAnywhere → bouton vert « Reload » pour prendre le nouveau code."
fi

echo ""
echo "=== OK (pull + pip) ==="
echo "WSGI attendu : ${APP_DIR}/pythonanywhere_wsgi.py"
echo "Hors Git sur PA : toolbox_users.json, toolbox_clients.json, variables Web (TOOLBOX_SECRET_KEY, …)"
