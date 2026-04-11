#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Balance générale à 6 colonnes (account.report) — prototype XML-RPC.

Idée initiale : rapport avec colonnes « Solde initial débit/crédit », mouvements, « Solde final
débit/crédit », plus des lignes agrégées par classe de compte (1–9) + total.

**Important — rapport avec la toolbox Senedoo**

La création **supportée en production** est ``create_balance_6cols_via_api.py`` / bouton staff
« Créer Balance OHADA » : colonnes avec préfixe ``ohada6_*`` et ligne feuille ``groupby account_id``
pour éviter les collisions avec le moteur standard Odoo sur ``debit`` / ``credit`` /
``balance_initial``. Ce fichier reste un **script autonome d’essai** (libellés d’expressions
``balance_initial``, ``debit``, ``credit``, ``balance`` sur les colonnes, comme souvent dans les
tutoriels Odoo).

Variables d’environnement (ou ``.env`` à côté du script) : ``ODOO_URL``, ``ODOO_DB``,
``ODOO_USER``, ``ODOO_PASSWORD``.

**Retour terrain :** exécution jugée satisfaisante sur Odoo **18.3** et **19** (XML-RPC,
création rapport + colonnes + lignes + menu selon droits).

Usage :
  python odoo_balance_6colonnes_claude.py
  python odoo_balance_6colonnes_claude.py --report-name-fr "Ma balance 6 col."
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

from odoo_client import OdooClient

# =============================================================================
# Noms du rapport (surchargés par --report-name-fr / --report-name-en)
# =============================================================================

DEFAULT_REPORT_NAME_FR = "Balance Générale 6 Colonnes"
DEFAULT_REPORT_NAME_EN = "General Ledger 6 Columns"


def _execute(
    client: OdooClient,
    model: str,
    method: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
) -> Any:
    return client.execute(model, method, args or [], kwargs or {})


def connect_odoo(url: str, db: str, user: str, password: str) -> tuple[int, OdooClient]:
    client = OdooClient(url, db, user, password)
    uid = client.authenticate()
    version_info = client.version()
    server_version = version_info.get("server_version", "?")
    print(f"\n{'=' * 60}")
    print("  CONNEXION À ODOO")
    print(f"{'=' * 60}")
    print(f"  URL  : {client.url}")
    print(f"  Base : {db}")
    print(f"  User : {user}\n")
    print(f"  Serveur Odoo version : {server_version}")
    print(f"  Authentifié — UID : {uid}\n")
    return uid, client


def check_accounting_installed(client: OdooClient) -> None:
    print("  Vérification du module Comptabilité...")
    modules = _execute(
        client,
        "ir.module.module",
        "search_read",
        [[["name", "=", "account"], ["state", "=", "installed"]]],
        {"fields": ["name", "state"], "limit": 1},
    )
    if not modules:
        print("  Le module 'account' n'est pas installé.", file=sys.stderr)
        sys.exit(1)
    print("  Module Comptabilité installé\n")


def check_existing_report(client: OdooClient, needle: str) -> list[dict[str, Any]]:
    return _execute(
        client,
        "account.report",
        "search_read",
        [[["name", "ilike", needle]]],
        {"fields": ["id", "name"], "limit": 5},
    )


def get_or_create_report(
    client: OdooClient,
    *,
    report_name_fr: str,
    report_name_en: str,
    reuse_ilike: str,
) -> int:
    print(f"{'=' * 60}")
    print("  CRÉATION DU RAPPORT PRINCIPAL")
    print(f"{'=' * 60}\n")

    existing = check_existing_report(client, reuse_ilike)
    if existing:
        report_id = existing[0]["id"]
        print(f"  Rapport existant trouvé (ID: {report_id}) → mise à jour colonnes/lignes\n")
        return int(report_id)

    report_vals = {
        "name": report_name_fr,
        "filter_date_range": True,
        "filter_unfold_all": True,
        "filter_journals": True,
        "filter_analytic": True,
        "filter_hierarchy": True,
        "filter_show_draft": True,
        "filter_unreconciled": False,
        "default_opening_date_filter": "this_year",
        "load_more_limit": 80,
        "search_bar": True,
        "prefix_groups_count": 3,
    }

    report_id = int(_execute(client, "account.report", "create", [report_vals]))
    print(f"  Rapport créé — ID : {report_id}\n")
    if report_name_en and report_name_en != report_name_fr:
        print(
            f"  (Info : libellé EN «{report_name_en}» non appliqué automatiquement ; "
            "utilisez les outils de traduction Odoo ou account_report_portable.)\n"
        )
    return report_id


