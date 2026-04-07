"""Version de la toolbox affichée dans l’interface (surcharge possible par variables d’environnement sur PA)."""
from __future__ import annotations

import os
from pathlib import Path

# Référence unique : à mettre à jour à chaque livraison utilisateur (nouvelle fonctionnalité ou correctif majeur).
# Convention suggérée (semver léger) :
#   - patch (1.3.x → 1.3.y) : correctifs sans changement de comportement visible ;
#   - minor (1.3.x → 1.4.0) : nouvelle fonctionnalité ou évolution d’écran / API toolbox ;
#   - adapter _DEFAULT_DATE au jour de la livraison (YYYY-MM-DD).
_DEFAULT_VERSION = "1.5.58"
_DEFAULT_DATE = "2026-04-06"

# Valeurs souvent mises par erreur dans l’onglet Web PA (ne reflètent pas la livraison réelle).
_IGNORE_TOOLBOX_APP_VERSION = frozenset({"1", "1.0", "1.0.0"})


def _version_from_env(raw: str | None, default: str) -> str:
    """PA : erreurs fréquentes TOOLBOX_APP_VERSION=1 ou =1.0.0 → mauvaise version affichée."""
    v = (raw or "").strip()
    if not v:
        return default
    if "." not in v:
        return default
    if v in _IGNORE_TOOLBOX_APP_VERSION:
        return default
    return v


TOOLBOX_APP_VERSION = _version_from_env(os.environ.get("TOOLBOX_APP_VERSION"), _DEFAULT_VERSION)
TOOLBOX_APP_DATE = (os.environ.get("TOOLBOX_APP_DATE") or _DEFAULT_DATE).strip() or _DEFAULT_DATE
TOOLBOX_APP_LABEL = (os.environ.get("TOOLBOX_APP_LABEL") or "Toolbox Senedoo").strip() or "Toolbox Senedoo"
TOOLBOX_APP_AUTHOR = (os.environ.get("TOOLBOX_APP_AUTHOR") or "Senedoo").strip() or "Senedoo"


def git_head_short() -> str:
    """Hash court du commit (lecture disque via git). Utile sur PA : après un git pull sans Reload Web, la « Version »
    ci-dessus peut rester figée en RAM alors que cette révision reflète le dépôt sur disque — incohérence = cliquer Reload."""
    try:
        import subprocess

        app_pkg = Path(__file__).resolve().parent.parent  # racine projet Flask (odoo-pythonanywhere)
        root = None
        for p in (app_pkg, app_pkg.parent):
            if (p / ".git").is_dir():
                root = p
                break
        if root is None:
            return "?"
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except OSError:
        pass
    return "?"
