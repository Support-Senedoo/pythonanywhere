#!/usr/bin/env bash
# Démarre la toolbox Flask en local (Mac / Linux).
# Prérequis : Python 3.9+ avec venv.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if ! command -v "$PY" &>/dev/null; then
  echo "Erreur : interpreteur introuvable ($PY). Definir PYTHON=/chemin/vers/python3" >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo ">>> Creation du venv (.venv) avec $PY"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo ">>> pip install -r requirements.txt"
pip install -q -r requirements.txt

if [[ ! -f toolbox_users.json ]] && [[ -f toolbox_users.example.json ]]; then
  echo ">>> Astuce : copier toolbox_users.example.json -> toolbox_users.json pour les comptes fichier."
  echo "    Sinon connexion demo (si TOOLBOX_DISABLE_DEV_LOGIN non defini) : support@senedoo.com / 2026@Senedoo (staff)"
fi

export FLASK_APP=web_app:create_app
export FLASK_DEBUG="${FLASK_DEBUG:-1}"
export TOOLBOX_JINJA_NO_CACHE="${TOOLBOX_JINJA_NO_CACHE:-1}"
PORT="${PORT:-5000}"

echo ">>> http://127.0.0.1:${PORT}/  (Ctrl+C pour arreter)"
exec flask run --host 127.0.0.1 --port "$PORT"