def delete_existing_columns(client: OdooClient, report_id: int) -> None:
    existing_cols = _execute(
        client,
        "account.report.column",
        "search",
        [[["report_id", "=", report_id]]],
    )
    if existing_cols:
        _execute(client, "account.report.column", "unlink", [existing_cols])
        print(f"  {len(existing_cols)} colonnes existantes supprimées")


def create_columns(client: OdooClient, report_id: int) -> list[int]:
    print(f"{'=' * 60}")
    print("  CRÉATION DES 6 COLONNES")
    print(f"{'=' * 60}\n")

    delete_existing_columns(client, report_id)

    columns = [
        {
            "name": "Solde Initial Débit",
            "expression_label": "balance_initial",
            "figure_type": "monetary",
            "report_id": report_id,
            "sequence": 1,
            "blank_if_zero": True,
            "custom_audit_name": "Solde Initial Débit",
            "optional_header": "Soldes Initiaux",
            "sortable": False,
        },
        {
            "name": "Solde Initial Crédit",
            "expression_label": "balance_initial",
            "figure_type": "monetary",
            "report_id": report_id,
            "sequence": 2,
            "blank_if_zero": True,
            "custom_audit_name": "Solde Initial Crédit",
            "optional_header": "Soldes Initiaux",
            "sortable": False,
        },
        {
            "name": "Mouvements Débit",
            "expression_label": "debit",
            "figure_type": "monetary",
            "report_id": report_id,
            "sequence": 3,
            "blank_if_zero": True,
            "custom_audit_name": "Mouvements Débit",
            "optional_header": "Mouvements",
            "sortable": True,
        },
        {
            "name": "Mouvements Crédit",
            "expression_label": "credit",
            "figure_type": "monetary",
            "report_id": report_id,
            "sequence": 4,
            "blank_if_zero": True,
            "custom_audit_name": "Mouvements Crédit",
            "optional_header": "Mouvements",
            "sortable": True,
        },
        {
            "name": "Solde Final Débit",
            "expression_label": "balance",
            "figure_type": "monetary",
            "report_id": report_id,
            "sequence": 5,
            "blank_if_zero": True,
            "custom_audit_name": "Solde Final Débit",
            "optional_header": "Soldes Finaux",
            "sortable": True,
        },
        {
            "name": "Solde Final Crédit",
            "expression_label": "balance",
            "figure_type": "monetary",
            "report_id": report_id,
            "sequence": 6,
            "blank_if_zero": True,
            "custom_audit_name": "Solde Final Crédit",
            "optional_header": "Soldes Finaux",
            "sortable": True,
        },
    ]

    created_ids: list[int] = []
    for col in columns:
        try:
            col_id = int(_execute(client, "account.report.column", "create", [col]))
            created_ids.append(col_id)
            print(f"  Colonne {col['sequence']} — «{col['name']}» (ID: {col_id})")
        except Exception as e:
            print(f"  Avertissement colonne {col['sequence']} «{col['name']}» : {e}")
            col_minimal = {
                "name": col["name"],
                "expression_label": col["expression_label"],
                "figure_type": col["figure_type"],
                "report_id": col["report_id"],
                "sequence": col["sequence"],
                "blank_if_zero": col["blank_if_zero"],
            }
            try:
                col_id = int(
                    _execute(client, "account.report.column", "create", [col_minimal])
                )
                created_ids.append(col_id)
                print(f"     Colonne créée en mode minimal (ID: {col_id})")
            except Exception as e2:
                print(f"     Échec définitif : {e2}")

    print(f"\n  {len(created_ids)}/6 colonnes créées\n")
    return created_ids


