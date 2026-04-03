"""
WSGI PythonAnywhere — application toolbox Flask (portails client + Senedoo).

Reprise / mise à jour du déploiement : voir DEPLOY_PYTHONANYWHERE.md à la racine de ce dossier.

Pour une config dédiée et commentaires détaillés, préférer `pa_wsgi.py`
(à référencer comme fichier WSGI dans l’onglet Web).

Variables utiles (onglet Web PythonAnywhere) :
  TOOLBOX_SECRET_KEY    — obligatoire en prod (chaîne longue aléatoire)
  TOOLBOX_USERS_PATH    — défaut : toolbox_users.json à la racine du projet
  TOOLBOX_CLIENTS_PATH  — défaut : toolbox_clients.json

Fichiers à créer sur le serveur (copier depuis *.example.json) :
  toolbox_users.json, toolbox_clients.json

Scripts CLI monobase : variables ODOO_* + config.py inchangés.
"""
from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from web_app import create_app

application = create_app()
