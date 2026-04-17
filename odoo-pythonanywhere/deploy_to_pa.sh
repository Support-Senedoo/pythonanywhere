#!/usr/bin/env bash
# Publie sur PythonAnywhere depuis Mac/Linux (meme flux que deploy_pa.ps1 : git push, scp deploy_pa.sh, ssh bash).
# Usage : ./deploy_to_pa.sh
#         ./deploy_to_pa.sh -SkipGitPush
# Cle : ~/.ssh/id_ed25519_pa_cursor si presente, sinon ~/.ssh/id_ed25519
#       DEPLOY_PA_IDENTITY=/chemin/cle pour forcer
# Cible SSH : DEPLOY_PA_SSH (defaut senedoo@ssh.pythonanywhere.com). EU : senedoo@ssh.eu.pythonanywhere.com
#
# OpenSSH 7.6+ : StrictHostKeyChecking=accept-new (evite "Host key verification failed" sans ssh-keyscan manuel).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SRC="${SCRIPT_DIR}/deploy_pa.sh"
REMOTE_SCRIPT="deploy_pa_run.sh"

if [[ ! -f "$DEPLOY_SRC" ]]; then
  echo "Fichier manquant : $DEPLOY_SRC" >&2
  exit 1
fi

IDENT="${DEPLOY_PA_IDENTITY:-}"
if [[ -z "$IDENT" ]]; then
  if [[ -f "${HOME}/.ssh/id_ed25519_pa_cursor" ]]; then
    IDENT="${HOME}/.ssh/id_ed25519_pa_cursor"
  else
    IDENT="${HOME}/.ssh/id_ed25519"
  fi
fi

USERHOST="${DEPLOY_PA_SSH:-senedoo@ssh.pythonanywhere.com}"

SKIP_PUSH=0
for arg in "$@"; do
  if [[ "$arg" == "-SkipGitPush" || "$arg" == "--skip-git-push" ]]; then
    SKIP_PUSH=1
  fi
done

if [[ ! -f "$IDENT" ]]; then
  echo "Cle SSH introuvable : $IDENT" >&2
  echo "Creer la cle (ex. setup_pa_automation_key.ps1 sur Windows) ou DEPLOY_PA_IDENTITY=..." >&2
  exit 1
fi

SSH_OPTS=(
  -i "$IDENT"
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=accept-new
  -o BatchMode=yes
)

echo ">>> Cle : $IDENT"
echo ">>> Cible : $USERHOST"

if [[ "$SKIP_PUSH" -eq 0 ]]; then
  GIT_TOP="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -n "$GIT_TOP" ]]; then
    echo ">>> Depot Git : $GIT_TOP"
    if [[ -n "$(git -C "$GIT_TOP" status --porcelain 2>/dev/null || true)" ]]; then
      echo ">>> ATTENTION : modifications non committees ne seront pas poussees. Commit puis relancer." >&2
    fi
    echo ">>> git push..."
    git -C "$GIT_TOP" push
  else
    echo ">>> Pas de depot Git detecte : push ignore." >&2
  fi
else
  echo ">>> SkipGitPush."
fi

TMP="$(mktemp "${TMPDIR:-/tmp}/deploy_pa_upload.XXXXXX")"
trap 'rm -f "$TMP"' EXIT
tr -d '\r' <"$DEPLOY_SRC" >"$TMP"

echo ">>> Envoi du script sur PA (scp)..."
scp "${SSH_OPTS[@]}" "$TMP" "${USERHOST}:~/${REMOTE_SCRIPT}"

echo ">>> Sur PA : pull + pip + reload (si token)..."
ssh "${SSH_OPTS[@]}" "$USERHOST" "chmod +x ~/${REMOTE_SCRIPT} && bash ~/${REMOTE_SCRIPT}; ec=\$?; rm -f ~/${REMOTE_SCRIPT}; exit \$ec"
code=$?
echo ">>> Termine (code $code)."
exit "$code"
