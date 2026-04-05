#!/usr/bin/env python3
"""
Crée sur la base Odoo un rapport « balance générale 6 colonnes » via XML-RPC.

**Découpage solde → débit / crédit (positifs affichés)** : uniquement sur les **quatre
colonnes extérieures** — **Débit initial**, **Crédit initial**, **Débit final**, **Crédit
final** (solde net : partie ≥ 0 en débit, partie ≤ 0 en valeur absolue en crédit). Les **deux
colonnes centrales de période** (**Débit** / **Crédit**) restent des **cumuls bruts** de
mouvement sur la période ; ne pas les remplacer par un solde net.

**Odoo 19 (constat code source communautaire)** : le moteur ``aggregation`` est **refusé**
dès qu’une ligne porte un ``groupby`` (ex. ``account_id``). Une balance par compte **ne peut
donc pas** utiliser ``initial_debit - initial_credit`` + ``positive`` sur cette ligne : la
création échoue et on retombait sur le domaine — avec en plus un ``root_report_id`` vers le
Grand livre, le rapport se comporte souvent comme une **variante** et affiche encore le **solde
signé** dans la colonne débit au lieu du découpage attendu.

**Stratégie toolbox** : rapport **autonome** (``root_report_id`` = faux), recopie **uniquement**
des options (filtres, solde initial…) depuis le Grand livre si trouvé, lignes en **domain** +
``sum_if_pos`` / ``-sum_if_neg`` sur les quatre colonnes extérieures, puis **réécriture**
XML-RPC des expressions pour garantir les sous-formules en base.

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
from web_app.odoo_account_reports import (
    copy_account_report_options_from_source,
    find_general_ledger_account_report_id,
    unlink_all_account_report_client_actions_for_report_ids,
)

# Rapport créé par la toolbox web (repère : account.report.line.code)
BALANCE_OHADA_NAME_FR = "Balance OHADA"
BALANCE_OHADA_NAME_EN = "Balance OHADA"
BALANCE_OHADA_LINE_CODE = "bal_ohada"


def _fields(models: Any, db: str, uid: int, password: str, model: str) -> set[str]:
    fg = execute_kw(models, db, uid, password, model, "fields_get", [], {})
    return set(fg.keys())


def _report_create_vals(
    field_names: set[str],
    *,
    root_report_id: int | None = None,
) -> dict[str, Any]:
    """``root_report_id`` explicite ; pour Balance OHADA on passe ``None`` (rapport autonome)."""
    vals: dict[str, Any] = {}
    if "root_report_id" in field_names:
        vals["root_report_id"] = int(root_report_id) if root_report_id else False
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

    - **Initial / final** : ``[]`` + ``sum_if_pos`` / ``-sum_if_neg`` — découpage du **solde
      net** (ne pas appliquer ce schéma aux colonnes de période).
    - **Période (2 colonnes du milieu)** : **inchangé** — filtres ``debit > 0`` / ``credit > 0``
      + ``sum`` / ``-sum`` (cumuls **bruts** des écritures sur la période).
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
        # Période : mouvements bruts (ne pas remplacer par un solde net débit − crédit).
        {
            "label": "debit",
            "engine": "domain",
            "formula": "[('debit', '>', 0)]",
            "subformula": "sum",
            "date_scope": "strict_range",
        },
        {
            "label": "credit",
            "engine": "domain",
            "formula": "[('credit', '>', 0)]",
            "subformula": "-sum",
            "date_scope": "strict_range",
        },
        # Finaux : solde net décomposé (comme les initiaux).
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


def _expressions_aggregation_ohada_line() -> list[dict[str, Any]]:
    """
    Référence **Studio / import XML** (ligne **sans** ``groupby`` ou hors v19). Avec
    ``groupby = account_id``, Odoo 19 **refuse** l’engine ``aggregation`` sur la même ligne :
    la toolbox n’utilise pas ce bloc pour la création API ; voir le domaine +
    ``_force_ohada_outer_domain_expressions``.
    """
    return [
        {
            "label": "debit_initial",
            "engine": "aggregation",
            "formula": "initial_debit - initial_credit",
            "subformula": "positive",
            "date_scope": "strict_range",
        },
        {
            "label": "credit_initial",
            "engine": "aggregation",
            "formula": "initial_credit - initial_debit",
            "subformula": "positive",
            "date_scope": "strict_range",
        },
        # Période : uniquement mouvements bruts (ne pas mettre debit - credit ici).
        {
            "label": "debit",
            "engine": "aggregation",
            "formula": "debit",
            "date_scope": "strict_range",
        },
        {
            "label": "credit",
            "engine": "aggregation",
            "formula": "credit",
            "date_scope": "strict_range",
        },
        {
            "label": "debit_final",
            "engine": "aggregation",
            "formula": "(initial_debit + debit) - (initial_credit + credit)",
            "subformula": "positive",
            "date_scope": "strict_range",
        },
        {
            "label": "credit_final",
            "engine": "aggregation",
            "formula": "(initial_credit + credit) - (initial_debit + debit)",
            "subformula": "positive",
            "date_scope": "strict_range",
        },
    ]


def _strip_variant_root_and_handlers(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    rep_field_names: set[str],
) -> None:
    """Rapport 100 % autonome : pas de racine ni handler métier (évite soldes signés type variante)."""
    vals: dict[str, Any] = {}
    if "root_report_id" in rep_field_names:
        vals["root_report_id"] = False
    if "section_main_report_ids" in rep_field_names:
        vals["section_main_report_ids"] = [(5, 0, 0)]
    if "custom_handler_model_name" in rep_field_names:
        vals["custom_handler_model_name"] = False
    if vals:
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report",
                "write",
                [[int(report_id)], vals],
            )
        except Exception:
            pass


def _force_ohada_outer_domain_expressions(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    line_code: str,
) -> None:
    """
    Réécrit les expressions des colonnes extérieures (initiaux / finaux) pour forcer le
    découpage solde : ``sum_if_pos`` / ``-sum_if_neg`` sur ``[]``, quoi qu’ait stocké la création.
    """
    line_ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "search",
        [[("report_id", "=", int(report_id)), ("code", "=", line_code)]],
        {"limit": 2},
    )
    if not line_ids:
        return
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "read",
        [line_ids[:1]],
        {"fields": ["expression_ids"]},
    )
    expr_ids = (rows[0] or {}).get("expression_ids") or []
    if not expr_ids:
        return
    expr_rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.expression",
        "read",
        [expr_ids],
        {"fields": ["id", "label"]},
    )
    targets: dict[str, dict[str, Any]] = {
        "debit_initial": {
            "engine": "domain",
            "formula": "[]",
            "subformula": "sum_if_pos",
            "date_scope": "to_beginning_of_period",
        },
        "credit_initial": {
            "engine": "domain",
            "formula": "[]",
            "subformula": "-sum_if_neg",
            "date_scope": "to_beginning_of_period",
        },
        "debit_final": {
            "engine": "domain",
            "formula": "[]",
            "subformula": "sum_if_pos",
            "date_scope": "from_beginning",
        },
        "credit_final": {
            "engine": "domain",
            "formula": "[]",
            "subformula": "-sum_if_neg",
            "date_scope": "from_beginning",
        },
    }
    for er in expr_rows:
        lbl = er.get("label")
        if lbl not in targets:
            continue
        eid = er.get("id")
        if not eid:
            continue
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report.expression",
                "write",
                [[int(eid)], dict(targets[str(lbl)])],
            )
        except Exception:
            continue


def _create_report_line_with_expressions(
    models: Any,
    db: str,
    uid: int,
    password: str,
    child_vals_base: dict[str, Any],
    exprs: list[dict[str, Any]],
) -> int:
    """Crée une ligne avec ``expression_ids`` ; repli création ligne puis expressions une à une."""
    expr_cmds = [(0, 0, dict(e)) for e in exprs]
    child_vals = dict(child_vals_base)
    child_vals["expression_ids"] = expr_cmds
    ctx_fr = {"context": {"lang": "fr_FR"}}
    try:
        return int(
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
        return child_id


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

    gl_id = find_general_ledger_account_report_id(models, db, uid, password)
    rep_vals = _report_create_vals(rep_fields, root_report_id=None)
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

    _strip_variant_root_and_handlers(
        models, db, uid, password, report_id, rep_fields
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

    col_fields = _fields(models, db, uid, password, "account.report.column")
    for seq, fr_lbl, en_lbl, expr_lbl in cols_spec:
        cv = _column_vals(seq, fr_lbl, expr_lbl)
        if "blank_if_zero" in col_fields:
            cv["blank_if_zero"] = True
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

    line_field_names = _fields(models, db, uid, password, "account.report.line")
    child_vals_base: dict[str, Any] = {
        "report_id": report_id,
        "parent_id": parent_id,
        "name": "Comptes",
        "code": line_code,
        "groupby": "account_id",
        "sequence": 20,
    }
    if "foldable" in line_field_names:
        child_vals_base["foldable"] = True

    if gl_id:
        try:
            copy_account_report_options_from_source(
                models, db, uid, password, gl_id, report_id
            )
        except Exception:
            pass

    child_id = _create_report_line_with_expressions(
        models,
        db,
        uid,
        password,
        child_vals_base,
        _expressions_domain_grouped_line(),
    )
    _force_ohada_outer_domain_expressions(
        models, db, uid, password, report_id, line_code
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


def _report_ids_from_line_codes(
    models: Any,
    db: str,
    uid: int,
    password: str,
    line_codes: tuple[str, ...],
) -> set[int]:
    out: set[int] = set()
    for code in line_codes:
        line_ids = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "search",
            [[("code", "=", code)]],
        )
        if not line_ids:
            continue
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
                    out.add(int(r[0]))
                except (TypeError, ValueError):
                    pass
    return out


def collect_balance_ohada_report_ids_for_cleanup(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> set[int]:
    """
    Identifiants des ``account.report`` créés par **cette** toolbox : uniquement ceux qui
    portent une ligne ``account.report.line`` avec le code feuille ``bal_ohada`` ou la ligne
    section ``bal_ohada_section`` (constantes toolbox). Aucune recherche par libellé : un
    rapport Studio nommé « Balance OHADA » sans ces codes n’est **pas** touché.
    """
    section = _section_line_code(BALANCE_OHADA_LINE_CODE)
    return _report_ids_from_line_codes(
        models,
        db,
        uid,
        password,
        (BALANCE_OHADA_LINE_CODE, section),
    )


def purge_balance_ohada_instances(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> set[int]:
    """
    Supprime menus + actions client + ``account.report`` pour tout ce qui est reconnu comme
    Balance OHADA (voir ``collect_balance_ohada_report_ids_for_cleanup``). Retourne l’ensemble
    d’ids qui étaient ciblés (même si certains ``unlink`` ont échoué).
    """
    from web_app.odoo_account_reports import (
        unlink_all_account_report_client_actions_for_report_ids,
    )

    to_remove = collect_balance_ohada_report_ids_for_cleanup(models, db, uid, password)
    unlink_all_account_report_client_actions_for_report_ids(
        models, db, uid, password, to_remove
    )
    for rid in sorted(to_remove, reverse=True):
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report",
                "unlink",
                [[rid]],
            )
        except Exception:
            continue
    return to_remove


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
    return sorted(
        _report_ids_from_line_codes(
            models, db, uid, password, (line_code,)
        )
    )


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

    Nettoyage : voir ``purge_balance_ohada_instances``.
    """
    purge_balance_ohada_instances(models, db, uid, password)
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
