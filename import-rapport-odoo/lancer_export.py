#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export interactif d'un rapport comptable vers un fichier JSON (base source).

  python lancer_export.py
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

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

from account_report_portable import cmd_export, connect  # noqa: E402


def _prompt(label: str, default: str | None = None) -> str:
    if default:
        s = input(f"{label} [{default}] : ").strip()
        return s if s else default
    while True:
        s = input(f"{label} : ").strip()
        if s:
            return s


def main() -> None:
    print("--- Export de rapport comptable Odoo vers JSON ---\n")

    default_url = os.environ.get("ODOO_URL", "").strip() or "https://votre-instance.odoo.com"
    url = _prompt("URL Odoo (sans slash final)", default_url)

    default_db = os.environ.get("ODOO_DB", "").strip()
    print(
        "\n  Nom exact de la base PostgreSQL (comme à la connexion Odoo).\n"
    )
    db = _prompt("Nom de la base", default_db or None)
    if not db:
        print("Erreur : nom de base obligatoire.", file=sys.stderr)
        sys.exit(1)

    default_user = os.environ.get("ODOO_USER", "").strip()
    user = _prompt("Identifiant", default_user or None)

    pw_env = os.environ.get("ODOO_PASSWORD", "").strip()
    if pw_env:
        use = input("Utiliser le mot de passe du fichier .env ? [O/n] : ").strip().lower()
        password = pw_env if use != "n" else getpass.getpass("Mot de passe ou clé API : ")
    else:
        password = getpass.getpass("Mot de passe ou clé API Odoo : ")

    rid_s = _prompt("Identifiant numérique du rapport (account.report), ex. 32", None)
    try:
        report_id = int(rid_s)
    except ValueError:
        print("Erreur : id invalide.", file=sys.stderr)
        sys.exit(1)

    here = Path(__file__).resolve().parent
    default_out = here / "rapport_export.json"
    out_s = _prompt("Fichier JSON de sortie", str(default_out))
    out_path = Path(out_s)

    print("\nConnexion...")
    models, uid = connect(url, db, user, password)
    print(f"  Connecté (uid={uid}). Export...\n")

    cmd_export(models, db, uid, password, report_id, out_path)
    print(f"\nCopiez ce fichier dans le même dossier sur une autre machine si besoin, puis utilisez lancer_import.py sur la base cible.")


if __name__ == "__main__":
    main()
