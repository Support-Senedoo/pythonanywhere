#!/usr/bin/env bash
# Configure le Mac pour que « git push origin master » fonctionne sans mot de passe
# (Cursor / agent / terminal), via une clé SSH dédiée GitHub — distincte de la clé PA.
#
# Usage : depuis n'importe où
#   bash odoo-pythonanywhere/scripts/setup_github_push_mac.sh
#
# Une seule action manuelle sur GitHub (une fois) :
#   Dépôt → Settings → Deploy keys → Add deploy key
#   Title : ex. « Mac Cursor Senedoo »
#   Key   : coller la ligne ssh-ed25519 … affichée ci-dessous
#   Cocher « Allow write access » (sinon le push sera refusé).
#
# Ne jamais committer la clé privée (~/.ssh/id_ed25519_github_senedoo).

set -euo pipefail

KEY="${HOME}/.ssh/id_ed25519_github_senedoo"
REPO_URL_SSH="git@github.com:Support-Senedoo/pythonanywhere.git"

ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "Erreur : lance ce script depuis le clone Git (dossier contenant .git)." >&2
  exit 1
fi

mkdir -p "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh" 2>/dev/null || true

if [[ ! -f "${KEY}" ]]; then
  echo ">>> Création de ${KEY} (sans passphrase)…"
  ssh-keygen -t ed25519 -f "${KEY}" -N "" -C "cursor-toolbox-Support-Senedoo-pythonanywhere"
  chmod 600 "${KEY}"
else
  echo ">>> Clé déjà présente : ${KEY}"
fi

CFG="${HOME}/.ssh/config"
MARK="id_ed25519_github_senedoo"
if [[ -f "${CFG}" ]] && grep -q "${MARK}" "${CFG}" 2>/dev/null; then
  echo ">>> Bloc Host github.com déjà présent dans ${CFG}"
else
  echo ">>> Ajout du bloc github.com dans ${CFG}"
  cat >> "${CFG}" <<EOF

# Senedoo — push GitHub sans mot de passe (deploy key avec « Allow write access »)
Host github.com
  HostName github.com
  User git
  IdentityFile ${KEY}
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
  chmod 600 "${CFG}" 2>/dev/null || true
fi

ssh-keyscan -t ed25519 github.com 2>/dev/null | sort -u >> "${HOME}/.ssh/known_hosts" 2>/dev/null || true

echo ">>> Remote origin → SSH"
git -C "${ROOT}" remote set-url origin "${REPO_URL_SSH}"

echo ""
echo "=== Collez cette clé PUBLIQUE sur GitHub (Deploy key + Allow write access) ==="
echo "    https://github.com/Support-Senedoo/pythonanywhere/settings/keys"
echo ""
cat "${KEY}.pub"
echo ""
echo "=== Test après enregistrement sur GitHub ==="
echo "    GIT_SSH_COMMAND=\"ssh -o BatchMode=yes\" git -C \"${ROOT}\" ls-remote origin HEAD"
