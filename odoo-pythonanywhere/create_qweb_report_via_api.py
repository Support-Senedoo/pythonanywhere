#!/usr/bin/env python3
"""
Crée (ou met à jour) un rapport PDF QWeb via l’API Odoo, sans déposer de module dans /addons.

Principe : même famille d’enregistrements que Studio / le XML chargé par un module :
  - ir.ui.view (type qweb, arch)
  - ir.model.data (xml id module.name → vue)
  - ir.actions.report

Limites possibles sur Odoo Online :
  - droits insuffisants sur ir.ui.view / ir.actions.report (besoin d’un profil pouvant
    modifier les vues techniques, souvent « Paramètres » / administrateur) ;
  - politiques Odoo peuvent restreindre certaines créations.

Usage :
  Variables ODOO_* ou arguments --url --db --user --password
  python create_qweb_report_via_api.py
  python create_qweb_report_via_api.py --remove   # supprime les enregistrements créés (xmlid)

Après création : Comptabilité → Comptes → filtrer les comptes P&L → sélectionner les lignes
→ Imprimer → « Liste comptes P&L (API) » (le PDF liste les comptes sélectionnés).

Pour générer le PDF automatiquement (search des comptes P&L + téléchargement) :
  voir export_pl_accounts_pdf.py
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Identifiants stables pour retrouver / supprimer les données créées
MODULE = "custom_pl_accounts"
XML_NAME_VIEW = "report_pl_accounts_api_document"
XML_NAME_REPORT = "action_report_pl_accounts_api"
VIEW_KEY = f"{MODULE}.{XML_NAME_VIEW}"


def connect(
    url: str, db: str, user: str, password: str
) -> tuple[Any, int, str, str]:
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


def qweb_arch() -> str:
    """Rapport minimal : tableau code / libellé / type pour chaque compte sélectionné."""
    return """<?xml version="1.0"?>
<t t-name="custom_pl_accounts.report_pl_accounts_api_document">
<t t-call="web.html_container">
    <t t-foreach="docs" t-as="o">
        <t t-set="company" t-value="o.company_ids[:1]"/>
        <t t-call="web.external_layout">
            <div class="page">
                <h2 class="mt-3">Comptes produits et charges (API)</h2>
                <p class="text-muted">Compte : <span t-field="o.code"/> — <span t-field="o.name"/></p>
                <p>Type : <span t-field="o.account_type"/></p>
            </div>
        </t>
    </t>
</t>
</t>
"""


def qweb_arch_table() -> str:
    """Une seule page, tableau (plus lisible si plusieurs comptes sélectionnés)."""
    return """<?xml version="1.0"?>
<t t-name="custom_pl_accounts.report_pl_accounts_api_document">
<t t-call="web.html_container">
    <t t-set="company" t-value="docs[0].company_ids[:1] if docs else None"/>
    <t t-call="web.external_layout">
        <div class="page">
            <h2 class="mt-3">Comptes produits et charges</h2>
            <p class="text-muted">Rapport généré via API (QWeb).</p>
            <table class="table table-sm table-bordered">
                <thead>
                    <tr><th>Code</th><th>Libellé</th><th>Type</th></tr>
                </thead>
                <tbody>
                    <t t-foreach="docs" t-as="o">
                        <tr>
                            <td><span t-field="o.code"/></td>
                            <td><span t-field="o.name"/></td>
                            <td><span t-field="o.account_type"/></td>
                        </tr>
                    </t>
                </tbody>
            </table>
        </div>
    </t>
