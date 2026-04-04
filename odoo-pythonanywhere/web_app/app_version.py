"""Version de la toolbox affichée dans l’interface (surcharge possible par variables d’environnement sur PA)."""
from __future__ import annotations

import os

# À incrémenter lors des livraisons visibles pour les utilisateurs.
_DEFAULT_VERSION = "1.3.2"
_DEFAULT_DATE = "2026-04-04"


def _version_from_env(raw: str | None, default: str) -> str:
    """PA : une erreur fréquente est TOOLBOX_APP_VERSION=1 (seul) → affichage « 1 ». On exige au moins un point (ex. 1.3.2)."""
    v = (raw or "").strip()
    if not v:
        return default
    if "." not in v:
        return default
    return v


TOOLBOX_APP_VERSION = _version_from_env(os.environ.get("TOOLBOX_APP_VERSION"), _DEFAULT_VERSION)
TOOLBOX_APP_DATE = (os.environ.get("TOOLBOX_APP_DATE") or _DEFAULT_DATE).strip() or _DEFAULT_DATE
TOOLBOX_APP_LABEL = (os.environ.get("TOOLBOX_APP_LABEL") or "Toolbox Senedoo").strip() or "Toolbox Senedoo"
TOOLBOX_APP_AUTHOR = (os.environ.get("TOOLBOX_APP_AUTHOR") or "Senedoo").strip() or "Senedoo"
