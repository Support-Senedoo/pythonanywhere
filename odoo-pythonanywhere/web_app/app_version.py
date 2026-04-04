"""Version de la toolbox affichée dans l’interface (surcharge possible par variables d’environnement sur PA)."""
from __future__ import annotations

import os

# À incrémenter lors des livraisons visibles pour les utilisateurs.
_DEFAULT_VERSION = "1.3.1"
_DEFAULT_DATE = "2026-04-04"

TOOLBOX_APP_VERSION = (os.environ.get("TOOLBOX_APP_VERSION") or _DEFAULT_VERSION).strip() or _DEFAULT_VERSION
TOOLBOX_APP_DATE = (os.environ.get("TOOLBOX_APP_DATE") or _DEFAULT_DATE).strip() or _DEFAULT_DATE
TOOLBOX_APP_LABEL = (os.environ.get("TOOLBOX_APP_LABEL") or "Toolbox Senedoo").strip() or "Toolbox Senedoo"