def create_report_lines(client: OdooClient, report_id: int) -> list[int]:
    print(f"{'=' * 60}")
    print("  CRÉATION DES LIGNES DE RAPPORT")
    print(f"{'=' * 60}\n")

    existing_lines = _execute(
        client,
        "account.report.line",
        "search",
        [[["report_id", "=", report_id]]],
    )
    if existing_lines:
        _execute(client, "account.report.line", "unlink", [existing_lines])
        print(f"  {len(existing_lines)} lignes existantes supprimées\n")

    classes = [
        ("1", "Comptes de capitaux", "^1"),
        ("2", "Comptes d'immobilisations", "^2"),
        ("3", "Comptes de stocks", "^3"),
        ("4", "Comptes de tiers", "^4"),
        ("5", "Comptes financiers", "^5"),
        ("6", "Comptes de charges", "^6"),
        ("7", "Comptes de produits", "^7"),
        ("8", "Comptes spéciaux", "^8"),
        ("9", "Comptes analytiques/divers", "^9"),
    ]

    line_ids: list[int] = []

    for code, label, domain_prefix in classes:
        line_vals = {
            "name": f"Classe {code} — {label}",
            "report_id": report_id,
            "code": f"CL_{code}",
            "sequence": int(code) * 10,
            "hierarchy_level": 0,
            "unfoldable": True,
            "foldable": True,
            "hide_if_zero": False,
        }

        try:
            line_id = int(_execute(client, "account.report.line", "create", [line_vals]))
            line_ids.append(line_id)
            print(f"  Ligne Classe {code} (ID: {line_id})")

            for expr_label, engine, formula in [
                ("balance_initial", "account_codes", f"{domain_prefix}"),
                ("debit", "account_codes", f"{domain_prefix}"),
                ("credit", "account_codes", f"{domain_prefix}"),
                ("balance", "account_codes", f"{domain_prefix}"),
            ]:
                expr_vals = {
                    "report_line_id": line_id,
                    "label": expr_label,
                    "engine": engine,
                    "formula": formula,
                    "date_scope": (
                        "from_fiscalyear" if expr_label == "balance_initial" else "strict_range"
                    ),
                    "subformula": "C" if expr_label in ("credit", "balance") else "D",
                }
                try:
                    _execute(client, "account.report.expression", "create", [expr_vals])
                except Exception:
                    expr_vals_min = {k: v for k, v in expr_vals.items() if k != "subformula"}
                    try:
                        _execute(
                            client,
                            "account.report.expression",
                            "create",
                            [expr_vals_min],
                        )
                    except Exception as ex2:
                        print(f"     Expression {expr_label} : {ex2}")

        except Exception as e:
            print(f"  Ligne Classe {code} : {e}")

    try:
        total_vals = {
            "name": "TOTAL GÉNÉRAL",
            "report_id": report_id,
            "code": "TOTAL_GENERAL",
            "sequence": 999,
            "hierarchy_level": 0,
            "unfoldable": False,
            "hide_if_zero": False,
        }
        total_id = int(_execute(client, "account.report.line", "create", [total_vals]))
        line_ids.append(total_id)
        print(f"  Ligne TOTAL GÉNÉRAL (ID: {total_id})")

        for expr_label, formula in [
            (
                "balance_initial",
                "CL_1 + CL_2 + CL_3 + CL_4 + CL_5 + CL_6 + CL_7 + CL_8 + CL_9",
            ),
            ("debit", "CL_1 + CL_2 + CL_3 + CL_4 + CL_5 + CL_6 + CL_7 + CL_8 + CL_9"),
            ("credit", "CL_1 + CL_2 + CL_3 + CL_4 + CL_5 + CL_6 + CL_7 + CL_8 + CL_9"),
            ("balance", "CL_1 + CL_2 + CL_3 + CL_4 + CL_5 + CL_6 + CL_7 + CL_8 + CL_9"),
        ]:
            total_expr = {
                "report_line_id": total_id,
                "label": expr_label,
                "engine": "aggregation",
                "formula": formula,
                "date_scope": (
                    "from_fiscalyear" if expr_label == "balance_initial" else "strict_range"
                ),
            }
            try:
                _execute(client, "account.report.expression", "create", [total_expr])
            except Exception as ex:
                print(f"     Expression total {expr_label} : {ex}")

    except Exception as e:
        print(f"  Ligne Total : {e}")

    print(f"\n  {len(line_ids)} lignes créées au total\n")
    return line_ids


def add_to_accounting_menu(client: OdooClient, report_id: int, menu_title: str) -> None:
    print(f"{'=' * 60}")
    print("  AJOUT AU MENU COMPTABILITÉ")
    print(f"{'=' * 60}\n")

    try:
        menu_items = _execute(
            client,
            "ir.ui.menu",
            "search_read",
            [[["name", "ilike", "Rapports"], ["parent_id.name", "ilike", "Comptabilité"]]],
            {"fields": ["id", "name", "complete_name"], "limit": 3},
        )

        if not menu_items:
            menu_items = _execute(
                client,
                "ir.ui.menu",
                "search_read",
                [
                    [
                        ["name", "ilike", "Reports"],
                        ["parent_id.name", "ilike", "Accounting"],
                    ]
                ],
                {"fields": ["id", "name", "complete_name"], "limit": 3},
            )

        if menu_items:
            print(f"  Menu parent trouvé : {menu_items[0]['complete_name']}")
        else:
            print("  Menu parent non trouvé — accès via URL directe\n")
            return

        title = (menu_title or DEFAULT_REPORT_NAME_FR).strip()[:255]
        action_vals = {
            "name": title,
            "type": "ir.actions.client",
            "tag": "account_report",
            "context": repr({"report_id": int(report_id)}),
        }
        action_id = int(_execute(client, "ir.actions.client", "create", [action_vals]))
        print(f"  Action créée (ID: {action_id})")

        menu_vals = {
            "name": title,
            "parent_id": menu_items[0]["id"],
            "action": f"ir.actions.client,{action_id}",
            "sequence": 50,
        }
        menu_id = int(_execute(client, "ir.ui.menu", "create", [menu_vals]))
        print(f"  Entrée de menu créée (ID: {menu_id})\n")

    except Exception as e:
        print(f"  Ajout au menu : {e}")
        print("       Le rapport reste accessible depuis la configuration des rapports.\n")


