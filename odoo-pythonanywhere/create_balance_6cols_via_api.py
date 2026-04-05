#!/usr/bin/env python3
"""
Crée sur la base Odoo un rapport « balance générale 6 colonnes » via XML-RPC.

**Odoo 19** : le moteur ``aggregation`` (« Aggregate Other Formulas ») est **incompatible**
avec ``groupby`` sur la même ligne (contrainte ``account.report.expression._validate_engine``).
Ce script crée donc une **ligne section** (sans groupby) puis une ligne enfant avec
``groupby = account_id`` et des expressions moteur **domain** (sous-formules ``sum`` /
``sum_if_pos`` / ``sum_if_neg`` selon la doc comptable v19). Les montants période
``débit`` / ``crédit`` reflètent le **découpage du solde net** de la période (positif /
négatif), pas nécessairement les bruts débit et crédit comme un vieux gabarit XML en
``aggregation``.

**Balance OHADA (toolbox)** : constantes ``BALANCE_OHADA_*`` + ``create_toolbox_balance_ohada`` /
``find_balance_ohada_report_id`` (ligne feuille ``code = bal_ohada``).

**Rapport déjà créé avec des en-têtes ``{'fr_FR': ...}`` en clair :** anciennes versions
passaient un dict via XML-RPC → Odoo stockait une chaîne. Supprimer le rapport depuis la
toolbox et le recréer (ou réécrire les ``name`` des colonnes/lignes avec deux ``write``
contexte ``fr_FR`` / ``en_US``, comme ``apply_record_field_translations``).

Prérequis : comptabilité + rapports configurables (account_reports), droits de
création sur ``account.report`` et sous-modèles.

Variables : ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD (ou .env à côté du script)

Usage :
  python create_balance_6cols_via_api.py
  python create_balance_6cols_via_api.py --name-fr "Autre libellé"
  python create_balance_6cols_via_api.py --line-code bal6_client_x

Après exécution : activer sur le rapport l’option « inclure le solde initial »
(ou équivalent) dans l’interface si les colonnes initiales restent à 0 — comme
pour le gabarit XML.
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

from account_report_portable import (
    apply_record_field_translations,
    apply_report_name_translations,
    execute_kw,
)
from odoo_client import OdooClient

# Rapport créé par la toolbox web (repère : account.report.line.code)
BALANCE_OHADA_NAME_FR = "Balance OHADA"
BALANCE_OHADA_NAME_EN = "Balance OHADA"
BALANCE_OHADA_LINE_CODE = "bal_ohada"


def _fields(models: Any, db: str, uid: int, password: str, model: str) -> set[str]:
    fg = execute_kw(models, db, uid, password, model, "fields_get", [], {})
    return set(fg.keys())


def _report_create_vals(field_names: set[str]) -> dict[str, Any]:
    """Rapport autonome (comme le XML : pas de variante racine)."""
    vals: dict[str, Any] = {}
    if "root_report_id" in field_names:
        vals["root_report_id"] = False
    if "section_main_report_ids" in field_names:
        vals["section_main_report_ids"] = [(5, 0, 0)]
    return vals


def _column_vals(
    sequence: int,
    fr: str,
    expression_label: str,
) -> dict[str, Any]:
    """Libellé FR seul à la création ; EN appliqué via ``apply_record_field_translations``."""
    return {
        "sequence": sequence,
        "name": fr,
        "expression_label": expression_label,
        "figure_type": "monetary",
    }


def _section_line_code(leaf_code: str) -> str:
    return f"{leaf_code}_section"


def _expressions_domain_grouped_line() -> list[dict[str, Any]]:
    """
    Expressions moteur « domain » compatibles avec groupby (Odoo 19+).
    Formule ``[]`` = toutes les lignes d’écriture pertinentes pour le compte (contexte groupby).
    """
    return [
        {
            "label": "debit_initial",
            "engine": "domain",
            "formula": "[]",
            "subformula": "sum_if_pos",
            "date_scope": "to_beginning_of_period",
        },
        {
            "label": "credit_initial",
            "engine": "domain",
            "formula": "[]",
            "subformula": "-sum_if_neg",
            "date_scope": "to_beginning_of_period",
        },
        {
            "label": "debit",
            "engine": "domain",
            "formula": "[]",
            "subformula": "sum_if_pos",
            "date_scope": "strict_range",
        },
        {
            "label": "credit",
            "engine": "domain",
            "formula": "[]",
            "subformula": "-sum_if_neg",
            "date_scope": "strict_range",
        },
        {
            "label": "debit_final",
            "engine": "domain",
            "formula": "[]",
            "subformula": "sum_if_pos",
            "date_scope": "from_beginning",
        },
        {
            "label": "credit_final",
            "engine": "domain",
            "formula": "[]",
            "subformula": "-sum_if_neg",
            "date_scope": "from_beginning",
        },
    ]


def create_balance_six_columns_rpc(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    name_fr: str,
    name_en: str,
    line_code: str,
) -> int:
    rep_fields = _fields(models, db, uid, password, "account.report")

    cols_spec = [
        (10, "Débit initial", "Opening debit", "debit_initial"),
        (20, "Crédit initial", "Opening credit", "credit_initial"),
        (30, "Débit", "Debit", "debit"),
        (40, "Crédit", "Credit", "credit"),
        (50, "Débit final", "Closing debit", "debit_final"),
        (60, "Crédit final", "Closing credit", "credit_final"),
    ]

    rep_vals = _report_create_vals(rep_fields)
    rep_vals["name"] = name_fr

    report_id = int(
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "create",
            [rep_vals],
            {"context": {"lang": "fr_FR"}},
        )
    )

    apply_report_name_translations(
        models,
        db,
        uid,
        password,
        report_id,
        name_fr,
        name_en,
    )

    for seq, fr_lbl, en_lbl, expr_lbl in cols_spec:
        cv = _column_vals(seq, fr_lbl, expr_lbl)
        cv["report_id"] = report_id
        col_id = int(
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report.column",
                "create",
                [cv],
                {"context": {"lang": "fr_FR"}},
            )
        )
        apply_record_field_translations(
            models,
            db,
            uid,
            password,
            "account.report.column",
            col_id,
            "name",
            fr_lbl,
            en_lbl,
        )

    # Ligne parente sans groupby (Odoo 19 : aggregation + groupby interdit sur la même ligne).
    section_code = _section_line_code(line_code)
    parent_vals: dict[str, Any] = {
        "report_id": report_id,
        "name": "Balance",
        "code": section_code,
        "sequence": 10,
    }
    parent_id = int(
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "create",
            [parent_vals],
            {"context": {"lang": "fr_FR"}},
        )
    )
    apply_record_field_translations(
        models,
        db,
        uid,
        password,
        "account.report.line",
        parent_id,
        "name",
        "Balance",
        "Balance",
    )

    exprs = _expressions_domain_grouped_line()
    expr_cmds = [(0, 0, dict(e)) for e in exprs]
    line_field_names = _fields(models, db, uid, password, "account.report.line")
    child_vals: dict[str, Any] = {
        "report_id": report_id,
        "parent_id": parent_id,
        "name": "Comptes",
        "code": line_code,
        "groupby": "account_id",
        "sequence": 20,
        "expression_ids": expr_cmds,
    }
    if "foldable" in line_field_names:
        child_vals["foldable"] = True

    ctx_fr = {"context": {"lang": "fr_FR"}}
    try:
        child_id = int(
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report.line",
                "create",
                [child_vals],
                ctx_fr,
            )
        )
    except Exception:
        child_vals.pop("expression_ids", None)
        child_id = int(
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report.line",
                "create",
                [child_vals],
                ctx_fr,
            )
        )
        for e in exprs:
            ev = dict(e)
            ev["report_line_id"] = child_id
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report.expression",
                "create",
                [ev],
            )

    apply_record_field_translations(
        models,
        db,
        uid,
        password,
        "account.report.line",
        child_id,
        "name",
        "Comptes",
        "Accounts",
    )

    return report_id


def create_balance_six_columns(
    client: OdooClient,
    *,
    name_fr: str,
    name_en: str,
    line_code: str,
) -> int:
    uid = client.authenticate()
    return create_balance_six_columns_rpc(
        client._object,
        client.db,
        uid,
        client.password,
        name_fr=name_fr,
        name_en=name_en,
        line_code=line_code,
    )


def find_all_balance_ohada_report_ids(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    line_code: str = BALANCE_OHADA_LINE_CODE,
) -> list[int]:
    """
    Tous les ``account.report`` qui contiennent une ligne feuille avec ce ``code``
    (défaut ``bal_ohada``), triés par id croissant.
    """
    line_ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "search",
        [[("code", "=", line_code)]],
    )
    if not line_ids:
        return []
    report_ids: set[int] = set()
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "read",
        [line_ids],
        {"fields": ["report_id"]},
    )
    for row in rows:
        r = row.get("report_id")
        if isinstance(r, (list, tuple)) and r and r[0]:
            try:
                report_ids.add(int(r[0]))
            except (TypeError, ValueError):
                pass
    return sorted(report_ids)


def find_balance_ohada_report_id(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    line_code: str = BALANCE_OHADA_LINE_CODE,
) -> int | None:
    """
    Retourne un id ``account.report`` toolbox OHADA (repère : ligne ``bal_ohada``).
    S’il y en a plusieurs, retourne le plus petit id (affichage / liens).
    """
    ids = find_all_balance_ohada_report_ids(
        models, db, uid, password, line_code=line_code
    )
    if not ids:
        return None
    return min(ids) if len(ids) > 1 else ids[0]


def create_toolbox_balance_ohada(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> int:
    """
    Retire toute instance existante (rapport, menus et actions client liés), puis crée
    « Balance OHADA » à neuf.
    """
    from web_app.odoo_account_reports import unlink_account_report

    for rid in sorted(
        find_all_balance_ohada_report_ids(models, db, uid, password), reverse=True
    ):
        unlink_account_report(models, db, uid, password, rid)
    return create_balance_six_columns_rpc(
        models,
        db,
        uid,
        password,
        name_fr=BALANCE_OHADA_NAME_FR,
        name_en=BALANCE_OHADA_NAME_EN,
        line_code=BALANCE_OHADA_LINE_CODE,
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description="Crée une balance 6 colonnes (account.report) via API Odoo."
    )
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument(
        "--password",
        default=os.environ.get("ODOO_PASSWORD", "").strip() or None,
    )
    p.add_argument(
        "--name-fr",
        default=BALANCE_OHADA_NAME_FR,
        help="Libellé du rapport (FR)",
    )
    p.add_argument(
        "--name-en",
        default="",
        help="Libellé du rapport (EN) ; défaut = même texte que --name-fr",
    )
    p.add_argument(
        "--line-code",
        default=BALANCE_OHADA_LINE_CODE,
        help="Code unique de la ligne feuille (account.report.line.code)",
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

    name_en = (args.name_en or "").strip() or args.name_fr
    line_code = (args.line_code or "").strip() or BALANCE_OHADA_LINE_CODE

    client = OdooClient(args.url, args.db, args.user, args.password)
    try:
        rid = create_balance_six_columns(
            client,
            name_fr=args.name_fr,
            name_en=name_en,
            line_code=line_code,
        )
    except Exception as e:
        print("Échec :", e, file=sys.stderr)
        return 1

    print(f"OK — rapport account.report id={rid} (ligne code={line_code!r}).")
    print(
        "Vérifiez dans Odoo l’option « solde initial » sur le rapport si besoin "
        "(colonnes initiales à 0 sinon)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
