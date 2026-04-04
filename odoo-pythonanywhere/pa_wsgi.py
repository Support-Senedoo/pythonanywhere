"""
Point d'entrée WSGI recommandé pour PythonAnywhere.

Onglet Web > fichier WSGI : chemin absolu vers ce fichier dans le clone Git, ex.
  /home/senedoo/pythonanywhere/odoo-pythonanywhere/pa_wsgi.py
(ne pas utiliser un ancien dossier « odoo-pythonanywhere » hors du clone : le git pull ne mettrait pas ce code à jour).

Variables d'environnement (onglet Web ou en tête de ce fichier avec os.environ.setdefault) :
  TOOLBOX_SECRET_KEY   — obligatoire en production (clé longue aléatoire)
  TOOLBOX_USERS_PATH   — optionnel, défaut : toolbox_users.json à la racine du projet
  TOOLBOX_CLIENTS_PATH — optionnel, défaut : toolbox_clients.json

Copier toolbox_users.example.json -> toolbox_users.json et toolbox_clients.example.json -> toolbox_clients.json
puis éditer (ne pas commiter les fichiers réels).
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Décommenter / adapter sur PythonAnywhere si besoin :
# os.environ.setdefault("TOOLBOX_SECRET_KEY", "changez-moi-longue-chaine-aleatoire")
# os.environ.setdefault("TOOLBOX_USERS_PATH", os.path.join(_HERE, "toolbox_users.json"))
# os.environ.setdefault("TOOLBOX_CLIENTS_PATH", os.path.join(_HERE, "toolbox_clients.json"))

from web_app import create_app

application = create_app()
