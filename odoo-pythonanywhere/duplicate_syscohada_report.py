#!/usr/bin/env python3
"""
Duplique le rapport comptable « Compte de résultat (SYSCOHADA) » via l'API XML-RPC
(méthode account.report.copy).

Usage :
  python duplicate_syscohada_report.py
  python duplicate_syscohada_report.py --url https://eric-favre-facture.odoo.com --db eric-favre-facture -u login -p secret

Variables : ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD (ou fichier .env à côté du script)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

# Libellé UI selon langue / base : FR ou EN (SYSCOHADA P&L)
SOURCE_REPORT_NAMES = (
    "Compte de résultat (SYSCOHADA)",
    "Profit and Loss (SYSCOHADA)",
)
DEFAULT_NEW_NAME = "Compte de résultat (SYSCOHADA) — copie détaillé Senedoo"


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
    return models.execute_kw(db, uid, password, model, method, args, kwargs or {})


def connect(url: str, db: str, user: str, password: str) -> tuple[Any, int]:
    import xmlrpc.client

    base = url.rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(db, user, password, {})
    if not uid:
        raise RuntimeError(
            "Authentification Odoo refusee (verifier ODOO_DB, login, mot de passe ou cle API)."
        )
    models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object", allow_none=True)
    return models, int(uid)


def find_report_id(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> int:
    for name in SOURCE_REPORT_NAMES:
        ids = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "search",
            [[("name", "=", name)]],
        )
        if len(ids) == 1:
            return ids[0]

    # Bases en anglais : « Profit and Loss » plutôt que « Compte de résultat »
    ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "search",
        [
            [
                ("name", "ilike", "SYSCOHADA"),
                ("name", "not ilike", "Balance"),
            ]
        ],
    )
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise RuntimeError(
            "Aucun account.report P&L SYSCOHADA trouvé (essayé : "
            + ", ".join(SOURCE_REPORT_NAMES)
            + "). Vérifiez Comptabilité > Configuration > Rapports comptables."
        )
    recs = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [ids],
        {"fields": ["name", "id"]},
    )
    raise RuntimeError(
        "Plusieurs rapports correspondent ; précisez manuellement l'id. "
        f"Candidats : {recs}"
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Duplique le rapport SYSCOHADA (account.report.copy)")
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("-u", "--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument("-p", "--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)
    p.add_argument(
        "--new-name",
        default=DEFAULT_NEW_NAME,
        help="Nom du rapport dupliqué (défaut : %(default)s)",
    )
    args = p.parse_args()

    missing = [
        n
        for n, v in [
            ("ODOO_URL ou --url", args.url),
            ("ODOO_DB ou --db", args.db),
            ("ODOO_USER ou -u", args.user),
            ("ODOO_PASSWORD ou -p", args.password),
        ]
        if not v
    ]
    if missing:
        print("Paramètres manquants :", ", ".join(missing), file=sys.stderr)
        print(
            "Créez odoo-pythonanywhere/.env (voir .env.example) ou passez --url --db -u -p.",
            file=sys.stderr,
        )
        sys.exit(1)

    models, uid = connect(args.url, args.db, args.user, args.password)
    src_id = find_report_id(models, args.db, uid, args.password)
    new_id = execute_kw(
        models,
        args.db,
        uid,
        args.password,
        "account.report",
        "copy",
        [src_id],
        {},
    )
    if isinstance(new_id, (list, tuple)):
        new_id = new_id[0]
    execute_kw(
        models,
        args.db,
        uid,
        args.password,
        "account.report",
        "write",
        [[new_id], {"name": args.new_name}],
    )
    print("OK — rapport dupliqué.")
    src_name = execute_kw(
        models,
        args.db,
        uid,
        args.password,
        "account.report",
        "read",
        [[src_id]],
        {"fields": ["name"]},
    )[0]["name"]
    print(f"  Source id={src_id}  (« {src_name} »)")
    print(f"  Nouveau id={new_id}  nom=« {args.new_name} »")


if __name__ == "__main__":
    main()
