#!/usr/bin/env python3
"""
1) Recherche tous les comptes « produits / charges » (types P&L Odoo 18).
2) Télécharge le PDF du rapport QWeb créé par create_qweb_report_via_api.py
   via la route HTTP /report/pdf/<report_name>/<ids> (session navigateur).

Prérequis : avoir exécuté create_qweb_report_via_api.py au moins une fois sur la base.

Usage :
  python export_pl_accounts_pdf.py
  python export_pl_accounts_pdf.py -o pl_comptes.pdf

Variables : ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Doit correspondre à create_qweb_report_via_api.py (ir.actions.report.report_name)
REPORT_NAME = "custom_pl_accounts.report_pl_accounts_api_document"

_PL_TYPES = (
    "income",
    "income_other",
    "expense",
    "expense_depreciation",
    "expense_direct_cost",
)


def connect_xmlrpc(url: str, db: str, user: str, password: str) -> tuple[Any, int, str, str]:
    import xmlrpc.client

    base = url.rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(db, user, password, {})
    if not uid:
        raise RuntimeError("Authentification refusée.")
    models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object", allow_none=True)
    return models, int(uid), db, password


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


def domain_pl_accounts(_models: Any, _db: str, _uid: int, _password: str, company_id: int | None) -> list:
    base = [("account_type", "in", list(_PL_TYPES))]
    if company_id is None:
        return base
    return [
        "&",
        *base,
        "|",
        ("company_ids", "=", False),
        ("company_ids", "in", [company_id]),
    ]


def search_pl_account_ids(
    models: Any,
    db: str,
    uid: int,
    password: str,
    company_id: int | None,
) -> list[int]:
    dom = domain_pl_accounts(models, db, uid, password, company_id)
    return execute_kw(models, db, uid, password, "account.account", "search", [dom], {"order": "code"})


def session_authenticate(base_url: str, db: str, login: str, password: str, opener: urllib.request.OpenerDirector) -> None:
    """Établit une session (cookies) comme le navigateur, pour /report/pdf/..."""
    url = base_url.rstrip("/") + "/web/session/authenticate"
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"db": db, "login": login, "password": password},
            "id": 1,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req, timeout=120) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    data = json.loads(body)
    if data.get("error"):
        raise RuntimeError(f"Session : {data['error']}")
    result = data.get("result")
    if not result or not result.get("uid"):
        raise RuntimeError("Échec session (uid manquant). Vérifie db / login / mot de passe.")


def download_report_pdf(
    base_url: str,
    db: str,
    login: str,
    password: str,
    doc_ids: list[int],
    report_name: str,
) -> bytes:
    if not doc_ids:
        raise RuntimeError("Aucun compte P&L trouvé : domaine vide.")

    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    session_authenticate(base_url, db, login, password, opener)

    ids_part = ",".join(str(i) for i in doc_ids)
    # Nom du rapport tel que dans ir.actions.report.report_name (avec points)
    path = f"/report/pdf/{urllib.parse.quote(report_name, safe='.')}/{ids_part}"
    pdf_url = base_url.rstrip("/") + path
    req = urllib.request.Request(pdf_url, method="GET")
    try:
        with opener.open(req, timeout=300) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"HTTP {e.code} lors du PDF : {body}") from e


def main() -> None:
    p = argparse.ArgumentParser(description="Export PDF comptes P&L via API + HTTP")
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument("--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)
    p.add_argument(
        "--company-id",
        type=int,
        default=None,
        help="ID res.company (sinon société de l'utilisateur connecté)",
    )
    p.add_argument(
        "-o",
        "--output",
        default="pl_comptes.pdf",
        help="Fichier PDF de sortie",
    )
    p.add_argument(
        "--report-name",
        default=REPORT_NAME,
        help="Champ report_name du rapport QWeb (défaut : celui du script create_qweb_report_via_api)",
    )
    args = p.parse_args()

    missing = [
        n
        for n, v in [
            ("ODOO_URL", args.url),
            ("ODOO_DB", args.db),
            ("ODOO_USER", args.user),
            ("ODOO_PASSWORD", args.password),
        ]
        if not v
    ]
    if missing:
        print("Manquant :", ", ".join(missing), file=sys.stderr)
        sys.exit(1)

    models, uid, db, password = connect_xmlrpc(args.url, args.db, args.user, args.password)

    company_id = args.company_id
    if company_id is None:
        u = execute_kw(
            models,
            db,
            uid,
            password,
            "res.users",
            "read",
            [[uid]],
            {"fields": ["company_id"]},
        )
        if u and u[0].get("company_id"):
            company_id = u[0]["company_id"][0]

    ids = search_pl_account_ids(models, db, uid, password, company_id)
    print(f"Comptes P&L trouvés : {len(ids)} (société filtre = {company_id})")

    if not ids:
        print("Rien à exporter.", file=sys.stderr)
        sys.exit(2)

    pdf = download_report_pdf(
        args.url,
        args.db,
        args.user,
        args.password,
        ids,
        args.report_name,
    )

    out = os.path.abspath(args.output)
    with open(out, "wb") as f:
        f.write(pdf)
    print(f"PDF écrit : {out} ({len(pdf)} octets)")


if __name__ == "__main__":
    main()