def verify_report(client: OdooClient, report_id: int) -> None:
    print(f"{'=' * 60}")
    print("  VÉRIFICATION FINALE")
    print(f"{'=' * 60}\n")

    report = _execute(
        client,
        "account.report",
        "read",
        [[report_id]],
        {"fields": ["name", "filter_date_range", "filter_journals"]},
    )[0]

    columns = _execute(
        client,
        "account.report.column",
        "search_read",
        [[["report_id", "=", report_id]]],
        {
            "fields": ["name", "sequence", "expression_label", "figure_type"],
            "order": "sequence asc",
        },
    )

    lines = _execute(
        client,
        "account.report.line",
        "search_read",
        [[["report_id", "=", report_id]]],
        {"fields": ["name", "code", "sequence"], "order": "sequence asc"},
    )

    print(f"  Rapport  : {report['name']}")
    print(f"  Colonnes : {len(columns)}")
    print(f"  Lignes   : {len(lines)}\n")

    print(f"  {'N°':<4} {'Nom de la colonne':<28} {'Expression':<20} {'Type'}")
    print(f"  {'-' * 4} {'-' * 28} {'-' * 20} {'-' * 12}")
    for col in columns:
        print(
            f"  {col['sequence']:<4} {col['name']:<28} "
            f"{col['expression_label']:<20} {col['figure_type']}"
        )

    print(f"\n  {'Code':<15} {'Ligne'}")
    print(f"  {'-' * 15} {'-' * 40}")
    for line in lines:
        print(f"  {line.get('code', ''):<15} {line['name']}")

    base = client.url.rstrip("/")
    print("\n  Accès (selon version / édition Odoo) :")
    print(f"     {base}/odoo/accounting/reports/{report_id}")
    print()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Prototype : balance 6 colonnes + lignes par classe (account.report via XML-RPC)."
    )
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument(
        "--password",
        default=os.environ.get("ODOO_PASSWORD", "").strip() or None,
    )
    p.add_argument(
        "--report-name-fr",
        default=DEFAULT_REPORT_NAME_FR,
        help="Libellé du rapport et du menu (FR)",
    )
    p.add_argument(
        "--report-name-en",
        default=DEFAULT_REPORT_NAME_EN,
        help="Réserve pour traductions (non appliqué automatiquement ici)",
    )
    p.add_argument(
        "--reuse-ilike",
        default="6 Colonnes",
        help="Si un rapport existe déjà avec ce motif dans le nom, le réutiliser (ilike)",
    )
    p.add_argument(
        "--skip-menu",
        action="store_true",
        help="Ne pas créer d'entrée de menu (évite les doublons si vous gérez le menu ailleurs)",
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
        print("Paramètres manquants :", ", ".join(missing), file=sys.stderr)
        return 1

    print(
        """
================================================================
      Balance 6 colonnes — prototype (XML-RPC)
      Production toolbox : create_balance_6cols_via_api.py
================================================================
"""
    )

    uid, client = connect_odoo(args.url, args.db, args.user, args.password)
    _ = uid

    check_accounting_installed(client)

    report_id = get_or_create_report(
        client,
        report_name_fr=args.report_name_fr,
        report_name_en=args.report_name_en or DEFAULT_REPORT_NAME_EN,
        reuse_ilike=(args.reuse_ilike or "6 Colonnes").strip() or "6 Colonnes",
    )

    create_columns(client, report_id)
    create_report_lines(client, report_id)
    if not args.skip_menu:
        add_to_accounting_menu(client, report_id, args.report_name_fr)

    verify_report(client, report_id)

    print(
        f"""
================================================================
  Configuration terminée (prototype)
  → Préférez « Balance OHADA » (staff) pour la prod Senedoo
================================================================
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
