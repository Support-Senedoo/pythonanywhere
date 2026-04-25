#!/usr/bin/env python3
"""
Connexion à Odoo via l'API distante (XML-RPC : /xmlrpc/2/common et /xmlrpc/2/object).

Variables d'environnement (ou fichier .env à côté du script si python-dotenv est installé) :
  ODOO_URL       URL de base, ex. https://mon-odoo.example.com
  ODOO_DB        nom de la base PostgreSQL Odoo
  ODOO_USER      login utilisateur Odoo
  ODOO_PASSWORD  mot de passe ou clé API si activée sur le compte
"""
from __future__ import annotations

import argparse
import os
import sys
import xmlrpc.client
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
    load_dotenv()
except ImportError:
    pass


def get_connection(
    url: str,
    db: str,
    username: str,
    password: str,
) -> tuple[int, Any, Any]:
    """Authentifie et retourne (uid, proxy_common, proxy_object)."""
    base = url.rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(db, username, password, {})
    if not uid:
        raise RuntimeError("Authentification Odoo refusée (base, login ou mot de passe).")
    models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object", allow_none=True)
    return int(uid), common, models


def execute_kw(
    models: Any,
    db: str,
    uid: int,
    password: str,
    model: str,
    method: str,
    args: list[Any],
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Appelle model.method via execute_kw (API standard Odoo)."""
    return models.execute_kw(db, uid, password, model, method, args, kwargs or {})


def main() -> None:
    p = argparse.ArgumentParser(description="Test de connexion Odoo (XML-RPC)")
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument("--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)
    args = p.parse_args()

    missing = [n for n, v in [("ODOO_URL", args.url), ("ODOO_DB", args.db), ("ODOO_USER", args.user), ("ODOO_PASSWORD", args.password)] if not v]
    if missing:
        print("Paramètres manquants :", ", ".join(missing), file=sys.stderr)
        print("Utilise les arguments --url --db --user --password ou les variables d'environnement.", file=sys.stderr)
        sys.exit(1)

    uid, common, models = get_connection(args.url, args.db, args.user, args.password)
    ver = common.version()
    print("Connexion OK — uid =", uid)
    print("Version serveur :", ver.get("server_version", ver))
    n = execute_kw(models, args.db, uid, args.password, "res.partner", "search_count", [[]])
    print("Exemple API — nombre de partenaires (res.partner) :", n)


if __name__ == "__main__":
    main()