</t>
</t>
"""


def ensure_xml_id(
    models: Any,
    db: str,
    uid: int,
    password: str,
    module: str,
    name: str,
    model: str,
    res_id: int,
) -> None:
    """Crée ou met à jour ir.model.data pour un xml id."""
    Imd = "ir.model.data"
    found = execute_kw(
        models,
        db,
        uid,
        password,
        Imd,
        "search",
        [[["module", "=", module], ["name", "=", name]]],
    )
    vals = {"model": model, "res_id": res_id}
    if found:
        execute_kw(models, db, uid, password, Imd, "write", [found, vals])
    else:
        execute_kw(
            models,
            db,
            uid,
            password,
            Imd,
            "create",
            [{"module": module, "name": name, **vals}],
        )


def create_or_update_report(models: Any, db: str, uid: int, password: str, table_mode: bool) -> dict[str, Any]:
    arch = qweb_arch_table() if table_mode else qweb_arch()
    View = "ir.ui.view"
    view_ids = execute_kw(
        models,
        db,
        uid,
        password,
        View,
        "search",
        [[["key", "=", VIEW_KEY]]],
    )

    view_vals: dict[str, Any] = {
        "name": "report_pl_accounts_api_document",
        "type": "qweb",
        "key": VIEW_KEY,
        "arch_db": arch,
    }

    if view_ids:
        execute_kw(models, db, uid, password, View, "write", [view_ids, view_vals])
        view_id = view_ids[0]
    else:
        view_id = execute_kw(models, db, uid, password, View, "create", [view_vals])

    ensure_xml_id(
        models, db, uid, password, MODULE, XML_NAME_VIEW, "ir.ui.view", view_id
    )

    report_name = f"{MODULE}.{XML_NAME_VIEW}"
    Report = "ir.actions.report"
    rep_ids = execute_kw(
        models,
        db,
        uid,
        password,
        Report,
        "search",
        [[["report_name", "=", report_name]]],
    )
    rep_vals = {
        "name": "Liste comptes P&L (API)",
        "model": "account.account",
        "report_type": "qweb-pdf",
        "report_name": report_name,
        "report_file": report_name,
        "print_report_name": "'Comptes_P&L'",
    }
    if rep_ids:
        execute_kw(models, db, uid, password, Report, "write", [rep_ids, rep_vals])
        report_id = rep_ids[0]
    else:
        report_id = execute_kw(models, db, uid, password, Report, "create", [rep_vals])

    ensure_xml_id(
        models, db, uid, password, MODULE, XML_NAME_REPORT, "ir.actions.report", report_id
    )

    return {
        "view_id": view_id,
        "report_id": report_id,
        "report_name": report_name,
        "message": "OK — rapport disponible dans le menu Imprimer sur la liste des comptes (modèle Compte).",
    }


def remove_customizations(models: Any, db: str, uid: int, password: str) -> None:
    Imd = "ir.model.data"
    for name, model in [
        (XML_NAME_REPORT, "ir.actions.report"),
        (XML_NAME_VIEW, "ir.ui.view"),
    ]:
        ids = execute_kw(
            models,
            db,
            uid,
            password,
            Imd,
            "search",
            [[["module", "=", MODULE], ["name", "=", name]]],
        )
        if not ids:
            continue
        data = execute_kw(
            models,
            db,
            uid,
            password,
            Imd,
            "read",
            [ids],
            {"fields": ["res_id", "model"]},
        )
        for row in data:
            rid = row["res_id"]
            m = row["model"]
            execute_kw(models, db, uid, password, m, "unlink", [[rid]])
        execute_kw(models, db, uid, password, Imd, "unlink", [ids])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument("--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)
    p.add_argument(
        "--remove",
        action="store_true",
        help="Supprime vue + rapport + xmlids créés par ce script",
    )
    p.add_argument(
        "--one-page-per-account",
        action="store_true",
        help="Un PDF avec une page par compte au lieu d’un tableau unique",
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

    models, uid, db, password = connect(args.url, args.db, args.user, args.password)

    if args.remove:
        remove_customizations(models, db, uid, password)
        print("Suppressions effectuées (si les enregistrements existaient).")
        return

    out = create_or_update_report(
        models, db, uid, password, table_mode=not args.one_page_per_account
    )
    print(out)


if __name__ == "__main__":
    main()
