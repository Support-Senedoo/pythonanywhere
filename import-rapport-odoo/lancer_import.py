#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Import interactif d'un rapport comptable (fichier JSON) vers une base Odoo via l'API.

Placez le fichier JSON dans ce dossier (ou indiquez un chemin complet), puis lancez :
  python lancer_import.py
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

# Permet d'importer account_report_portable depuis le dossier voisin du projet
_ROOT = Path(__file__).resolve().parent.parent
_PA = _ROOT / "odoo-pythonanywhere"
if str(_PA) not in sys.path:
    sys.path.insert(0, str(_PA))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
    load_dotenv(_PA / ".env")
except ImportError:
    pass

from account_report_portable import cmd_import, connect  # noqa: E402


def _prompt(label: str, default: str | None = None, required: bool = True) -> str:
    if default:
        s = input(f"{label} [{default}] : ").strip()
        return s if s else default
    while True:
        s = input(f"{label} : ").strip()
        if s:
            return s
        if not required:
            return ""
        print("  (valeur obligatoire)")


def main() -> None:
    print("--- Import de rapport comptable Odoo (JSON) ---\n")

    default_url = os.environ.get("ODOO_URL", "").strip() or "https://votre-instance.odoo.com"
    url = _prompt("URL Odoo (sans slash final)", default_url)

    default_db = os.environ.get("ODOO_DB", "").strip()
    print(
        "\n  Le nom de la base est celui affiché à la connexion Odoo "
        "(souvent proche du sous-domaine, ex. ma-societe pour ma-societe.odoo.com).\n"
    )
    db = _prompt("Nom exact de la base de données", default_db or None)
    if not db:
        print("Erreur : le nom de la base est obligatoire.", file=sys.stderr)
        sys.exit(1)

    default_user = os.environ.get("ODOO_USER", "").strip()
    user = _prompt("Identifiant (e-mail)", default_user or None)

    pw_env = os.environ.get("ODOO_PASSWORD", "").strip()
    if pw_env:
        use = input("Utiliser le mot de passe du fichier .env ? [O/n] : ").strip().lower()
        password = pw_env if use != "n" else getpass.getpass("Mot de passe ou clé API Odoo : ")
    else:
        password = getpass.getpass("Mot de passe ou clé API Odoo : ")
    if not password:
        print("Erreur : mot de passe vide.", file=sys.stderr)
        sys.exit(1)

    here = Path(__file__).resolve().parent
    json_candidates = sorted(here.glob("*.json"))
    default_json = ""
    if json_candidates:
        default_json = str(json_candidates[0])
        print(f"\n  Fichiers JSON trouvés dans ce dossier : {[p.name for p in json_candidates]}")

    json_path_s = _prompt(
        "Chemin du fichier JSON à importer",
        default_json or None,
    )
    json_path = Path(json_path_s)
    if not json_path.is_file():
        print(f"Erreur : fichier introuvable : {json_path}", file=sys.stderr)
        sys.exit(1)

    new_name = input(
        "\nNom du rapport une fois importé (Entrée = reprendre le nom du fichier JSON) : "
    ).strip() or None

    print("\nConnexion...")
    models, uid = connect(url, db, user, password)
    print(f"  Connecté (uid={uid}). Import en cours...\n")

    cmd_import(models, db, uid, password, json_path, new_name)

    print(
        "\nTerminé. Ouvrez Odoo : Comptabilité > Configuration > Rapports comptables "
        "pour voir le nouveau rapport."
    )


if __name__ == "__main__":
    main()
